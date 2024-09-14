from reportlab.lib import colors
from reportlab.lib.pagesizes import A5
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer, Frame, KeepInFrame
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from io import BytesIO
from datetime import datetime

# Register DejaVu font
pdfmetrics.registerFont(TTFont('DejaVu', 'DejaVuSans.ttf'))

def create_job_result_pdf(job_result):
    buffer = BytesIO()
    
    # Use A5 size and adjust margins
    doc = SimpleDocTemplate(buffer, pagesize=A5, 
                            leftMargin=10*mm, rightMargin=10*mm, 
                            topMargin=10*mm, bottomMargin=15*mm)
    
    elements = []

    styles = getSampleStyleSheet()
    
    # Adjust font sizes for A5
    centered_style = ParagraphStyle(name='Centered', parent=styles['Normal'], fontName='DejaVu', alignment=TA_CENTER, fontSize=9, leading=11)
    left_style = ParagraphStyle(name='Left', parent=styles['Normal'], fontName='DejaVu', alignment=TA_LEFT, fontSize=9, leading=11)
    right_style = ParagraphStyle(name='Right', parent=styles['Normal'], fontName='DejaVu', alignment=TA_RIGHT, fontSize=9, leading=11)
    title_style = ParagraphStyle(name='Title', parent=styles['Heading1'], fontName='DejaVu', alignment=TA_CENTER, fontSize=12)

    # Add company information
    elements.append(Paragraph("Công ty TNHH DV XNK Thành Hưng", centered_style))
    elements.append(Paragraph("Quảng Nghiệp - Phước Hưng  - Tuy Phước - Bình Định", centered_style))
    elements.append(Paragraph("SĐT: 836-118", centered_style))

    elements.append(Spacer(1, 5*mm))

    # Add the title
    title = Paragraph(f"Phiếu kiểm đếm hàng hóa - {job_result['customer_name']}", title_style)
    elements.append(title)

    elements.append(Spacer(1, 5*mm))

    # Format the date
    date_time = job_result.get('date_time', 'N/A')
    if date_time != 'N/A':
        try:
            date_obj = datetime.strptime(date_time, '%Y-%m-%d %H:%M:%S')
            formatted_date = date_obj.strftime('%d-%m-%Y %H:%M')
        except ValueError:
            formatted_date = date_time
    else:
        formatted_date = 'N/A'

    # Job details table
    data = [
        ["Ngày & Giờ", formatted_date],
        ["Nguồn", job_result.get('job_type', 'N/A')],
        ["Khách hàng", job_result.get('customer_name', 'N/A')],
        ["Số xe", job_result.get('truck_number', 'N/A')],
        ["Số đơn hàng", job_result.get('order_number', 'N/A')],
        ["Hàng hóa", job_result.get('commodity', 'N/A')],
        ["Trọng lượng/Đơn vị", str(job_result.get('weight_per_unit', 'N/A'))],
        ["Số lượng cuối cùng", str(job_result.get('final_count', 0))],
        ["Tổng trọng lượng", f"{float(job_result.get('final_count', 0)) * float(job_result.get('weight_per_unit', 0)):.2f} Kg"],
    ]

    if 'note' in job_result and job_result['note']:
        data.append(["Ghi chú", job_result['note']])

    # Adjust table style for A5
    table = Table(data, colWidths=[40*mm, 80*mm])
    table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (0, -1), colors.grey),
        ('TEXTCOLOR', (0, 0), (0, -1), colors.whitesmoke),
        ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
        ('FONTNAME', (0, 0), (-1, -1), 'DejaVu'),
        ('FONTSIZE', (0, 0), (-1, -1), 8),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
        ('BACKGROUND', (1, 1), (-1, -1), colors.beige),
        ('BOX', (0, 0), (-1, -1), 1, colors.black),
        ('GRID', (0, 0), (-1, -1), 1, colors.black),
    ]))
    elements.append(table)

    # Footer
    def add_footer(canvas, doc):
        canvas.saveState()
        footer_frame = Frame(doc.leftMargin, doc.bottomMargin, doc.width, 20*mm)
        footer_content = [
            Paragraph("Ngày _____ Tháng _____ Năm _____", centered_style),
            Spacer(1, 5*mm),
            Table([
                [Paragraph("Chữ kí khách hàng", left_style), Paragraph("Người xuất phiếu", right_style)]
            ], colWidths=[60*mm, 60*mm])
        ]
        footer_frame.addFromList([KeepInFrame(doc.width, 20*mm, footer_content)], canvas)
        canvas.restoreState()

    doc.build(elements, onFirstPage=add_footer, onLaterPages=add_footer)
    buffer.seek(0)
    return buffer