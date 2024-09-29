import cv2
import numpy as np
from ultralytics import YOLO
import torch, logging

logger = logging.getLogger(__name__)

class RiceBagDetector:
    def __init__(self, model_path, detection_line_position=0.5, is_vertical=True, desired_direction=1):
        self.device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
        self.model = YOLO(model_path).to(self.device)
        self.detection_line_position = detection_line_position
        self.is_vertical = is_vertical
        self.desired_direction = desired_direction  # 1 for left to right or top to bottom, -1 for opposite
        self.bag_count = 0
        self.tracked_bags = {}
        self.next_bag_id = 1
        self.frame_count = 0
        self.process_every_n_frames = 1
        self.arrow_color = (0, 255, 255)

        # Optimize model for inference
        self.model.conf = 0.25
        self.model.iou = 0.45
        if self.device.type != 'cpu':
            self.model.fuse()

    def update_line_position(self, new_position):
        self.detection_line_position = new_position

    def update_line_orientation(self, is_vertical):
        self.is_vertical = is_vertical

    def update_desired_direction(self, new_direction):
        if new_direction in (1, -1):
            self.desired_direction = new_direction
        else:
            raise ValueError("Desired direction must be either 1 or -1")

    def draw_direction_arrow(self, frame):
        height, width = frame.shape[:2]
        center_x, center_y = width // 2, height // 2
        arrow_length = min(width, height) // 10  # Adjust this value to change arrow size

        # Always draw horizontal arrow
        if self.desired_direction == 1:  # Left to right
            start_point = (center_x - arrow_length // 2, center_y)
            end_point = (center_x + arrow_length // 2, center_y)
        else:  # Right to left
            start_point = (center_x + arrow_length // 2, center_y)
            end_point = (center_x - arrow_length // 2, center_y)

        cv2.arrowedLine(frame, start_point, end_point, self.arrow_color, 2, tipLength=0.3)

        # Add text to indicate loading/unloading
        text = "Loading" if self.desired_direction == 1 else "Unloading"
        text_size = cv2.getTextSize(text, cv2.FONT_HERSHEY_SIMPLEX, 0.5, 1)[0]
        text_x = center_x - text_size[0] // 2
        text_y = center_y + arrow_length // 2 + 20
        cv2.putText(frame, text, (text_x, text_y), cv2.FONT_HERSHEY_SIMPLEX, 0.5, self.arrow_color, 1)

    def process_frame(self, frame):
        self.frame_count += 1
        if self.frame_count % self.process_every_n_frames != 0:
            return frame, self.bag_count

        if frame is None:
            logger.error("Received None frame in process_frame method")
            return frame, self.bag_count

        native_height, native_width = frame.shape[:2]
        try:
            if self.is_vertical:
                detection_line_pos = int(native_width * self.detection_line_position)
                detection_line = [(detection_line_pos, 0), (detection_line_pos, native_height)]
            else:
                detection_line_pos = int(native_height * self.detection_line_position)
                detection_line = [(0, detection_line_pos), (native_width, detection_line_pos)]

            resized_frame = cv2.resize(frame, (640, 640))
            frame_tensor = torch.from_numpy(resized_frame).to(self.device).permute(2, 0, 1).float() / 255.0
            frame_tensor = frame_tensor.unsqueeze(0)

            results = self.model(frame_tensor, conf=0.25, imgsz=224)[0]

            current_bags = {}
            for box in results.boxes:
                class_label = int(box.cls)
                if class_label == 0:  # Assuming class 0 is 'bag'
                    x_min, y_min, x_max, y_max = map(int, box.xyxy[0].cpu().numpy())
                    x_min = int(x_min * native_width / 640)
                    x_max = int(x_max * native_width / 640)
                    y_min = int(y_min * native_height / 640)
                    y_max = int(y_max * native_height / 640)
                    
                    confidence = float(box.conf)
                    
                    center_x = (x_max)
                    center_y = (y_min)

                    closest_bag_id = self.find_closest_bag(center_x, center_y)

                    if closest_bag_id and self.calculate_distance(center_x, center_y, *self.tracked_bags[closest_bag_id]) < 100:
                        bag_id = closest_bag_id
                    else:
                        bag_id = self.next_bag_id
                        self.next_bag_id += 1

                    current_bags[bag_id] = (center_x, center_y)

                    if bag_id in self.tracked_bags:
                        prev_point = self.tracked_bags[bag_id]
                        crossed, direction = self.is_crossing_line((center_x, center_y), prev_point, detection_line_pos)
                        if crossed:
                            if direction == self.desired_direction:  # Moving in the desired direction
                                self.bag_count = max(0, self.bag_count + 1)
                            else:  # Moving against the desired direction
                                self.bag_count = max(0, self.bag_count - 1)

                    cv2.rectangle(frame, (x_min, y_min), (x_max, y_max), (0, 255, 0), 2)
                    cv2.putText(frame, f"Bag {bag_id}: {confidence:.2f}", (x_min, y_min - 10), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 0), 2)
                    cv2.circle(frame, (center_x, center_y), 5, (255, 0, 0), -1)

            cv2.line(frame, detection_line[0], detection_line[1], (255, 0, 0), 2)
            cv2.putText(frame, f"Bag Count: {self.bag_count}", (10, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 0), 2)

            # Draw the direction arrow
            self.draw_direction_arrow(frame)

            self.tracked_bags = current_bags
            
        except Exception as e:
            logger.error(f"Error in process_frame: {str(e)}")
            return frame, self.bag_count

        return frame, self.bag_count

    def find_closest_bag(self, x, y):
        closest_bag_id = None
        min_distance = float('inf')
        for bag_id, (prev_x, prev_y) in self.tracked_bags.items():
            distance = self.calculate_distance(x, y, prev_x, prev_y)
            if distance < min_distance:
                min_distance = distance
                closest_bag_id = bag_id
        return closest_bag_id

    @staticmethod
    def calculate_distance(x1, y1, x2, y2):
        return ((x1 - x2) ** 2 + (y1 - y2) ** 2) ** 0.5

    def is_crossing_line(self, point, prev_point, line_pos):
        if self.is_vertical:
            crossed = (prev_point[0] < line_pos and point[0] >= line_pos) or (prev_point[0] > line_pos and point[0] <= line_pos)
            if crossed:
                direction = 1 if point[0] > prev_point[0] else -1
            else:
                direction = 0
        else:
            crossed = (prev_point[1] < line_pos and point[1] >= line_pos) or (prev_point[1] > line_pos and point[1] <= line_pos)
            if crossed:
                direction = 1 if point[1] > prev_point[1] else -1
            else:
                direction = 0
        return crossed, direction