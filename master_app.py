import sys
import os
from PyQt5.QtWidgets import QApplication, QWidget, QVBoxLayout, QPushButton, QListWidget, QHBoxLayout, QLineEdit, QLabel, QMessageBox
from PyQt5.QtCore import Qt
import json
from pathlib import Path
from main_cv2 import AppWindow  # Import the main application window

class MasterApp(QWidget):
    def __init__(self):
        super().__init__()
        self.active_windows = {}  # Store AppWindow instances instead of processes
        self.initUI()
        self.load_camera_list()

    def initUI(self):
        self.setWindowTitle('Rice Bag Counter Master App')
        self.setGeometry(100, 100, 300, 200)

        layout = QVBoxLayout()

        # Input source management
        input_layout = QHBoxLayout()
        self.input_edit = QLineEdit()
        self.input_edit.setPlaceholderText("Đặt tên")
        input_layout.addWidget(self.input_edit)
        
        add_button = QPushButton('Thêm vào')
        add_button.clicked.connect(self.add_input_source)
        input_layout.addWidget(add_button)
        
        layout.addLayout(input_layout)

        # List of cameras
        layout.addWidget(QLabel('Danh sách bộ đếm đã được tạo:'))
        self.source_list = QListWidget()
        layout.addWidget(self.source_list)

        # Buttons layout
        button_layout = QHBoxLayout()
        
        launch_button = QPushButton('Mở bộ đếm đã chọn')
        launch_button.clicked.connect(self.launch_selected_camera)
        button_layout.addWidget(launch_button)
        
        launch_all_button = QPushButton('Mở tất cả bộ đếm')
        launch_all_button.clicked.connect(self.launch_all_cameras)
        button_layout.addWidget(launch_all_button)
        
        remove_button = QPushButton('Xóa bộ đếm đã chọn')
        remove_button.clicked.connect(self.remove_selected_camera)
        button_layout.addWidget(remove_button)
        
        layout.addLayout(button_layout)

        # Status section
        layout.addWidget(QLabel('Bộ đếm đang chạy:'))
        self.active_list = QListWidget()
        layout.addWidget(self.active_list)

        self.setLayout(layout)

    def load_camera_list(self):
        """Load saved camera list from file"""
        try:
            camera_file = Path('camera_list.json')
            if camera_file.exists():
                with open(camera_file, 'r') as f:
                    cameras = json.load(f)
                    for camera in cameras:
                        self.source_list.addItem(camera)
        except Exception as e:
            QMessageBox.warning(self, 'Lỗi', f'Error loading camera list: {str(e)}')

    def save_camera_list(self):
        """Save camera list to file"""
        try:
            cameras = [self.source_list.item(i).text() 
                      for i in range(self.source_list.count())]
            with open('camera_list.json', 'w') as f:
                json.dump(cameras, f)
        except Exception as e:
            QMessageBox.warning(self, 'Lỗi', f'Error saving camera list: {str(e)}')

    def add_input_source(self):
        camera_name = self.input_edit.text().strip()
        if camera_name:
            # Check for duplicates
            existing_items = [self.source_list.item(i).text() 
                            for i in range(self.source_list.count())]
            if camera_name not in existing_items:
                self.source_list.addItem(camera_name)
                self.input_edit.clear()
                self.save_camera_list()
            else:
                QMessageBox.warning(self, 'Lỗi', 'Tên bộ đếm này đã tồn tại!')

    def launch_camera(self, camera_name):
        """Launch a single camera instance"""
        if camera_name not in self.active_windows or not self.active_windows[camera_name].isVisible():
            try:
                # Create new AppWindow instance
                window = AppWindow()
                window.setWindowTitle(f"Rice Bag Counter - {camera_name}")
                
                # Store reference to window
                self.active_windows[camera_name] = window
                
                # Show the window
                window.show()
                
                # Update active list
                self.update_active_list()
                
            except Exception as e:
                QMessageBox.critical(self, 'Error', f'Failed to launch camera {camera_name}: {str(e)}')

    def launch_selected_camera(self):
        """Launch selected cameras from the list"""
        selected_items = self.source_list.selectedItems()
        if not selected_items:
            QMessageBox.warning(self, 'Warning', 'Vui lòng chọn một bộ đếm để mở')
            return
            
        for item in selected_items:
            self.launch_camera(item.text())

    def launch_all_cameras(self):
        """Launch all cameras in the list"""
        for i in range(self.source_list.count()):
            camera_name = self.source_list.item(i).text()
            self.launch_camera(camera_name)

    def remove_selected_camera(self):
        """Remove selected camera from the list"""
        selected_items = self.source_list.selectedItems()
        if not selected_items:
            return
            
        for item in selected_items:
            camera_name = item.text()
            # Close window if it's open
            if camera_name in self.active_windows:
                self.active_windows[camera_name].close()
                del self.active_windows[camera_name]
            self.source_list.takeItem(self.source_list.row(item))
        
        self.save_camera_list()
        self.update_active_list()

    def update_active_list(self):
        """Update the list of active cameras"""
        self.active_list.clear()
        # Update list based on visible windows
        for camera_name, window in list(self.active_windows.items()):
            if window.isVisible():
                self.active_list.addItem(f"{camera_name} (Running)")
            else:
                del self.active_windows[camera_name]

    def closeEvent(self, event):
        """Handle application closing"""
        try:
            # Save camera list before closing
            self.save_camera_list()
            
            # Ask if user wants to close all running instances
            if self.active_windows:
                reply = QMessageBox.question(self, 'Đóng tất cả',
                    'Bạn có muốn đóng tất cả bộ đếm không?',
                    QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
                
                if reply == QMessageBox.Yes:
                    # Close all active windows
                    for window in self.active_windows.values():
                        window.close()
            
            event.accept()
            
        except Exception as e:
            print(f"Error during cleanup: {e}")
            event.accept()

if __name__ == '__main__':
    app = QApplication(sys.argv)
    master_app = MasterApp()
    master_app.show()
    sys.exit(app.exec_())