import cv2, logging, os, torch, threading, gc, time
import numpy as np
from ultralytics import YOLO

from threading import Lock, Thread
from PyQt5.QtCore import QThread, pyqtSignal
 
from pathlib import Path
from queue import Queue
from collections import deque
from tracker import BagTracker

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)

class RTSPFrameGrabber(QThread):
    """Dedicated thread for capturing RTSP frames with improved error handling"""
    def __init__(self, rtsp_url, buffer_size=30):
        super().__init__()
        self.rtsp_url = rtsp_url
        self.frame_queue = Queue(maxsize=buffer_size)
        self.stop_flag = False
        self.cap = None
        self._is_connected = False
        self._lock = Lock()
        self._cleanup_lock = Lock()
        
        # Initialize reconnection-related attributes
        self._reconnect_count = 0
        self._max_reconnects = 5
        self._restart_cooldown = 2.0
        self._last_restart_time = time.time()
        self._consecutive_failures = 0
        self._max_consecutive_failures = 3

    def configure_capture(self):
        """Configure capture with enhanced error handling and H.264 support"""
        try:
            # Clean up existing capture first
            self.cleanup_capture()
            time.sleep(0.5)

            # Enhanced FFmpeg settings for better H.264 handling and network resilience
            os.environ['OPENCV_FFMPEG_CAPTURE_OPTIONS'] = (
                'rtsp_transport;tcp|'
                'fflags;nobuffer|'
                'max_delay;500000|'
                'reorder_queue_size;2000|'
                'max_analyze_duration;1000000|'
                'analyzeduration;1000000|'
                'probesize;1000000|'
                'buffer_size;512000|'
                'stimeout;30000000|'
                'rtsp_flags;prefer_tcp|'
                'enable_drefs;0|'
                'sync;ext'
            )
            
            with self._lock:
                # Create capture with explicit FFmpeg backend
                self.cap = cv2.VideoCapture(self.rtsp_url, cv2.CAP_FFMPEG)
                
                if not self.cap.isOpened():
                    raise RuntimeError(f"Failed to open RTSP stream: {self.rtsp_url}")

                # Configure capture properties
                self.cap.set(cv2.CAP_PROP_BUFFERSIZE, 2)  # Double buffer
                self.cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*'H264'))
                
                fps = self.cap.get(cv2.CAP_PROP_FPS)
                self.frame_interval = 1.0 / 30.0  # Default to 30 FPS
                if 0 < fps <= 30:
                    self.frame_interval = 1.0 / fps

                # Multiple test frame reads to ensure stable connection
                success_reads = 0
                for _ in range(3):
                    ret, frame = self.read_frame_with_retry()
                    if ret and frame is not None:
                        success_reads += 1
                    time.sleep(0.1)
                    
                if success_reads < 2:
                    raise RuntimeError("Failed to establish stable connection")

                self._is_connected = True
                self._reconnect_count = 0
                self._consecutive_failures = 0
                logging.info(f"Successfully connected to {self.rtsp_url}")
                return True

        except Exception as e:
            logging.error(f"Error configuring capture: {str(e)}")
            self.cleanup_capture()
            return False

    def run(self):
        """Main capture loop with enhanced error handling"""
        reconnect_delay = 0.5
        max_reconnect_delay = 15.0
        last_frame_time = time.time()
        connection_attempts = 0
        max_connection_attempts = 5
        last_error_time = 0
        error_cooldown = 5.0
        last_frame_check = time.time()
        frame_check_interval = 5.0
        consecutive_read_failures = 0
        max_consecutive_failures = 5

        while not self.stop_flag:
            try:
                current_time = time.time()

                # Handle disconnected state
                if not self._is_connected or self.cap is None:
                    if connection_attempts >= max_connection_attempts:
                        logging.error("Max connection attempts reached. Stopping frame grabber.")
                        break
                        
                    logging.warning(f"Attempting to reconnect in {reconnect_delay:.1f} seconds...")
                    time.sleep(reconnect_delay)
                    
                    if self.configure_capture():
                        reconnect_delay = 0.5
                        connection_attempts = 0
                        consecutive_read_failures = 0
                        last_error_time = 0
                    else:
                        reconnect_delay = min(reconnect_delay * 2, max_reconnect_delay)
                        connection_attempts += 1
                    continue

                # Periodic connection check
                if current_time - last_frame_check > frame_check_interval:
                    if not self.cap.isOpened():
                        logging.warning("Periodic check: Capture is no longer valid")
                        self._is_connected = False
                        continue
                    last_frame_check = current_time

                # Frame rate control
                if current_time - last_frame_time < self.frame_interval:
                    time.sleep(0.001)
                    continue

                # Read frame with enhanced error handling
                ret, frame = self.read_frame_with_retry()
                
                if not ret or frame is None:
                    consecutive_read_failures += 1
                    if consecutive_read_failures >= max_consecutive_failures:
                        logging.error("Too many consecutive read failures. Reconnecting...")
                        self._is_connected = False
                        consecutive_read_failures = 0
                    continue

                # Reset failure counter on successful read
                consecutive_read_failures = 0

                # Update frame queue with backpressure handling
                if not self.frame_queue.full():
                    self.frame_queue.put(frame)
                else:
                    try:
                        self.frame_queue.get_nowait()
                        self.frame_queue.put(frame)
                    except:
                        pass

                # Update tracking variables
                last_frame_time = current_time
                connection_attempts = 0

            except Exception as e:
                current_time = time.time()
                if current_time - last_error_time > error_cooldown:
                    logging.error(f"Error in frame grabber: {str(e)}")
                    self._is_connected = False
                    self.cleanup_capture()
                    time.sleep(reconnect_delay)
                    last_error_time = current_time
                else:
                    time.sleep(0.1)
                
                gc.collect()

    def get_frame(self):
        """Get latest frame with timeout handling"""
        try:
            frame = self.frame_queue.get(timeout=0.1)
            if frame is not None and frame.size > 0:
                return frame
            else:
                logging.warning("Retrieved invalid frame from queue")
                return None
        except:
            return None

    def stop(self):
        """Safe shutdown of frame grabber with enhanced RTSP cleanup"""
        try:
            # Set stop flag first to prevent new frames from being added
            self.stop_flag = True
            
            # Set connection state to false to prevent new read attempts
            self._is_connected = False
            
            # Clear frame queue first
            while not self.frame_queue.empty():
                try:
                    self.frame_queue.get_nowait()
                except:
                    pass

            # Wait a short moment for any ongoing operations to complete
            time.sleep(0.2)
            
            # Cleanup capture resources with timeout protection
            cleanup_timeout = threading.Timer(3.0, lambda: None)
            cleanup_timeout.start()
            
            try:
                self.cleanup_capture()
            finally:
                cleanup_timeout.cancel()
            
            # Force garbage collection
            gc.collect()
            
        except Exception as e:
            logging.error(f"Error during frame grabber stop: {str(e)}")
        finally:
            try:
                if self.isRunning():
                    # Wait for thread to finish with timeout
                    self.wait(1000)  # 1 second timeout
                    
                    # Force quit if still running
                    if self.isRunning():
                        logging.warning("Thread did not stop gracefully, forcing termination")
                        # Ensure capture is released before termination
                        try:
                            if hasattr(self, 'cap') and self.cap is not None:
                                self.cap.release()
                                self.cap = None
                        except:
                            pass
                        self.terminate()
                        self.wait()
            except Exception as e:
                logging.error(f"Error waiting for thread to stop: {str(e)}")


    def cleanup_capture(self):
        """Safe cleanup of capture resources with enhanced RTSP handling"""
        with self._cleanup_lock:
            try:
                if hasattr(self, 'cap') and self.cap is not None:
                    # First set running flag to false
                    self._is_connected = False
                    
                    # Clear any remaining frames in the queue
                    while not self.frame_queue.empty():
                        try:
                            self.frame_queue.get_nowait()
                        except:
                            pass

                    # Release capture with safer approach
                    def release_capture():
                        try:
                            if self.cap is not None:
                                # Set buffer size to 0 to prevent new frames
                                try:
                                    self.cap.set(cv2.CAP_PROP_BUFFERSIZE, 0)
                                except:
                                    pass
                                    
                                # Stop RTSP stream first if possible
                                try:
                                    # Some cameras support this command
                                    self.cap.set(cv2.CAP_PROP_SETTINGS, 1)
                                except:
                                    pass
                                    
                                # Release with retries
                                for _ in range(3):
                                    try:
                                        self.cap.release()
                                        break
                                    except:
                                        time.sleep(0.1)
                        except:
                            pass

                    # Run release in thread with timeout
                    release_thread = Thread(target=release_capture)
                    release_thread.daemon = True
                    release_thread.start()
                    release_thread.join(timeout=2.0)
                    
            except Exception as e:
                logging.warning(f"Non-critical error during capture release: {str(e)}")
            finally:
                # Ensure capture is set to None
                self.cap = None
                # Force cleanup of OpenCV windows
                try:
                    cv2.destroyAllWindows()
                except:
                    pass
                # Force garbage collection
                gc.collect()

    def read_frame_with_retry(self, max_retries=3, retry_delay=0.1):
        """Read frame with retries and enhanced error handling"""
        for attempt in range(max_retries):
            try:
                if self.cap is None or not self.cap.isOpened():
                    return False, None
                    
                # Try to read frame with timeout
                read_timeout = threading.Timer(2.0, lambda: setattr(self, '_is_connected', False))
                read_timeout.start()
                
                try:
                    ret, frame = self.cap.read()
                    read_timeout.cancel()
                    
                    if ret and frame is not None and frame.size > 0:
                        return True, frame
                        
                    # Short delay before retry
                    time.sleep(retry_delay)
                        
                except Exception as e:
                    read_timeout.cancel()
                    logging.warning(f"Frame read attempt {attempt + 1} failed: {str(e)}")
                    time.sleep(retry_delay)
                    continue
                    
            except Exception as e:
                logging.error(f"Critical error during frame read: {str(e)}")
                return False, None
                
        return False, None


