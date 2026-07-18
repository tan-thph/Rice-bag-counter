from fastapi import (FastAPI, HTTPException, WebSocket, BackgroundTasks,
                     Request, WebSocketDisconnect, UploadFile, File, Form)
from fastapi.responses import HTMLResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.middleware.cors import CORSMiddleware
from fastapi.encoders import jsonable_encoder
from pydantic import BaseModel, Field
from typing import Optional, Union
from concurrent.futures import ThreadPoolExecutor
from ultralytics import YOLO
from threading import Lock, Event
from datetime import datetime
import cv2, asyncio, json, os, time, logging, base64, uuid, traceback, tempfile

from detector import RiceBagDetector
from print import create_job_result_pdf

# ── App setup ─────────────────────────────────────────────────────────────────

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)

app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")

# ── Shared YOLO model ─────────────────────────────────────────────────────────
# Loaded once at startup and shared across all concurrent jobs.
# YOLO sets model.conf / model.iou per-instance via RiceBagDetector, so each
# detector gets its own attribute without reloading weights from disk.
_MODEL_PATH = "best_n_v15_imgsz224_ep200.pt"
logger.info(f"Loading YOLO model from {_MODEL_PATH} ...")
_shared_model = YOLO(_MODEL_PATH)
_shared_model.fuse()   # fuse Conv+BN layers for faster inference
logger.info("YOLO model ready.")

# ── Runtime state ─────────────────────────────────────────────────────────────

cameras = {
    "Băng tải 1": "rtsp://tan001:tan001@192.168.0.62/stream1",
    "Băng tải 2": "rtsp://tan001:tan001@192.168.0.62/stream2",
}

active_jobs      = {}   # {job_id: dict}
job_results      = []   # list of completed-job dicts
connected_clients = {}  # {job_id: set of WebSocket}
frame_locks      = {}   # {job_id: threading.Lock}
video_job_events = {}   # {job_id: threading.Event}
rtsp_detectors   = {}   # {job_id: RiceBagDetector}
video_detectors  = {}   # {job_id: RiceBagDetector}

# ── Pydantic models ───────────────────────────────────────────────────────────

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
    desired_direction: int = Field(1, ge=-1, le=1)
    video_path: Optional[str] = None

class LineUpdate(BaseModel):
    new_position: Optional[float] = Field(None, ge=0, le=1)
    new_orientation: Optional[str] = Field(None, pattern='^(vertical|horizontal)$')

class DesiredDirectionUpdate(BaseModel):
    new_direction: int = Field(..., ge=-1, le=1)

# ── Routes ────────────────────────────────────────────────────────────────────

@app.get("/", response_class=HTMLResponse)
async def read_root(request: Request):
    initial_data = {
        "activeJobs": active_jobs,
        "jobResults": job_results,
        "cameras": list(cameras.keys()),
    }
    encoded_data = json.dumps(initial_data, default=_json_encode)
    return templates.TemplateResponse("index.html", {
        "request": request,
        "initial_data_json": encoded_data,
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
    active_jobs[job_id]["bag_count"] = 0

    if job.job_type == "rtsp":
        background_tasks.add_task(run_rtsp_detection_job, job_id)
    elif job.job_type == "video":
        background_tasks.add_task(run_video_detection_job, job_id)
    else:
        raise HTTPException(status_code=400, detail="Invalid job type")

    return {"job_id": job_id, "message": f"{job.job_type.upper()} job created successfully"}

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
    desired_direction: int = Form(1),
    background_tasks: BackgroundTasks = BackgroundTasks(),
):
    if not file:
        raise HTTPException(status_code=400, detail="No file uploaded")

    job_id = str(uuid.uuid4())

    with tempfile.NamedTemporaryFile(delete=False, suffix=".mp4") as tmp:
        tmp_path = tmp.name
        tmp.write(await file.read())

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
            desired_direction=desired_direction,
            video_path=tmp_path,
        )
        active_jobs[job_id] = job.dict()
        active_jobs[job_id]["bag_count"] = 0

        if job_type != "video":
            raise HTTPException(status_code=400, detail="Invalid job type for this endpoint")

        background_tasks.add_task(run_video_detection_job, job_id)
        return {"job_id": job_id, "message": "Video uploaded and job created successfully"}

    except Exception as e:
        logger.error(f"Error processing video upload: {e}")
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise HTTPException(status_code=500, detail=f"Error processing video upload: {e}")

@app.get("/jobs")
async def get_jobs():
    try:
        return {
            job_id: {k: v for k, v in job.items() if k != "current_frame"}
            for job_id, job in active_jobs.items()
        }
    except Exception as e:
        logger.error(f"Error in get_jobs: {e}")
        raise HTTPException(status_code=500, detail=f"Internal server error: {e}")

