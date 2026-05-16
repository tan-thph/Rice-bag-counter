import cv2
import torch
import logging
from collections import deque

logger = logging.getLogger(__name__)

# ── Tuning knobs ────────────────────────────────────────────────────────────
MAX_FRAMES_MISSING  = 20   # frames to keep a ghost track alive for re-association
BASE_MATCH_DIST     = 120  # base pixel distance for matching a detection to a track
VELOCITY_ALPHA      = 0.4  # EMA smoothing for velocity (higher = faster adaptation)
# ────────────────────────────────────────────────────────────────────────────


class TrackedBag:
    """Per-bag state: position history, smoothed velocity, zone membership."""

    def __init__(self, bag_id, center, bbox, zone, frame_count):
        self.bag_id        = bag_id
        self.positions     = deque([center], maxlen=10)
        self.bbox          = bbox
        self.zone          = zone                            # 'A' | 'B' | 'crossing'
        # committed_zone: last zone where the bag was *fully* inside (not crossing).
        # None means we have not seen it fully inside any zone yet.
        self.committed_zone = zone if zone in ('A', 'B') else None
        self.frames_missing = 0
        self.velocity       = (0.0, 0.0)                    # smoothed px/frame

    # ── Position helpers ─────────────────────────────────────────────────────

    @property
    def center(self):
        return self.positions[-1]

    @property
    def predicted_center(self):
        """Linear extrapolation: last position + velocity × ghost age."""
        cx, cy = self.positions[-1]
        steps  = self.frames_missing + 1
        return (cx + self.velocity[0] * steps,
                cy + self.velocity[1] * steps)

    # ── Update ───────────────────────────────────────────────────────────────

    def _update_velocity(self, new_center):
        raw_vx = new_center[0] - self.positions[-1][0]
        raw_vy = new_center[1] - self.positions[-1][1]
        self.velocity = (
            VELOCITY_ALPHA * raw_vx + (1 - VELOCITY_ALPHA) * self.velocity[0],
            VELOCITY_ALPHA * raw_vy + (1 - VELOCITY_ALPHA) * self.velocity[1],
        )

    def update(self, center, bbox, zone, frame_count):
        self._update_velocity(center)
        self.positions.append(center)
        self.bbox           = bbox
        self.zone           = zone
        # Only commit to a zone when the bag is fully inside it
        if zone in ('A', 'B'):
            self.committed_zone = zone
        self.frames_missing = 0


