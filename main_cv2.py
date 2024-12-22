import sys, os, json, cv2
from PyQt5.QtWidgets import (QApplication, QWidget, QVBoxLayout, QPushButton, 
                           QHBoxLayout, QLabel, QComboBox, QGridLayout, 
                           QLineEdit, QMessageBox, QDoubleSpinBox, QDialog,
                           QRadioButton, QButtonGroup, QFrame, QFileDialog)
from PyQt5.QtCore import Qt, QTimer, QDateTime
from PyQt5.QtGui import QImage, QPixmap
from yolov8_cv2 import DetectionThread
from record_handler import RecordManager
from datetime import datetime
from qt_styles import StyleSheet

from record_handler import HistoryDialog
from camera_manager import CameraManager, AddCameraDialog

# Camera configurations
DEFAULT_CAMERAS = {
    "Băng tải 1": "rtsp://admin:abcd1234@192.168.1.222:554/cam/realmonitor?channel=4&subtype=0",
    "Băng tải 2": "rtsp://admin:abcd1234@192.168.1.222:554/cam/realmonitor?channel=3&subtype=0",
    "Test 1": "rtsp://tan001:tan001@192.168.0.62/stream1"
}

class AppWindow(QWidget):
    def __init__(self):
        super().__init__()
        self.setStyleSheet(StyleSheet.get_main_style())
        self.detection_thread = None
        self.last_bag_count = 0
        self.record_manager = RecordManager()
        self.current_source_type = None
        self.current_video_path = None
        self.camera_manager = CameraManager()
        self.init_ui()
        self.connect_signals()
        self.load_existing_records()

    def init_ui(self):
        """Initialize the user interface"""
        self.setWindowTitle("Rice Bag Counter")
        self.setMinimumSize(1905, 900)
        
        # Main layout
        main_layout = QHBoxLayout(self)
        left_panel = QVBoxLayout()
        right_panel = QVBoxLayout()
        
        # Setup panels
        self.setup_video_panel(left_panel)
        self.setup_control_panel(right_panel)
        
        # Add panels to main layout
        main_layout.addLayout(left_panel, 2)  # Video takes 2/3 of width
        main_layout.addLayout(right_panel, 1)  # Controls take 1/3 of width

    def init_camera_management(self):
        """Initialize camera management UI"""
        # Create single line layout
        header_layout = QHBoxLayout()
        header_layout.setObjectName("cameraHeader")
        header_layout.setContentsMargins(10, 5, 10, 5)
        header_layout.setSpacing(8)

        # Add "Select Camera" label
        camera_label = QLabel("Select Camera:")
        camera_label.setObjectName("selectCameraLabel")

        # Setup camera combo box
        self.camera_combo = QComboBox()
        self.camera_combo.setObjectName("cameraCombo")
        self.camera_combo.setMinimumWidth(200)
        self.camera_combo.setFixedHeight(32)  # Set fixed height for combo box

        # Setup add camera button
        self.add_camera_button = QPushButton("➕")
        self.add_camera_button.setObjectName("addButton")
        self.add_camera_button.setToolTip("Add New Camera")
        self.add_camera_button.clicked.connect(self.show_add_camera_dialog)
        self.add_camera_button.setFixedSize(32, 32)  # Match combo box height

        # Setup remove camera button
        self.remove_camera_button = QPushButton("➖")
        self.remove_camera_button.setObjectName("removeButton")
        self.remove_camera_button.setToolTip("Remove Custom Camera")
        self.remove_camera_button.clicked.connect(self.remove_selected_camera)
        self.remove_camera_button.setFixedSize(32, 32)  # Match combo box height

        # Add all components to header layout
        header_layout.addWidget(camera_label)
        header_layout.addWidget(self.camera_combo)
        header_layout.addWidget(self.add_camera_button)
        header_layout.addWidget(self.remove_camera_button)
        header_layout.addStretch()

        # Load cameras into combo box
        self.load_cameras()

        return header_layout

    def load_cameras(self):
        """Load all cameras into combo box"""
        self.camera_combo.clear()
        self.camera_combo.addItem("Default")
        
        # Add default cameras
        for name in DEFAULT_CAMERAS:
            self.camera_combo.addItem(name)
            
        # Add custom cameras
        for name in self.camera_manager.get_all_cameras():
            self.camera_combo.addItem(name)

    def show_add_camera_dialog(self):
        """Show dialog to add new camera"""
        dialog = AddCameraDialog(self)
        if dialog.exec_() == QDialog.Accepted:
            name, url = dialog.save_camera()
            try:
                self.camera_manager.add_camera(name, url)
                self.load_cameras()
                QMessageBox.information(self, "Success", 
                                      f"Camera '{name}' added successfully!")
            except Exception as e:
                QMessageBox.critical(self, "Error", 
                                   f"Failed to add camera: {str(e)}")

    def remove_selected_camera(self):
        """Remove selected camera if it's a custom camera"""
        current_camera = self.camera_combo.currentText()
        
        if current_camera in DEFAULT_CAMERAS:
            QMessageBox.warning(self, "Remove Error", 
                              "Cannot remove default cameras")
            return
            
        if current_camera in self.camera_manager.get_all_cameras():
            reply = QMessageBox.question(
                self,
                "Confirm Removal",
                f"Are you sure you want to remove camera '{current_camera}'?",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No
            )
            
            if reply == QMessageBox.Yes:
                if self.camera_manager.remove_camera(current_camera):
                    self.load_cameras()
                    QMessageBox.information(self, "Success", 
                                          f"Camera '{current_camera}' removed successfully!")
                else:
                    QMessageBox.warning(self, "Error", 
                                      f"Failed to remove camera '{current_camera}'")

    def start_camera(self):
        """Start detection using selected camera"""
        selected_camera = self.camera_combo.currentText()
        if selected_camera == "Default":
            source = 0
        else:
            source = (self.camera_manager.get_camera_url(selected_camera) or 
                     DEFAULT_CAMERAS.get(selected_camera, 0))
        self.start_detection(source, "Camera")

    def setup_video_panel(self, layout):
        """Setup the video display and camera controls"""
        # Add camera management header
        layout.addLayout(self.init_camera_management())
        
        # Video display
        video_container = QWidget()
        video_container.setFixedSize(1280, 720)
        video_container.setStyleSheet("background-color: #111827; border-radius: 4px;")
        
        self.video_label = QLabel()
        self.video_label.setAlignment(Qt.AlignCenter)
        self.video_label.setMinimumSize(1280, 720)
        self.video_label.setMaximumSize(1280, 720)
        self.video_label.setStyleSheet("background-color: transparent;")
        
        # Add video label to container
        video_layout = QVBoxLayout(video_container)
        video_layout.setContentsMargins(0, 0, 0, 0)
        video_layout.addWidget(self.video_label)
        
        # Add video container to main layout
        layout.addWidget(video_container, 0, Qt.AlignCenter)
        
        # Button container with fixed width matching video feed
        button_container = QWidget()
        button_container.setFixedWidth(1280)
        button_layout = QHBoxLayout(button_container)
        button_layout.setSpacing(20)
        button_layout.setContentsMargins(0, 10, 0, 10)
        
        # Create buttons with consistent size
        self.start_camera_btn = QPushButton("Start Camera")
        self.start_video_btn = QPushButton("Load Video")
        self.stop_btn = QPushButton("Stop")
        
        # Set object names for styling
        self.start_camera_btn.setObjectName("startButton")
        self.start_video_btn.setObjectName("loadButton")
        self.stop_btn.setObjectName("stopButton")
        
        # Set fixed sizes for all buttons
        button_width = 150
        button_height = 40
        for btn in [self.start_camera_btn, self.start_video_btn, self.stop_btn]:
            btn.setFixedSize(button_width, button_height)
        
        # Add buttons to layout with center alignment
        button_layout.addStretch()
        button_layout.addWidget(self.start_camera_btn)
        button_layout.addWidget(self.start_video_btn)
        button_layout.addWidget(self.stop_btn)
        button_layout.addStretch()
        
        # Add button container to main layout
        layout.addWidget(button_container, 0, Qt.AlignCenter)

    def setup_control_panel(self, layout):
        """Setup the control panel with detection settings and info"""
        layout.setSpacing(8)
        layout.setContentsMargins(5, 5, 5, 5)
        
        # 1. Detection Line Controls Card
        line_group = QFrame()
        line_group.setObjectName("card")
        line_layout = QVBoxLayout(line_group)
        line_layout.setSpacing(5)
        line_layout.setContentsMargins(5, 5, 5, 5)
        
        # Line orientation controls
        orientation_layout = QHBoxLayout()
        orientation_layout.setSpacing(5)
        orientation_label = QLabel("Thanh đếm:")
        orientation_label.setObjectName("fieldLabel")
        self.vertical_radio = QRadioButton("Thanh Dọc")
        self.horizontal_radio = QRadioButton("Thanh Ngang")
        
        # Create orientation button group
        self.orientation_group = QButtonGroup(self)
        self.orientation_group.addButton(self.vertical_radio)
        self.orientation_group.addButton(self.horizontal_radio)
        self.vertical_radio.setChecked(True)
        
        orientation_layout.addWidget(orientation_label)
        orientation_layout.addWidget(self.vertical_radio)
        orientation_layout.addWidget(self.horizontal_radio)
        orientation_layout.addStretch()
        
        # Count direction controls
        direction_layout = QHBoxLayout()
        direction_layout.setSpacing(5)
        direction_label = QLabel("Hướng đếm:")
        direction_label.setObjectName("fieldLabel")
        self.left_to_right = QRadioButton("Trái → Phải")
        self.right_to_left = QRadioButton("Phải → Trái")
        
        # Create direction button group
        self.direction_group = QButtonGroup(self)
        self.direction_group.addButton(self.left_to_right)
        self.direction_group.addButton(self.right_to_left)
        self.left_to_right.setChecked(True)
        
        direction_layout.addWidget(direction_label)
        direction_layout.addWidget(self.left_to_right)
        direction_layout.addWidget(self.right_to_left)
        direction_layout.addStretch()
        
        # Line position control
        position_layout = QHBoxLayout()
        position_layout.setSpacing(5)
        position_label = QLabel("Vị trí:")
        position_label.setObjectName("fieldLabel")
        self.detection_line_position = QDoubleSpinBox()
        self.detection_line_position.setRange(0.01, 0.99)
        self.detection_line_position.setSingleStep(0.1)
        self.detection_line_position.setValue(0.5)
        self.detection_line_position.setFixedWidth(100)
        
        position_layout.addWidget(position_label)
        position_layout.addWidget(self.detection_line_position)
        position_layout.addStretch()
        
        # Update button with reduced size
        self.update_button = QPushButton("Cập nhật")
        self.update_button.setObjectName("updateButton")
        self.update_button.setToolTip("Cập nhật vị trí và hướng đếm")
        self.update_button.clicked.connect(self.update_detection_line)
        self.update_button.setEnabled(False)
        self.update_button.setFixedHeight(25)  # Reduced height
        self.update_button.setFixedWidth(100)  # Added width constraint
        
        # Add all controls to line group
        line_layout.addLayout(orientation_layout)
        line_layout.addLayout(direction_layout)
        line_layout.addLayout(position_layout)
        line_layout.addWidget(self.update_button, 0, Qt.AlignLeft)  # Align left
        
        layout.addWidget(line_group)
        
        # 2. Information Input Card
        info_group = QFrame()
        info_group.setObjectName("card")
        info_layout = QGridLayout(info_group)
        info_layout.setVerticalSpacing(16)
        
        # Initialize fields
        self.customer_name = QLineEdit()
        self.customer_name.setPlaceholderText("Nhập tên khách hàng")
        
        self.truck_number = QLineEdit()
        self.truck_number.setPlaceholderText("Nhập biển số xe")
        
        self.commodity = QLineEdit()
        self.commodity.setPlaceholderText("Nhập loại hàng")
        
        self.weight_per_bag = QLineEdit()
        self.weight_per_bag.setPlaceholderText("Nhập trọng lượng mỗi bao")
        self.weight_per_bag.textChanged.connect(self.update_total_weight)
        
        self.total_weight = QLabel("0.0 kg")
        self.total_weight.setObjectName("valueLabel")
        
        # Add fields to layout
        fields = [
            ("Tên khách hàng:", self.customer_name),
            ("Biển số xe:", self.truck_number),
            ("Loại hàng:", self.commodity),
            ("Trọng lượng mỗi bao (kg):", self.weight_per_bag),
            ("Tổng trọng lượng:", self.total_weight)
        ]
        
        for i, (label_text, widget) in enumerate(fields):
            label = QLabel(label_text)
            label.setObjectName("fieldLabel")
            info_layout.addWidget(label, i, 0)
            info_layout.addWidget(widget, i, 1)
        
        layout.addWidget(info_group)

        # 3. Status Display Card
        status_group = QFrame()
        status_group.setObjectName("card")
        status_layout = QVBoxLayout(status_group)
        status_layout.setSpacing(5)

        self.status_label = QLabel("Bộ đếm sẵn sàng!")
        self.status_label.setObjectName("statusLabel")
        self.status_label.setWordWrap(True)
        self.status_label.setMinimumHeight(60)
        self.status_label.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        status_layout.addWidget(self.status_label)

        self.count_label = QLabel("Số lượng bao: 0")
        self.count_label.setObjectName("countLabel")
        status_layout.addWidget(self.count_label)

        # View History button with reduced size
        self.view_history_btn = QPushButton("Xem Lịch Sử")
        self.view_history_btn.setObjectName("historyButton")
        self.view_history_btn.setFixedHeight(25)  # Reduced height
        self.view_history_btn.setFixedWidth(100)  # Added width constraint
        self.view_history_btn.clicked.connect(self.show_history)
        
        # Add the button in a new horizontal layout for left alignment
        history_btn_layout = QHBoxLayout()
        history_btn_layout.addWidget(self.view_history_btn)
        history_btn_layout.addStretch()
        status_layout.addLayout(history_btn_layout)

        layout.addWidget(status_group)

    def connect_signals(self):
        """Connect all signal handlers"""
        self.start_camera_btn.clicked.connect(self.start_camera)
        self.start_video_btn.clicked.connect(self.start_video)
        self.stop_btn.clicked.connect(self.stop_detection)
        self.weight_per_bag.textChanged.connect(self.update_total_weight)

    def start_camera(self):
        """Start detection using selected camera"""
        selected_camera = self.camera_combo.currentText()
        source = DEFAULT_CAMERAS.get(selected_camera, 0)  # Use 0 for default camera
        self.start_detection(source, "Camera")

    def start_video(self):
        """Start detection using video file"""
        video_path, _ = QFileDialog.getOpenFileName(
            self, "Select Video", "", "Video Files (*.mp4 *.avi *.mov)"
        )
        if video_path:
            self.start_detection(video_path, "Video")

    def start_detection(self, source, source_type):
        """Start the detection process"""
        try:
            if self.detection_thread and self.detection_thread.isRunning():
                self.stop_detection()

            # Configure detection parameters
            self.detection_thread = DetectionThread(
                source,
                "Detection Feed",
                self.detection_line_position.value(),
                self.vertical_radio.isChecked(),
                "left_to_right" if self.left_to_right.isChecked() else "right_to_left"
            )
            
            self.current_source_type = source_type
            if source_type == "Video":
                self.current_video_path = source
                
            # Connect signals
            self.detection_thread.update_frame.connect(self.update_frame)
            self.detection_thread.finished.connect(self.detection_finished)
            
            # Start detection
            self.detection_thread.start()
            
            # Update UI
            self.update_ui_state(running=True)  
            self.status_label.setText(f"Đang đếm với ({source_type})")
            self.update_button.setEnabled(True)

        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to start detection: {str(e)}")
            self.update_ui_state(running=False)

    def update_frame(self, frame, count):
        """Update the video frame and count display"""
        try:
            if frame is None:
                return
                
            # Convert frame for display
            rgb_frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            h, w, ch = rgb_frame.shape
            qt_image = QImage(rgb_frame.data, w, h, ch * w, QImage.Format_RGB888)
            
            # Scale image to fit display while maintaining aspect ratio
            scaled_pixmap = QPixmap.fromImage(qt_image).scaled(
                self.video_label.size(),
                Qt.KeepAspectRatio,
                Qt.SmoothTransformation
            )
            
            # Update displays
            self.video_label.setPixmap(scaled_pixmap)
            self.last_bag_count = count
            self.count_label.setText(f"Số bao đã đếm: {count}")
            self.update_total_weight()
            
        except Exception as e:
            print(f"Error updating frame: {e}")

    def stop_detection(self):
        """Stop the detection process"""
        if self.detection_thread and self.detection_thread.isRunning():
            self.detection_thread.stop()
            self.detection_thread.wait()
            self.update_ui_state(running=False)
            self.status_label.setText("Bộ đếm đã ngưng")
            self.video_label.clear()


    def update_detection_line(self):
        """Update detection line parameters in real-time"""
        if self.detection_thread and self.detection_thread.isRunning():
            try:
                # Get current values from UI
                new_position = self.detection_line_position.value()
                is_vertical = self.vertical_radio.isChecked()
                count_direction = "left_to_right" if self.left_to_right.isChecked() else "right_to_left"
                
                # Update detection thread parameters
                self.detection_thread.detection_line_position = new_position
                self.detection_thread.is_vertical = is_vertical
                self.detection_thread.count_direction = count_direction
                
                # Update status label with formatted message using two lines
                orientation = "Thanh dọc" if is_vertical else "Thanh ngang"
                direction = "Trái -> Phải" if count_direction == "left_to_right" else "Phải -> Trái"
                
                status_msg = (f"Đã cập nhật: Vị trí {new_position:.2f}\n"
                            f"Loại: {orientation} | Hướng đếm: {direction}")
                self.status_label.setText(status_msg)
                
            except Exception as e:
                QMessageBox.warning(
                    self,
                    "Lỗi Cập Nhật",
                    f"Không thể cập nhật thông số đếm: {str(e)}"
                )
        else:
            self.status_label.setText("Vui lòng bắt đầu phát hiện\ntrước khi cập nhật")
            self.update_button.setEnabled(False)


    def update_ui_state(self, running=False):
        """Update UI elements based on detection state"""
        self.start_camera_btn.setEnabled(not running)
        self.start_video_btn.setEnabled(not running)
        self.stop_btn.setEnabled(running)
        self.camera_combo.setEnabled(not running)
        self.update_button.setEnabled(running)

    def update_total_weight(self):
        """Update total weight based on weight per bag and count"""
        try:
            weight_per_bag = float(self.weight_per_bag.text() or 0)
            total = weight_per_bag * self.last_bag_count
            self.total_weight.setText(f"{total:.2f} kg")
        except ValueError:
            self.total_weight.setText("0.0 kg")

    def detection_finished(self, count):
        """Handle detection completion"""
        self.update_ui_state(running=False)
        self.status_label.setText(f"Bộ đếm kết thúc!")
        self.save_current_record(count)

    def save_current_record(self, count):
        """Save detection results"""
        if not self.customer_name.text() or not self.truck_number.text():
            return
            
        record = {
            "customer_name": self.customer_name.text(),
            "truck_number": self.truck_number.text(),
            "commodity": self.commodity.text(),
            "date_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "weight_per_bag": self.weight_per_bag.text(),
            "total_weight": self.total_weight.text(),
            "bag_count": count,
            "source_type": self.current_source_type,
            "timestamp": datetime.now().isoformat()
        }
        
        if self.record_manager.add_record(record):
            self.status_label.setText("Record saved successfully")

    def load_existing_records(self):
        """Load and display existing detection records"""
        try:
            records = self.record_manager.get_all_records()
            if records:
                latest = records[0]
                self.last_bag_count = latest.get('bag_count', 0)
                self.count_label.setText(f"Số bao từ lần đếm trước: {self.last_bag_count}")
        except Exception as e:
            print(f"Error loading records: {e}")

    def show_history(self):
        """Show the history dialog"""
        try:
            # Refresh records before showing dialog
            self.record_manager.load_records()
            records = self.record_manager.get_all_records()
            
            # Create and show dialog
            dialog = HistoryDialog(self, records)
            dialog.exec_()
        except Exception as e:
            QMessageBox.critical(
                self,
                "Error",
                f"Failed to load history: {str(e)}"
            )


    def closeEvent(self, event):
        """Handle application closure"""
        # Create custom message box
        msg_box = QMessageBox()
        msg_box.setWindowTitle('Thoát')
        msg_box.setText('Bạn có chắc chắn muốn thoát?')
        
        # Create and set up custom buttons
        yes_button = QPushButton('Có')
        no_button = QPushButton('Không')
        
        msg_box.addButton(yes_button, QMessageBox.YesRole)
        msg_box.addButton(no_button, QMessageBox.NoRole)
        msg_box.setDefaultButton(no_button)
        
        # Set fixed size for message box
        msg_box.setFixedSize(400, 200)
        
        # Apply stylesheet
        msg_box.setStyleSheet(StyleSheet.get_message_box_style())
        
        # Show message box and get response
        reply = msg_box.exec_()
        
        if msg_box.clickedButton() == yes_button:
            self.stop_detection()
            event.accept()
        else:
            event.ignore()

if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = AppWindow()
    window.show()
    sys.exit(app.exec_())