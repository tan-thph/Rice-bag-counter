from fastapi import FastAPI, HTTPException, WebSocket, BackgroundTasks, Request, WebSocketDisconnect, UploadFile, File, Form
from fastapi.responses import HTMLResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, Field
from typing import List, Optional
from concurrent.futures import ThreadPoolExecutor
from ultralytics import YOLO
import cv2, asyncio, json, os, time, asyncio, logging, base64, uuid, torch, traceback

from detector import RiceBagDetector
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse  
 
import numpy as np
from datetime import datetime
import tempfile, io
from fastapi.middleware.cors import CORSMiddleware
from typing import Union, Optional
from threading import Lock, Event
from print import create_job_result_pdf

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # In production, replace with frontend URL
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Set up logging
logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)

# Mount the static directory and set up templates
app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")

cameras = {
    "Băng tải 1": "rtsp://tan001:tan001@192.168.0.62/stream1",
    "Băng tải 2": "rtsp://tan001:tan001@192.168.0.62/stream2"
}

active_jobs = {}
job_results = []
connected_clients = {}
frame_locks = {}
video_job_events ={}

class Job(BaseModel):
    job_type: str
    camera: Optional[str] = None
    customer_name: str
    truck_number: str
    commodity: str
    weight_per_unit: float
    order_number: str
    note: Optional[str] = None
    detection_line_orientation: str = "vertical"
    detection_line_position: float = 0.5
    video_path: Optional[str] = None

class LineUpdate(BaseModel):
    new_position: Optional[float] = Field(None, ge=0, le=1)
    new_orientation: Optional[str] = Field(None, pattern='^(vertical|horizontal)$')


@app.get("/", response_class=HTMLResponse)
async def read_root(request: Request):
    initial_data = {
        "activeJobs": active_jobs,
        "jobResults": job_results,
        "cameras": list(cameras.keys())
    }
    
    encoded_data = json.dumps(initial_data, default=custom_jsonable_encoder)
    
    return templates.TemplateResponse("index.html", {
        "request": request,
        "initial_data_json": encoded_data
    })

@app.get("/cameras")
async def get_cameras():
    return cameras

@app.post("/jobs")
async def create_job(job: Job, background_tasks: BackgroundTasks):
    if job.job_type == "rtsp" and not job.camera:
        raise HTTPException(status_code=400, detail="Camera is required for RTSP jobs")
    
    job_id = str(uuid.uuid4())
    active_jobs[job_id] = job.dict()
    active_jobs[job_id]['bag_count'] = 0
    
    if job.job_type == "rtsp":
        background_tasks.add_task(run_rtsp_detection_job, job_id)
    else:
        raise HTTPException(status_code=400, detail="Invalid job type for this endpoint")
    
    return {"job_id": job_id, "message": "RTSP job created successfully"}

@app.post("/upload_video")
async def upload_video(
    file: UploadFile = File(...),
    job_type: str = Form(...),
    customer_name: str = Form(...),
    truck_number: str = Form(...),
    commodity: str = Form(...),
    weight_per_unit: float = Form(...),
    order_number: str = Form(...),
    note: Optional[str] = Form(None),
    detection_line_orientation: str = Form("vertical"),
    detection_line_position: float = Form(0.5),
    background_tasks: BackgroundTasks = BackgroundTasks()
):
    if not file:
        raise HTTPException(status_code=400, detail="No file uploaded")

    job_id = str(uuid.uuid4())
    
    # Create a temporary file with a .mp4 extension
    with tempfile.NamedTemporaryFile(delete=False, suffix=".mp4") as temp_file:
        temp_file_path = temp_file.name
        # Write the uploaded file content to the temporary file
        temp_file.write(await file.read())

    try:
        job = Job(
            job_type=job_type,
            customer_name=customer_name,
            truck_number=truck_number,
            commodity=commodity,
            weight_per_unit=weight_per_unit,
            order_number=order_number,
            note=note,
            detection_line_orientation=detection_line_orientation,
            detection_line_position=detection_line_position,
            video_path=temp_file_path
        )
        active_jobs[job_id] = job.dict()
        active_jobs[job_id]['bag_count'] = 0

        if job_type == "video":
            background_tasks.add_task(run_video_detection_job, job_id)
        else:
            raise HTTPException(status_code=400, detail="Invalid job type for this endpoint")

        return {"job_id": job_id, "message": "Video uploaded and job created successfully"}
    except Exception as e:
        logger.error(f"Error processing video upload: {str(e)}")
        # Make sure to delete the temporary file if an error occurs
        os.unlink(temp_file_path)
        raise HTTPException(status_code=500, detail=f"Error processing video upload: {str(e)}")

