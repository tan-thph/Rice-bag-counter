
import sys, os
from PyQt5.QtWidgets import (QWidget, QPushButton, 
                             QVBoxLayout, QHBoxLayout, 
                             QFileDialog, QMessageBox, QTextEdit)

from PyQt5.QtWidgets import (QDialog, QTableWidget, QTableWidgetItem, QVBoxLayout, 
                           QPushButton, QHeaderView, QDialogButtonBox,
                           QMessageBox, QFileDialog)
from PyQt5.QtPrintSupport import QPrinter, QPrintDialog
from PyQt5.QtCore import QSizeF, QMarginsF, Qt, QDateTime, QUrl
from PyQt5.QtGui import QPageSize, QTextDocument, QDesktopServices
import json
from datetime import datetime

# New imports for PDF generation
from reportlab.lib.pagesizes import A5, landscape
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, Frame, KeepInFrame
from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT
import tempfile
import os

from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont

from qt_styles import StyleSheet

# Get the directory of the current script
current_dir = os.path.dirname(os.path.abspath(__file__))
font_path = os.path.join(current_dir, 'fonts', 'DejaVuSans.ttf')
app_dir = os.path.dirname(current_dir)
font_path = os.path.join(app_dir, 'resources', 'fonts', 'DejaVuSans.ttf')

# Add debug prints to verify paths
print(f"Current directory: {current_dir}")
print(f"App directory: {app_dir}")
print(f"Font path: {font_path}")
print(f"Font exists: {os.path.exists(font_path)}")

# Only register font if it exists
if not os.path.exists(font_path):
    raise FileNotFoundError(f"Font file not found at: {font_path}")

# Register DejaVu font
pdfmetrics.registerFont(TTFont('DejaVu', font_path))

class DetectionRecord:
    def __init__(self, customer_name="", truck_number="", commodity="", 
                 date_time="", weight_per_bag="", total_weight="", 
                 bag_count=0, source_type="Camera"):
        self.customer_name = customer_name
        self.truck_number = truck_number
        self.commodity = commodity
        self.date_time = date_time
        self.weight_per_bag = weight_per_bag
        self.total_weight = total_weight
        self.bag_count = bag_count
        self.source_type = source_type

    def to_dict(self):
        return {
            "customer_name": self.customer_name,
            "truck_number": self.truck_number,
            "commodity": self.commodity,
            "date_time": self.date_time,
            "weight_per_bag": self.weight_per_bag,
            "total_weight": self.total_weight,
            "bag_count": self.bag_count,
            "source_type": self.source_type
        }

    @classmethod
    def from_dict(cls, data):
        return cls(**data)

class RecordManager:
    def __init__(self):
        self.records = []
        self.records_dir = self._get_records_dir()
        self.load_records()

    def _get_records_dir(self):
        """Get or create the records directory in Downloads folder"""
        downloads_path = os.path.expanduser("~/Downloads")
        records_dir = os.path.join(downloads_path, "records")
        
        if not os.path.exists(records_dir):
            try:
                os.makedirs(records_dir)
                print(f"Created records directory at: {records_dir}")
            except Exception as e:
                print(f"Error creating records directory: {e}")
                return None
        
        return records_dir

    def generate_filename(self):
        """Generate a unique filename for the record"""
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        return f"record_{timestamp}.json"

    def add_record(self, record):
        """Add a new record and save it to file"""
        if not self.records_dir:
            print("Records directory not available")
            return False

        try:
            # Add timestamp if not present
            if 'timestamp' not in record:
                record['timestamp'] = datetime.now().isoformat()

            # Save to individual file
            filename = self.generate_filename()
            filepath = os.path.join(self.records_dir, filename)
            
            with open(filepath, 'w', encoding='utf-8') as f:
                json.dump(record, f, ensure_ascii=False, indent=4)

            self.records.append(record)
            print(f"Record saved to: {filepath}")
            return True

        except Exception as e:
            print(f"Error saving record: {e}")
            return False

    def load_records(self):
        """Load all records from the records directory"""
        if not self.records_dir:
            print("Records directory not available")
            return

        try:
            self.records = []
            for filename in os.listdir(self.records_dir):
                if filename.endswith('.json'):
                    filepath = os.path.join(self.records_dir, filename)
                    try:
                        with open(filepath, 'r', encoding='utf-8') as f:
                            record = json.load(f)
                            self.records.append(record)
                    except Exception as e:
                        print(f"Error loading record {filename}: {e}")

            # Sort records by timestamp if available
            self.records.sort(key=lambda x: x.get('timestamp', ''), reverse=True)
            print(f"Loaded {len(self.records)} records")

        except Exception as e:
            print(f"Error loading records: {e}")

    def get_all_records(self):
        """Return all records"""
        return self.records

    def filter_records_by_date(self, start_date, end_date):
        """Filter records between start_date and end_date"""
        filtered = []
        for record in self.records:
            try:
                record_date = datetime.strptime(record['date_time'], "%Y-%m-%d %H:%M:%S").date()
                if start_date <= record_date <= end_date:
                    filtered.append(record)
            except (KeyError, ValueError) as e:
                print(f"Error processing record date: {e}")
        return filtered
    
    pass

