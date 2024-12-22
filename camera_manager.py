import json
from pathlib import Path
from PyQt5.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QPushButton, 
                           QLabel, QLineEdit, QComboBox, QTextEdit, QMessageBox)
import cv2
from qt_styles import StyleSheet
# Camera brand RTSP templates
CAMERA_BRANDS = {
    "Hikvision": {
        "template": "rtsp://{username}:{password}@{ip}:{port}/Streaming/Channels/{channel}01",
        "default_port": "554",
        "default_channel": "1",
        "description": "Hikvision IP Camera"
    },
    "Dahua": {
        "template": "rtsp://{username}:{password}@{ip}:{port}/cam/realmonitor?channel={channel}&subtype=0",
        "default_port": "554",
        "default_channel": "1",
        "description": "Dahua IP Camera"
    },
    "Axis": {
        "template": "rtsp://{username}:{password}@{ip}:{port}/axis-media/media.amp",
        "default_port": "554",
        "description": "Axis IP Camera"
    },
    "DLink": {
        "template": "rtsp://{username}:{password}@{ip}:{port}/live{channel}.sdp",
        "default_port": "554",
        "default_channel": "1",
        "description": "D-Link IP Camera"
    },
    "Generic": {
        "template": "rtsp://{username}:{password}@{ip}:{port}/{stream}",
        "default_port": "554",
        "description": "Generic RTSP Camera"
    }
}

class CameraManager:
    def __init__(self):
        self.custom_cameras = self.load_custom_cameras()
        print("Loaded custom cameras:", self.custom_cameras)  # Debug print
    
    def load_custom_cameras(self):
        """Load custom cameras from settings file"""
        try:
            settings_path = Path.home() / '.ricebagcounter' / 'camera_settings.json'
            if settings_path.exists():
                with open(settings_path, 'r') as f:
                    cameras = json.load(f)
                    print(f"Loaded cameras from {settings_path}: {cameras}")  # Debug print
                    return cameras
            print(f"No camera settings file found at {settings_path}")  # Debug print
            return {}
        except Exception as e:
            print(f"Error loading custom cameras: {e}")
            return {}

    def save_custom_cameras(self):
        """Save custom cameras to settings file"""
        try:
            settings_path = Path.home() / '.ricebagcounter' / 'camera_settings.json'
            settings_path.parent.mkdir(parents=True, exist_ok=True)
            with open(settings_path, 'w') as f:
                json.dump(self.custom_cameras, f)
                print(f"Saved cameras to {settings_path}: {self.custom_cameras}")  # Debug print
        except Exception as e:
            print(f"Error saving custom cameras: {e}")
            raise

    def add_camera(self, name, url):
        """Add a new camera"""
        if name in self.custom_cameras:
            raise ValueError("Camera name already exists")
        self.custom_cameras[name] = url
        self.save_custom_cameras()

    def remove_camera(self, name):
        """Remove a camera"""
        if name in self.custom_cameras:
            del self.custom_cameras[name]
            self.save_custom_cameras()
            return True
        return False

    def get_camera_url(self, name):
        """Get camera URL by name"""
        url = self.custom_cameras.get(name)
        return url

    def get_all_cameras(self):
        """Get all custom cameras"""
        return self.custom_cameras
    
class AddCameraDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.parent = parent
        self.setWindowTitle("Add New Camera")
        self.setModal(True)
        self.setMinimumWidth(500)
        self.init_ui()

    def init_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(10)

        # Camera name input
        name_layout = QHBoxLayout()
        name_label = QLabel("Camera Name:")
        name_label.setFixedWidth(120)
        self.name_input = QLineEdit()
        name_layout.addWidget(name_label)
        name_layout.addWidget(self.name_input)
        layout.addLayout(name_layout)

        # Brand selection
        brand_layout = QHBoxLayout()
        brand_label = QLabel("Camera Brand:")
        brand_label.setFixedWidth(120)
        self.brand_combo = QComboBox()
        self.brand_combo.addItems(CAMERA_BRANDS.keys())
        self.brand_combo.currentTextChanged.connect(self.update_form)
        brand_layout.addWidget(brand_label)
        brand_layout.addWidget(self.brand_combo)
        layout.addLayout(brand_layout)

        # IP Address
        ip_layout = QHBoxLayout()
        ip_label = QLabel("IP Address:")
        ip_label.setFixedWidth(120)
        self.ip_input = QLineEdit()
        ip_layout.addWidget(ip_label)
        ip_layout.addWidget(self.ip_input)
        layout.addLayout(ip_layout)

        # Port
        port_layout = QHBoxLayout()
        port_label = QLabel("Port:")
        port_label.setFixedWidth(120)
        self.port_input = QLineEdit()
        port_layout.addWidget(port_label)
        port_layout.addWidget(self.port_input)
        layout.addLayout(port_layout)

        # Username
        username_layout = QHBoxLayout()
        username_label = QLabel("Username:")
        username_label.setFixedWidth(120)
        self.username_input = QLineEdit()
        username_layout.addWidget(username_label)
        username_layout.addWidget(self.username_input)
        layout.addLayout(username_layout)

        # Password
        password_layout = QHBoxLayout()
        password_label = QLabel("Password:")
        password_label.setFixedWidth(120)
        self.password_input = QLineEdit()
        self.password_input.setEchoMode(QLineEdit.Password)
        password_layout.addWidget(password_label)
        password_layout.addWidget(self.password_input)
        layout.addLayout(password_layout)

        # Channel
        channel_layout = QHBoxLayout()
        channel_label = QLabel("Channel:")
        channel_label.setFixedWidth(120)
        self.channel_input = QLineEdit()
        channel_layout.addWidget(channel_label)
        channel_layout.addWidget(self.channel_input)
        layout.addLayout(channel_layout)

        # RTSP URL Preview
        preview_layout = QVBoxLayout()
        preview_label = QLabel("Generated RTSP URL:")
        self.preview_text = QTextEdit()
        self.preview_text.setReadOnly(True)
        self.preview_text.setMaximumHeight(60)
        preview_layout.addWidget(preview_label)
        preview_layout.addWidget(self.preview_text)
        layout.addLayout(preview_layout)

        # Description
        self.description_label = QLabel()
        self.description_label.setStyleSheet("color: #666; font-style: italic;")
        self.description_label.setWordWrap(True)
        layout.addWidget(self.description_label)

        # Create button layout
        button_layout = QHBoxLayout()
        
        # Test button (separate from dialog buttons)
        self.test_btn = QPushButton("Test Connection")
        self.test_btn.setStyleSheet("""
            QPushButton {
                background-color: #3b82f6;
                color: white;
                border: none;
                padding: 8px 16px;
                border-radius: 6px;
                min-width: 100px;
                font-weight: 500;
                font-size: 16px;
            }
            QPushButton:hover {
                background-color: #2563eb;
            }
        """)
        self.test_btn.clicked.connect(self.test_connection)
        button_layout.addWidget(self.test_btn)
        
        # Add spacer
        button_layout.addStretch()
        
        # Create Save and Cancel buttons
        self.save_btn = QPushButton("Save")
        self.save_btn.setStyleSheet("""
            QPushButton {
                background-color: #059669;
                color: white;
                border: none;
                padding: 8px 16px;
                border-radius: 6px;
                min-width: 100px;
                font-weight: 500;
                font-size: 16px;
            }
            QPushButton:hover {
                background-color: #047857;
            }
        """)
        
        cancel_btn = QPushButton("Cancel")
        cancel_btn.setStyleSheet("""
            QPushButton {
                background-color: #6b7280;
                color: white;
                border: none;
                padding: 8px 16px;
                border-radius: 6px;
                min-width: 100px;
                font-weight: 500;
                font-size: 16px;
            }
            QPushButton:hover {
                background-color: #4b5563;
            }
        """)
        
        self.save_btn.clicked.connect(self.save_camera)
        cancel_btn.clicked.connect(self.reject)
        
        button_layout.addWidget(cancel_btn)
        button_layout.addWidget(self.save_btn)
        
        layout.addLayout(button_layout)

        # Set initial values and connect signals
        self.update_form()
        self._connect_signals()

    def _connect_signals(self):
        """Connect signals for live preview"""
        for input_field in [self.name_input, self.ip_input, self.port_input,
                          self.username_input, self.password_input, self.channel_input]:
            input_field.textChanged.connect(self.update_preview)

    def update_form(self):
        """Update form based on selected brand"""
        brand = self.brand_combo.currentText()
        brand_info = CAMERA_BRANDS[brand]
        
        self.port_input.setText(brand_info.get("default_port", "554"))
        self.channel_input.setVisible("default_channel" in brand_info)
        if "default_channel" in brand_info:
            self.channel_input.setText(brand_info["default_channel"])
            
        self.description_label.setText(brand_info["description"])
        self.update_preview()

    def update_preview(self):
        """Update the RTSP URL preview"""
        try:
            brand = self.brand_combo.currentText()
            template = CAMERA_BRANDS[brand]["template"]
            
            params = {
                "username": self.username_input.text(),
                "password": self.password_input.text(),
                "ip": self.ip_input.text(),
                "port": self.port_input.text(),
                "channel": self.channel_input.text() if self.channel_input.isVisible() else "",
                "stream": "stream"
            }
            
            url = template.format(**params)
            self.preview_text.setText(url)
            
        except Exception as e:
            self.preview_text.setText("Invalid input parameters")

    def test_connection(self):
        """Test the RTSP connection"""
        rtsp_url = self.preview_text.toPlainText()
        if not rtsp_url:
            self.show_message("Test Connection", 
                            "Please fill in all required fields", 
                            QMessageBox.Warning)
            return

        try:
            cap = cv2.VideoCapture(rtsp_url)
            if cap.isOpened():
                ret, _ = cap.read()
                cap.release()
                
                if ret:
                    self.show_message("Test Success", 
                                    "Successfully connected to camera!")
                else:
                    self.show_message("Test Failed", 
                                    "Connected but failed to get video stream",
                                    QMessageBox.Warning)
            else:
                self.show_message("Test Failed", 
                                "Failed to connect to camera",
                                QMessageBox.Warning)
                
        except Exception as e:
            self.show_message("Test Error", 
                            f"Error testing connection: {str(e)}",
                            QMessageBox.Critical)


    def save_camera(self):
        """Save the camera configuration"""
        name = self.name_input.text()
        url = self.preview_text.toPlainText()
        
        if not name or not url:
            self.show_message("Input Error", 
                            "Please fill in all required fields",
                            QMessageBox.Warning)
            return
            
        self.accept()
        return name, url
        
    def show_message(self, title, message, icon=QMessageBox.Information):
        """Show a styled message box"""
        msg_box = QMessageBox(self)
        msg_box.setWindowTitle(title)
        msg_box.setText(message)
        msg_box.setIcon(icon)
        msg_box.setStyleSheet(StyleSheet.get_message_box_style())
        return msg_box.exec_()