@app.get("/jobs")
async def get_jobs():
    try:
        jobs = {job_id: {k: v for k, v in job.items() if k != "current_frame"} for job_id, job in active_jobs.items()}
        return jobs
    except Exception as e:
        logger.error(f"Error in get_jobs: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Internal server error: {str(e)}")

async def run_rtsp_detection_job(job_id: str):
    job = active_jobs[job_id]
    detector = RiceBagDetector("best_n_v15_imgsz224_ep200.pt", 
                               detection_line_position=job["detection_line_position"],
                               is_vertical=(job["detection_line_orientation"] == "vertical"))
    
    rtsp_url = cameras.get(job["camera"], job["camera"])
    cap = cv2.VideoCapture(rtsp_url)
    
    if not cap.isOpened():
        logger.error(f"Failed to open RTSP stream: {rtsp_url}")
        add_job_result(job_id, job, "error", 0)
        del active_jobs[job_id]
        return

    frame_locks[job_id] = Lock()

    def process_frames():
        nonlocal cap, detector
        while job_id in active_jobs:
            ret, frame = cap.read()
            if not ret:
                logger.warning(f"Failed to read frame from RTSP stream: {rtsp_url}")
                break
            
            # Update detector's line position and orientation if they have changed
            if detector.detection_line_position != active_jobs[job_id]["detection_line_position"]:
                detector.update_line_position(active_jobs[job_id]["detection_line_position"])
            
            if detector.is_vertical != (active_jobs[job_id]["detection_line_orientation"] == "vertical"):
                detector.update_line_orientation(active_jobs[job_id]["detection_line_orientation"] == "vertical")
            
            processed_frame, bag_count = detector.process_frame(frame)
            
            with frame_locks[job_id]:
                active_jobs[job_id]["bag_count"] = bag_count
                _, buffer = cv2.imencode('.jpg', processed_frame)
                active_jobs[job_id]["current_frame"] = buffer.tobytes()

            time.sleep(0.033)  # Aim for ~30 FPS

    with ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(process_frames)
        
        try:
            while job_id in active_jobs:
                if future.done():
                    break
                await asyncio.sleep(1)
                
                with frame_locks[job_id]:
                    bag_count = active_jobs[job_id]["bag_count"]
                
                if job_id in connected_clients:
                    for websocket in connected_clients[job_id]:
                        await websocket.send_json({"job_id": job_id, "bag_count": bag_count})
        
        finally:
            cap.release()
            del frame_locks[job_id]
            if job_id in active_jobs:
                final_count = active_jobs[job_id]["bag_count"]
                job_data = active_jobs[job_id]
                del active_jobs[job_id]
                add_job_result(job_id, job_data, "completed", final_count)
                update_jobs()