class PDFGenerator:
    @staticmethod
    def generate_pdf(record):
        # Create a temporary file for the PDF
        with tempfile.NamedTemporaryFile(delete=False, suffix='.pdf') as temp_file:
            buffer = temp_file.name

        # Create the PDF document
        doc = SimpleDocTemplate(
            buffer,
            pagesize=landscape(A5),
            leftMargin=10*mm,
            rightMargin=10*mm,
            topMargin=10*mm,
            bottomMargin=10*mm
        )

        elements = []
        styles = getSampleStyleSheet()

        # Define styles
        centered_style = ParagraphStyle(
            name='Centered',
            parent=styles['Normal'],
            fontName='DejaVu',
            alignment=TA_CENTER,
            fontSize=10,
            leading=12
        )
        
        left_style = ParagraphStyle(
            name='Left',
            parent=styles['Normal'],
            fontName='DejaVu',
            alignment=TA_LEFT,
            fontSize=10,
            leading=12
        )
        
        right_style = ParagraphStyle(
            name='Right',
            parent=styles['Normal'],
            fontName='DejaVu',
            alignment=TA_RIGHT,
            fontSize=10,
            leading=12
        )
        
        title_style = ParagraphStyle(
            name='Title',
            parent=styles['Heading1'],
            fontName='DejaVu',
            alignment=TA_CENTER,
            fontSize=14
        )

        # Add company information
        elements.append(Paragraph("Công ty TNHH DV XNK Thành Hưng", centered_style))
        elements.append(Paragraph("Quảng Nghiệp - Phước Hưng - Tuy Phước - Bình Định", centered_style))
        elements.append(Paragraph("SĐT: 836-118", centered_style))
        elements.append(Spacer(1, 5*mm))

        # Add title
        elements.append(Paragraph(f"Phiếu kết quả kiểm đếm hàng hóa - {record.get('customer_name', 'N/A')}", title_style))
        elements.append(Spacer(1, 5*mm))

        # Format date
        date_time = record.get('date_time', 'N/A')
        if date_time != 'N/A':
            try:
                date_obj = datetime.strptime(date_time, '%Y-%m-%d %H:%M:%S')
                formatted_date = date_obj.strftime('%d-%m-%Y %H:%M')
            except ValueError:
                formatted_date = date_time
        else:
            formatted_date = 'N/A'

        # Calculate total weight
        try:
            weight_per_bag = float(record.get('weight_per_bag', 0))
            bag_count = float(record.get('bag_count', 0))
            total_weight = f"{weight_per_bag * bag_count:.2f} Kg"
        except (ValueError, TypeError):
            total_weight = "N/A"

        # Create table data
        data = [
            ["Ngày & Giờ", formatted_date, "Loại công việc", record.get('source_type', 'N/A')],
            ["Khách hàng", record.get('customer_name', 'N/A'), "Số xe", record.get('truck_number', 'N/A')],
            ["Số đơn hàng", "N/A", "Hàng hóa", record.get('commodity', 'N/A')],
            ["Trọng lượng/Đơn vị", f"{record.get('weight_per_bag', 'N/A')} Kg", "Số lượng cuối cùng", str(record.get('bag_count', 'N/A'))],
            ["Tổng trọng lượng", total_weight, "", ""]
        ]

        # Create and style table
        table = Table(data, colWidths=[40*mm, 60*mm, 40*mm, 60*mm])
        table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (0, -1), colors.grey),
            ('BACKGROUND', (2, 0), (2, -1), colors.grey),
            ('TEXTCOLOR', (0, 0), (0, -1), colors.whitesmoke),
            ('TEXTCOLOR', (2, 0), (2, -1), colors.whitesmoke),
            ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
            ('FONTNAME', (0, 0), (-1, -1), 'DejaVu'),
            ('FONTSIZE', (0, 0), (-1, -1), 10),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 6),
            ('BACKGROUND', (1, 0), (1, -1), colors.white),
            ('BACKGROUND', (3, 0), (3, -1), colors.white),
            ('BOX', (0, 0), (-1, -1), 1, colors.black),
            ('GRID', (0, 0), (-1, -1), 1, colors.black),
        ]))
        elements.append(table)

        # Add footer
        def add_footer(canvas, doc):
            canvas.saveState()
            footer_frame = Frame(doc.leftMargin, doc.bottomMargin, doc.width, 20*mm)
            footer_content = [
                Paragraph("Ngày _____ Tháng _____ Năm _____", centered_style),
                Spacer(1, 5*mm),
                Table(
                    [[Paragraph("Chữ kí khách hàng", left_style),
                      Paragraph("Người xuất phiếu", right_style)]],
                    colWidths=[100*mm, 100*mm]
                )
            ]
            footer_frame.addFromList([KeepInFrame(doc.width, 20*mm, footer_content)], canvas)
            canvas.restoreState()

        # Build PDF
        doc.build(elements, onFirstPage=add_footer, onLaterPages=add_footer)
        
        # Open PDF with default viewer
        QDesktopServices.openUrl(QUrl.fromLocalFile(buffer))
        return buffer

