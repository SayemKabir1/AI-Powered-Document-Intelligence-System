from pathlib import Path
from openpyxl import Workbook

workbook = Workbook()
sheet = workbook.active
sheet.title = "Invoice"

sheet.append([
    "invoice_number",
    "vendor_name",
    "customer_name",
    "invoice_date",
    "currency",
    "subtotal",
    "tax",
    "total",
    "description",
    "quantity",
    "unit_price",
    "amount",
])

sheet.append([
    "INV-XLSX-001",
    "Northstar Office Supplies",
    "Example Customer Ltd",
    "2026-10-15",
    "BDT",
    5000.00,
    750.00,
    5750.00,
    "Printer Paper",
    25,
    200.00,
    5000.00,
])

output_path = Path("/app/xlsx_sample_invoice.xlsx")
workbook.save(output_path)

print(f"Created Excel test invoice: {output_path}")