async def run_video_detection_job(job_id: str):
    job = active_jobs[job_id]
    detector = RiceBagDetector("best_n_v15_imgsz224_ep200.pt", 
                               detection_line_position=job["detection_line_position"],
                               is_vertical=(job["detection_line_orientation"] == "vertical"))
    
    cap = cv2.VideoCapture(job["video_path"])
    fps = cap.get(cv2.CAP_PROP_FPS)
    frame_time = 1 / fps if fps > 0 else 0.033  # Default to 30 FPS if unable to get FPS
    
    if not cap.isOpened():
        logger.error(f"Failed to open video file: {job['video_path']}")
        add_job_result(job_id, job, "error", 0)
        del active_jobs[job_id]
        return

    frame_locks[job_id] = Lock()
    video_job_events[job_id] = Event()

    def process_frames():
        nonlocal cap, detector
        frame_count = 0
        while job_id in active_jobs and not video_job_events[job_id].is_set():
            try:
                ret, frame = cap.read()
                if not ret:
                    logger.info(f"Reached end of video for job {job_id}")
                    break

                frame_count += 1
                logger.debug(f"Processing frame {frame_count} for job {job_id}")
                
                # Update detector's line position and orientation if they have changed
                if detector.detection_line_position != active_jobs[job_id]["detection_line_position"]:
                    detector.update_line_position(active_jobs[job_id]["detection_line_position"])
                
                if detector.is_vertical != (active_jobs[job_id]["detection_line_orientation"] == "vertical"):
                    detector.update_line_orientation(active_jobs[job_id]["detection_line_orientation"] == "vertical")
                
                processed_frame, bag_count = detector.process_frame(frame)
                
                with frame_locks[job_id]:
                    active_jobs[job_id]["bag_count"] = bag_count
                    _, buffer = cv2.imencode('.jpg', processed_frame)
                    active_jobs[job_id]["current_frame"] = buffer.tobytes()

                time.sleep(frame_time)

            except Exception as e:
                logger.error(f"Error processing frame {frame_count} for job {job_id}: {str(e)}")
                logger.error(traceback.format_exc())
                # If there's an error, we'll skip this frame and continue with the next one
                continue

        cap.release()
        logger.info(f"Video job {job_id} finished processing")
        if job_id in active_jobs:
            final_count = active_jobs[job_id]["bag_count"]
            job_data = active_jobs[job_id]
            del active_jobs[job_id]
            add_job_result(job_id, job_data, "completed", final_count)
            update_jobs()

    with ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(process_frames)
        
        try:
            while job_id in active_jobs and not video_job_events[job_id].is_set():
                if future.done():
                    break
                await asyncio.sleep(1)
                
                with frame_locks[job_id]:
                    bag_count = active_jobs[job_id]["bag_count"]
                
                if job_id in connected_clients:
                    for websocket in connected_clients[job_id]:
                        await websocket.send_json({"job_id": job_id, "bag_count": bag_count})
        
        except Exception as e:
            logger.error(f"Error in run_video_detection_job for job {job_id}: {str(e)}")
            logger.error(traceback.format_exc())
        
        finally:
            video_job_events[job_id].set()  # Signal the thread to stop
            try:
                future.result()  # Wait for the thread to finish
            except Exception as e:
                logger.error(f"Error in process_frames thread for job {job_id}: {str(e)}")
                logger.error(traceback.format_exc())
            
            del frame_locks[job_id]
            del video_job_events[job_id]
            
            # Clean up the video file
            try:
                os.unlink(job["video_path"])
            except Exception as e:
                logger.error(f"Error removing temporary video file: {str(e)}")

def add_job_result(job_id: str, job: Union[dict, Job], status: str, final_count: int):
    if isinstance(job, dict):
        job_data = job
    elif isinstance(job, Job):
        job_data = job.dict()
    else:
        raise ValueError("Job must be either a dictionary or a Job object")

    job_results.append({
        "job_id": job_id,
        "job_type": job_data.get("job_type", "unknown"),
        "date_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "camera": job_data.get("camera", "N/A") if job_data.get("job_type") == "rtsp" else "N/A",
        "customer_name": job_data.get("customer_name", "N/A"),
        "truck_number": job_data.get("truck_number", "N/A"),
        "commodity": job_data.get("commodity", "N/A"),
        "weight_per_unit": job_data.get("weight_per_unit", 0),
        "order_number": job_data.get("order_number", "N/A"),
        "final_count": final_count,
        "status": status
    })