@app.get("/job_results")
async def get_job_results():
    return job_results

@app.post("/update_line/{job_id}")
async def update_line(job_id: str, update: LineUpdate):
    if job_id not in active_jobs:
        raise HTTPException(status_code=404, detail="Job not found")

    # Read both detection-line fields together under the frame lock so the
    # processing thread always sees a consistent pair.
    lock = frame_locks.get(job_id)
    if lock:
        with lock:
            job = active_jobs[job_id]
            if update.new_position is not None:
                job["detection_line_position"] = update.new_position
            if update.new_orientation is not None:
                job["detection_line_orientation"] = update.new_orientation
    else:
        job = active_jobs[job_id]
        if update.new_position is not None:
            job["detection_line_position"] = update.new_position
        if update.new_orientation is not None:
            job["detection_line_orientation"] = update.new_orientation

    return {
        "message": f"Line updated for job {job_id}",
        "new_position": job["detection_line_position"],
        "new_orientation": job["detection_line_orientation"],
    }

@app.post("/update_desired_direction/{job_id}")
async def update_desired_direction(job_id: str, update: DesiredDirectionUpdate):
    if job_id not in active_jobs:
        raise HTTPException(status_code=404, detail="Job not found")

    job = active_jobs[job_id]
    job["desired_direction"] = update.new_direction

    detector = (rtsp_detectors if job["job_type"] == "rtsp" else video_detectors).get(job_id)
    if detector:
        detector.update_desired_direction(update.new_direction)

    return {"message": f"Desired direction updated for job {job_id}",
            "new_direction": update.new_direction}

@app.post("/stop_job/{job_id}")
async def stop_job(job_id: str):
    if job_id not in active_jobs:
        raise HTTPException(status_code=404, detail=f"Job {job_id} not found")

    job         = active_jobs[job_id]
    final_count = job["bag_count"]
    job_model   = Job(**{k: v for k, v in job.items() if k in Job.__annotations__})

    if job["job_type"] == "video" and job_id in video_job_events:
        video_job_events[job_id].set()   # signal processing thread to stop
        # Do NOT delete the temp file here — run_video_detection_job's finally
        # block does it after the thread has actually released the file handle.

    del active_jobs[job_id]
    _notify_clients_job_ended(job_id)
    add_job_result(job_id, job_model, "stopped", final_count)
    update_jobs()
    return {"message": f"Job {job_id} stopped successfully"}

@app.get("/video_feed/{job_id}")
async def video_feed(job_id: str):
    if job_id not in active_jobs:
        raise HTTPException(status_code=404, detail="Job not found")

    async def generate():
        while job_id in active_jobs:
            lock = frame_locks.get(job_id)
            if lock:
                with lock:
                    frame_data = active_jobs.get(job_id, {}).get("current_frame")
            else:
                frame_data = active_jobs.get(job_id, {}).get("current_frame")

            if frame_data is not None:
                yield (b"--frame\r\n"
                       b"Content-Type: image/jpeg\r\n\r\n" + frame_data + b"\r\n")
            await asyncio.sleep(0.033)   # ~30 FPS

    return StreamingResponse(generate(),
                             media_type="multipart/x-mixed-replace; boundary=frame")

@app.websocket("/ws/{job_id}")
async def websocket_endpoint(websocket: WebSocket, job_id: str):
    await websocket.accept()
    connected_clients.setdefault(job_id, set()).add(websocket)
    try:
        while True:
            if job_id in active_jobs:
                count = active_jobs[job_id].get("bag_count", 0)
                try:
                    await websocket.send_json({"job_id": job_id, "bag_count": count})
                except Exception:
                    break   # client gone — exit cleanly
            else:
                # Job has ended; notify the client so it can refresh results.
                try:
                    await websocket.send_json({"job_id": job_id, "status": "ended"})
                except Exception:
                    pass
                break
            await asyncio.sleep(1)
    except WebSocketDisconnect:
        pass
    finally:
        connected_clients.get(job_id, set()).discard(websocket)
        if not connected_clients.get(job_id):
            connected_clients.pop(job_id, None)

@app.get("/print_job_result/{job_id}")
async def print_job_result(job_id: str):
    job_result = next((r for r in job_results if r["job_id"] == job_id), None)
    if not job_result:
        raise HTTPException(status_code=404, detail="Job result not found")
    pdf_buffer = create_job_result_pdf(job_result)
    return StreamingResponse(
        pdf_buffer,
        media_type="application/pdf",
        headers={"Content-Disposition": f"attachment; filename=job_result_{job_id}.pdf"},
    )

# ── Background job runners ────────────────────────────────────────────────────

