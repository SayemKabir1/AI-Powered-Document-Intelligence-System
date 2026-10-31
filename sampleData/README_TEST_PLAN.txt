TASK 1 CONTROLLED DOCUMENT TEST PACK
Purpose: local verification only. All names and values are fictional.

Suggested order:
1. 01_invoice_csv.csv                 CSV baseline
2. 02_invoice_multi_sheet.xlsx        XLSX; two sheets (Invoice, SupportingData)
3. 03_invoice_legacy_xls.xls          legacy XLS
4. 04_invoice_photo.jpg               JPG OCR
5. 05_invoice_photo.tiff              TIFF OCR
6. 06_invoice_two_page_digital.pdf    digital PDF, 2 pages; line items on page 2
7. 07_invoice_two_page_scanned.pdf    scanned PDF, 2 image pages; line items on page 2
8. 08_poor_quality_scan.png           intentionally degraded image; expect possible field warnings
9. 09_poor_quality_scanned.pdf        intentionally degraded scan PDF; expect possible field warnings
10. 10_corrupted.pdf                  should fail gracefully and record a failed job/error
11. 11_corrupted.jpg                  should fail gracefully and record a failed job/error
12. 12_unsupported.txt                should be rejected by upload validation, or fail gracefully if accepted

Expected key values (only require exact extraction on clean samples):
01 CSV: INV-CSV-201; 2026-10-01; CSV Test Supplies; subtotal 100; tax 15; total 115; BDT; USB cables x2 @50, amount 100.
02 XLSX: INV-XLSX-202; 2026-10-02; XLSX Test Supplies; subtotal 240; tax 36; total 276; BDT; Wireless mouse x3 @80, amount 240. Also verify the second sheet is included in processing metadata/text if the UI/API exposes it.
03 XLS: INV-XLS-203; 2026-10-03; Legacy Excel Supplies; subtotal 50; tax 7.5; total 57.5; BDT; HDMI adapter x1 @50, amount 50.
04 JPG: INV-JPG-310; 2026-10-04; JPG Test Supplies; subtotal 320; tax 48; total 368; BDT; Keyboard x4 @80, amount 320.
05 TIFF: INV-TIFF-410; 2026-10-05; TIFF Test Supplies; subtotal 125; tax 18.75; total 143.75; BDT; Notebook x5 @25, amount 125.
06 digital PDF: INV-PDF-MULTI-204; 2026-10-07; MultiPage PDF Supplies; subtotal 500; tax 75; total 575; BDT; Network switch x2 @250, amount 500. Confirm page count is 2 and page-two details are extracted.
07 scanned PDF: INV-SCAN-MULTI-205; 2026-10-08; Scanned MultiPage Supplies; subtotal 640; tax 96; total 736; BDT; Ethernet cables x8 @80, amount 640. Confirm page count is 2 and page-two OCR details are included.

Cautions:
- Upload one file at a time initially. Wait until status is Completed or Failed before proceeding.
- For poor-quality scans, don't require every field to be exact; confirm processing completes, source text is recorded, and uncertain fields are flagged or left blank rather than invented.
- For corrupted files, a clear Failed status or explicit upload rejection is a correct handling result; a crashed worker or API is not.
- Save screenshots or record status, extracted values, pages/sheets metadata, processing duration, and any error for each test.
- Some spreadsheet parsing metadata may be visible only through the API. Use API docs if the UI doesn't show page/sheet counts.