@app.post("/update_line/{job_id}")
async def update_line(job_id: str, update: LineUpdate):
    if job_id not in active_jobs:
        raise HTTPException(status_code=404, detail="Job not found")
    
    job = active_jobs[job_id]
    
    if update.new_position is not None:
        job["detection_line_position"] = update.new_position
    
    if update.new_orientation is not None:
        job["detection_line_orientation"] = update.new_orientation
    
    return {"message": f"Line updated for job {job_id}", "new_position": job["detection_line_position"], "new_orientation": job["detection_line_orientation"]}


@app.post("/upload_video")
async def upload_video(
    file: UploadFile = File(...),
    job_type: str = Form(...),
    customer_name: str = Form(...),
    truck_number: str = Form(...),
    commodity: str = Form(...),
    weight_per_unit: float = Form(...),
    order_number: str = Form(...),
    note: Optional[str] = Form(None),
    detection_line_orientation: str = Form("vertical"),
    detection_line_position: float = Form(0.5),
    background_tasks: BackgroundTasks = BackgroundTasks()
):
    if not file:
        raise HTTPException(status_code=400, detail="No file uploaded")

    job_id = str(uuid.uuid4())
    
    with tempfile.NamedTemporaryFile(delete=False, suffix=".mp4") as temp_file:
        temp_file_path = temp_file.name
        temp_file.write(await file.read())

    try:
        job = Job(
            job_type=job_type,
            customer_name=customer_name,
            truck_number=truck_number,
            commodity=commodity,
            weight_per_unit=weight_per_unit,
            order_number=order_number,
            note=note,
            detection_line_orientation=detection_line_orientation,
            detection_line_position=detection_line_position,
            video_path=temp_file_path
        )
        active_jobs[job_id] = job.dict()
        active_jobs[job_id]['bag_count'] = 0

        if job_type == "video":
            background_tasks.add_task(run_video_detection_job, job_id)
        else:
            raise HTTPException(status_code=400, detail="Invalid job type for this endpoint")

        return {"job_id": job_id, "message": "Video uploaded and job created successfully"}
    except Exception as e:
        logger.error(f"Error processing video upload: {str(e)}")
        os.unlink(temp_file_path)
        raise HTTPException(status_code=500, detail=f"Error processing video upload: {str(e)}")

@app.get("/job_results")
async def get_job_results():
    return job_results

def custom_jsonable_encoder(obj):
    if isinstance(obj, bytes):
        return base64.b64encode(obj).decode('utf-8')
    return jsonable_encoder(obj)

def generate_frames(job_id: str):
    fps = 10
    frame_interval = 1 / fps
    
    while job_id in active_jobs:
        start_time = time.time()
        
        frame_data = active_jobs[job_id].get("current_frame")
        if frame_data is not None:
            yield (b'--frame\r\n'
                   b'Content-Type: image/jpeg\r\n\r\n' + frame_data + b'\r\n')
        
        processing_time = time.time() - start_time
        if processing_time < frame_interval:
            time.sleep(frame_interval - processing_time)

@app.get("/video_feed/{job_id}")
async def video_feed(job_id: str):
    job = active_jobs.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    
    async def generate():
        while job_id in active_jobs:
            frame_data = active_jobs[job_id].get("current_frame")
            if frame_data is not None:
                # Decode the JPEG frame
                frame = cv2.imdecode(np.frombuffer(frame_data, np.uint8), cv2.IMREAD_COLOR)
                
                # Downscale to 144p
                small_frame = cv2.resize(frame, (720, 480))
                
                # Apply some blur to reduce noise and improve compression
                #small_frame = cv2.GaussianBlur(small_frame, (5, 5), 0)
                
                # Upscale back to 720p
                large_frame = cv2.resize(small_frame, (720, 480), interpolation=cv2.INTER_LINEAR)
                
                # Encode to JPEG with low quality
                encode_param = [int(cv2.IMWRITE_JPEG_QUALITY), 20]
                _, buffer = cv2.imencode('.jpg', large_frame, encode_param)
                
                yield (b'--frame\r\n'
                       b'Content-Type: image/jpeg\r\n\r\n' + buffer.tobytes() + b'\r\n')
            await asyncio.sleep(0.033)  # Aim for ~30 FPS

    return StreamingResponse(generate(), media_type="multipart/x-mixed-replace; boundary=frame")


