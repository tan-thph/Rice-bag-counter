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
        # Keep existing initialization
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
        
        # Add new variables for duplicate prevention
        self.recent_counts = []  # List of (x, y, timestamp) tuples
        self.min_distance = 50   # Minimum pixels between counts
        self.count_timeout = 0.7 # Seconds to wait before counting in same area
        
        # Initialize zone tracking
        self.bags_in_zone = {}  # {bag_id: (position, entry_time, last_seen_time)}
        self.disappeared_positions = {}  # Track last positions of disappeared bags
        self.reappearance_threshold = 0.5  # Time threshold for considering reappearance (seconds)
        self.zone_entry_positions = {}  # Track where bags entered the zone
        
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

    def check_duplicate_count(self, x, y, current_time):
        """Check if a point is too close to recently counted points"""
        # Remove old counts based on timeout
        self.recent_counts = [(px, py, pt) for px, py, pt in self.recent_counts 
                            if current_time - pt < self.count_timeout]

        # Check distance to all recent count positions
        for px, py, _ in self.recent_counts:
            distance = np.sqrt((x - px)**2 + (y - py)**2)
            if distance < self.min_distance:
                return False  # Too close to recent count

        # Add new count position
        self.recent_counts.append((x, y, current_time))
        return True

    def check_line_crossing(self, current_point, prev_point, line_pos, is_vertical):
        """Modified check_line_crossing with duplicate prevention"""
        try:
            current_time = time.time()
            
            if is_vertical:
                # For vertical line
                crossed = (prev_point[0] - line_pos) * (current_point[0] - line_pos) <= 0
                if crossed:
                    # Check for duplicates before counting
                    if not self.check_duplicate_count(current_point[0], current_point[1], current_time):
                        return 0
                        
                    if self.count_direction == "left_to_right":
                        return 1 if prev_point[0] < line_pos else -1
                    else:
                        return 1 if prev_point[0] > line_pos else -1
            else:
                # For horizontal line
                crossed = (prev_point[1] - line_pos) * (current_point[1] - line_pos) <= 0
                if crossed:
                    # Check for duplicates before counting
                    if not self.check_duplicate_count(current_point[0], current_point[1], current_time):
                        return 0
                        
                    if self.count_direction == "left_to_right":
                        return 1 if current_point[0] > prev_point[0] else -1
                    else:
                        return 1 if current_point[0] < prev_point[0] else -1
            return 0
        except Exception as e:
            print(f"Error in check_line_crossing: {e}")
            return 0

    def process_frame(self, frame, model, line_pos):
        """Process frame with improved tracking and cleanup"""
        try:
            height, width = frame.shape[:2]
            frame_size = (width, height)
            current_time = time.time()
            
            results = model(frame, verbose=False)
            current_bags = {}
            count_change = 0
            current_bag_ids = set()
            
            # Process detected bags
            if len(results) > 0:
                for r in results:
                    boxes = r.boxes
                    for box in boxes:
                        try:
                            if float(box.conf) < 0.6:
                                continue
                                
                            x_min, y_min, x_max, y_max = map(int, box.xyxy[0])
                            center = (x_max, y_min)
                            
                            bag_id = self.track_bag(center, self.tracked_bags)
                            current_bags[bag_id] = center
                            current_bag_ids.add(bag_id)
                            
                            if bag_id in self.tracked_bags:
                                crossing_result = self.check_zone_crossing(
                                    center,
                                    self.tracked_bags[bag_id],
                                    line_pos,
                                    self.is_vertical,
                                    frame_size,
                                    bag_id
                                )
                                count_change += crossing_result if crossing_result is not None else 0
                            
                            # Draw visualization
                            cv2.rectangle(frame, (x_min, y_min), (x_max, y_max), (0, 255, 0), 2)
                            cv2.circle(frame, center, 5, (255, 0, 0), -1)
                            cv2.putText(frame, f"Bag {bag_id}", (x_min, y_min - 10),
                                    cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 0), 2)
                                    
                            # Draw movement vector
                            if bag_id in self.tracked_bags:
                                prev_pos = self.tracked_bags[bag_id]
                                cv2.arrowedLine(frame, prev_pos, center, (0, 255, 255), 2)
                                
                        except Exception as box_error:
                            print(f"Error processing box: {box_error}")
                            continue
            
            # Handle disappeared bags and cleanup
            disappeared_bags = []
            for bag_id in list(self.bags_in_zone.keys()):
                if bag_id not in current_bag_ids:
                    last_seen_time = self.bags_in_zone[bag_id][2]
                    if current_time - last_seen_time > 0.5:  # If bag hasn't been seen for 0.5 seconds
                        disappeared_bags.append(bag_id)
                        # Only count the bag once when it disappears
                        if bag_id not in self.disappeared_positions:
                            crossing_result = self.handle_disappeared_bag(bag_id, frame_size, line_pos)
                            count_change += crossing_result
            
            # Clean up disappeared bags
            for bag_id in disappeared_bags:
                if bag_id in self.bags_in_zone:
                    del self.bags_in_zone[bag_id]
                if bag_id in self.zone_entry_positions:
                    del self.zone_entry_positions[bag_id]
            
            # Update tracked bags
            self.tracked_bags = current_bags
            
            # Debug information
            print(f"Current frame stats:")
            print(f"- Active bags: {len(current_bags)}")
            print(f"- Bags in zone: {len(self.bags_in_zone)}")
            print(f"- Count change this frame: {count_change}")
            
            return frame, current_bags, count_change
            
        except Exception as e:
            print(f"Error in process_frame: {e}")
            return frame, {}, 0


    def draw_detection_line(self, frame, line_pos):
        """Draw the detection line on the frame"""
        height, width = frame.shape[:2]
        if self.is_vertical:
            cv2.line(frame, (line_pos, 0), (line_pos, height), (255, 0, 0), 2)
        else:
            cv2.line(frame, (0, line_pos), (width, line_pos), (255, 0, 0), 2)

    def draw_detection_zone(self, frame, line_pos):
        """Draw the detection zone on the frame"""
        height, width = frame.shape[:2]
        
        if self.is_vertical:
            zone_width = int(width * 0.08)  # 8% of frame width
            # Draw main detection line
            cv2.line(frame, (line_pos, 0), (line_pos, height), (255, 0, 0), 2)
            # Draw zone boundaries
            cv2.line(frame, (line_pos - zone_width, 0), (line_pos - zone_width, height), (255, 0, 0), 1)
            cv2.line(frame, (line_pos + zone_width, 0), (line_pos + zone_width, height), (255, 0, 0), 1)
            # Fill zone with semi-transparent color
            overlay = frame.copy()
            cv2.rectangle(overlay, (line_pos - zone_width, 0), (line_pos + zone_width, height), (255, 0, 0), -1)
            cv2.addWeighted(overlay, 0.2, frame, 0.8, 0, frame)
        else:
            zone_height = int(height * 0.08)  # 8% of frame height
            # Draw main detection line
            cv2.line(frame, (0, line_pos), (width, line_pos), (255, 0, 0), 2)
            # Draw zone boundaries
            cv2.line(frame, (0, line_pos - zone_height), (width, line_pos - zone_height), (255, 0, 0), 1)
            cv2.line(frame, (0, line_pos + zone_height), (width, line_pos + zone_height), (255, 0, 0), 1)
            # Fill zone with semi-transparent color
            overlay = frame.copy()
            cv2.rectangle(overlay, (0, line_pos - zone_height), (width, line_pos + zone_height), (255, 0, 0), -1)
            cv2.addWeighted(overlay, 0.2, frame, 0.8, 0, frame)


    def check_zone_crossing(self, current_point, prev_point, line_pos, is_vertical, frame_size, bag_id):
        """Enhanced zone crossing detection with improved tracking"""
        try:
            current_time = time.time()
            current_in_zone = self.is_point_in_zone(current_point, line_pos, frame_size)
            
            #print(f"Bag {bag_id} - In zone: {current_in_zone}, Position: {current_point}")
            
            # Handle new appearance inside zone
            if current_in_zone and bag_id not in self.bags_in_zone:
                #print(f"Bag {bag_id} appeared inside zone")
                self.bags_in_zone[bag_id] = (current_point, current_time, current_time)
                self.zone_entry_positions[bag_id] = current_point
                return 0

            # Update tracking for existing bags
            if current_in_zone:
                if bag_id in self.bags_in_zone:
                    #print(f"Bag {bag_id} still in zone")
                    self.bags_in_zone[bag_id] = (current_point, 
                                            self.bags_in_zone[bag_id][1],
                                            current_time)
                else:
                    #print(f"Bag {bag_id} entered zone")
                    self.bags_in_zone[bag_id] = (current_point, current_time, current_time)
                    self.zone_entry_positions[bag_id] = current_point
            elif bag_id in self.bags_in_zone:
                # Bag is exiting the zone
                entry_pos = self.zone_entry_positions.get(bag_id)
                if entry_pos:
                    #print(f"Bag {bag_id} exiting zone. Entry pos: {entry_pos}, Exit pos: {current_point}")
                    
                    # Calculate movement
                    dx = current_point[0] - entry_pos[0]
                    
                    # Clean up tracking before counting
                    del self.bags_in_zone[bag_id]
                    del self.zone_entry_positions[bag_id]
                    
                    # Check for duplicates
                    if not self.check_duplicate_count(current_point[0], current_point[1], current_time):
                        #print(f"Bag {bag_id} too close to recent count")
                        return 0
                    
                    # Count based on movement
                    if abs(dx) > 20:  # Minimum movement threshold
                        moving_right = dx > 0
                        if self.count_direction == "left_to_right":
                            count_value = 1 if moving_right else -1
                        else:
                            count_value = 1 if not moving_right else -1
                        #print(f"Bag {bag_id} counted: {count_value} (dx={dx})")
                        return count_value
                    else:
                        print(f"Bag {bag_id} had insufficient movement (dx={dx})")
                        
            return 0
            
        except Exception as e:
            print(f"Error in check_zone_crossing: {e}")
            return 0

    def is_point_in_zone(self, point, line_pos, frame_size):
        """Helper to check if a point is in the zone"""
        if self.is_vertical:
            zone_width = frame_size[0] * 0.1
            zone_start = line_pos - zone_width
            zone_end = line_pos + zone_width
            return zone_start <= point[0] <= zone_end
        else:
            zone_height = frame_size[1] * 0.1
            zone_start = line_pos - zone_height
            zone_end = line_pos + zone_height
            return zone_start <= point[1] <= zone_end

    def handle_disappeared_bag(self, bag_id, frame_size, line_pos):
        """Handle counting logic for disappeared bags"""
        try:
            if bag_id in self.bags_in_zone:
                last_position = self.bags_in_zone[bag_id][0]
                entry_position = self.zone_entry_positions.get(bag_id)
                
                # Store the last known position
                self.disappeared_positions[bag_id] = (last_position, time.time())
                
                # If bag disappeared while in zone, determine count based on entry vs last position
                if entry_position:
                    # Calculate movement
                    dx = last_position[0] - entry_position[0]
                    
                    # For vertical detection line
                    if self.is_vertical:
                        if abs(dx) > 20:  # Minimum movement threshold
                            moving_right = dx > 0
                            if self.count_direction == "left_to_right":
                                count_value = 1 if moving_right else -1
                            else:
                                count_value = 1 if not moving_right else -1
                            #print(f"Disappeared bag {bag_id} counted: {count_value} (dx={dx})")
                            return count_value
                        else:
                            print(f"Disappeared bag {bag_id} had insufficient movement (dx={dx})")
                    else:
                        # Similar logic for horizontal line
                        if abs(dx) > 20:
                            moving_right = dx > 0
                            if self.count_direction == "left_to_right":
                                count_value = 1 if moving_right else -1
                            else:
                                count_value = 1 if not moving_right else -1
                            print(f"Disappeared bag {bag_id} counted: {count_value} (dx={dx})")
                            return count_value
                        else:
                            print(f"Disappeared bag {bag_id} had insufficient movement (dx={dx})")
                
            return 0
                
        except Exception as e:
            print(f"Error handling disappeared bag: {e}")
            return 0


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
                self.draw_detection_zone(frame, line_pos)  # Changed from draw_detection_line
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
