import cv2, logging, os, torch, threading, gc, time
import numpy as np
from ultralytics import YOLO

from threading import Lock, Thread
from PyQt5.QtCore import QThread, pyqtSignal
 
from pathlib import Path
from queue import Queue
from collections import deque



class BagTracker:
    def __init__(self, confidence_threshold=0.5):
        self.tracked_bags = {}
        self.next_bag_id = 1
        self.confidence_threshold = confidence_threshold
        self.zone_history = {}
        self.movement_history = deque(maxlen=30)
        self.min_movement_threshold = 20
        self.disappeared_bags = {}
        self.disappear_timeout = 0.5
        self.last_known_positions = {}
        self.last_count_time = 0
        self.count_cooldown = 1.5
        self.counted_bags = set()
        self.processed_disappearances = set()  # New: Track which disappearances we've processed
        self._lock = Lock()

    def update(self, detections, frame_size, line_pos, is_vertical, count_direction):
        """Update tracking with improved reappearance handling"""
        with self._lock:
            current_bags = {}
            count_change = 0
            current_time = time.time()
            self.counted_bags.add(bag_id)
            
            if current_time - self.last_count_time < self.count_cooldown:
                return 0, current_bags

            # Process new detections
            for detection in detections:
                if float(detection.conf) < self.confidence_threshold:
                    continue
                    
                x_min, y_min, x_max, y_max = map(int, detection.xyxy[0])
                center = (int((x_min + x_max) / 2), int((y_min + y_max) / 2))
                
                bag_id = self._track_bag(center)
                current_bags[bag_id] = center
                self.last_known_positions[bag_id] = center
                
                # Handle reappeared bags
                if bag_id in self.disappeared_bags:
                    # Remove from disappeared bags without additional processing
                    # if it was already counted or processed
                    if bag_id in self.counted_bags or bag_id in self.processed_disappearances:
                        del self.disappeared_bags[bag_id]
                        continue
                        
                    # Otherwise, process normally
                    del self.disappeared_bags[bag_id]
                
                # Update zone tracking
                if self._is_in_detection_zone(center, line_pos, frame_size, is_vertical):
                    if bag_id not in self.zone_history:
                        self.zone_history[bag_id] = []
                    self.zone_history[bag_id].append(center)
                    
                    # Only check for crossing if not already counted
                    if len(self.zone_history[bag_id]) >= 2 and bag_id not in self.counted_bags:
                        crossing = self._check_valid_crossing(
                            bag_id, line_pos, is_vertical, count_direction, frame_size
                        )
                        if crossing:
                            count_change += crossing
                            self.counted_bags.add(bag_id)
                            self.processed_disappearances.add(bag_id)
                            self.last_count_time = current_time
                            del self.zone_history[bag_id]

            # Handle disappeared bags
            disappeared_ids = set(self.tracked_bags.keys()) - set(current_bags.keys())
            for bag_id in disappeared_ids:
                if bag_id not in self.disappeared_bags and bag_id not in self.counted_bags:
                    last_pos = self.last_known_positions.get(bag_id)
                    if last_pos:
                        in_zone = bag_id in self.zone_history
                        self.disappeared_bags[bag_id] = (last_pos, current_time, in_zone)

            # Process disappeared bags
            additional_count = self._process_disappeared_bags(
                current_time, line_pos, is_vertical, count_direction, frame_size
            )
            count_change += additional_count

            # Update tracking data
            self._cleanup_tracking(current_bags, current_time)
            self.tracked_bags = current_bags

            return count_change, current_bags

    def _is_near_zone_exit(self, point, line_pos, frame_size, is_vertical, count_direction):
        """Check if a point is near the exit of the detection zone"""
        width, height = frame_size
        zone_width = width * 0.1 if is_vertical else height * 0.1
        
        if is_vertical:
            # For vertical line
            if count_direction == "left_to_right":
                return point[0] > line_pos and abs(point[0] - line_pos) <= zone_width/2
            else:
                return point[0] < line_pos and abs(point[0] - line_pos) <= zone_width/2
        else:
            # For horizontal line
            if count_direction == "left_to_right":
                return point[1] < line_pos and abs(point[1] - line_pos) <= zone_width/2
            else:
                return point[1] > line_pos and abs(point[1] - line_pos) <= zone_width/2

    def _track_bag(self, current_point, max_distance=100):
        """Track bag with movement prediction"""
        closest_bag_id = None
        min_distance = float('inf')
        
        for bag_id, prev_point in self.tracked_bags.items():
            predicted_point = self._predict_position(bag_id, prev_point)
            distance = np.sqrt(
                (current_point[0] - predicted_point[0])**2 + 
                (current_point[1] - predicted_point[1])**2
            )
            
            if distance < min_distance and distance < max_distance:
                min_distance = distance
                closest_bag_id = bag_id
        
        if closest_bag_id is None:
            closest_bag_id = self.next_bag_id
            self.next_bag_id += 1
        
        return closest_bag_id

    def _predict_position(self, bag_id, prev_point):
        """Predict next position based on movement history"""
        if bag_id in self.zone_history and len(self.zone_history[bag_id]) >= 2:
            recent_points = self.zone_history[bag_id][-2:]
            dx = recent_points[1][0] - recent_points[0][0]
            dy = recent_points[1][1] - recent_points[0][1]
            return (prev_point[0] + dx, prev_point[1] + dy)
        return prev_point

    def _is_in_detection_zone(self, point, line_pos, frame_size, is_vertical):
        """Check if point is within detection zone"""
        width, height = frame_size
        if is_vertical:
            zone_width = width * 0.1
            return abs(point[0] - line_pos) <= zone_width/2
        else:
            zone_height = height * 0.1
            return abs(point[1] - line_pos) <= zone_height/2

    def _check_valid_crossing(self, bag_id, line_pos, is_vertical, count_direction, frame_size):
        history = self.zone_history[bag_id]
        if len(history) < 2:
            return 0
            
        start_pos = history[0]
        current_pos = history[-1]
        movement = self._calculate_movement(start_pos, current_pos, is_vertical)
        
        if movement < self.min_movement_threshold:
            return 0

        # Determine actual screen movement direction (left-to-right or right-to-left)
        moving_right = current_pos[0] > start_pos[0]
        moving_left = current_pos[0] < start_pos[0]
        
        if is_vertical:
            crossed_forward = start_pos[0] < line_pos and current_pos[0] > line_pos
            crossed_backward = start_pos[0] > line_pos and current_pos[0] < line_pos

        else:
            crossed_forward = start_pos[1] > line_pos and current_pos[1] < line_pos
            crossed_backward = start_pos[1] < line_pos and current_pos[1] > line_pos
        
        # Determine count based on actual movement direction
        if count_direction == "left_to_right":
            if moving_right and (crossed_forward or crossed_backward):
                return 1
            elif moving_left and (crossed_forward or crossed_backward):
                return -1
        else:  # right_to_left
            if moving_left and (crossed_forward or crossed_backward):
                return 1
            elif moving_right and (crossed_forward or crossed_backward):
                return -1
        return 0


    def _calculate_movement(self, start_pos, current_pos, is_vertical):
        """Calculate total movement distance"""
        return abs(current_pos[0] - start_pos[0]) if is_vertical else abs(current_pos[1] - start_pos[1])

    def _process_disappeared_bags(self, current_time, line_pos, is_vertical, count_direction, frame_size):
        """Process disappeared bags with stricter double-counting prevention"""
        count_change = 0
        to_remove = []
        
        for bag_id, (last_pos, disappear_time, in_zone) in self.disappeared_bags.items():
            # Skip if we haven't waited long enough
            if current_time - disappear_time < self.disappear_timeout:
                continue
                
            # Skip if already counted or processed
            if bag_id in self.counted_bags or bag_id in self.processed_disappearances:
                to_remove.append(bag_id)
                continue
            
            # Only process bags that disappeared while in the zone and haven't been processed
            if in_zone and bag_id not in self.processed_disappearances:
                if bag_id in self.zone_history and len(self.zone_history[bag_id]) >= 2:
                    start_pos = self.zone_history[bag_id][0]
                    end_pos = self.zone_history[bag_id][-1]
                    
                    # Check if the bag was moving towards the exit AND close to the line
                    moving_towards_exit = self._is_moving_towards_exit(
                        start_pos, end_pos, line_pos, is_vertical, count_direction
                    )
                    
                    near_exit = self._is_near_zone_exit(
                        end_pos, line_pos, frame_size, is_vertical, count_direction
                    )
                    
                    # Only count if both conditions are met
                    if moving_towards_exit and near_exit:
                        count_change += 1
                        self.counted_bags.add(bag_id)
                        
            # Always mark as processed once we've handled it
            self.processed_disappearances.add(bag_id)
            to_remove.append(bag_id)
        
        # Clean up processed bags
        for bag_id in to_remove:
            self.disappeared_bags.pop(bag_id, None)
        
        return count_change

    def _is_moving_towards_exit(self, start_pos, end_pos, line_pos, is_vertical, count_direction):
        # Determine actual screen movement direction
        moving_right = end_pos[0] > start_pos[0]
        moving_left = end_pos[0] < start_pos[0]
        
        # Count based on actual movement matching count direction
        if count_direction == "left_to_right":
            return moving_right
        else:  # right_to_left
            return moving_left
                
    def _cleanup_tracking(self, current_bags, current_time):
        """Clean up tracking data with improved state preservation"""
        # Clean up zone history for bags that are no longer in the zone
        for bag_id in list(self.zone_history.keys()):
            if bag_id not in current_bags and bag_id not in self.disappeared_bags:
                del self.zone_history[bag_id]
        
        # Clean up position history for completely gone bags
        for bag_id in list(self.last_known_positions.keys()):
            if (bag_id not in current_bags and 
                bag_id not in self.disappeared_bags and 
                bag_id not in self.counted_bags):
                del self.last_known_positions[bag_id]
        
        # Only remove from processed_disappearances if the bag is completely gone
        # and has been counted
        for bag_id in list(self.processed_disappearances):
            if (bag_id not in current_bags and 
                bag_id not in self.disappeared_bags and 
                bag_id not in self.last_known_positions and
                bag_id in self.counted_bags):
                self.processed_disappearances.remove(bag_id)
                
        # Clean up counted_bags only for completely gone bags
        for bag_id in list(self.counted_bags):
            if (bag_id not in current_bags and 
                bag_id not in self.disappeared_bags and 
                bag_id not in self.last_known_positions and
                bag_id not in self.zone_history):
                self.counted_bags.remove(bag_id)