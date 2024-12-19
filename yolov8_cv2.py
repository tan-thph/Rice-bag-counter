import cv2
import numpy as np
from ultralytics import YOLO
import time
from threading import Lock
from PyQt5.QtCore import Qt, QThread, pyqtSignal
import torch, os

# Get the directory of the current script
current_dir = os.path.dirname(os.path.abspath(__file__))
model_path = os.path.join(current_dir, 'models', 'best_yolo11_n_v15_ep100_sz320.pt')
app_dir = os.path.dirname(current_dir)
model_path = os.path.join(app_dir, 'resources', 'models', 'best_yolo11_n_v15_ep100_sz320.pt')

class DetectionThread(QThread):
    update_frame = pyqtSignal(object, int)
    finished = pyqtSignal(int)

    def __init__(self, input_source, window_name, detection_line_position, is_vertical, count_direction):
        super().__init__()
        self.input_source = input_source
        self.window_name = window_name
        self.stop_flag = False
        self._detection_line_position = detection_line_position
        self._is_vertical = is_vertical
        self._count_direction = count_direction
        self.cap = None
        self.device = torch.device('cuda' if torch.cuda.is_available() else 'cpu')
        self._lock = Lock()
        
    @property
    def count_direction(self):
        with self._lock:
            return self._count_direction

    @count_direction.setter
    def count_direction(self, value):
        with self._lock:
            self._count_direction = value


    @property
    def detection_line_position(self):
        return self._detection_line_position

    @detection_line_position.setter
    def detection_line_position(self, value):
        # Ensure thread-safe update
        self._lock(1)  # Small delay to avoid conflicts
        self._detection_line_position = value

    @property
    def is_vertical(self):
        return self._is_vertical

    @is_vertical.setter
    def is_vertical(self, value):
        self._lock(1)
        self._is_vertical = value

    def run(self):   
        try:          
            count_change = 0

            try:
                model = YOLO(model_path)
                model.to(self.device)
            except Exception as e:
                print(f"Error loading model: {e}")
                self.finished.emit(0)
                return  
            
            self.cap = cv2.VideoCapture(self.input_source)
            if not self.cap.isOpened():
                print(f"Lỗi: Không thể mở video {self.input_source}")
                return

            # Get video properties
            fps = self.cap.get(cv2.CAP_PROP_FPS)
            if isinstance(self.input_source, str) and fps > 0:
                frame_delay = 1.0 / fps
            else:
                frame_delay = 1.0 / 30

            self.cap.set(cv2.CAP_PROP_FRAME_WIDTH, 1280)
            self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 720)

            model = YOLO(model_path)
            model.to(self.device)
            
            bag_count = 0
            tracked_bags = {}
            next_bag_id = 1
            last_frame_time = time.time()

            while not self.stop_flag:
                count_change = 0
                current_time = time.time()
                elapsed = current_time - last_frame_time
                sleep_time = frame_delay - elapsed
                
                if sleep_time > 0:
                    time.sleep(sleep_time)
                
                ret, frame = self.cap.read()
                if not ret:
                    break

                last_frame_time = time.time()
                height, width = frame.shape[:2]
                
                # Get current line position and orientation
                is_vertical = self.is_vertical
                line_pos = int(width * self.detection_line_position) if is_vertical else int(height * self.detection_line_position)
                
                # Draw detection line with current settings
                if is_vertical:
                    cv2.line(frame, (line_pos, 0), (line_pos, height), (255, 0, 0), 2)
                else:
                    cv2.line(frame, (0, line_pos), (width, line_pos), (255, 0, 0), 2)

                # Process frame with YOLO
                results = model(frame, imgsz=224)
                current_bags = {}

                if len(results) > 0 and len(results[0].boxes) > 0:
                    for box in results[0].boxes:
                        if int(box.cls) == 0 and float(box.conf) > 0.5:
                            x_min, y_min, x_max, y_max = map(int, box.xyxy[0])
                            if self.is_vertical:
                                center_x = x_max
                                center_y = y_min
                            else:
                                center_x = x_max
                                center_y = y_max

                            closest_bag_id = None
                            min_distance = float('inf')
                            
                            for bag_id, (prev_x, prev_y) in tracked_bags.items():
                                distance = ((center_x - prev_x) ** 2 + (center_y - prev_y) ** 2) ** 0.5
                                if distance < min_distance and distance < 100:
                                    min_distance = distance
                                    closest_bag_id = bag_id

                            bag_id = closest_bag_id if closest_bag_id else next_bag_id
                            if not closest_bag_id:
                                next_bag_id += 1

                            current_bags[bag_id] = (center_x, center_y)

                            # Check line crossing with direction
                            if bag_id in tracked_bags:
                                prev_point = tracked_bags[bag_id]
                                cross_result = self.is_crossing_line(
                                    (center_x, center_y), 
                                    prev_point, 
                                    line_pos, 
                                    self.is_vertical,
                                    self.count_direction
                                )
                                
                                # Update count if there's a crossing
                                if cross_result != 0:
                                    new_count = bag_count + cross_result
                                    if new_count >= 0:  # Only update if result won't be negative
                                        bag_count = new_count
                                        # Add visual indicator
                                        indicator_text = "+" if cross_result > 0 else "-"
                                        indicator_color = (0, 255, 0) if cross_result > 0 else (0, 0, 255)
                                        cv2.putText(frame, indicator_text, 
                                                (center_x - 20, center_y - 20),
                                                cv2.FONT_HERSHEY_SIMPLEX, 0.7, 
                                                indicator_color, 2)

                # Update display
                direction_text = "Left → Right" if self.count_direction == "left_to_right" else "Right → Left"
                cv2.putText(frame, f"Bag count: {bag_count}", 
                            (10, 30), cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 255, 0), 2)
                cv2.putText(frame, f"Direction: {direction_text}", 
                            (10, 70), cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 255, 0), 2)

                self.update_frame.emit(frame, bag_count)

            self.finished.emit(bag_count)

        except Exception as e:
            print(f"Error in detection thread: {e}")
            self.finished.emit(0)
        finally:
            self.cleanup()

    def stop(self):
        self.stop_flag = True

    def cleanup(self):
        if hasattr(self, 'cap') and self.cap is not None:
            self.cap.release()
            self.cap = None