@app.websocket("/ws/{job_id}")
async def websocket_endpoint(websocket: WebSocket, job_id: str):
    await websocket.accept()
    if job_id not in connected_clients:
        connected_clients[job_id] = set()
    connected_clients[job_id].add(websocket)
    try:
        while True:
            if job_id in active_jobs:
                await websocket.send_json({"job_id": job_id, "bag_count": active_jobs[job_id].get("bag_count", 0)})
            await asyncio.sleep(1)
    except WebSocketDisconnect:
        connected_clients[job_id].remove(websocket)
        if not connected_clients[job_id]:
            del connected_clients[job_id]


@app.get("/print_job_result/{job_id}")
async def print_job_result(job_id: str):
    job_result = next((result for result in job_results if result["job_id"] == job_id), None)
    if not job_result:
        raise HTTPException(status_code=404, detail="Job result not found")

    pdf_buffer = create_job_result_pdf(job_result)
    
    return StreamingResponse(pdf_buffer, media_type="application/pdf", headers={"Content-Disposition": f"attachment; filename=job_result_{job_id}.pdf"})

def save_jobs_to_file():
    with open("jobs_data.json", "w") as f:
        json.dump({"active_jobs": active_jobs, "job_results": job_results}, f)

def load_jobs_from_file():
    global active_jobs, job_results
    try:
        with open("jobs_data.json", "r") as f:
            data = json.load(f)
            active_jobs = data["active_jobs"]
            job_results = data["job_results"]
    except FileNotFoundError:
        pass  # No saved data yet
    except json.JSONDecodeError:
        print("Error decoding JSON from jobs_data.json. Starting with empty jobs.")
        active_jobs = {}
        job_results = []

# Call this function when the server starts
load_jobs_from_file()

# Call this function whenever jobs are updated
def update_jobs():
    serializable_active_jobs = {}
    for job_id, job_data in active_jobs.items():
        serializable_job = {k: v for k, v in job_data.items() if k != "current_frame"}
        serializable_active_jobs[job_id] = serializable_job
    with open("jobs_data.json", "w") as f:
        json.dump({"active_jobs": serializable_active_jobs, "job_results": job_results}, f, default=str)

@app.post("/stop_job/{job_id}")
async def stop_job(job_id: str):
    if job_id in active_jobs:
        job = active_jobs[job_id]
        job_model = Job(**{k: v for k, v in job.items() if k in Job.__annotations__})
        final_count = job["bag_count"]
        
        if job["job_type"] == "video":
            if job_id in video_job_events:
                video_job_events[job_id].set()  # Signal the video processing thread to stop
            if "video_path" in job:
                try:
                    os.remove(job["video_path"])
                except FileNotFoundError:
                    logger.warning(f"Video file not found: {job['video_path']}")
                except Exception as e:
                    logger.error(f"Error removing video file: {str(e)}")
        
        del active_jobs[job_id]
        add_job_result(job_id, job_model, "stopped", final_count)
        update_jobs()
        return {"message": f"Job {job_id} stopped successfully"}
    else:
        raise HTTPException(status_code=404, detail=f"Job {job_id} not found")

def update_jobs():
    serializable_active_jobs = {}
    for job_id, job_data in active_jobs.items():
        serializable_job = {k: v for k, v in job_data.items() if k != "current_frame"}
        serializable_active_jobs[job_id] = serializable_job
    
    with open("jobs_data.json", "w") as f:
        json.dump({"active_jobs": serializable_active_jobs, "job_results": job_results}, f, default=str)
    pass
    
if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=9000)