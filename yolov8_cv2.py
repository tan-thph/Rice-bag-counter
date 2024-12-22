import cv2
import numpy as np
from ultralytics import YOLO
import time
from threading import Lock
from PyQt5.QtCore import QThread, pyqtSignal
import torch
import os
from pathlib import Path

class DetectionThread(QThread):
    update_frame = pyqtSignal(object, int)
    finished = pyqtSignal(int)

    def __init__(self, input_source, window_name, detection_line_position, is_vertical, count_direction):
        super().__init__()
        self.input_source = input_source
        self.window_name = window_name
        self._detection_line_position = detection_line_position
        self._is_vertical = is_vertical
        self._count_direction = count_direction
        self.stop_flag = False
        self._lock = Lock()
        
        # Initialize tracking variables
        self.tracked_bags = {}
        self.next_bag_id = 1
        self.bag_count = 0
        
        # Setup device
        self.device = torch.device('cuda' if torch.cuda.is_available() else 'cpu')
        
        # Get model path
        current_dir = Path(__file__).resolve().parent
        self.model_path = current_dir / 'resources' / 'models' / 'best_yolo11_n_v15_ep100_sz320.pt'
        if not (current_dir / 'resource' /'models').exists():
            (current_dir / 'resources' / 'models').mkdir(parents=True, exist_ok=True) 

    @property
    def detection_line_position(self):
        with self._lock:
            return self._detection_line_position

    @detection_line_position.setter
    def detection_line_position(self, value):
        with self._lock:
            self._detection_line_position = value

    @property
    def is_vertical(self):
        with self._lock:
            return self._is_vertical

    @is_vertical.setter
    def is_vertical(self, value):
        with self._lock:
            self._is_vertical = value

    @property
    def count_direction(self):
        with self._lock:
            return self._count_direction

    @count_direction.setter
    def count_direction(self, value):
        with self._lock:
            self._count_direction = value

    def load_model(self):
        """Load YOLO model with error handling"""
        try:
            if not self.model_path.exists():
                raise FileNotFoundError(f"Model not found at {self.model_path}")
            
            model = YOLO(str(self.model_path))
            model.to(self.device)
            return model
        except Exception as e:
            print(f"Error loading model: {e}")
            raise

    def setup_video_capture(self):
        """Setup video capture with proper configuration"""
        try:
            cap = cv2.VideoCapture(self.input_source)
            if not cap.isOpened():
                raise RuntimeError(f"Failed to open video source: {self.input_source}")
            
            # Set resolution
            cap.set(cv2.CAP_PROP_FRAME_WIDTH, 1280)
            cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 720)
            
            # Get and validate FPS
            fps = cap.get(cv2.CAP_PROP_FPS)
            if fps <= 0:
                fps = 30.0
                
            return cap, fps
        except Exception as e:
            print(f"Error setting up video capture: {e}")
            raise

    def track_bag(self, current_point, prev_bags, max_distance=100):
        """Track bags between frames using distance-based matching"""
        closest_bag_id = None
        min_distance = float('inf')
        
        for bag_id, prev_point in prev_bags.items():
            distance = np.sqrt((current_point[0] - prev_point[0])**2 + 
                             (current_point[1] - prev_point[1])**2)
            if distance < min_distance and distance < max_distance:
                min_distance = distance
                closest_bag_id = bag_id
                
        if closest_bag_id is None:
            closest_bag_id = self.next_bag_id
            self.next_bag_id += 1
            
        return closest_bag_id

    def check_line_crossing(self, current_point, prev_point, line_pos, is_vertical):
        """Check if a bag has crossed the detection line"""
        if is_vertical:
            # For vertical line
            crossed = (prev_point[0] - line_pos) * (current_point[0] - line_pos) <= 0
            if crossed:
                if self.count_direction == "left_to_right":
                    return 1 if prev_point[0] < line_pos else -1
                else:
                    return 1 if prev_point[0] > line_pos else -1
        else:
            # For horizontal line
            crossed = (prev_point[1] - line_pos) * (current_point[1] - line_pos) <= 0
            if crossed:
                if self.count_direction == "left_to_right":
                    return 1 if prev_point[1] < line_pos else -1
                else:
                    return 1 if prev_point[1] > line_pos else -1
        return 0

    def process_frame(self, frame, model, line_pos):
        """Process a single frame for bag detection and tracking"""
        height, width = frame.shape[:2]
        
        # Run YOLO detection
        results = model(frame, imgsz=224)
        current_bags = {}
        count_change = 0
        
        # Process detections
        if len(results) > 0 and len(results[0].boxes) > 0:
            for box in results[0].boxes:
                # Filter detections
                if int(box.cls) != 0 or float(box.conf) < 0.5:
                    continue
                    
                # Get coordinates
                x_min, y_min, x_max, y_max = map(int, box.xyxy[0])
                
                # Calculate center point based on orientation
                if self.is_vertical:
                    center = (x_max, y_min)
                else:
                    center = (x_max, y_max)
                
                # Track bag
                bag_id = self.track_bag(center, self.tracked_bags)
                current_bags[bag_id] = center
                
                # Check crossing if bag was previously tracked
                if bag_id in self.tracked_bags:
                    count_change += self.check_line_crossing(
                        center,
                        self.tracked_bags[bag_id],
                        line_pos,
                        self.is_vertical
                    )
                
                # Draw visualization
                cv2.rectangle(frame, (x_min, y_min), (x_max, y_max), (0, 255, 0), 2)
                cv2.circle(frame, center, 5, (255, 0, 0), -1)
                cv2.putText(frame, f"Bag {bag_id}", (x_min, y_min - 10),
                          cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 0), 2)
        
        return frame, current_bags, count_change

    def draw_detection_line(self, frame, line_pos):
        """Draw the detection line on the frame"""
        height, width = frame.shape[:2]
        if self.is_vertical:
            cv2.line(frame, (line_pos, 0), (line_pos, height), (255, 0, 0), 2)
        else:
            cv2.line(frame, (0, line_pos), (width, line_pos), (255, 0, 0), 2)

    def add_info_overlay(self, frame, bag_count):
        """Add information overlay to the frame"""
        # Add count and direction information
        direction_text = "Trai -> Phai" if self.count_direction == "left_to_right" else "Phai -> Trai"
        orientation = "Doc" if self.is_vertical else "Ngang"
        
        cv2.putText(frame, f"SL: {bag_count}", (10, 30),
                    cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 255, 0), 2)
        cv2.putText(frame, f"{direction_text}", (10, 70),
                    cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 255, 0), 2)
        cv2.putText(frame, f"Huong: {orientation}", (10, 110),
                    cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 255, 0), 2)

    def run(self):
        cap = None

        try:
            # Initialize model and video capture
            model = self.load_model()
            cap, fps = self.setup_video_capture()
            frame_delay = 1.0 / fps
            last_frame_time = time.time()
            
            while not self.stop_flag:
                # Get the latest parameters inside the loop using the lock
                with self._lock:
                    current_position = self._detection_line_position
                    current_is_vertical = self._is_vertical
                    current_count_direction = self._count_direction
                
                # Maintain frame rate
                current_time = time.time()
                elapsed = current_time - last_frame_time
                if elapsed < frame_delay:
                    time.sleep(frame_delay - elapsed)
                
                # Read frame
                ret, frame = cap.read()
                if not ret:
                    break
                    
                last_frame_time = time.time()
                
                # Calculate line position using the latest parameters
                height, width = frame.shape[:2]
                line_pos = int(width * current_position) if current_is_vertical \
                        else int(height * current_position)
                
                # Process frame with updated parameters
                frame, current_bags, count_change = self.process_frame(frame, model, line_pos)
                
                # Update tracking and count
                self.tracked_bags = current_bags
                self.bag_count = max(0, self.bag_count + count_change)
                
                # Draw visualizations with updated parameters
                self.draw_detection_line(frame, line_pos)
                self.add_info_overlay(frame, self.bag_count)
                
                # Emit update
                self.update_frame.emit(frame, self.bag_count)
            
            self.finished.emit(self.bag_count)
            
        except Exception as e:
            print(f"Error in detection thread: {e}")
            self.finished.emit(0)
        finally:
            if cap is not None:
                cap.release()

    def stop(self):
        """Stop the detection thread"""
        self.stop_flag = True

def main(input_source, window_name, emit_frame_signal, check_stop, cap, get_line_position, get_is_vertical, get_count_direction):
    """Legacy main function for backwards compatibility"""
    thread = DetectionThread(input_source, window_name, get_line_position(), get_is_vertical(), get_count_direction())
    thread.update_frame.connect(emit_frame_signal)
    thread.start()
    return thread.bag_count