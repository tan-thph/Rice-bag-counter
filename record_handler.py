import os, sys, json, tempfile
from datetime import datetime
from pathlib import Path
from PyQt5.QtWidgets import (
    QDialog, QTableWidget, QTableWidgetItem, QVBoxLayout, 
    QHBoxLayout, QPushButton, QHeaderView, QMessageBox,
    QLabel, QLineEdit, QWidget
)
from PyQt5.QtCore import Qt, QUrl
from PyQt5.QtGui import QDesktopServices
from reportlab.lib import colors
from reportlab.lib.pagesizes import A5, landscape
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import mm
from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, 
    TableStyle, Frame, KeepInFrame
)
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from qt_styles import StyleSheet

class FontManager:
    """Manages font registration and fallback for PDF generation"""
    FONT_PATHS = [
        Path(__file__).parent.parent / 'resources' / 'fonts' / 'DejaVuSans.ttf',
        Path('/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf'),
        Path('C:/Windows/Fonts/arial.ttf')
    ]

    @classmethod
    def initialize(cls):
        """Initialize fonts with fallback options"""
        for font_path in cls.FONT_PATHS:
            if font_path.exists():
                try:
                    if 'DejaVu' not in pdfmetrics.getRegisteredFontNames():
                        pdfmetrics.registerFont(TTFont('DejaVu', str(font_path)))
                    return True
                except Exception as e:
                    print(f"Error registering font {font_path}: {e}")
        raise FileNotFoundError("No suitable fonts found")

class RecordManager:
    """Manages detection records storage and retrieval"""
    
    def __init__(self):
        self.records = []
        self.records_dir = self._initialize_records_directory()
        self.load_records()

    def _initialize_records_directory(self):
        """Initialize the records directory based on OS"""
        if sys.platform == 'win32':
            base_dir = Path(os.getenv('APPDATA')) / 'RiceBagCounter'
        else:
            base_dir = Path.home() / '.ricebagcounter'

        records_dir = base_dir / 'records'
        records_dir.mkdir(parents=True, exist_ok=True)
        return records_dir

    def add_record(self, record_data):
        """Add a new detection record"""
        try:
            # Validate record data
            self._validate_record(record_data)
            
            # Add metadata
            record = dict(record_data)
            record['timestamp'] = datetime.now().isoformat()
            record['id'] = str(int(datetime.now().timestamp() * 1000))
            
            # Save to file
            file_path = self.records_dir / f"record_{record['id']}.json"
            with open(file_path, 'w', encoding='utf-8') as f:
                json.dump(record, f, ensure_ascii=False, indent=2)
            
            self.records.append(record)
            return True
        except Exception as e:
            print(f"Error adding record: {e}")
            return False

    def _validate_record(self, record):
        """Validate required fields in record"""
        required_fields = ['customer_name', 'truck_number', 'bag_count']
        missing_fields = [field for field in required_fields if not record.get(field)]
        if missing_fields:
            raise ValueError(f"Missing required fields: {', '.join(missing_fields)}")

    def load_records(self):
        """Load all records from storage"""
        try:
            self.records = []
            for file_path in self.records_dir.glob('*.json'):
                try:
                    with open(file_path, 'r', encoding='utf-8') as f:
                        record = json.load(f)
                        self.records.append(record)
                except Exception as e:
                    print(f"Error loading record {file_path}: {e}")

            # Sort by timestamp descending
            self.records.sort(key=lambda x: x.get('timestamp', ''), reverse=True)
        except Exception as e:
            print(f"Error loading records: {e}")

    def get_all_records(self):
        """Return all records"""
        return self.records

    def filter_records_by_date(self, start_date, end_date):
        """Filter records within date range"""
        filtered = []
        for record in self.records:
            try:
                record_date = datetime.strptime(
                    record['date_time'], 
                    "%Y-%m-%d %H:%M:%S"
                ).date()
                if start_date <= record_date <= end_date:
                    filtered.append(record)
            except (KeyError, ValueError) as e:
                print(f"Error filtering record: {e}")
        return filtered

