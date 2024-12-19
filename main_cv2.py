import sys
from PyQt5.QtWidgets import (QApplication, QWidget, QPushButton, 
                             QVBoxLayout, QHBoxLayout, QLabel, 
                             QFileDialog, QComboBox, QLineEdit, QGridLayout, 
                             QTextEdit, QDialog, QDateEdit, QFrame, QLayout,
                             QDialogButtonBox, QMessageBox, QDoubleSpinBox, QButtonGroup, QRadioButton)
from PyQt5.QtCore import (Qt, QThread, pyqtSignal, QDateTime,
                          QPoint, QDate, QTimer, QPointF, QSettings)
from PyQt5.QtGui import QImage, QPixmap, QPolygonF, QPainter, QPen
from PyQt5.QtPrintSupport import QPrinter, QPrintDialog
import cv2
from yolov8_cv2 import DetectionThread as DT

import json
from datetime import datetime

from record_handler import RecordManager, DetectionRecord, HistoryDialog
import numpy as np

from qt_styles import StyleSheet

# Camera dictionary
cameras = {
    "Băng tải 1": "rtsp://admin:abcd1234@192.168.1.222:554/cam/realmonitor?channel=4&subtype=0",
    "Băng tải 2": "rtsp://admin:abcd1234@192.168.1.222:554/cam/realmonitor?channel=3&subtype=0",
    "Test 1": "rtsp://tan001:tan001@192.168.0.62/stream1"
}

class AddCameraDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Add New Camera")
        self.setMinimumWidth(400)
        self.setStyleSheet("""
            QDialog {
                background-color: #f9fafb;
            }
            QLineEdit {
                padding: 8px;
                border: 1px solid #e5e7eb;
                border-radius: 6px;
                background: white;
            }
            QComboBox {
                padding: 8px;
                border: 1px solid #e5e7eb;
                border-radius: 6px;
                background: white;
            }
            QLabel {
                color: #374151;
                font-weight: 500;
            }
            QPushButton {
                background-color: #2563eb;
                color: white;
                border: none;
                padding: 8px 16px;
                border-radius: 6px;
                font-weight: 600;
            }
            QPushButton[text="Cancel"] {
                background-color: #6b7280;
            }
        """)
        self.init_ui()

    def init_ui(self):
        layout = QVBoxLayout()
        form_layout = QGridLayout()

        # Camera name input
        self.camera_name = QLineEdit()
        form_layout.addWidget(QLabel("Camera Name:"), 0, 0)
        form_layout.addWidget(self.camera_name, 0, 1)

        # Brand selection
        self.brand_combo = QComboBox()
        self.brand_combo.addItems(["Hikvision", "Dahua", "Other"])
        self.brand_combo.currentTextChanged.connect(self.on_brand_changed)
        form_layout.addWidget(QLabel("Brand:"), 1, 0)
        form_layout.addWidget(self.brand_combo, 1, 1)

        # Common fields
        self.username = QLineEdit()
        self.password = QLineEdit()
        self.password.setEchoMode(QLineEdit.Password)
        self.nvr_ip = QLineEdit()
        self.channel = QLineEdit()
        
        form_layout.addWidget(QLabel("Username:"), 2, 0)
        form_layout.addWidget(self.username, 2, 1)
        form_layout.addWidget(QLabel("Password:"), 3, 0)
        form_layout.addWidget(self.password, 3, 1)
        form_layout.addWidget(QLabel("NVR IP:"), 4, 0)
        form_layout.addWidget(self.nvr_ip, 4, 1)
        form_layout.addWidget(QLabel("Channel:"), 5, 0)
        form_layout.addWidget(self.channel, 5, 1)

        # Additional fields for "Other" brand
        self.port = QLineEdit("554")  # Default RTSP port
        self.stream_path = QLineEdit()
        self.port_label = QLabel("Port:")
        self.stream_path_label = QLabel("Stream Path:")
        
        form_layout.addWidget(self.port_label, 6, 0)
        form_layout.addWidget(self.port, 6, 1)
        form_layout.addWidget(self.stream_path_label, 7, 0)
        form_layout.addWidget(self.stream_path, 7, 1)
        
        # Initially hide "Other" brand specific fields
        self.port_label.hide()
        self.port.hide()
        self.stream_path_label.hide()
        self.stream_path.hide()

        # Preview of the RTSP URL
        self.preview_label = QLabel()
        self.preview_label.setWordWrap(True)
        self.preview_label.setStyleSheet("background-color: #f0f0f0; padding: 5px;")

        # Buttons
        button_box = QDialogButtonBox(
            QDialogButtonBox.Ok | QDialogButtonBox.Cancel
        )
        button_box.accepted.connect(self.accept)
        button_box.rejected.connect(self.reject)

        # Add all widgets to main layout
        layout.addLayout(form_layout)
        layout.addWidget(QLabel("RTSP URL Preview:"))
        layout.addWidget(self.preview_label)
        layout.addWidget(button_box)

        self.setLayout(layout)

        # Connect text changed signals
        for widget in [self.username, self.password, self.nvr_ip, 
                      self.channel, self.port, self.stream_path]:
            widget.textChanged.connect(self.update_preview)

    def on_brand_changed(self, brand):
        # Show/hide fields based on brand selection
        is_other = brand == "Other"
        self.port_label.setVisible(is_other)
        self.port.setVisible(is_other)
        self.stream_path_label.setVisible(is_other)
        self.stream_path.setVisible(is_other)
        self.update_preview()

    def update_preview(self):
        brand = self.brand_combo.currentText()
        username = self.username.text()
        password = self.password.text()
        nvr_ip = self.nvr_ip.text()
        channel = self.channel.text()
        port = self.port.text()
        stream_path = self.stream_path.text()

        if brand == "Hikvision":
            url = f"rtsp://{username}:{password}@{nvr_ip}:554/Streaming/Channels/{channel}01"
        elif brand == "Dahua":
            url = f"rtsp://{username}:{password}@{nvr_ip}:554/cam/realmonitor?channel={channel}&subtype=0"
        else:
            url = f"rtsp://{username}:{password}@{nvr_ip}:{port}/{stream_path}"

        self.preview_label.setText(f"URL Preview:\n{url}")
        
    def get_camera_data(self):
        return {
            "name": self.camera_name.text(),
            "url": self.preview_label.text().split("\n")[1]  # Get the URL from preview
        }