def main(input_source, window_name, emit_frame_signal, check_stop, cap, get_line_position, get_is_vertical, get_count_direction):
    model = YOLO(model_path)
    bag_count = 0
    tracked_bags = {}
    next_bag_id = 1
    
    ret, frame = cap.read()
    if not ret:
        print("Failed to read frame from video source")
        return 0
    
    while True:
        if check_stop():
            break

        ret, frame = cap.read()
        if not ret:
            break

        height, width = frame.shape[:2]
        
        # Get current settings for each frame
        is_vertical = get_is_vertical()
        detection_line_position = get_line_position()
        count_direction = get_count_direction()

        # Calculate line position based on current settings
        if is_vertical:
            detection_line_pos = int(width * detection_line_position)
            cv2.line(frame, (detection_line_pos, 0), (detection_line_pos, height), (255, 0, 0), 2)
        else:
            detection_line_pos = int(height * detection_line_position)
            cv2.line(frame, (0, detection_line_pos), (width, detection_line_pos), (255, 0, 0), 2)

        # Process frame
        results = model(frame, imgsz=224)
        current_bags = {}

        if results and len(results[0].boxes) > 0:
            for box in results[0].boxes:
                if int(box.cls) == 0 and float(box.conf) > 0.5:  # Bag detection with confidence threshold
                    x_min, y_min, x_max, y_max = map(int, box.xyxy[0])
                    confidence = float(box.conf)

                    # Calculate center point based on current orientation
                    if is_vertical:
                        center_x = x_max
                        center_y = y_min
                    else:
                        center_x = x_max
                        center_y = y_max

                    # Track bags
                    closest_bag_id = None
                    min_distance = float('inf')
                    for bag_id, (prev_x, prev_y) in tracked_bags.items():
                        distance = ((center_x - prev_x) ** 2 + (center_y - prev_y) ** 2) ** 0.5
                        if distance < min_distance and distance < 100:
                            min_distance = distance
                            closest_bag_id = bag_id

                    bag_id = closest_bag_id if closest_bag_id else next_bag_id
                    if not closest_bag_id:
                        next_bag_id += 1

                    current_bags[bag_id] = (center_x, center_y)

                    # Check line crossing with direction
                    if bag_id in tracked_bags:
                        prev_point = tracked_bags[bag_id]
                        cross_result = is_crossing_line(
                            (center_x, center_y),
                            prev_point,
                            detection_line_pos,
                            is_vertical,
                            count_direction
                        )
                        
                        # Update bag count and display crossing indicator
                        if cross_result != 0 and bag_count + cross_result >= 0:  # Prevent negative counts
                            bag_count += cross_result
                            
                            # Add direction indicator
                            direction_text = "+" if cross_result > 0 else "-"
                            color = (0, 255, 0) if cross_result > 0 else (0, 0, 255)
                            cv2.putText(frame, direction_text, 
                                    (center_x - 20, center_y - 20),
                                    cv2.FONT_HERSHEY_SIMPLEX, 0.7, 
                                    color, 2)

                    # Draw visualization
                    cv2.rectangle(frame, (x_min, y_min), (x_max, y_max), (0, 255, 0), 2)
                    cv2.putText(frame, f"Bag {bag_id}: {confidence:.2f}", 
                              (x_min, y_min - 10),
                              cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 0), 2)
                    cv2.circle(frame, (center_x, center_y), 5, (255, 0, 0), -1)

        # Update display info
        direction_text = "Left → Right" if count_direction == "left_to_right" else "Right → Left"
        orientation = "Thanh dọc" if is_vertical else "Thanh ngang"
        cv2.putText(frame, f"Bag count: {bag_count}", 
                   (10, 30), cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 255, 0), 2)
        cv2.putText(frame, f"Direction: {direction_text}", 
                   (10, 70), cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 255, 0), 2)

        tracked_bags = current_bags.copy()
        emit_frame_signal(frame, bag_count)

    return bag_count

def is_crossing_line(point, prev_point, line_pos, is_vertical, count_direction="left_to_right"):
    if is_vertical:
        # For vertical line crossing
        # Check if the point actually crossed the line
        if (prev_point[0] - line_pos) * (point[0] - line_pos) <= 0:  # This means a crossing occurred
            if count_direction == "left_to_right":
                # Moving left to right (positive direction)
                if prev_point[0] < line_pos:
                    return 1
                # Moving right to left (negative direction)
                else:
                    return -1
            else:  # right_to_left
                # Moving right to left (positive direction)
                if prev_point[0] > line_pos:
                    return 1
                # Moving left to right (negative direction)
                else:
                    return -1
    else:
        # For horizontal line crossing
        # Check if the point actually crossed the line
        if (prev_point[1] - line_pos) * (point[1] - line_pos) <= 0:  # This means a crossing occurred
            if count_direction == "left_to_right":  # top to bottom
                # Moving top to bottom (positive direction)
                if prev_point[1] < line_pos:
                    return 1
                # Moving bottom to top (negative direction)
                else:
                    return -1
            else:  # right_to_left (bottom to top)
                # Moving bottom to top (positive direction)
                if prev_point[1] > line_pos:
                    return 1
                # Moving top to bottom (negative direction)
                else:
                    return -1
    
    return 0  # No crossing