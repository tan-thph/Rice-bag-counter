import cv2
import logging
from collections import deque

logger = logging.getLogger(__name__)

# ── Tuning knobs ────────────────────────────────────────────────────────────
MAX_FRAMES_MISSING = 20   # frames to keep a ghost track alive for re-association
BASE_MATCH_DIST    = 120  # base pixel distance for matching a detection to a track
VELOCITY_ALPHA     = 0.4  # EMA smoothing for velocity (higher = faster adaptation)
INFER_SIZE         = 224  # must match the size the model was trained at
# ────────────────────────────────────────────────────────────────────────────


class TrackedBag:
    """Per-bag state: position history, smoothed velocity, zone membership."""

    def __init__(self, bag_id, center, bbox, zone, frame_count):
        self.bag_id         = bag_id
        self.positions      = deque([center], maxlen=10)
        self.bbox           = bbox
        self.zone           = zone                           # 'A' | 'B' | 'crossing'
        # committed_zone: last zone the bag was *fully* inside (never 'crossing').
        # None until the bag has been fully inside a zone at least once.
        self.committed_zone = zone if zone in ('A', 'B') else None
        self.frames_missing = 0
        self.velocity       = (0.0, 0.0)                   # smoothed px/frame
        # Net +1s this bag has contributed to bag_count so far. Lets a
        # reverse move only undo a crossing this same bag actually earned
        # (see RiceBagDetector._apply_count).
        self.count_contribution = 0

    @property
    def center(self):
        return self.positions[-1]

    @property
    def predicted_center(self):
        """Linear extrapolation: last known position + velocity × ghost age."""
        cx, cy = self.positions[-1]
        steps  = self.frames_missing + 1
        return (cx + self.velocity[0] * steps,
                cy + self.velocity[1] * steps)

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
        if zone in ('A', 'B'):          # only commit to full zones
            self.committed_zone = zone
        self.frames_missing = 0


