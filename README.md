# Rice Bag Counter

A real-time computer vision application for counting rice bags on conveyor belts. Supports live RTSP camera feeds and pre-recorded video files. Built with FastAPI, YOLOv8, and Vue.js.

---

## Table of Contents

- [Overview](#overview)
- [How It Works](#how-it-works)
- [Core Features](#core-features)
- [Counting Logic](#counting-logic)
- [Tech Stack](#tech-stack)
- [Installation](#installation)
- [Running the App](#running-the-app)
- [Usage Guide](#usage-guide)
- [API Reference](#api-reference)
- [Configuration](#configuration)
- [Limitations](#limitations)
- [Potential Improvements](#potential-improvements)

---

## Overview

Rice Bag Counter automates the manual process of counting bags loaded onto or off a truck via a conveyor belt. An operator creates a "job" by entering shipment details (customer, truck, order number, commodity, weight per bag), then starts a live or recorded video feed. The app detects each bag using a trained YOLOv8 model, tracks it across frames, and counts it exactly once when the entire bag has crossed a configurable detection line.

Results are saved persistently and can be exported as a formatted PDF receipt in Vietnamese.

![Architecture Diagram](docs/architecture.png)

---

## How It Works

```
Camera / Video File
        │
        ▼
  OpenCV VideoCapture
        │
        ▼
  YOLOv8 Inference  ──►  Bounding boxes (class 0 = bag)
        │
        ▼
  Zone Classification
  (Zone A | crossing | Zone B)
        │
        ▼
  Ghost-Tracking & Velocity Prediction
  (re-associate disappeared bags via EMA velocity)
        │
        ▼
  Committed-Zone State Machine
  (count fires only on full A↔B transition)
        │
        ▼
  WebSocket → Browser  (live count)
  MJPEG Stream → Browser  (annotated video)
        │
        ▼
  Job Result → PDF Report
```

---

## Core Features

### 1. Dual Input Modes
- **RTSP stream** — connects directly to IP cameras (e.g. Hikvision, Dahua) over the local network.
- **Video upload** — accepts any video file (MP4, AVI, MKV, etc.) for offline processing.

### 2. Zone-Based Counting
The detection line splits the frame into **Zone A** (left/above) and **Zone B** (right/below). A bag is counted only when its entire bounding box has cleared the line — not just its centre. This eliminates false counts from bags that hover near the line or partially reverse.

### 3. Ghost Tracking + Velocity Prediction
When YOLO misses a bag for up to 20 frames (≈ 0.67 s at 30 fps), the tracker keeps a "ghost" track alive using a smoothed velocity estimate. If the bag reappears within the predicted search radius it is re-associated to the original track, inheriting its zone history. This correctly handles the most common failure mode: **a bag disappears in Zone A and reappears in Zone B** — the A→B transition is still counted without duplication.

### 4. Bi-Directional Counting
Each job is configured with a **desired direction**:
- **Loading (A→B)** — bags moving onto the truck increment the count.
- **Unloading (B→A)** — bags moving off the truck increment the count.

Bags moving against the desired direction decrement the count, self-correcting for conveyor reversals or operator mistakes.

### 5. Live Detection Line Adjustment
The detection line position (0–1, as a fraction of frame width/height) and orientation (vertical/horizontal) can be updated while a job is running without restarting it.

### 6. Real-Time WebSocket Updates
The browser receives the current bag count over a WebSocket every second. The annotated video stream is delivered as MJPEG via a separate endpoint.

### 7. PDF Report Generation
Completed jobs can be exported as an A5 landscape PDF receipt containing job metadata, final count, total weight, and signature fields. The PDF uses DejaVu fonts to render Vietnamese characters correctly.

### 8. Persistent Job Storage
Active and completed jobs are serialised to `jobs_data.json`. On server restart, active jobs that had no running threads are automatically moved to results with status `interrupted` rather than being presented as still-active.

---

## Counting Logic

The core state machine lives in `detector.py → RiceBagDetector`.

### Zones

For a **vertical** detection line at pixel position `L`:

| Condition | Zone |
|-----------|------|
| `x_max < L` (entire bag to the left) | Zone A |
| `x_min > L` (entire bag to the right) | Zone B |
| `x_min ≤ L ≤ x_max` (straddles line) | crossing |

For a **horizontal** line, the same logic applies to `y_min` / `y_max`.

### State Machine

```
        ┌───────────────────────────────────────────┐
        │                                           │
     Zone A  ──► crossing ──► Zone B   ← COUNT fires here (A→B committed)
        │                       │
        │◄──── crossing ◄───────┘         ← COUNT fires here (B→A committed)
        │
  [bounce: A→crossing→A = no count]
```

`committed_zone` only updates when the bag is fully inside A or B. A count fires only when `committed_zone` changes — so a bag that grazes the line and retreats never triggers a false count.

### Ghost Tracking

```
Frame N:   bag detected in Zone A  → track #5, committed_zone='A', velocity=(12, 0)
Frame N+1: bag not detected        → ghost #5, frames_missing=1, predicted_x = last_x + 12
Frame N+2: bag not detected        → ghost #5, frames_missing=2, predicted_x = last_x + 24
Frame N+3: bag detected in Zone B  → distance to predicted < threshold → RE-ASSOCIATED to #5
                                      committed_zone changes A→B → COUNT +1  ✓
```

### Match Threshold

```
threshold = BASE_MATCH_DIST(120px) + speed_px_per_frame × frames_missing
```

A fast bag missing for several frames gets a proportionally wider search radius.

### Visual Overlay Legend

| Colour | Meaning |
|--------|---------|
| Blue box | Bag fully in Zone A |
| Yellow box | Bag crossing the detection line |
| Green box | Bag fully in Zone B |
| Grey box (dashed) | Ghost track (bag not currently detected) |
| Cyan arrow on bag | Current velocity vector (×8 scale) |
| Red dot | Bounding box centre |
| Red line | Detection line |

---

## Tech Stack

| Component | Technology |
|-----------|-----------|
| Backend API | Python 3.10+ · FastAPI · Uvicorn |
| Object Detection | YOLOv8n (Ultralytics) · PyTorch |
| Video Processing | OpenCV |
| Real-time Updates | WebSocket (native FastAPI) |
| Video Streaming | MJPEG over HTTP (multipart/x-mixed-replace) |
| Frontend | Vue.js 2.6 · Axios (CDN) |
| PDF Generation | ReportLab |
| Persistence | JSON flat file |

---

## Installation

### Prerequisites

- Python 3.10 or higher
- CUDA-capable GPU recommended (falls back to CPU automatically)
- Network access to RTSP camera(s) for live mode

### Steps

```bash
# 1. Clone the repository
git clone https://github.com/tan-thph/rice-bag-detector-web-app.git
cd rice-bag-detector-web-app

# 2. Create and activate a virtual environment
python -m venv venv
# Windows
venv\Scripts\activate
# Linux / macOS
source venv/bin/activate

# 3. Install dependencies
pip install fastapi uvicorn ultralytics opencv-python-headless torch torchvision reportlab python-multipart jinja2

# 4. Verify the model file is present
ls best_n_v15_imgsz224_ep200.pt
```

> **Note:** A `requirements.txt` is not yet included. See [Potential Improvements](#potential-improvements).

### RTSP Camera Setup

Edit the `cameras` dictionary in `main.py`:

```python
cameras = {
    "Conveyor 1": "rtsp://username:password@192.168.0.62/stream1",
    "Conveyor 2": "rtsp://username:password@192.168.0.62/stream2",
}
```

---

## Running the App

```bash
python main.py
```

The server starts on `http://0.0.0.0:9000`. Open `http://localhost:9000` in your browser.

To run in the background (Linux/macOS):

```bash
nohup python main.py &
```

---

## Usage Guide

### Creating a Job

1. Fill in the job form:
   - **Customer Name** — name of the customer receiving/sending the shipment.
   - **Truck Number** — vehicle plate number.
   - **Order Number** — internal order reference.
   - **Commodity** — product name (e.g. "Gạo ST25").
   - **Weight per Unit** — weight of one bag in kg.
   - **Desired Direction** — `Loading` (left→right) or `Unloading` (right→left).
   - **Detection Line Orientation** — `Vertical` (bags move left/right) or `Horizontal` (bags move up/down).
   - **Detection Line Position** — 0.0 to 1.0 (fraction of frame). Default 0.5 (centre).
2. Click **RTSP Job** to start a live camera feed, or **Video Job** to upload a recording.

### Monitoring

- Click **Show Video** on any active job to open the annotated live stream.
- The bag count updates in real time via WebSocket.
- Use **Update Line** to reposition the detection line mid-job if the conveyor view shifts.
- Use **Update Direction** to flip between loading and unloading.

### Stopping and Exporting

- Click **Stop Job** to end counting. The job moves to the Results table.
- Click **Print** on any result row to download a PDF receipt.

---

## API Reference

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/` | Main dashboard (HTML) |
| `GET` | `/cameras` | List configured cameras |
| `POST` | `/jobs` | Create an RTSP job |
| `POST` | `/upload_video` | Upload video and create a video job |
| `GET` | `/jobs` | List active jobs |
| `GET` | `/job_results` | List completed job results |
| `POST` | `/update_line/{job_id}` | Update detection line position/orientation |
| `POST` | `/update_desired_direction/{job_id}` | Change counting direction |
| `POST` | `/stop_job/{job_id}` | Stop an active job |
| `GET` | `/video_feed/{job_id}` | MJPEG video stream |
| `WS` | `/ws/{job_id}` | WebSocket for real-time bag count |
| `GET` | `/print_job_result/{job_id}` | Download PDF report |

### Example: Create RTSP Job

```bash
curl -X POST http://localhost:9000/jobs \
  -H "Content-Type: application/json" \
  -d '{
    "job_type": "rtsp",
    "camera": "Conveyor 1",
    "customer_name": "Nguyen Van A",
    "truck_number": "51A-12345",
    "commodity": "Gao ST25",
    "weight_per_unit": 50.0,
    "order_number": "ORD-2024-001",
    "detection_line_orientation": "vertical",
    "detection_line_position": 0.5,
    "desired_direction": 1
  }'
```

---

## Configuration

All tuning parameters are at the top of `detector.py`:

```python
MAX_FRAMES_MISSING = 20    # Ghost track lifetime (frames). Increase for slower/choppier streams.
BASE_MATCH_DIST    = 120   # Base matching radius (pixels). Increase for wider conveyor belts.
VELOCITY_ALPHA     = 0.4   # EMA smoothing (0–1). Higher = faster velocity adaptation.
```

YOLO inference parameters are set in `RiceBagDetector.__init__`:

```python
self.model.conf = 0.25   # Confidence threshold. Raise to reduce false positives.
self.model.iou  = 0.45   # NMS IoU threshold.
```

---

## Limitations

### Detection Model
- **Single class only** — the model detects one class (`bag`). Mixed commodity loads are not distinguished.
- **Fixed image size mismatch** — the model was trained at `imgsz=224` but inference resizes input to `640×640` before passing `imgsz=224` to YOLO, adding an unnecessary double-resize step.
- **No re-training UI** — adding new bag types or improving accuracy requires offline model retraining.
- **Occlusion sensitivity** — heavily stacked or overlapping bags may be detected as one, causing undercounting.

### Tracking
- **Greedy matching only** — detections are matched to tracks in detection order, not globally optimised (Hungarian algorithm). In dense scenes with many simultaneous bags, ID switches are possible.
- **Ghost timeout** — if a bag disappears for more than `MAX_FRAMES_MISSING` frames (default ≈ 0.67 s), its track is dropped. A bag that is occluded longer than this will be assigned a new ID and may be missed or double-counted.
- **No appearance features** — matching is purely distance-based. Bags that look different from each other are not exploited for better association.

### Streaming
- **RTSP no auto-reconnect** — if the RTSP stream drops (network hiccup, camera reboot), the job ends immediately with an error. There is no automatic reconnection or retry.
- **Single detection line per job** — only one line can be active per job. Multi-zone counting (e.g. entry + exit gates) is not supported.
- **No stream health monitoring** — stale or frozen RTSP frames are processed as valid without detection.

### Data & Storage
- **Flat JSON persistence** — `jobs_data.json` grows indefinitely; there is no archival, pruning, or search capability.
- **No authentication** — the web interface has no login. Anyone on the network can create, stop, or view jobs.
- **RTSP credentials in source code** — camera URLs including usernames and passwords are hardcoded in `main.py`. These should be moved to environment variables.
- **In-memory frames** — the current annotated frame for each job is held in RAM as JPEG bytes. Running many concurrent jobs increases memory usage proportionally.

### Frontend
- **Vue.js 2 (EOL)** — Vue 2 reached end of life in December 2023. The frontend should be migrated to Vue 3 or another modern framework.
- **No offline support** — the dashboard requires CDN access (Vue.js, Axios) to load.
- **No video progress indicator** — when processing an uploaded video, there is no progress bar showing how far through the file processing has reached.

### Operational
- **No requirements.txt** — dependencies must be installed manually.
- **No health check endpoint** — there is no `/health` route to verify the server or camera connectivity before creating a job.
- **No unit or integration tests** — correctness of detection and counting logic is not automatically verified.
- **Hardcoded company info in PDF** — the company name, address, and phone number in generated reports are hardcoded in `print.py`.

---

## Potential Improvements

| Priority | Improvement |
|----------|-------------|
| High | Add `requirements.txt` / `pyproject.toml` for reproducible installs |
| High | Move RTSP credentials to `.env` / environment variables |
| High | RTSP auto-reconnect with exponential back-off |
| High | Add `/health` endpoint for camera and server status checks |
| Medium | Hungarian algorithm for globally optimal detection-to-track assignment |
| Medium | Multi-line counting (entry + exit simultaneously) per job |
| Medium | Video processing progress endpoint (`GET /job_progress/{job_id}`) |
| Medium | Database backend (SQLite → PostgreSQL) to replace flat JSON |
| Medium | User authentication (JWT or session-based) |
| Medium | `requirements.txt` and Docker image for easy deployment |
| Medium | Confidence / IoU threshold controls in the UI |
| Medium | Fix double-resize issue (`640→224` in one step, not two) |
| Low | Migrate frontend to Vue 3 + Vite |
| Low | CSV/Excel export of job results |
| Low | Configurable company info for PDF reports |
| Low | Appearance-based re-identification (bag colour/texture features) for more robust matching |
| Low | Kalman filter instead of linear velocity extrapolation |
| Low | Model warm-up on server start to avoid first-frame latency spike |
| Low | Shared YOLO model instance across concurrent jobs (currently loaded once per job) |