class RiceBagDetector:
    """
    Zone-based rice bag counter with ghost tracking and velocity prediction.

    Counting model
    ──────────────
    The detection line divides the frame into two zones:
      Zone A  – fully on the 'left' (or 'above') side of the line
      Zone B  – fully on the 'right' (or 'below') side of the line
      crossing – bounding box straddles the line

    A count fires only when a bag's *committed zone* transitions A↔B, meaning
    the entire bounding box has cleared the line.  A→crossing→A bounce-backs
    do not count.

    Ghost tracking
    ──────────────
    When a detection disappears (occluded mid-crossing, model missed it, etc.)
    the track is kept alive as a "ghost" for MAX_FRAMES_MISSING frames.  Each
    frame the ghost's predicted position advances by its smoothed velocity.  If
    a new detection lands within the adaptive match threshold it is re-associated
    to the ghost, inheriting its zone history.

    This handles the key scenario: bag disappears in Zone A, YOLO loses it while
    it crosses the line, bag reappears in Zone B → still matched → A→B counted.
    """

    def __init__(self, model_path, detection_line_position=0.5,
                 is_vertical=True, desired_direction=1):
        from ultralytics import YOLO
        self.device = torch.device('cuda' if torch.cuda.is_available() else 'cpu')
        self.model  = YOLO(model_path).to(self.device)
        self.model.conf = 0.25
        self.model.iou  = 0.45
        if self.device.type != 'cpu':
            self.model.fuse()

        self.detection_line_position = detection_line_position
        self.is_vertical             = is_vertical
        self.desired_direction       = desired_direction

        self.bag_count    = 0
        self.tracked_bags = {}   # {bag_id: TrackedBag}
        self.next_bag_id  = 1
        self.frame_count  = 0
        self.arrow_color  = (0, 255, 255)   # BGR yellow

    # ── Public API ────────────────────────────────────────────────────────────

    def update_line_position(self, new_position):
        self.detection_line_position = new_position

    def update_line_orientation(self, is_vertical):
        self.is_vertical = is_vertical

    def update_desired_direction(self, new_direction):
        if new_direction in (1, -1):
            self.desired_direction = new_direction
        else:
            raise ValueError('Desired direction must be 1 or -1')

    # ── Zone helpers ──────────────────────────────────────────────────────────

    def _get_zone(self, bbox, line_pos):
        """
        'A'        – entire bbox is left of (or above) the line
        'B'        – entire bbox is right of (or below) the line
        'crossing' – bbox straddles the line
        """
        x_min, y_min, x_max, y_max = bbox
        if self.is_vertical:
            if x_max < line_pos:   return 'A'
            if x_min > line_pos:   return 'B'
        else:
            if y_max < line_pos:   return 'A'
            if y_min > line_pos:   return 'B'
        return 'crossing'

    # ── Tracking ──────────────────────────────────────────────────────────────

    def _match_to_track(self, center, already_matched):
        """
        Greedy nearest-predicted-centre match.
        The match threshold expands with ghost age and bag speed so that a fast
        bag that was missing for several frames can still be re-associated.
        """
        best_id   = None
        best_dist = float('inf')

        for bag_id, bag in self.tracked_bags.items():
            if bag_id in already_matched:
                continue
            pred = bag.predicted_center
            dist = ((center[0] - pred[0]) ** 2 + (center[1] - pred[1]) ** 2) ** 0.5
            speed     = (bag.velocity[0] ** 2 + bag.velocity[1] ** 2) ** 0.5
            threshold = BASE_MATCH_DIST + speed * bag.frames_missing
            if dist < threshold and dist < best_dist:
                best_dist = dist
                best_id   = bag_id

        return best_id

    def _apply_count(self, bag, old_committed):
        """
        Fire a count change when a bag moves between fully-committed zones.
        Fires only on A↔B transitions; 'crossing' and None are ignored.
        """
        new_committed = bag.committed_zone
        if old_committed is None or new_committed is None:
            return
        if old_committed == new_committed:
            return

        # 1  = A→B (left-to-right or top-to-bottom)
        # -1 = B→A (right-to-left or bottom-to-top)
        direction = 1 if new_committed == 'B' else -1

        if direction == self.desired_direction:
            self.bag_count += 1
        else:
            self.bag_count = max(0, self.bag_count - 1)

    # ── Drawing helpers ───────────────────────────────────────────────────────

    def draw_direction_arrow(self, frame):
        h, w   = frame.shape[:2]
        cx, cy = w // 2, h // 2
        length = min(w, h) // 10

        if self.is_vertical:
            # bags cross horizontally
            if self.desired_direction == 1:
                start, end = (cx - length // 2, cy), (cx + length // 2, cy)
            else:
                start, end = (cx + length // 2, cy), (cx - length // 2, cy)
        else:
            # bags cross vertically
            if self.desired_direction == 1:
                start, end = (cx, cy - length // 2), (cx, cy + length // 2)
            else:
                start, end = (cx, cy + length // 2), (cx, cy - length // 2)

        cv2.arrowedLine(frame, start, end, self.arrow_color, 2, tipLength=0.3)
        text     = 'Loading' if self.desired_direction == 1 else 'Unloading'
        (tw, _), _ = cv2.getTextSize(text, cv2.FONT_HERSHEY_SIMPLEX, 0.5, 1)
        cv2.putText(frame, text,
                    (cx - tw // 2, cy + length // 2 + 20),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.5, self.arrow_color, 1)

    def _draw_zone_labels(self, frame, line_pos):
        h, w = frame.shape[:2]
        font  = cv2.FONT_HERSHEY_SIMPLEX
        color = (200, 200, 200)
        if self.is_vertical:
            cv2.putText(frame, 'Zone A', (max(line_pos - 75, 5), 20),       font, 0.5, color, 1)
            cv2.putText(frame, 'Zone B', (min(line_pos + 5, w - 65), 20),   font, 0.5, color, 1)
        else:
            cv2.putText(frame, 'Zone A', (5, max(line_pos - 8, 15)),        font, 0.5, color, 1)
            cv2.putText(frame, 'Zone B', (5, min(line_pos + 18, h - 5)),    font, 0.5, color, 1)

    # ── Main loop ─────────────────────────────────────────────────────────────

    def process_frame(self, frame):
        self.frame_count += 1

        if frame is None:
            logger.error('Received None frame in process_frame')
            return frame, self.bag_count

        native_h, native_w = frame.shape[:2]

        try:
            # ── Detection line pixel position ──────────────────────────────
            if self.is_vertical:
                line_pos   = int(native_w * self.detection_line_position)
                line_start = (line_pos, 0)
                line_end   = (line_pos, native_h)
            else:
                line_pos   = int(native_h * self.detection_line_position)
                line_start = (0, line_pos)
                line_end   = (native_w, line_pos)

            # ── YOLO inference ─────────────────────────────────────────────
            resized = cv2.resize(frame, (640, 640))
            tensor  = (torch.from_numpy(resized)
                       .to(self.device)
                       .permute(2, 0, 1)
                       .float()
                       .div(255.0)
                       .unsqueeze(0))
            results = self.model(tensor, conf=0.25, imgsz=224)[0]

            # ── Parse detections (class 0 = bag) ──────────────────────────
            detections = []
            for box in results.boxes:
                if int(box.cls) != 0:
                    continue
                x_min, y_min, x_max, y_max = map(int, box.xyxy[0].cpu().numpy())
                x_min = int(x_min * native_w / 640)
                x_max = int(x_max * native_w / 640)
                y_min = int(y_min * native_h / 640)
                y_max = int(y_max * native_h / 640)
                center = ((x_min + x_max) // 2, (y_min + y_max) // 2)
                zone   = self._get_zone((x_min, y_min, x_max, y_max), line_pos)
                detections.append((center, (x_min, y_min, x_max, y_max),
                                   float(box.conf), zone))

            # ── Match detections → tracks ──────────────────────────────────
            next_tracked = {}
            matched_ids  = set()

            for center, bbox, conf, zone in detections:
                track_id = self._match_to_track(center, matched_ids)

                if track_id is not None:
                    # Re-associated to an existing (or ghost) track
                    matched_ids.add(track_id)
                    bag          = self.tracked_bags[track_id]
                    old_committed = bag.committed_zone
                    bag.update(center, bbox, zone, self.frame_count)
                    self._apply_count(bag, old_committed)
                else:
                    # New track — first appearance, no count yet
                    track_id = self.next_bag_id
                    self.next_bag_id += 1
                    bag = TrackedBag(track_id, center, bbox, zone, self.frame_count)

                next_tracked[track_id] = bag

            # ── Age unmatched tracks (keep as ghosts) ──────────────────────
            for bag_id, bag in self.tracked_bags.items():
                if bag_id not in matched_ids:
                    bag.frames_missing += 1
                    if bag.frames_missing <= MAX_FRAMES_MISSING:
                        next_tracked[bag_id] = bag  # ghost still alive

            self.tracked_bags = next_tracked

            # ── Draw ───────────────────────────────────────────────────────
            self._draw_zone_labels(frame, line_pos)

            for bag_id, bag in self.tracked_bags.items():
                is_ghost = bag.frames_missing > 0
                x_min, y_min, x_max, y_max = bag.bbox

                # Colour by zone: blue=A, yellow=crossing, green=B, grey=ghost
                if is_ghost:
                    color = (128, 128, 128)
                elif bag.zone == 'B':
                    color = (0, 255, 0)
                elif bag.zone == 'crossing':
                    color = (0, 255, 255)
                else:
                    color = (255, 100, 0)

                thickness = 1 if is_ghost else 2
                cv2.rectangle(frame, (x_min, y_min), (x_max, y_max), color, thickness)
                cv2.putText(frame, f'#{bag_id}',
                            (x_min, max(y_min - 8, 10)),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.45, color, 1)

                if not is_ghost:
                    cx, cy = bag.center
                    cv2.circle(frame, (cx, cy), 4, (0, 0, 255), -1)
                    # Velocity arrow (scaled ×8 for visibility)
                    vx, vy = bag.velocity
                    if abs(vx) > 0.5 or abs(vy) > 0.5:
                        cv2.arrowedLine(frame,
                                        (cx, cy),
                                        (int(cx + vx * 8), int(cy + vy * 8)),
                                        (0, 200, 255), 1, tipLength=0.4)

            cv2.line(frame, line_start, line_end, (0, 0, 255), 2)
            cv2.putText(frame, f'Count: {self.bag_count}',
                        (10, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 255, 0), 2)
            self.draw_direction_arrow(frame)

        except Exception as e:
            logger.error(f'Error in process_frame: {e}', exc_info=True)

        return frame, self.bag_count