async def run_rtsp_detection_job(job_id: str):
    job      = active_jobs[job_id]
    detector = RiceBagDetector(
        _shared_model,
        detection_line_position=job["detection_line_position"],
        is_vertical=(job["detection_line_orientation"] == "vertical"),
        desired_direction=job["desired_direction"],
    )
    rtsp_detectors[job_id] = detector

    rtsp_url = cameras.get(job["camera"], job["camera"])
    cap = cv2.VideoCapture(rtsp_url)
    # Ask OpenCV/FFMPEG to time out stalled reads instead of blocking forever.
    cap.set(cv2.CAP_PROP_OPEN_TIMEOUT_MSEC, 5_000)
    cap.set(cv2.CAP_PROP_READ_TIMEOUT_MSEC, 10_000)

    if not cap.isOpened():
        logger.error(f"Failed to open RTSP stream: {rtsp_url}")
        add_job_result(job_id, job, "error", 0)
        active_jobs.pop(job_id, None)
        rtsp_detectors.pop(job_id, None)
        return

    frame_locks[job_id] = Lock()
    last_frame_time = time.monotonic()

    def process_frames():
        nonlocal last_frame_time
        while job_id in active_jobs:
            t0 = time.monotonic()
            try:
                ret, frame = cap.read()

                if not ret:
                    # Stall detection: if no frame for 10 s the stream is dead.
                    if time.monotonic() - last_frame_time > 10:
                        logger.warning(f"RTSP stream stalled for job {job_id}")
                        break
                    time.sleep(0.05)
                    continue

                last_frame_time = time.monotonic()

                # stop_job() can delete active_jobs[job_id] from the asyncio
                # thread at any point after the while-check above; guard the
                # dict access so that race doesn't surface as an uncaught
                # KeyError on this background thread.
                if job_id not in active_jobs:
                    break

                # Read detection-line settings atomically with the frame lock.
                with frame_locks[job_id]:
                    line_pos    = active_jobs[job_id]["detection_line_position"]
                    line_orient = active_jobs[job_id]["detection_line_orientation"]

                if detector.detection_line_position != line_pos:
                    detector.update_line_position(line_pos)
                if detector.is_vertical != (line_orient == "vertical"):
                    detector.update_line_orientation(line_orient == "vertical")

                processed_frame, bag_count = detector.process_frame(frame)

                with frame_locks[job_id]:
                    if job_id not in active_jobs:
                        break
                    active_jobs[job_id]["bag_count"] = bag_count
                    _, buf = cv2.imencode(".jpg", processed_frame)
                    active_jobs[job_id]["current_frame"] = buf.tobytes()
            except KeyError:
                # Job was stopped concurrently; exit cleanly instead of
                # propagating an exception that would be silently dropped
                # by the executor.
                break

            # Sleep only the time remaining in the target interval.
            elapsed = time.monotonic() - t0
            sleep_s = max(0.0, 0.033 - elapsed)
            if sleep_s:
                time.sleep(sleep_s)

    with ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(process_frames)
        try:
            while job_id in active_jobs:
                if future.done():
                    break
                await asyncio.sleep(1)
        finally:
            cap.release()
            frame_locks.pop(job_id, None)
            rtsp_detectors.pop(job_id, None)
            _notify_clients_job_ended(job_id)
            if job_id in active_jobs:
                final_count = active_jobs[job_id]["bag_count"]
                job_data    = active_jobs.pop(job_id)
                add_job_result(job_id, job_data, "completed", final_count)
                update_jobs()


