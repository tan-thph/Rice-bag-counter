class StyleSheet:
    @staticmethod
    def get_color_scheme():
        """Define the color palette for consistent styling"""
        return {
            # Theme colors
            'primary': '#2563eb',      # Blue
            'success': '#059669',      # Green
            'danger': '#dc2626',       # Red
            'warning': '#f59e0b',      # Orange
            
            # Neutral colors
            'text-primary': '#1f2937',
            'text-secondary': '#374151',
            'text-light': '#6b7280',
            
            # Background colors
            'bg-main': '#f9fafb',
            'bg-card': '#ffffff',
            'bg-dark': '#111827',
            
            # Border colors
            'border': '#e5e7eb',
            'border-focus': '#2563eb'
        }

    @staticmethod
    def get_main_style():
        """Get the main application stylesheet"""
        colors = StyleSheet.get_color_scheme()
        
        return f"""
            /* Base Styles */
            QWidget {{
                font-family: 'Segoe UI', Arial, sans-serif;
                font-size: 18px;
                color: {colors['text-primary']};
                background-color: {colors['bg-main']};
            }}
            
            /* Frame Styles */
            QFrame#card {{
                background: {colors['bg-card']};
                border-radius: 12px;
                padding: 24px;
                border: 1px solid {colors['border']};
            }}
            
            /* Button Styles */
            QPushButton {{
                color: white;
                border: none;
                padding: 12px 24px;
                border-radius: 8px;
                font-weight: 600;
                min-width: 140px;
                min-height: 48px;
                font-size: 18px;
            }}
            
            QPushButton:disabled {{
                background-color: {colors['text-light']};
                opacity: 0.7;
            }}
            
            #startButton, #loadButton, #stopButton {{
                border: none;
                border-radius: 6px;
                font-size: 14px;
                font-weight: 500;
                padding: 8px 16px;
            }}
            
            #startButton {{
                background-color: #059669;  /* Green */
                color: white;
            }}
            
            #startButton:hover {{
                background-color: #047857;
            }}
            
            #loadButton {{
                background-color: #3b82f6;  /* Blue */
                color: white;
            }}
            
            #loadButton:hover {{
                background-color: #2563eb;
            }}
            
            #stopButton {{
                background-color: #dc2626;  /* Red */
                color: white;
            }}
            
            #stopButton:hover {{
                background-color: #b91c1c;
            }}
            
            #startButton:disabled, #loadButton:disabled, #stopButton:disabled {{
                background-color: #9ca3af;
                color: #e5e7eb;
            }}
            
            QPushButton#updateButton {{
                background-color: {colors['primary']};
            }}
            
            QPushButton#historyButton {{
                background-color: {colors['primary']};
            }}
            
            /* Input Field Styles */
            QLineEdit, QComboBox, QDoubleSpinBox {{
                border: 2px solid {colors['border']};
                border-radius: 6px;
                padding: 12px 16px;
                background: {colors['bg-card']};
                min-height: 24px;
                font-size: 18px;
            }}
            
            QLineEdit:focus, QComboBox:focus, QDoubleSpinBox:focus {{
                border-color: {colors['border-focus']};
                outline: none;
            }}
            
            /* ComboBox specific styles */
            QComboBox::drop-down {{
                border: none;
                width: 30px;
            }}
            
            QComboBox::down-arrow {{
                image: url(:/icons/dropdown.png);
                width: 12px;
                height: 12px;
            }}
            
            /* Labels */
            QLabel {{
                font-size: 18px;
                color: {colors['text-primary']};
            }}
            
            QLabel#sectionTitle {{
                font-size: 26px;
                font-weight: bold;
                margin-bottom: 16px;
            }}
            
            QLabel#fieldLabel {{
                color: {colors['text-secondary']};
                font-weight: 500;
                padding: 10px 0;
            }}
            
            QLabel#countLabel {{
                background: {colors['bg-card']};
                border: 1px solid {colors['border']};
                border-radius: 8px;
                padding: 12px;
                font-size: 18px;
            }}
            
            QLabel#statusLabel {{
                color: {colors['text-secondary']};
                padding: 8px;
                font-size: 18px;
            }}
            
            QLabel#videoFeed {{
                background-color: {colors['bg-dark']};
                border-radius: 12px;
                min-height: 480px;
            }}
            
            /* List and Table Styles */
            QListWidget, QTableWidget {{
                border: 1px solid {colors['border']};
                border-radius: 6px;
                padding: 4px;
                font-size: 18px;
                background: {colors['bg-card']};
            }}
            
            QListWidget::item, QTableWidget::item {{
                padding: 8px;
                border-radius: 4px;
            }}
            
            QListWidget::item:selected, QTableWidget::item:selected {{
                background-color: {colors['primary']};
                color: white;
            }}
            
            /* Table Header */
            QHeaderView::section {{
                background-color: {colors['bg-main']};
                padding: 8px;
                font-size: 18px;
                font-weight: bold;
                border: 1px solid {colors['border']};
            }}
            
            /* RadioButton Styles */
            QRadioButton {{
                font-size: 18px;
                spacing: 8px;
            }}
            
            QRadioButton::indicator {{
                width: 20px;
                height: 20px;
            }}
            
            /* ScrollBar Styles */
            QScrollBar:vertical {{
                border: none;
                background: {colors['bg-main']};
                width: 12px;
                border-radius: 6px;
            }}
            
            QScrollBar::handle:vertical {{
                background: {colors['text-light']};
                border-radius: 6px;
                min-height: 30px;
            }}
            
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
                border: none;
                background: none;
            }}
            
            /* Dialog Styles */
            QDialog {{
                background-color: {colors['bg-main']};
            }}
            
            /* Tooltip Styles */
            QToolTip {{
                background-color: {colors['bg-dark']};
                color: white;
                border: none;
                padding: 8px;
                border-radius: 4px;
                font-size: 16px;
            }}
            QLabel#valueLabel {{
                font-size: 18px;
                color: #1f2937;
                font-weight: bold;
                background: #f3f4f6;
                padding: 8px 12px;
                border-radius: 6px;
            }}

            QFrame#card {{
                background: white;
                border-radius: 12px;
                padding: 20px;
                border: 1px solid #e5e7eb;
            }}

            QLabel#fieldLabel {{
                font-size: 18px;
                color: #374151;
                font-weight: 500;
            }}

            #updateButton, #historyButton {{
                background-color: #3b82f6;
                color: white;
                border: none;
                border-radius: 4px;
                font-size: 12px;
                padding: 4px 8px;
            }}
            
            #updateButton:hover, #historyButton:hover {{
                background-color: #2563eb;
            }}
            
            #updateButton:disabled {{
                background-color: #9ca3af;
            }}

            QLabel#selectCameraLabel {{
                font-size: 14px;
                font-weight: 500;
                color: #374151;
                margin-right: 10px;
            }}
            
            QComboBox#cameraCombo {{
                padding: 4px 8px;
                border: 1px solid #e5e7eb;
                border-radius: 4px;
                background-color: white;
                margin-right: 5px;
            }}
            
            QPushButton#addButton, QPushButton#removeButton {{
                background-color: white;
                border: 1px solid #e5e7eb;
                border-radius: 4px;
                font-size: 16px;
                padding: 0;
                margin: 0 2px;
                width: 32px;
                height: 32px;
                line-height: 32px;
                text-align: center;
            }}
                QPushButton#addButton {{
                color: #059669;
            }}
            
            QPushButton#addButton:hover {{
                background-color: #f0fdf4;
            }}
            
            QPushButton#removeButton {{
                color: #dc2626;
            }}
            
            QPushButton#removeButton:hover {{
                background-color: #fef2f2;
            }}

        """

    @staticmethod
    def get_history_dialog_style():
        return """
        QDialog {
            background-color: white;
        }
        
        QTableWidget {
            gridline-color: #e5e7eb;
            font-size: 22px;
        }
        
        QTableWidget::item {
            padding: 12px;
        }
        
        QHeaderView::section {
            background-color: #f3f4f6;
            padding: 12px;
            font-size: 22px;
            font-weight: bold;
            border: 1px solid #e5e7eb;
        }
        
        QPushButton#printButton {
            background-color: #3b82f6;
            color: white;
            border: none;
            border-radius: 6px;
            font-size: 18px;
            font-weight: 500;
            padding: 8px 16px;
        }
        
        QPushButton#printButton:hover {
            background-color: #2563eb;
        }
        
        QPushButton#printButton:pressed {
            background-color: #1d4ed8;
        }
        
        QLineEdit {
            padding: 8px;
            border: 1px solid #e5e7eb;
            border-radius: 4px;
            font-size: 18px;
        }
        
        QLabel {
            font-size: 18px;
        }
        """

    @staticmethod
    def get_camera_dialog_style():
        """Get styles specific to the camera configuration dialog"""
        colors = StyleSheet.get_color_scheme()
        
        return f"""
            QDialog {{
                background-color: {colors['bg-main']};
                min-width: 600px;
            }}
            
            QDialog QLabel {{
                font-size: 18px;
                color: {colors['text-secondary']};
                font-weight: 500;
            }}
            
            QDialog QLineEdit {{
                border: 2px solid {colors['border']};
                border-radius: 6px;
                padding: 12px;
                background: {colors['bg-card']};
                font-size: 18px;
            }}
            
            QDialog QComboBox {{
                border: 2px solid {colors['border']};
                border-radius: 6px;
                padding: 12px;
                background: {colors['bg-card']};
                font-size: 18px;
            }}
            
            QDialog QPushButton {{
                background-color: {colors['primary']};
                color: white;
                border: none;
                padding: 12px 24px;
                border-radius: 8px;
                min-width: 120px;
                font-weight: 600;
                font-size: 18px;
            }}
            
            QDialog QPushButton:default {{
                background-color: {colors['success']};
            }}
            
            QDialog QPushButton[text="Cancel"] {{
                background-color: {colors['text-light']};
            }}
        """
    
    @staticmethod
    def get_message_box_style():
        return """
        QMessageBox {
            background-color: #1F2937;
        }
        QLabel {
            color: white;
            min-width: 300px;
            min-height: 40px;
        }
        QPushButton {
            min-width: 100px;
            min-height: 30px;
            background-color: #374151;
            color: white;
            border: 1px solid #4B5563;
            border-radius: 4px;
            padding: 5px;
        }
        QPushButton:hover {
            background-color: #4B5563;
        }
        """