class PDFGenerator:
    """Generates PDF reports from detection records"""
    
    @staticmethod
    def generate_pdf(record):
        """Generate PDF report for a record"""
        try:
            FontManager.initialize()
            
            # Create temporary file
            with tempfile.NamedTemporaryFile(delete=False, suffix='.pdf') as temp_file:
                pdf_path = temp_file.name

            # Setup document
            doc = SimpleDocTemplate(
                pdf_path,
                pagesize=landscape(A5),
                leftMargin=10*mm,
                rightMargin=10*mm,
                topMargin=10*mm,
                bottomMargin=10*mm
            )

            # Generate content
            elements = PDFGenerator._generate_content(record)
            
            # Build PDF
            doc.build(
                elements,
                onFirstPage=PDFGenerator._add_footer,
                onLaterPages=PDFGenerator._add_footer
            )

            # Open PDF
            QDesktopServices.openUrl(QUrl.fromLocalFile(pdf_path))
            return pdf_path

        except Exception as e:
            print(f"Error generating PDF: {e}")
            raise

    @staticmethod
    def _generate_content(record):
        """Generate PDF content elements"""
        styles = PDFGenerator._get_styles()
        elements = []

        # Add header
        elements.extend([
            Paragraph("Nhà Máy Xay Xát Gạo Thạnh Hương", styles['centered']),
            Paragraph("Thành lập và hoạt động từ năm 1996", styles['centered']),
            Paragraph("Địa chỉ: Quảng Nghiệp - Phước Hưng - Tuy Phước - Bình Định", styles['centered']),
            Paragraph("SĐT: 0256 3 836 118", styles['centered']),
            Spacer(1, 5*mm),
            Paragraph(
                f"Phiếu kết quả kiểm đếm hàng hóa - Khách hàng: {record.get('customer_name', ' ')}", 
                styles['title']
            ),
            Spacer(1, 5*mm)
        ])

        # Add table
        table_data = PDFGenerator._prepare_table_data(record)
        table = Table(table_data, colWidths=[40*mm, 60*mm, 40*mm, 60*mm])
        table.setStyle(PDFGenerator._get_table_style())
        elements.append(table)

        return elements

    @staticmethod
    def _get_styles():
        """Get document styles"""
        styles = getSampleStyleSheet()
        return {
            'centered': ParagraphStyle(
                'Centered',
                parent=styles['Normal'],
                fontName='DejaVu',
                alignment=TA_CENTER,
                fontSize=10,
                leading=12
            ),
            'left': ParagraphStyle(
                'Left',
                parent=styles['Normal'],
                fontName='DejaVu',
                alignment=TA_LEFT,
                fontSize=10,
                leading=12
            ),
            'right': ParagraphStyle(
                'Right',
                parent=styles['Normal'],
                fontName='DejaVu',
                alignment=TA_RIGHT,
                fontSize=10,
                leading=12
            ),
            'title': ParagraphStyle(
                'Title',
                parent=styles['Heading1'],
                fontName='DejaVu',
                alignment=TA_CENTER,
                fontSize=14
            )
        }

    @staticmethod
    def _prepare_table_data(record):
        """Prepare data for PDF table"""
        try:
            # Format date
            date_time = record.get('date_time', 'N/A')
            if date_time != 'N/A':
                try:
                    # Try different date formats
                    try:
                        date_obj = datetime.strptime(date_time, '%Y-%m-%d %H:%M:%S')
                    except ValueError:
                        # Try alternate format if first one fails
                        date_obj = datetime.strptime(date_time, '%d-%m-%Y %H:%M')
                    formatted_date = date_obj.strftime('%d-%m-%Y %H:%M')
                except ValueError:
                    formatted_date = date_time
            else:
                formatted_date = 'N/A'

            # Calculate total weight
            try:
                # Clean and convert weight per bag
                weight_per_bag_str = str(record.get('weight_per_bag', '0'))
                weight_per_bag_str = weight_per_bag_str.replace(',', '.').strip()
                weight_per_bag = float(weight_per_bag_str)

                # Clean and convert bag count
                bag_count_str = str(record.get('bag_count', '0'))
                bag_count = int(bag_count_str)

                total_weight = f"{weight_per_bag * bag_count:.2f} Kg"
            except (ValueError, TypeError):
                # If calculation fails, try to use provided total weight
                total_weight = record.get('total_weight', 'N/A')
                if total_weight != 'N/A':
                    total_weight = f"{total_weight} Kg"

            # Prepare table data with cleaned values
            return [
                ["Ngày & Giờ", formatted_date, "Loại công việc", record.get('source_type', 'N/A')],
                ["Khách hàng", record.get('customer_name', 'N/A'), "Số xe", record.get('truck_number', 'N/A')],
                ["Số đơn hàng", "N/A", "Hàng hóa", record.get('commodity', 'N/A')],
                ["Trọng lượng mỗi bao", f"{weight_per_bag:.2f} Kg", "Số bao đã đếm", str(bag_count)],
                ["Tổng trọng lượng", total_weight, "", ""]
            ]
        except Exception as e:
            print(f"Error preparing table data: {e}")
            # Return safe default values if processing fails
            return [
                ["Ngày & Giờ", "N/A", "Loại công việc", "N/A"],
                ["Khách hàng", "N/A", "Số xe", "N/A"],
                ["Số đơn hàng", "N/A", "Hàng hóa", "N/A"],
                ["Trọng lượng mỗi bao", "N/A", "Số  bao đã đếm", "N/A"],
                ["Tổng trọng lượng", "N/A", "", ""]
            ]

    @staticmethod
    def _get_table_style():
        """Get table styling"""
        return TableStyle([
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
        ])

    @staticmethod
    def _add_footer(canvas, doc):
        """Add footer to PDF pages"""
        canvas.saveState()
        styles = PDFGenerator._get_styles()
        
        footer_frame = Frame(
            doc.leftMargin, 
            doc.bottomMargin, 
            doc.width, 
            40*mm
        )
        
        footer_content = [
            Paragraph("Ngày _____ Tháng _____ Năm _____", styles['centered']),
            Spacer(1, 5*mm),
            Table(
                [[Paragraph("Chữ kí khách hàng", styles['left']),
                  Paragraph("Người xuất phiếu", styles['right'])]],
                colWidths=[100*mm, 100*mm]
            )
        ]
        
        footer_frame.addFromList(
            [KeepInFrame(doc.width, 20*mm, footer_content)],
            canvas
        )
        canvas.restoreState()