class RiceBagDetector:
    """
    Zone-based rice bag counter with ghost tracking and velocity prediction.

    Accepts a pre-loaded YOLO model instance so the weights are shared across
    concurrent jobs rather than loaded from disk once per job.

    Counting model
    ──────────────
    The detection line divides the frame into two zones:
      Zone A  – entire bbox is left of (or above) the line
      Zone B  – entire bbox is right of (or below) the line
      crossing – bbox straddles the line

    A count fires only when committed_zone transitions A↔B (entire bag cleared
    the line).  A→crossing→A bounce-backs do not count.

    Ghost tracking
    ──────────────
    Unmatched tracks are kept alive for MAX_FRAMES_MISSING frames.  Each frame
    the predicted position advances by the smoothed velocity.  A detection that
    reappears within the adaptive threshold is re-associated to the ghost,
    inheriting its zone history — this correctly handles the common case of a
    bag disappearing in Zone A and reappearing in Zone B.
    """

    def __init__(self, model, detection_line_position=0.5,
                 is_vertical=True, desired_direction=1):
        # model is a pre-loaded YOLO instance (shared across jobs)
        self.model = model
        self.model.conf = 0.25
        self.model.iou  = 0.45

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
            if x_max < line_pos:  return 'A'
            if x_min > line_pos:  return 'B'
        else:
            if y_max < line_pos:  return 'A'
            if y_min > line_pos:  return 'B'
        return 'crossing'

    # ── Tracking helpers ──────────────────────────────────────────────────────

    def _match_detections_to_tracks(self, detections):
        """
        Global greedy nearest-neighbour matching.

        Detections are matched to tracks in ascending distance order across
        the *whole frame*, not in whatever order YOLO happened to emit boxes.
        Matching one detection at a time (in YOLO's arbitrary output order)
        lets an earlier detection claim a track it merely satisfies the
        threshold for, even when a later detection in the same frame is a far
        closer match for that same track — misattributing the zone
        transition (and therefore the count) to the wrong physical bag
        whenever two bags are near each other, which is most often exactly
        at the counting line. Sorting all candidate pairs first and
        committing the closest ones fixes that order-dependence.

        Threshold expands with ghost age and bag speed to handle fast bags
        that were missing for several frames.

        Returns {detection_index: track_id} for matched detections.
        """
        candidates = []
        for det_idx, (center, bbox, conf, zone) in enumerate(detections):
            for bag_id, bag in self.tracked_bags.items():
                pred  = bag.predicted_center
                dist  = ((center[0] - pred[0]) ** 2 + (center[1] - pred[1]) ** 2) ** 0.5
                speed = (bag.velocity[0] ** 2 + bag.velocity[1] ** 2) ** 0.5
                threshold = BASE_MATCH_DIST + speed * bag.frames_missing
                if dist < threshold:
                    candidates.append((dist, det_idx, bag_id))

        candidates.sort(key=lambda c: c[0])

        matched_dets  = set()
        matched_bags  = set()
        assignment    = {}
        for dist, det_idx, bag_id in candidates:
            if det_idx in matched_dets or bag_id in matched_bags:
                continue
            assignment[det_idx] = bag_id
            matched_dets.add(det_idx)
            matched_bags.add(bag_id)

        return assignment

    def _apply_count(self, bag, old_committed):
        """
        Fire a count change when committed_zone transitions A↔B.
        'crossing' and None are ignored — only full-zone commits count.

        A bag whose track was first created already fully inside a zone
        (e.g. the belt extends beyond the camera's view) never earns a +1
        for that starting position — only an observed crossing counts. If
        such a bag later moves to the other zone, that must not manufacture
        a spurious -1: only undo a crossing this same bag actually
        contributed earlier, tracked via bag.count_contribution.
        """
        new_committed = bag.committed_zone
        if old_committed is None or new_committed is None:
            return
        if old_committed == new_committed:
            return

        direction = 1 if new_committed == 'B' else -1   # 1=A→B, -1=B→A

        if direction == self.desired_direction:
            self.bag_count += 1
            bag.count_contribution += 1
        elif bag.count_contribution > 0:
            self.bag_count = max(0, self.bag_count - 1)
            bag.count_contribution -= 1

    # ── Drawing helpers ───────────────────────────────────────────────────────

    def draw_direction_arrow(self, frame):
        h, w   = frame.shape[:2]
        cx, cy = w // 2, h // 2
        length = min(w, h) // 10

        if self.is_vertical:
            if self.desired_direction == 1:
                start, end = (cx - length // 2, cy), (cx + length // 2, cy)
            else:
                start, end = (cx + length // 2, cy), (cx - length // 2, cy)
        else:
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
        h, w  = frame.shape[:2]
        font  = cv2.FONT_HERSHEY_SIMPLEX
        color = (200, 200, 200)
        if self.is_vertical:
            cv2.putText(frame, 'Zone A', (max(line_pos - 75, 5), 20),      font, 0.5, color, 1)
            cv2.putText(frame, 'Zone B', (min(line_pos + 5, w - 65), 20),  font, 0.5, color, 1)
        else:
            cv2.putText(frame, 'Zone A', (5, max(line_pos - 8, 15)),       font, 0.5, color, 1)
            cv2.putText(frame, 'Zone B', (5, min(line_pos + 18, h - 5)),   font, 0.5, color, 1)

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
            # Resize directly to the model's training size — no double-resize.
            # Passing a numpy BGR array lets YOLO handle normalisation and
            # device transfer internally.
            resized = cv2.resize(frame, (INFER_SIZE, INFER_SIZE))
            results = self.model(resized, conf=0.25, imgsz=INFER_SIZE,
                                 verbose=False)[0]

            # ── Parse detections (class 0 = bag) ──────────────────────────
            detections = []
            for box in results.boxes:
                if int(box.cls) != 0:
                    continue
                x_min, y_min, x_max, y_max = map(int, box.xyxy[0].cpu().numpy())
                # Scale from INFER_SIZE space back to native frame space
                x_min = int(x_min * native_w / INFER_SIZE)
                x_max = int(x_max * native_w / INFER_SIZE)
                y_min = int(y_min * native_h / INFER_SIZE)
                y_max = int(y_max * native_h / INFER_SIZE)
                center = ((x_min + x_max) // 2, (y_min + y_max) // 2)
                zone   = self._get_zone((x_min, y_min, x_max, y_max), line_pos)
                detections.append((center, (x_min, y_min, x_max, y_max),
                                   float(box.conf), zone))

            # ── Match detections → tracks ──────────────────────────────────
            next_tracked   = {}
            matched_ids    = set()
            assignment     = self._match_detections_to_tracks(detections)

            for det_idx, (center, bbox, conf, zone) in enumerate(detections):
                track_id = assignment.get(det_idx)

                if track_id is not None:
                    matched_ids.add(track_id)
                    bag           = self.tracked_bags[track_id]
                    old_committed = bag.committed_zone
                    bag.update(center, bbox, zone, self.frame_count)
                    self._apply_count(bag, old_committed)
                else:
                    track_id = self.next_bag_id
                    self.next_bag_id += 1
                    bag = TrackedBag(track_id, center, bbox, zone, self.frame_count)

                next_tracked[track_id] = bag

            # ── Age unmatched tracks as ghosts ─────────────────────────────
            for bag_id, bag in self.tracked_bags.items():
                if bag_id not in matched_ids:
                    bag.frames_missing += 1
                    if bag.frames_missing <= MAX_FRAMES_MISSING:
                        next_tracked[bag_id] = bag

            self.tracked_bags = next_tracked

            # ── Draw ───────────────────────────────────────────────────────
            self._draw_zone_labels(frame, line_pos)

            for bag_id, bag in self.tracked_bags.items():
                is_ghost = bag.frames_missing > 0
                x_min, y_min, x_max, y_max = bag.bbox

                # blue=Zone A, yellow=crossing, green=Zone B, grey=ghost
                if is_ghost:
                    color = (128, 128, 128)
                elif bag.zone == 'B':
                    color = (0, 255, 0)
                elif bag.zone == 'crossing':
                    color = (0, 255, 255)
                else:
                    color = (255, 100, 0)

                cv2.rectangle(frame, (x_min, y_min), (x_max, y_max),
                              color, 1 if is_ghost else 2)
                cv2.putText(frame, f'#{bag_id}',
                            (x_min, max(y_min - 8, 10)),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.45, color, 1)

                if not is_ghost:
                    cx, cy = bag.center
                    cv2.circle(frame, (cx, cy), 4, (0, 0, 255), -1)
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
