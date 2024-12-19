class StyleSheet:
    @staticmethod
    def get_main_style():
        return """
            QWidget {
                font-family: 'Segoe UI', Arial, sans-serif;
                font-size: 22px;
                color: #1f2937;
            }
            
            QMainWindow, QWidget {
                background-color: #f9fafb;
            }
            
            /* Card Styles */
            QFrame#card {
                background: white;
                border-radius: 12px;
                padding: 24px;
                border: 1px solid #e5e7eb;
            }
            
            /* Button Styles */
            QPushButton {
                background-color: #2563eb;
                color: white;
                border: none;
                padding: 16px 24px;
                border-radius: 8px;
                font-weight: 600;
                min-width: 120px;
                min-height: 48px;
            }
            
            QPushButton#startButton {
                background-color: #2563eb;
            }
            
            QPushButton#loadButton {
                background-color: #059669;
            }
            
            QPushButton#stopButton {
                background-color: #dc2626;
            }
            
            /* Video Feed Style */
            QLabel#videoFeed {
                background-color: #111827;
                border-radius: 12px;
                min-height: 480px;
            }
            
            /* Section Title Style */
            QLabel#sectionTitle {
                font-size: 24px;
                font-weight: bold;
                margin-bottom: 16px;
            }
            
            /* Combo Box Style */
            QComboBox {
                background: white;
                border: 1px solid #e5e7eb;
                border-radius: 6px;
                padding: 8px 16px;
                min-width: 200px;
            }
            
            /* Count Label Style */
            QLabel#countLabel {
                background: white;
                border: 1px solid #e5e7eb;
                border-radius: 8px;
                padding: 12px;
                font-size: 22px;
            }
            
            /* Form Field Labels */
            QLabel#fieldLabel {
                font-size: 22px;
                color: #374151;
                font-weight: 500;
            }
            
            /* Input Fields */
            QLineEdit {
                border: 1px solid #e5e7eb;
                border-radius: 6px;
                padding: 8px 12px;
                background: white;
            }
        """

    @staticmethod
    def get_main_style():
        return """
            QWidget {
                font-family: 'Segoe UI', Arial, sans-serif;
                font-size: 22px;  /* Increased from 14px */
                color: #1f2937;
            }
            
            QMainWindow, QWidget {
                background-color: #f9fafb;
            }
            
            /* Card Styles */
            QFrame#card {
                background: white;
                border-radius: 12px;
                padding: 28px;  /* Increased padding */
                border: 1px solid #e5e7eb;
            }
            
            /* Button Styles */
            QPushButton {
                background-color: #2563eb;
                color: white;
                border: none;
                padding: 18px 28px;  /* Increased padding */
                border-radius: 8px;
                font-weight: 600;
                font-size: 22px;  /* Explicit font size for buttons */
                min-width: 140px;  /* Increased from 120px */
                min-height: 52px;  /* Increased from 48px */
            }
            
            QPushButton#startButton {
                background-color: #2563eb;
            }
            
            QPushButton#loadButton {
                background-color: #059669;
            }
            
            QPushButton#stopButton {
                background-color: #dc2626;
            }
            
            QPushButton#updateButton {
                background-color: #2563eb;
            }
            
            QPushButton#historyButton {
                background-color: #2563eb;
            }
            
            /* Video Feed Style */
            QLabel#videoFeed {
                background-color: #111827;
                border-radius: 12px;
                min-height: 480px;
            }
            
            /* Section Title Style */
            QLabel#sectionTitle {
                font-size: 28px;  /* Increased from 24px */
                font-weight: bold;
                margin-bottom: 20px;  /* Increased margin */
            }
            
            /* Combo Box Style */
            QComboBox {
                background: white;
                border: 1px solid #e5e7eb;
                border-radius: 6px;
                padding: 10px 18px;  /* Increased padding */
                min-width: 220px;  /* Increased from 200px */
                font-size: 22px;  /* Explicit font size */
            }
            
            /* Count Label Style */
            QLabel#countLabel {
                background: white;
                border: 1px solid #e5e7eb;
                border-radius: 8px;
                padding: 14px;  /* Increased padding */
                font-size: 22px;  /* Increased from 16px */
            }
            
            /* Status Label Style */
            QLabel#statusLabel {
                font-size: 22px;
                padding: 10px;
            }
            
            /* Form Field Labels */
            QLabel#fieldLabel {
                font-size: 22px;
                color: #374151;
                font-weight: 500;
                padding: 5px 0;
            }
            
            /* Input Fields */
            QLineEdit {
                border: 1px solid #e5e7eb;
                border-radius: 6px;
                padding: 10px 14px;  /* Increased padding */
                background: white;
                font-size: 22px;  /* Explicit font size */
                min-height: 24px;  /* Minimum height for better touch */
            }
            
            /* Spinbox Style */
            QDoubleSpinBox {
                border: 1px solid #e5e7eb;
                border-radius: 6px;
                padding: 10px 14px;
                background: white;
                font-size: 22px;
                min-height: 24px;
            }
            
            /* Radio Button Style */
            QRadioButton {
                font-size: 22px;
                padding: 5px;
            }
            
            /* List Widget Style */
            QListWidget {
                font-size: 22px;
                border: 1px solid #e5e7eb;
                border-radius: 6px;
                padding: 5px;
            }
            
            QListWidget::item {
                padding: 8px;
            }
            
            /* Table Widget Style */
            QTableWidget {
                font-size: 22px;
                gridline-color: #e5e7eb;
            }
            
            QTableWidget QHeaderView::section {
                font-size: 22px;
                padding: 8px;
                background-color: #f3f4f6;
            }
            
            QTableWidget::item {
                padding: 8px;
            }
        """
    
    @staticmethod
    def get_history_dialog_style():
        return """
            QDialog {
                background-color: #f9fafb;
                min-width: 1200px;  /* Increased from 600px */
            }
            
            QDialog QTextEdit {
                border: 1px solid #e5e7eb;
                border-radius: 8px;
                padding: 14px;  /* Increased padding */
                background: white;
                font-size: 22px;  /* Increased from 14px */
            }
            
            QDialog QPushButton {
                background-color: #008087;
                color: white;
                border: none;
                padding: 16px 30px;  /* Increased padding */
                border-radius: 8px;
                min-width: 180px;  /* Increased from 120px */
                font-weight: 600;
                font-size: 18px;
            }
            
            QDialog QPushButton:hover {
                background-color: #1d4ed8;
            }
            
            QDialog QLabel {
                font-size: 22px;
                padding: 5px 0;
            }
        """