class DetectionThread(QThread):
    update_frame = pyqtSignal(object, int)
    finished = pyqtSignal(int)

    def __init__(self, input_source, window_name, detection_line_position, is_vertical, count_direction):
        super().__init__()
        self.input_source = input_source
        self.window_name = window_name
        self.stop_flag = False
        self.cap = None
        self._detection_line_position = detection_line_position
        self._is_vertical = is_vertical
        self._count_direction = count_direction
        self.record_manager = RecordManager()

    @property
    def count_direction(self):
        return self._count_direction

    @count_direction.setter
    def count_direction(self, value):
        self._count_direction = value

    @property
    def detection_line_position(self):
        return self._detection_line_position

    @detection_line_position.setter
    def detection_line_position(self, value):
        self._detection_line_position = value

    @property
    def is_vertical(self):
        return self._is_vertical

    @is_vertical.setter
    def is_vertical(self, value):
        self._is_vertical = value

    def run(self):
        try:
            print(f"Running rice_bag_detection with input_source: {self.input_source}")
            if isinstance(self.input_source, str) and self.input_source in cameras:
                self.input_source = cameras[self.input_source]
            
            if isinstance(self.input_source, str) and self.input_source == "Default":
                self.input_source = 0

            self.cap = cv2.VideoCapture(self.input_source)
            if not self.cap.isOpened():
                print(f"Error: Unable to open video source {self.input_source}")
                return

            self.cap.set(cv2.CAP_PROP_FRAME_WIDTH, 1280)
            self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 720)

            # Create getter functions to pass current values
            def get_line_position():
                return self.detection_line_position

            def get_is_vertical():
                return self.is_vertical

            def get_count_direction():
                return self.count_direction

            from yolov8_cv2 import main
            bag_count = main(
                self.input_source,
                self.window_name,
                self.update_frame.emit,
                self.check_stop,
                self.cap,
                get_line_position,    
                get_is_vertical,
                get_count_direction   # Add direction getter
            )
            
            if not self.stop_flag:
                self.finished.emit(bag_count)

        except Exception as e:
            print(f"Exception in DetectionThread: {e}")
            import traceback
            traceback.print_exc()
        finally:
            self.cleanup()

    def save_current_record(self, bag_count):
        record = DetectionRecord(
            customer_name=self.customer_name.text(),
            truck_number=self.truck_number.text(),
            commodity=self.commodity.text(),
            date_time=self.date_time.text(),
            weight_per_bag=self.weight_per_bag.text(),
            total_weight=self.total_weight.text(),
            bag_count=bag_count,
            source_type="Video" if hasattr(self, 'current_video_path') else "Camera"
        )
        self.record_manager.add_record(record)

    def show_history(self):
        """Show the detection history dialog with error handling"""
        try:
            records = self.record_manager.get_all_records()
            HistoryDialog.show_history_dialog(self, records)
        except Exception as e:
            print(f"Error showing history: {e}")
            QMessageBox.critical(self, "Error", "Failed to show history window.")

    def cleanup(self):
        if self.cap is not None:
            self.cap.release()
            self.cap = None

    def stop(self):
        self.stop_flag = True
        if self.cap is not None:
            self.cap.release()

    def check_stop(self):
        return self.stop_flag

      