class HistoryDialog(QDialog):
    """Dialog for viewing detection history"""
    
    def __init__(self, parent, records):
        super().__init__(parent)
        self.records = records
        self.init_ui()
        self.setStyleSheet(StyleSheet.get_history_dialog_style())

    def init_ui(self):
        """Initialize the dialog UI"""
        self.setWindowTitle("Detection History")
        self.setMinimumSize(1800, 800)
        
        layout = QVBoxLayout(self)
        layout.setSpacing(20)
        layout.setContentsMargins(20, 20, 20, 20)
        
        # Add search functionality
        self.setup_search()
        
        # Setup and populate table
        self.setup_table()
        self.populate_table(self.records)
        
        # Add close button
        self.add_close_button(layout)

    def setup_search(self):
        """Setup search functionality"""
        search_layout = QHBoxLayout()
        
        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("Tìm kiếm...")
        self.search_input.textChanged.connect(self.filter_records)
        
        search_layout.addWidget(QLabel("Tìm kiếm:"))
        search_layout.addWidget(self.search_input)
        search_layout.addStretch()
        
        self.layout().addLayout(search_layout)

    def filter_records(self, text):
        """Filter records based on search text"""
        if not text:
            self.populate_table(self.records)
            return
            
        filtered = []
        search_text = text.lower()
        
        for record in self.records:
            if any(search_text in str(value).lower() 
                  for value in record.values()):
                filtered.append(record)
                
        self.populate_table(filtered)

    def setup_table(self):
        """Setup the table widget"""
        self.table = QTableWidget()
        self.table.setSortingEnabled(True)
        
        columns = [
            ("Ngày và giờ", 250),
            ("Khách hàng", 200),
            ("Biển số xe", 150),
            ("Loại\nhàng", 150),
            ("Số\nđơn hàng", 150),
            ("Trọng lượng\nmỗi bao (kg)", 200),
            ("Số\nbao", 80),
            ("Tổng\ntrọng lượng", 180),
            ("Nguồn", 120),
            ("In", 220)
        ]
        
        self.table.setColumnCount(len(columns))
        
        headers = []
        for i, (header, width) in enumerate(columns):
            self.table.setColumnWidth(i, width)
            headers.append(header)
        
        self.table.setHorizontalHeaderLabels(headers)
        
        # Lock column widths
        header = self.table.horizontalHeader()
        for i in range(len(columns)):
            header.setSectionResizeMode(i, QHeaderView.Fixed)
        
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
        
        self.table.verticalHeader().setDefaultSectionSize(80)
        self.table.verticalHeader().setVisible(True)
        self.layout().addWidget(self.table)

    def create_print_button(self, row):
        """Create a print button for a table row"""
        print_button = QPushButton("In")
        print_button.setObjectName("printButton")
        print_button.setFixedSize(120, 45)
        print_button.clicked.connect(lambda: self.print_record(row))
        
        # Add direct styling to ensure visibility
        print_button.setStyleSheet("""
            QPushButton#printButton {
                background-color: #3b82f6;  /* Blue background */
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
        """)
        
        return print_button

    def populate_table(self, records):
        """Populate table with records"""
        self.table.setRowCount(len(records))
        
        for row, record in enumerate(records):
            # Define columns and their alignment
            columns = [
                ('date_time', Qt.AlignLeft),
                ('customer_name', Qt.AlignLeft),
                ('truck_number', Qt.AlignLeft),
                ('commodity', Qt.AlignLeft),
                ('order_number', Qt.AlignLeft),
                ('weight_per_bag', Qt.AlignRight),
                ('bag_count', Qt.AlignRight),
                ('total_weight', Qt.AlignRight),
                ('source_type', Qt.AlignCenter)
            ]
            
            # Set data for each column
            for col, (field, alignment) in enumerate(columns):
                item = QTableWidgetItem(str(record.get(field, '')))
                item.setTextAlignment(alignment | Qt.AlignVCenter)
                self.table.setItem(row, col, item)
            
            # Add print button in the last column
            self.table.setCellWidget(row, len(columns), self.create_print_button(row))

    def add_close_button(self, layout):
        """Add close button to dialog"""
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
        """Handle printing of a record"""
        try:
            # Create a dictionary with the correct field mappings
            header_mappings = {
                "Ngày và giờ": "date_time",
                "Khách hàng": "customer_name",
                "Biển số xe": "truck_number",
                "Loại hàng": "commodity",
                "Số đơn hàng": "order_number",
                "Trọng lượng mỗi bao (kg)": "weight_per_bag",
                "Số bao": "bag_count",
                "Tổng trọng lượng (kg)": "total_weight",
                "Nguồn": "source_type"
            }

            # Extract data from table into a properly formatted record
            record_data = {}
            for col in range(self.table.columnCount() - 1):  # Exclude the print button column
                header = self.table.horizontalHeaderItem(col).text()
                item = self.table.item(row, col)
                if item:
                    # Map the table header to the correct field name
                    if header in header_mappings:
                        field_name = header_mappings[header]
                        # Clean up the data
                        value = item.text().strip()
                        if header == "Trọng lượng\nmỗi bao (kg)":
                            # Remove "kg" if present and convert to proper format
                            value = value.replace("Kg", "").replace("kg", "").strip()
                        elif header == "Tổng\ntrọng lượng":
                            # Extract just the number from the total weight
                            value = value.split()[0] if value else "0"
                        record_data[field_name] = value

            # Generate PDF with proper data structure
            try:
                pdf_path = PDFGenerator.generate_pdf(record_data)
                if pdf_path:
                    # Open the generated PDF
                    QDesktopServices.openUrl(QUrl.fromLocalFile(pdf_path))
                else:
                    QMessageBox.warning(self, "Print Error", "Failed to generate PDF report.")

            except Exception as e:
                QMessageBox.critical(self, "PDF Generation Error", 
                                f"Error generating PDF: {str(e)}")

        except Exception as e:
            QMessageBox.critical(self, "Error", 
                            f"Error preparing record data: {str(e)}")