class RecordPrinter:
    @staticmethod
    def print_record(record, parent_widget=None):
        """Generate and open PDF for a record"""
        try:
            pdf_path = PDFGenerator.generate_pdf(record)
            return pdf_path
        except Exception as e:
            print(f"Error generating PDF: {e}")
            if parent_widget:
                QMessageBox.critical(parent_widget, "PDF Generation Error", 
                                   f"Failed to generate PDF: {str(e)}")
            return None
        
class HistoryDialog(QDialog):
    def __init__(self, parent, records):
        super().__init__(parent)
        self.init_ui(records)

    def init_ui(self, records):
        # Basic window setup
        self.setWindowTitle("Detection History")
        self.setMinimumSize(2000, 800)
        
        # Main layout
        layout = QVBoxLayout(self)
        layout.setSpacing(20)
        layout.setContentsMargins(20, 20, 20, 20)
        
        # Create and setup table
        self.setup_table()
        
        # Populate table with data
        self.populate_table(records)
        
        # Add table to layout
        layout.addWidget(self.table)
        
        # Add close button
        self.add_close_button(layout)

    def setup_table(self):
        self.table = QTableWidget()
        
        # Set up columns
        columns = [
            ("Ngày và giờ", 250),
            ("Khách hàng", 200),
            ("Biển số xe", 200),
            ("Loại hàng", 200),
            ("Trọng lượng/bao (kg)", 250),
            ("Số bao", 120),
            ("Tổng trọng lượng (kg)", 300),
            ("Nguồn", 120),
            (" ", 220)
        ]
        
        self.table.setColumnCount(len(columns))
        
        # Set headers and column widths
        headers = []
        for i, (header, width) in enumerate(columns):
            self.table.setColumnWidth(i, width)
            headers.append(header)
        
        self.table.setHorizontalHeaderLabels(headers)
        
        # Lock column widths
        header = self.table.horizontalHeader()
        for i in range(len(columns)):
            header.setSectionResizeMode(i, QHeaderView.Fixed)
        
        # Style the table
        self.table.setStyleSheet("""
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
                height: 60px;
            }
        """)
        
        # Set row height
        self.table.verticalHeader().setDefaultSectionSize(80)
        
        # Additional table properties
        self.table.setShowGrid(True)
        self.table.setAlternatingRowColors(True)
        self.table.verticalHeader().setVisible(True)

    def create_print_button(self, row):
        container = QWidget()
        layout = QHBoxLayout(container)
        
        # Remove margins to prevent button shifting
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        
        # Create print button
        print_button = QPushButton("In")
        print_button.setFixedSize(120, 45)
        print_button.clicked.connect(lambda: self.print_record(row))
        print_button.setStyleSheet("""
            QPushButton {
                background-color: #2563eb;
                color: white;
                border: none;
                border-radius: 6px;
                font-size: 20px;
                padding: 10px 20px;
            }
            QPushButton:hover {
                background-color: #1d4ed8;
            }
        """)
        
        # Add button to layout and center it
        layout.addWidget(print_button, 0, Qt.AlignCenter)
        
        return container

    def populate_table(self, records):
        self.table.setRowCount(len(records))
        
        for row, record in enumerate(records):
            # Set data for each column
            columns = [
                ('date_time', Qt.AlignLeft),
                ('customer_name', Qt.AlignLeft),
                ('truck_number', Qt.AlignLeft),
                ('commodity', Qt.AlignLeft),
                ('weight_per_bag', Qt.AlignRight),
                ('bag_count', Qt.AlignRight),
                ('total_weight', Qt.AlignRight),
                ('source_type', Qt.AlignCenter)
            ]
            
            for col, (field, alignment) in enumerate(columns):
                item = QTableWidgetItem(str(record.get(field, '')))
                item.setTextAlignment(alignment | Qt.AlignVCenter)
                self.table.setItem(row, col, item)
            
            # Add print button
            self.table.setCellWidget(row, 8, self.create_print_button(row))

    def add_close_button(self, layout):
        close_button = QPushButton("Đóng cửa sổ")
        close_button.setFixedHeight(60)
        close_button.clicked.connect(self.close)
        close_button.setStyleSheet("""
            QPushButton {
                background-color: #dc2626;
                color: white;
                border: none;
                border-radius: 6px;
                font-size: 22px;
                padding: 12px 24px;
            }
            QPushButton:hover {
                background-color: #b91c1c;
            }
        """)
        layout.addWidget(close_button)

    def print_record(self, row):
        # Get data from the selected row
        record_data = {}
        for col in range(self.table.columnCount() - 1):  # Exclude the Actions column
            header = self.table.horizontalHeaderItem(col).text()
            item = self.table.item(row, col)
            record_data[header] = item.text() if item else ""

        # Create printer dialog
        printer = QPrinter(QPrinter.HighResolution)
        dialog = QPrintDialog(printer, self)
        
        if dialog.exec_() == QPrintDialog.Accepted:
            # Print logic here - you can customize this based on your needs
            pass