class DetectionThread(QThread):
    """Thread for running object detection and tracking"""
    update_frame = pyqtSignal(object, int)
    finished = pyqtSignal(int)

    def __init__(self, input_source, window_name, detection_line_position, is_vertical, count_direction, target_fps=30):
        super().__init__()
        self.input_source = input_source
        self.window_name = window_name
        self._detection_line_position = detection_line_position
        self._is_vertical = is_vertical
        self._count_direction = count_direction
        self.stop_flag = False
        self._lock = Lock()
        self._cleanup_lock = Lock()
        
        self.bag_count = 0
        self.frame_grabber = None
        self.tracker = BagTracker()
        
        self.is_paused = False
        self.pause_lock = Lock()
        
        # Enhanced FPS control
        self.target_fps = target_fps
        self.frame_interval = 1.0 / target_fps
        self.last_frame_time = time.time()
        self.frame_count = 0
        self.processing_times = deque(maxlen=30)  # Track processing times
        self.actual_fps = 0
        
        # Initialize model
        self.device = torch.device('cuda' if torch.cuda.is_available() else 'cpu')
        current_dir = Path(__file__).resolve().parent
        self.model_path = current_dir / 'resources' / 'models' / 'best_yolo11_n_v15_ep100_sz320.pt'

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
            logging.info("Model loaded successfully")
            return model
        except Exception as e:
            logging.error(f"Error loading model: {str(e)}")
            raise

    def cleanup_resources(self):
        """Enhanced cleanup with FPS monitoring reset"""
        with self._cleanup_lock:
            # Reset FPS monitoring
            self.frame_count = 0
            self.processing_times.clear()
            self.actual_fps = 0
            
            # Clean up frame grabber
            if hasattr(self, 'frame_grabber') and self.frame_grabber is not None:
                try:
                    self.frame_grabber.stop()
                    self.frame_grabber = None
                except Exception as e:
                    logging.error(f"Error stopping frame grabber: {str(e)}")

            # Clean up video capture
            if hasattr(self, 'cap') and self.cap is not None:
                try:
                    self.cap.release()
                    self.cap = None
                except Exception as e:
                    logging.error(f"Error releasing video capture: {str(e)}")
            
            # Force cleanup of OpenCV windows
            try:
                cv2.destroyAllWindows()
            except:
                pass

    def draw_detection_zone(self, frame, line_pos):
        """Draw detection zone visualization"""
        try:
            height, width = frame.shape[:2]
            overlay = frame.copy()
            
            if self._is_vertical:
                zone_width = int(width * 0.04)
                # Draw main line
                cv2.line(frame, (line_pos, 0), (line_pos, height), (255, 0, 0), 2)
                # Draw zone
                cv2.rectangle(overlay, 
                            (line_pos - zone_width//2, 0),
                            (line_pos + zone_width//2, height),
                            (255, 100, 100), -1)
            else:
                zone_height = int(height * 0.05)
                # Draw main line
                cv2.line(frame, (0, line_pos), (width, line_pos), (255, 0, 0), 2)
                # Draw zone
                cv2.rectangle(overlay,
                            (0, line_pos - zone_height//2),
                            (width, line_pos + zone_height//2),
                            (255, 100, 100), -1)

            # Apply transparency
            cv2.addWeighted(overlay, 0.3, frame, 0.7, 0, frame)
        except Exception as e:
            logging.error(f"Error drawing detection zone: {str(e)}")

    def draw_tracking_info(self, frame, current_bags):
        """Draw tracking visualization"""
        try:
            info_overlay = frame.copy()
            padding = 10
            
            for bag_id, center in current_bags.items():
                # Draw bag marker
                cv2.circle(frame, center, 7, (0, 0, 0), -1)
                cv2.circle(frame, center, 5, (0, 255, 0), -1)
                
                # Draw ID
                text = f"ID {bag_id}"
                font = cv2.FONT_HERSHEY_SIMPLEX
                font_scale = 0.5
                thickness = 2
                
                (text_width, text_height), _ = cv2.getTextSize(text, font, font_scale, thickness)
                
                text_x = center[0] - text_width // 2
                text_y = center[1] - 20
                
                # Draw text background
                cv2.rectangle(info_overlay,
                            (text_x - padding, text_y - text_height - padding),
                            (text_x + text_width + padding, text_y + padding),
                            (0, 0, 0), -1)
                
                # Apply transparency
                cv2.addWeighted(info_overlay, 0.5, frame, 0.5, 0, frame)
                
                # Draw text
                cv2.putText(frame, text,
                           (text_x, text_y),
                           font, font_scale, (255, 255, 255), thickness)
        except Exception as e:
            logging.error(f"Error drawing tracking info: {str(e)}")

    def draw_count_overlay(self, frame):
        """Draw count information overlay with FPS"""
        try:
            info_overlay = frame.copy()
            padding = 10
            
            # Prepare count text
            count_text = f"SL: {self.bag_count} bao"
            fps_text = f"FPS: {self.actual_fps:.1f}"
            font = cv2.FONT_HERSHEY_SIMPLEX
            
            # Get text sizes
            (count_width, count_height), _ = cv2.getTextSize(count_text, font, 1, 2)
            (fps_width, fps_height), _ = cv2.getTextSize(fps_text, font, 1, 2)
            
            # Calculate maximum width needed
            max_width = max(count_width, fps_width)
            
            # Draw background
            cv2.rectangle(info_overlay,
                        (10 - padding, 10 - padding),
                        (10 + max_width + padding, 70 + padding),
                        (0, 0, 0), -1)
            cv2.addWeighted(info_overlay, 0.5, frame, 0.5, 0, frame)
            
            # Draw text
            cv2.putText(frame, count_text,
                       (10, 35), font, 1, (255, 255, 255), 2)
            cv2.putText(frame, fps_text, (10, 65), font, 1, (255, 255, 255), 2)
                                   
        except:
            pass


    def restart_capture(self):
        """Perform a full restart of the capture system"""
        try:
            logging.info("Performing full capture restart...")
            self.cleanup_capture()
            time.sleep(1)
            
            # Reset all states
            self._is_connected = False
            self._reconnect_count = 0
            self._last_restart_time = time.time()
            
            # Clear any remaining frames
            while not self.frame_queue.empty():
                try:
                    self.frame_queue.get_nowait()
                except:
                    pass
                    
            # Force garbage collection
            gc.collect()
            
            return self.configure_capture()
        except Exception as e:
            logging.error(f"Error during capture restart: {str(e)}")
            return False

    def calculate_delay(self):
        """Calculate appropriate delay to maintain target FPS"""
        if not self.processing_times:
            return self.frame_interval
            
        avg_processing_time = sum(self.processing_times) / len(self.processing_times)
        required_delay = max(0, self.frame_interval - avg_processing_time)
        return required_delay

    def run(self):
        """Main detection loop with synchronized FPS control"""
        try:
            model = self.load_model()
            start_time = time.time()
            next_frame_time = start_time
            
            # Initialize video capture based on source type
            if isinstance(self.input_source, str):
                if self.input_source.startswith('rtsp'):
                    # RTSP stream handling
                    self.cleanup_resources()
                    time.sleep(1)
                    
                    self.frame_grabber = RTSPFrameGrabber(self.input_source)
                    self.frame_grabber.start()
                    time.sleep(2)
                else:
                    # Local video file handling
                    self.cap = cv2.VideoCapture(self.input_source)
                    if not self.cap.isOpened():
                        raise RuntimeError(f"Failed to open video file: {self.input_source}")
                    
                    # Get video properties
                    video_fps = self.cap.get(cv2.CAP_PROP_FPS)
                    if video_fps <= 0 or video_fps > self.target_fps:
                        video_fps = self.target_fps
                    
                    self.frame_interval = 1.0 / video_fps

                    # Set buffer size for video file
                    self.cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
            else:
                # Webcam handling
                self.cap = cv2.VideoCapture(self.input_source)
                if not self.cap.isOpened():
                    raise RuntimeError("Failed to open webcam")
        
            while not self.stop_flag:
                current_time = time.time()
                
                # Wait until next frame is due
                time_until_next = next_frame_time - current_time
                if time_until_next > 0:
                    time.sleep(time_until_next)
                    continue
                
                with self.pause_lock:
                    if self.is_paused:
                        time.sleep(0.1)
                        next_frame_time = time.time() + self.frame_interval
                        continue

                # Start timing frame processing
                frame_start_time = time.time()

                # Get frame based on source type
                frame = None
                if self.frame_grabber:
                    frame = self.frame_grabber.get_frame()
                elif hasattr(self, 'cap') and self.cap is not None:
                    ret, frame = self.cap.read()
                    if not ret:
                        if isinstance(self.input_source, str) and not self.input_source.startswith('rtsp'):
                            break
                        continue
                
                if frame is None:
                    continue

                # Process frame
                try:
                    with self._lock:
                        line_pos = int(frame.shape[1] * self._detection_line_position) if self._is_vertical \
                                else int(frame.shape[0] * self._detection_line_position)

                    # Run detection
                    results = model(frame, verbose=False)
                    count_change, current_bags = self.tracker.update(
                        results[0].boxes,
                        frame.shape[:2],
                        line_pos,
                        self._is_vertical,
                        self._count_direction
                    )
                    
                    self.bag_count = max(0, self.bag_count + count_change)
                    
                    # Draw visualizations
                    self.draw_detection_zone(frame, line_pos)
                    self.draw_tracking_info(frame, current_bags)
                    self.draw_count_overlay(frame)
                    
                    # Record processing time
                    processing_time = time.time() - frame_start_time
                    self.processing_times.append(processing_time)
                    
                    # Update frame count and calculate FPS
                    self.frame_count += 1
                    if self.frame_count % 30 == 0:
                        elapsed_time = time.time() - start_time
                        self.actual_fps = self.frame_count / elapsed_time
                    
                    # Emit update
                    self.update_frame.emit(frame, self.bag_count)
                    
                    # Calculate next frame time
                    next_frame_time = frame_start_time + self.frame_interval

                except Exception as e:
                    logging.error(f"Error processing frame: {str(e)}")
                    next_frame_time = time.time() + self.frame_interval
                    continue

        except Exception as e:
            logging.error(f"Detection error: {str(e)}")
            self.finished.emit(0)
        finally:
            self.cleanup_resources()
            self.finished.emit(self.bag_count)

    def stop(self):
        """Safe shutdown of detection thread"""
        try:
            self.stop_flag = True
            self.cleanup_resources()
        except Exception as e:
            logging.error(f"Error during detection thread stop: {str(e)}")
        finally:
            try:
                if self.isRunning():
                    self.wait(1000)
            except Exception as e:
                logging.error(f"Error waiting for thread to stop: {str(e)}")

    def pause(self):
        """Pause detection"""
        with self.pause_lock:
            self.is_paused = True

    def resume(self):
        """Resume detection"""
        with self.pause_lock:
            self.is_paused = False

    def __del__(self):
        """Ensure cleanup on object destruction"""
        self.cleanup_resources()