async def run_video_detection_job(job_id: str):
    job      = active_jobs[job_id]
    detector = RiceBagDetector(
        _shared_model,
        detection_line_position=job["detection_line_position"],
        is_vertical=(job["detection_line_orientation"] == "vertical"),
        desired_direction=job["desired_direction"],
    )
    video_detectors[job_id] = detector

    cap = cv2.VideoCapture(job["video_path"])
    fps        = cap.get(cv2.CAP_PROP_FPS) or 30.0
    frame_time = 1.0 / fps

    if not cap.isOpened():
        logger.error(f"Failed to open video file: {job['video_path']}")
        add_job_result(job_id, job, "error", 0)
        active_jobs.pop(job_id, None)
        return

    frame_locks[job_id]      = Lock()
    video_job_events[job_id] = Event()

    def process_frames():
        frame_count = 0
        while job_id in active_jobs and not video_job_events[job_id].is_set():
            t0 = time.monotonic()
            try:
                ret, frame = cap.read()
                if not ret:
                    logger.info(f"End of video for job {job_id}")
                    break

                frame_count += 1

                with frame_locks[job_id]:
                    line_pos    = active_jobs[job_id]["detection_line_position"]
                    line_orient = active_jobs[job_id]["detection_line_orientation"]

                if detector.detection_line_position != line_pos:
                    detector.update_line_position(line_pos)
                if detector.is_vertical != (line_orient == "vertical"):
                    detector.update_line_orientation(line_orient == "vertical")

                processed_frame, bag_count = detector.process_frame(frame)

                with frame_locks[job_id]:
                    active_jobs[job_id]["bag_count"] = bag_count
                    _, buf = cv2.imencode(".jpg", processed_frame)
                    active_jobs[job_id]["current_frame"] = buf.tobytes()

            except Exception as e:
                logger.error(f"Frame {frame_count} error for job {job_id}: {e}")
                logger.debug(traceback.format_exc())

            elapsed = time.monotonic() - t0
            sleep_s = max(0.0, frame_time - elapsed)
            if sleep_s:
                time.sleep(sleep_s)

        cap.release()
        logger.info(f"Video job {job_id} processing finished")

        if job_id in active_jobs:
            final_count = active_jobs[job_id]["bag_count"]
            job_data    = active_jobs.pop(job_id)
            add_job_result(job_id, job_data, "completed", final_count)
            update_jobs()

    with ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(process_frames)
        try:
            while job_id in active_jobs and not video_job_events[job_id].is_set():
                if future.done():
                    break
                await asyncio.sleep(1)
        except Exception as e:
            logger.error(f"run_video_detection_job error for {job_id}: {e}")
            logger.debug(traceback.format_exc())
        finally:
            video_job_events[job_id].set()  # signal thread if not already
            try:
                future.result(timeout=10)   # wait for thread to release file
            except Exception as e:
                logger.error(f"process_frames thread error for {job_id}: {e}")

            frame_locks.pop(job_id, None)
            video_job_events.pop(job_id, None)
            video_detectors.pop(job_id, None)
            _notify_clients_job_ended(job_id)

            # Safe to delete temp file only after thread has finished and
            # released the VideoCapture handle.
            try:
                os.unlink(job["video_path"])
            except OSError as e:
                logger.error(f"Could not delete temp video file: {e}")

# ── Helpers ───────────────────────────────────────────────────────────────────

def _notify_clients_job_ended(job_id: str):
    """Remove the connected-clients entry for a finished job."""
    connected_clients.pop(job_id, None)

def add_job_result(job_id: str, job: Union[dict, Job], status: str, final_count: int):
    job_data = job if isinstance(job, dict) else job.dict()
    job_results.append({
        "job_id":          job_id,
        "job_type":        job_data.get("job_type", "unknown"),
        "date_time":       datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "camera":          job_data.get("camera", "N/A") if job_data.get("job_type") == "rtsp" else "N/A",
        "customer_name":   job_data.get("customer_name", "N/A"),
        "truck_number":    job_data.get("truck_number", "N/A"),
        "commodity":       job_data.get("commodity", "N/A"),
        "weight_per_unit": job_data.get("weight_per_unit", 0),
        "order_number":    job_data.get("order_number", "N/A"),
        "final_count":     final_count,
        "status":          status,
    })

def _json_encode(obj):
    if isinstance(obj, bytes):
        return base64.b64encode(obj).decode("utf-8")
    return jsonable_encoder(obj)

def update_jobs():
    serialisable = {
        jid: {k: v for k, v in jdata.items() if k != "current_frame"}
        for jid, jdata in active_jobs.items()
    }
    with open("jobs_data.json", "w") as f:
        json.dump({"active_jobs": serialisable, "job_results": job_results},
                  f, default=str)

def load_jobs_from_file():
    global job_results
    try:
        with open("jobs_data.json", "r") as f:
            data = json.load(f)
        # Previously active jobs have no running threads after restart;
        # surface them as interrupted results rather than phantom active jobs.
        for job_id, job_data in data.get("active_jobs", {}).items():
            job_results.append({
                "job_id":          job_id,
                "job_type":        job_data.get("job_type", "unknown"),
                "date_time":       datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "camera":          job_data.get("camera", "N/A") if job_data.get("job_type") == "rtsp" else "N/A",
                "customer_name":   job_data.get("customer_name", "N/A"),
                "truck_number":    job_data.get("truck_number", "N/A"),
                "commodity":       job_data.get("commodity", "N/A"),
                "weight_per_unit": job_data.get("weight_per_unit", 0),
                "order_number":    job_data.get("order_number", "N/A"),
                "final_count":     job_data.get("bag_count", 0),
                "status":          "interrupted",
            })
        job_results.extend(data.get("job_results", []))
    except FileNotFoundError:
        pass
    except json.JSONDecodeError:
        logger.error("jobs_data.json is corrupt — starting with empty state.")

load_jobs_from_file()

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=9000)