class AppWindow(QWidget):
    update_frame = pyqtSignal(object, int)

    def __init__(self):
        super().__init__()
        self.setStyleSheet(StyleSheet.get_main_style())
        self.detection_thread = None
        self.last_bag_count = 0
        self.record_manager = RecordManager()
        self.settings = QSettings('Thanh Huong', 'RiceBagDetection')
        
        self.init_ui()
        self.load_existing_records()

    def init_ui(self):
        # Set window properties
        self.setWindowTitle("Rice Bag Detection App")
        self.setMinimumSize(1820, 1000)

        # Create main layout structure
        main_layout = QHBoxLayout()
        main_layout.setContentsMargins(20, 20, 20, 20)
        main_layout.setSpacing(20)
        self.setLayout(main_layout)

        # Create left and right sections
        left_layout = QVBoxLayout()
        right_layout = QVBoxLayout()
        left_layout.setSpacing(12)
        main_layout.addLayout(left_layout, 2)  # 2 is the stretch factor
        main_layout.addLayout(right_layout, 1)  # 1 is the stretch factor

        # Create card containers
        video_card = QFrame()
        video_card.setObjectName("card")
        details_card = QFrame()
        details_card.setObjectName("card")

        # Setup Video Card
        self.setup_video_card(video_card)
        left_layout.addWidget(video_card)

        # Setup Details Card
        self.setup_details_card(details_card)
        right_layout.addWidget(details_card)

    def setup_video_card(self, video_card):
        video_card_layout = QVBoxLayout(video_card)
        video_card_layout.setSpacing(12)

        # 1. Video Feed Label and Camera Selection
        self.video_feed_label = QLabel("Video Feed")
        self.video_feed_label.setObjectName("sectionTitle")
        video_card_layout.addWidget(self.video_feed_label)

        # 2. Camera Management
        camera_header = self.init_camera_management()
        video_card_layout.addLayout(camera_header)

        # 3. Video Display Area
        self.video_label = QLabel()
        self.video_label.setAlignment(Qt.AlignCenter)
        self.video_label.setMinimumSize(1280, 720)
        self.video_label.setObjectName("videoFeed")
        video_card_layout.addWidget(self.video_label)

        # 4. Control Buttons
        button_layout = QHBoxLayout()
        
        self.start_camera_button = QPushButton("Camera")
        self.start_video_button = QPushButton("Video")
        self.stop_button = QPushButton("Ngừng chạy")
        self.update_line_button = QPushButton("Cập nhật vị trí và hướng đếm")  # Updated button text

        # Set object names for styling
        self.start_camera_button.setObjectName("startButton")
        self.start_video_button.setObjectName("loadButton")
        self.stop_button.setObjectName("stopButton")
        self.update_line_button.setObjectName("updateButton")

        # Connect button signals
        self.start_camera_button.clicked.connect(lambda: self.start_detection(0))
        self.start_video_button.clicked.connect(self.start_video_detection)
        self.stop_button.clicked.connect(self.stop_detection)
        self.update_line_button.clicked.connect(self.update_detection_line)

        button_layout.addWidget(self.start_camera_button)
        button_layout.addWidget(self.start_video_button)
        button_layout.addWidget(self.stop_button)
        
        video_card_layout.addLayout(button_layout)
        video_card_layout.addWidget(self.update_line_button)
        
        # 5. Status and Count Labels
        self.status_label = QLabel("Click 'Start' to begin rice bag detection.")
        self.status_label.setAlignment(Qt.AlignCenter)
        self.status_label.setWordWrap(True)
        self.status_label.setObjectName("statusLabel")

        self.last_count_label = QLabel(f"Số lượng bao đã đếm: {self.last_bag_count}")
        self.last_count_label.setAlignment(Qt.AlignCenter)
        self.last_count_label.setObjectName("countLabel")

        video_card_layout.addWidget(self.status_label)
        video_card_layout.addWidget(self.last_count_label)

        # Initially disable appropriate buttons
        self.stop_button.setEnabled(False)
        self.update_line_button.setEnabled(False)

    def setup_details_card(self, details_card):
        details_layout = QVBoxLayout(details_card)
        details_layout.setSpacing(12)

        # 1. Title
        details_title = QLabel("Nhập thông tin để bắt đầu")
        details_title.setObjectName("sectionTitle")
        details_layout.addWidget(details_title)

        # 2. Form Layout
        form_layout = QGridLayout()
        form_layout.setSpacing(12)

        # Create form fields
        self.customer_name = QLineEdit()
        self.truck_number = QLineEdit()
        self.commodity = QLineEdit()
        self.date_time = QLabel()
        self.weight_per_bag = QLineEdit()
        self.weight_per_bag.setPlaceholderText("Nhập trọng lượng mỗi bao")
        self.weight_per_bag.textChanged.connect(self.update_total_weight)
        self.total_weight = QLabel("0.0 kg")

        # Create orientation controls
        self.orientation_group = QButtonGroup(self)
        self.vertical_radio = QRadioButton("Thanh Dọc")
        self.horizontal_radio = QRadioButton("Thanh Ngang")
        self.orientation_group.addButton(self.vertical_radio)
        self.orientation_group.addButton(self.horizontal_radio)
        self.vertical_radio.setChecked(True)

        # Create direction controls
        direction_container = QWidget()
        direction_layout = QVBoxLayout(direction_container)
        
        self.direction_group = QButtonGroup(self)
        self.left_to_right = QRadioButton("Trái → Phải")
        self.right_to_left = QRadioButton("Phải → Trái")
        self.direction_group.addButton(self.left_to_right)
        self.direction_group.addButton(self.right_to_left)
        self.left_to_right.setChecked(True)
        
        direction_layout.addWidget(self.left_to_right)
        direction_layout.addWidget(self.right_to_left)
        direction_layout.setSpacing(8)

        # Create detection line position control
        self.detection_line_position = QDoubleSpinBox()
        self.detection_line_position.setRange(0.1, 0.9)
        self.detection_line_position.setSingleStep(0.1)
        self.detection_line_position.setValue(0.5)
        self.detection_line_position.setDecimals(2)

        # Add fields to form layout with labels
        labels_and_widgets = [
            ("Tên khách hàng:", self.customer_name),
            ("Biển số xe:", self.truck_number),
            ("Loại hàng:", self.commodity),
            ("Thanh đếm:", self.create_orientation_layout()),
            ("Hướng di chuyển:", direction_container),
            ("Vị trí thanh đếm:", self.detection_line_position),
            ("Trọng lượng mỗi bao (kg):", self.weight_per_bag),
            ("Tổng trọng lượng (kg):", self.total_weight)
        ]

        for i, (label_text, widget) in enumerate(labels_and_widgets):
            label = QLabel(label_text)
            label.setObjectName("fieldLabel")
            form_layout.addWidget(label, i, 0)
            if isinstance(widget, QLayout):
                form_layout.addLayout(widget, i, 1)
            else:
                form_layout.addWidget(widget, i, 1)

        details_layout.addLayout(form_layout)
        details_layout.addStretch()

        #History button
        self.view_history_button = QPushButton("Xem lịch sử")
        self.view_history_button.setObjectName("historyButton")
        self.view_history_button.clicked.connect(self.show_history)
        details_layout.addWidget(self.view_history_button)

    def create_orientation_layout(self):
        orientation_layout = QHBoxLayout()
        orientation_layout.addWidget(self.vertical_radio)
        orientation_layout.addWidget(self.horizontal_radio)
        return orientation_layout

    def connect_signals(self):
        # Connect all button signals
        self.start_camera_button.clicked.connect(lambda: self.start_detection(0))
        self.start_video_button.clicked.connect(self.start_video_detection)
        self.stop_button.clicked.connect(self.stop_detection)
        self.update_line_button.clicked.connect(self.update_detection_line)
        self.view_history_button.clicked.connect(self.show_history)

    def show_history(self):
        try:
            records = self.record_manager.get_all_records()
            if records:
                dialog = HistoryDialog(self, records)
                dialog.exec_()
            else:
                QMessageBox.information(self, "History", "No detection records found.")
        except Exception as e:
            print(f"Error showing history: {e}")
            QMessageBox.critical(self, "Error", f"Failed to show history window: {str(e)}")


    def init_camera_management(self):
        # Create camera selection container
        camera_container = QWidget()
        camera_layout = QHBoxLayout(camera_container)
        camera_layout.setContentsMargins(0, 0, 0, 0)
        camera_layout.setSpacing(8)
        
        # Setup camera combo box
        self.camera_combo = QComboBox()
        self.camera_combo.setObjectName("cameraCombo")
        
        # Setup add camera button
        self.add_camera_button = QPushButton("➕")
        self.add_camera_button.setObjectName("addButton")
        self.add_camera_button.setToolTip("Add New Camera")
        self.add_camera_button.clicked.connect(self.show_add_camera_dialog)
        
        # Setup remove camera button
        self.remove_camera_button = QPushButton("➖")
        self.remove_camera_button.setObjectName("removeButton")
        self.remove_camera_button.setToolTip("Remove Custom Camera")
        self.remove_camera_button.clicked.connect(self.remove_selected_camera)
        
        # Add widgets to camera container
        camera_layout.addWidget(self.camera_combo)
        camera_layout.addWidget(self.add_camera_button)
        camera_layout.addWidget(self.remove_camera_button)
        
        # Load cameras into combo box
        self.load_cameras()
        
        # Update the header layout
        camera_header_layout = QHBoxLayout()
        camera_header_layout.setObjectName("cameraHeader")
        camera_header_layout.addWidget(self.video_feed_label)
        camera_header_layout.addStretch()
        camera_header_layout.addWidget(camera_container)
        
        return camera_header_layout
        

    def remove_selected_camera(self):
        current_camera = self.camera_combo.currentText()
        
        # Check if the current selection is a default camera
        if current_camera == "Default" or current_camera in cameras:
            QMessageBox.warning(
                self,
                "Không thể xóa Camera",
                "Default cameras không thể bị xóa."
            )
            return
        
        # Confirm removal
        reply = QMessageBox.question(
            self,
            "Xóa Camera",
            f"Bạn có muốn xóa camera '{current_camera}'?",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No
        )
        
        if reply == QMessageBox.Yes:
            # Remove from settings
            saved_cameras = self.settings.value('custom_cameras', {})
            if isinstance(saved_cameras, dict) and current_camera in saved_cameras:
                del saved_cameras[current_camera]
                self.settings.setValue('custom_cameras', saved_cameras)
                
                # Remove from cameras dictionary if it exists there
                if current_camera in cameras:
                    del cameras[current_camera]
                
                # Reload the camera list
                self.load_cameras()
                
                QMessageBox.information(
                    self,
                    "Success",
                    f"Camera '{current_camera}' đã bị xóa."
                )

    def load_cameras(self):
        """Load saved cameras from settings"""
        self.camera_combo.clear()
        self.camera_combo.addItem("Default")
        
        # Load built-in cameras first
        for camera_name in cameras.keys():
            self.camera_combo.addItem(camera_name)
        
        # Load custom cameras
        saved_cameras = self.settings.value('custom_cameras', {})
        if isinstance(saved_cameras, dict) and saved_cameras:
            for camera_name, url in saved_cameras.items():
                # Only add if it's not a default camera
                if camera_name not in cameras:
                    self.camera_combo.addItem(camera_name)
                    cameras[camera_name] = url

    def show_add_camera_dialog(self):
        """Show dialog for adding a new camera"""
        dialog = AddCameraDialog(self)
        if dialog.exec_() == QDialog.Accepted:
            camera_data = dialog.get_camera_data()
            
            # Save to settings
            saved_cameras = self.settings.value('custom_cameras', {})
            if not isinstance(saved_cameras, dict):
                saved_cameras = {}
                
            saved_cameras[camera_data['name']] = camera_data['url']
            self.settings.setValue('custom_cameras', saved_cameras)
            
            # Update cameras dictionary and combo box
            cameras[camera_data['name']] = camera_data['url']
            self.load_cameras()
            
            # Show success message
            QMessageBox.information(self, "Success", 
                f"Camera '{camera_data['name']}' has been added successfully.")


    def load_existing_records(self):
        """Load existing records and update the UI"""
        try:
            records = self.record_manager.get_all_records()
            if records:
                latest_record = records[0]  # Most recent record
                self.status_label.setText(f"Đã tải {len(records)} lịch sử đếm")
                
                # Update last count from most recent record
                if 'bag_count' in latest_record:
                    self.last_bag_count = latest_record['bag_count']
                    self.last_count_label.setText(f"Số lượng bao từ lấn đếm trước: {self.last_bag_count}")
                
        except Exception as e:
            self.status_label.setText("Đã xảy ra lỗi khi tải lịch sử bộ đếm")

    def update_detection_line(self):
        if self.detection_thread and self.detection_thread.isRunning():
            # Update position
            new_position = self.detection_line_position.value()
            self.detection_thread.detection_line_position = new_position
            
            # Update orientation
            is_vertical = self.vertical_radio.isChecked()
            self.detection_thread.is_vertical = is_vertical
            
            # Update counting direction
            count_direction = "left_to_right" if self.left_to_right.isChecked() else "right_to_left"
            self.detection_thread.count_direction = count_direction
            
            # Update status label with full settings
            orientation = "Thanh dọc" if is_vertical else "Thanh ngang"
            direction = "Trái → Phải" if count_direction == "left_to_right" else "Phải → Trái"
            self.status_label.setText(
                f"Cập nhật: {orientation}, "
                f"Vị trí {new_position:.2f}, "
                f"Hướng đếm {direction}"
            )

    def input_source(self):
        self.camera_combo.clear()
        self.camera_combo.addItem("Default")
        
        # Add camera options from the dictionary
        for camera_name in cameras.keys():
            self.camera_combo.addItem(camera_name)

    def start_detection(self, input_source):
        try:
            if self.detection_thread and self.detection_thread.isRunning():
                self.stop_detection()

            detection_line_pos = self.detection_line_position.value()
            is_vertical = self.vertical_radio.isChecked()
            count_direction = "left_to_right" if self.left_to_right.isChecked() else "right_to_left"

            # For camera detection
            if input_source == 0:
                selected_camera = self.camera_combo.currentText()
                if selected_camera in cameras:
                    actual_source = cameras[selected_camera]
                elif selected_camera == "Default":
                    actual_source = 0
                else:
                    raise Exception("Invalid camera selection")

                source_type = "Camera"
                window_name = "Camera Feed"
            else:  # Video detection
                actual_source = input_source
                source_type = "Video"
                window_name = "Video Feed"
                self.current_video_path = input_source

            # Create detection thread with all required parameters
            self.detection_thread = DetectionThread(
                actual_source,
                window_name,
                detection_line_pos,
                is_vertical,
                count_direction
            )

            # Store source type for record keeping
            self.current_source_type = source_type
            
            self.detection_thread.update_frame.connect(self.update_frame)
            self.detection_thread.finished.connect(self.detection_finished)
            
            self.detection_thread.start()

            # Update UI
            self.start_camera_button.setEnabled(False)
            self.start_video_button.setEnabled(False)
            self.stop_button.setEnabled(True)
            self.update_line_button.setEnabled(True)
            self.status_label.setText(f"Detection in progress using {source_type}...")

            current_datetime = QDateTime.currentDateTime()
            self.date_time.setText(current_datetime.toString("yyyy-MM-dd hh:mm:ss"))

        except Exception as e:
            QMessageBox.critical(self, "Detection Error", 
                f"An error occurred while starting detection:\n{str(e)}")
            self.start_camera_button.setEnabled(True)
            self.start_video_button.setEnabled(True)
            self.stop_button.setEnabled(False)
            self.update_line_button.setEnabled(False)


    def clear_all_selections(self):
        self.detection_area = None
        self.detection_line = None
        self.is_drawing = False
        self.drawing_points = []
        self.selection_mode = None
        self.status_label.setText("Tất cả lựa chọn đã bị xóa.")
              
       
        self.update_frame(self.current_frame, self.last_bag_count)

    def start_video_detection(self):
        self.current_window_name = "Video Feed"
        video_path, _ = QFileDialog.getOpenFileName(self, "Vui lòng chọn Video", "", "Video Files (*.mp4 *.avi *.mov)")
        if video_path:
            self.start_detection(video_path)

    def detection_finished(self, bag_count):
        try:
            self.last_bag_count = bag_count
            self.status_label.setText(f"Bộ đếm kết thúc. Số lượng bao đã đếm: {bag_count}")
            self.stop_button.setEnabled(False)
            self.start_camera_button.setEnabled(True)
            self.start_video_button.setEnabled(True)
            self.save_current_record(bag_count)
            self.update_total_weight()
            print(f"Bộ đếm kết thúc. {bag_count} bao đã được đếm")
        except Exception as e:
            print(f"Xảy ra lỗi khi kết thúc bộ đếm: {e}")

    def update_frame(self, frame, count):
        try:
            if frame is not None:
                # Convert frame to RGB for Qt
                rgb_frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                
                # Create QImage with original resolution
                h, w, ch = rgb_frame.shape
                bytes_per_line = ch * w
                qt_image = QImage(rgb_frame.data, w, h, bytes_per_line, QImage.Format_RGB888)
                
                # Get the video label's size
                label_size = self.video_label.size()
                
                # Calculate scaling ratios
                width_ratio = label_size.width() / 1280
                height_ratio = label_size.height() / 720
                
                # Use the smaller ratio to maintain aspect ratio
                scale_ratio = min(width_ratio, height_ratio)
                
                # Calculate new size maintaining 16:9 aspect ratio
                new_width = int(1280 * scale_ratio)
                new_height = int(720 * scale_ratio)
                
                # Scale the image
                scaled_pixmap = QPixmap.fromImage(qt_image).scaled(
                    new_width, 
                    new_height,
                    Qt.KeepAspectRatio,
                    Qt.SmoothTransformation
                )
                
                # Update UI
                self.video_label.setPixmap(scaled_pixmap)
                self.video_label.setAlignment(Qt.AlignCenter)
                
                # Update count in UI
                self.last_bag_count = count
                self.last_count_label.setText(f"Số lượng bao đã đếm: {count}")
                self.update_total_weight()
                
                # Force UI update
                QApplication.processEvents()
                
        except Exception as e:
            print(f"Xảy ra lỗi với update_Frame: {e}")

    def update_gui(self):
        QApplication.processEvents()

    def update_total_weight(self):
        try:
            weight_per_bag = float(self.weight_per_bag.text())
            total_weight = weight_per_bag * self.last_bag_count
            self.total_weight.setText(f"{total_weight:.2f} kg")
        except ValueError:
            self.total_weight.setText("0.0 kg")

   
    def print_results(self):
        printer = QPrinter()
        print_dialog = QPrintDialog(printer, self)
        if print_dialog.exec() == QPrintDialog.Accepted:
            self.render_printer_content(printer)

    def render_printer_content(self, printer):
        text_edit = QTextEdit()
        text_edit.setText(f"""
        Customer Name: {self.customer_name.text()}
        Truck Number Plate: {self.truck_number.text()}
        Commodity: {self.commodity.text()}
        Date & Time: {self.date_time.text()}
        Weight per Bag (kg): {self.weight_per_bag.text()}
        Total Weight: {self.total_weight.text()}
        Last run bag count: {self.last_bag_count}
        """)
        text_edit.print_(printer)


    def save_current_record(self, bag_count):
        """Save the current detection record"""
        try:
            # Only save if we have valid data
            if not self.customer_name.text() or not self.truck_number.text():
                print("Skipping record save - missing required fields")
                return False
                
            record = {
                "customer_name": self.customer_name.text(),
                "truck_number": self.truck_number.text(),
                "commodity": self.commodity.text(),
                "date_time": self.date_time.text(),
                "weight_per_bag": self.weight_per_bag.text(),
                "total_weight": self.total_weight.text(),   
                "bag_count": bag_count,
                "source_type": getattr(self, 'current_source_type', 'Unknown'),
                "timestamp": datetime.now().isoformat()  # Add timestamp for uniqueness
            }
            
            if self.record_manager.add_record(record):
                self.status_label.setText("Record saved successfully")
                return True
            else:
                self.status_label.setText("Error saving record")
                return False
                
        except Exception as e:
            print(f"Error saving record: {e}")
            self.status_label.setText("Error saving record")
            return False

    def filter_records(self):
        """Filter records by date range"""
        dialog = QDialog(self)
        dialog.setWindowTitle("Filter Records")

        start_date_edit = QDateEdit()
        start_date_edit.setCalendarPopup(True)
        start_date_edit.setDisplayFormat("yyyy-MM-dd")
        start_date_edit.setDate(QDate.currentDate().addDays(-30))

        end_date_edit = QDateEdit()
        end_date_edit.setCalendarPopup(True)
        end_date_edit.setDisplayFormat("yyyy-MM-dd")
        end_date_edit.setDate(QDate.currentDate())

        button_box = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)

        layout = QVBoxLayout()
        layout.addWidget(QLabel("Start Date:"))
        layout.addWidget(start_date_edit)
        layout.addWidget(QLabel("End Date:"))
        layout.addWidget(end_date_edit)
        layout.addWidget(button_box)

        dialog.setLayout(layout)

        def filter_data():
            start_date = start_date_edit.date().toPyDate()
            end_date = end_date_edit.date().toPyDate()
            filtered_records = self.record_manager.filter_records_by_date(start_date, end_date)
            self.display_filtered_records(filtered_records)
            dialog.accept()

        button_box.accepted.connect(filter_data)
        button_box.rejected.connect(dialog.reject)
        dialog.exec_()

    def display_filtered_records(self, filtered_records):
        dialog = QDialog(self)
        dialog.setWindowTitle("Filtered Records")

        text_edit = QTextEdit()
        text_edit.setReadOnly(True)

        if filtered_records:
            for record in filtered_records:
                text_edit.append(f"""
                Tên Khách hàng: {record["customer_name"]}
                Biển số xe: {record["truck_number"]}
                Loại hàng: {record["commodity"]}
                Ngày giờ: {record["date_time"]}
                Trọng lượng mỗi bao (kg): {record["weight_per_bag"]}
                Tổng trọng lượng: {record["total_weight"]}
                Số lượng bao: {record["bag_count"]}
                """)
        else:
            text_edit.setText("Không tìm thấy kết quả.")

        layout = QVBoxLayout()
        layout.addWidget(text_edit)

        button_box = QDialogButtonBox(QDialogButtonBox.Ok)
        button_box.accepted.connect(dialog.accept)
        layout.addWidget(button_box)

        dialog.setLayout(layout)
        dialog.exec_()
    

    def closeEvent(self, event):
        reply = QMessageBox.question(self, 'Đóng bộ đếm', 'Bạn có muốn đóng bộ đếm này?',
                                    QMessageBox.Yes | QMessageBox.No, QMessageBox.No)

        if reply == QMessageBox.Yes:
            try:
                # Stop any running detection first
                if self.detection_thread and self.detection_thread.isRunning():
                    self.stop_detection()
                
                # Cleanup resources
                self.cleanup_threads()
                
                # Accept the close event
                event.accept()
                
            except Exception as e:
                print(f"Error during window cleanup: {e}")
                event.accept()
        else:
            event.ignore()

    def cleanup_threads(self):
        """Clean up any remaining threads and resources"""
        if self.detection_thread:
            if self.detection_thread.isRunning():
                self.detection_thread.stop()
                self.detection_thread.wait()
            self.detection_thread = None

    def stop_detection(self):
        """Stop detection without closing the app window"""
        try:
            if self.detection_thread and self.detection_thread.isRunning():
                print("Đang đóng bộ đếm...")
                # Stop the thread
                self.detection_thread.stop()
                self.detection_thread.wait()  # Wait for thread to finish
                
                # Update UI elements
                self.start_camera_button.setEnabled(True)
                self.start_video_button.setEnabled(True)
                self.stop_button.setEnabled(False)
                self.update_line_button.setEnabled(False)
                self.status_label.setText("Ngưng tác vụ đếm bao.")
                
                # Clear the video label but keep it visible
                self.video_label.clear()
                self.video_label.setText("Video đã ngừng")
                
                # Update the count label
                self.last_count_label.setText(f"Số lượng bao từ lần đếm trước: {self.last_bag_count}")
                
                print("Detection thread đã dừng.")
        except Exception as e:
            print(f"Xảy ra lỗi với Dectection: {e}")

if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = AppWindow()
    window.show()
    
    exit_code = app.exec_()
    
    # Ensure proper cleanup before exiting
    print("Application is closing, performing cleanup...")
    window.cleanup_threads()
   
    
    sys.exit(exit_code)