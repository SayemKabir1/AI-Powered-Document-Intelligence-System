from __future__ import annotations
from decimal import Decimal, InvalidOperation
from datetime import datetime
from typing import Any
from app.schemas import InvoiceData

REQUIRED_FIELDS = ["invoice_number", "invoice_date", "supplier_name", "total"]

SUPPORTED_CURRENCIES = {
    "USD", "EUR", "GBP", "BDT", "INR", "JPY", "CAD", "AUD", "SGD", "CNY",
    "CHF", "AED", "SAR", "QAR", "KWD", "BHD", "OMR", "NPR", "PKR", "LKR",
    "THB", "MYR", "IDR", "PHP", "KRW", "HKD", "NZD", "ZAR", "NGN", "KES",
    "EGP", "TRY", "BRL", "MXN", "ARS", "CLP", "COP", "SEK", "NOK", "DKK",
    "PLN", "CZK", "HUF", "RON", "UAH", "ILS", "TWD", "VND", "MMK", "GHS",
}

def _decimal(value: Any) -> Decimal | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        number = Decimal(str(value))
        if not number.is_finite():
            return None
        return number
    except (InvalidOperation, ValueError, TypeError):
        return None

def validate_invoice(data: InvoiceData, existing_invoices: list[dict[str, Any]] | None = None, field_evidence: dict[str, Any] | None = None) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    errors: list[dict[str, Any]] = []
    warnings: list[dict[str, Any]] = []
    values = data.model_dump()
    for field in REQUIRED_FIELDS:
        if values.get(field) in (None, "", []):
            warnings.append({"code": "missing_required_field", "field": field, "message": f"Required field '{field}' is missing; manual review is recommended."})
    for field in ("customer_name", "subtotal", "tax", "currency"):
        if values.get(field) in (None, "", []):
            warnings.append({"code": "missing_field", "field": field, "message": f"Field '{field}' was not confidently extracted; manual review may be needed."})
    currency_value = values.get("currency")
    if currency_value not in (None, "", []):
        currency_code = str(currency_value).strip().upper()
        if currency_code not in SUPPORTED_CURRENCIES:
            warnings.append({
                "code": "unsupported_currency",
                "field": "currency",
                "message": (
                    f"Currency code '{currency_value}' is not recognized; "
                    "verify it against the source document."
                ),
            })

    if data.invoice_date:
        try:
            datetime.strptime(data.invoice_date, "%Y-%m-%d")
        except ValueError:
            warnings.append({"code": "invoice_date_needs_review", "field": "invoice_date", "message": "The date could not be normalized unambiguously to YYYY-MM-DD; verify the source date before relying on it."})
    if field_evidence is not None:
        for field in ("invoice_number", "invoice_date", "supplier_name", "total"):
            if values.get(field) not in (None, "", []) and not field_evidence.get(field):
                warnings.append({"code": "source_evidence_not_found", "field": field, "message": f"Could not find a direct source-text snippet for extracted field '{field}'; verify it against the original document."})
    if not data.line_items and data.subtotal is not None:
        warnings.append({"code": "line_items_not_extracted", "field": "line_items", "message": "No line items were confidently extracted; compare against the source document."})
    amount_fields = ["subtotal", "tax", "total"]
    for field in amount_fields:
        amount = _decimal(values.get(field))
        if amount is not None and amount < 0:
            errors.append({"code": "negative_amount", "field": field, "message": f"'{field}' is negative."})
    subtotal = _decimal(data.subtotal)
    tax = _decimal(data.tax)
    total = _decimal(data.total)
    if subtotal is not None and tax is not None and total is not None:
        difference = abs((subtotal + tax) - total)
        if difference > Decimal("0.02"):
            errors.append({"code": "subtotal_tax_total_mismatch", "field": "total", "message": f"Subtotal + tax differs from total by {difference.quantize(Decimal('0.01'))}.", "expected_total": float(subtotal + tax), "actual_total": float(total)})
    line_amounts = [_decimal(item.amount) for item in data.line_items]
    if data.line_items and all(amount is not None for amount in line_amounts) and subtotal is not None:
        line_sum = sum((amount for amount in line_amounts if amount is not None), Decimal(0))
        if abs(line_sum - subtotal) > Decimal("0.02"):
            errors.append({"code": "line_items_subtotal_mismatch", "field": "subtotal", "message": f"Line-item amounts sum to {line_sum}, which differs from subtotal {subtotal}.", "line_items_sum": float(line_sum), "subtotal": float(subtotal)})
    for index, item in enumerate(data.line_items):
        quantity, unit_price, amount = _decimal(item.quantity), _decimal(item.unit_price), _decimal(item.amount)
        missing_item_fields = [name for name, value in (("quantity", item.quantity), ("unit_price", item.unit_price), ("amount", item.amount)) if value is None]
        if missing_item_fields:
            warnings.append({"code": "incomplete_line_item", "field": f"line_items[{index}]", "message": f"Line item {index + 1} is missing {', '.join(missing_item_fields)}; verify these values against the source document."})
        if quantity is not None and quantity <= 0:
            errors.append({"code": "invalid_line_item_quantity", "field": f"line_items[{index}].quantity", "message": f"Line-item quantity at row {index + 1} must be greater than zero."})
        if unit_price is not None and unit_price < 0:
            errors.append({
                "code": "negative_line_item_unit_price",
                "field": f"line_items[{index}].unit_price",
                "message": f"Line-item unit price at row {index + 1} is negative.",
            })
        if amount is not None and amount < 0:
            errors.append({"code": "negative_line_item_amount", "field": f"line_items[{index}].amount", "message": f"Line-item amount at row {index + 1} is negative."})
        if quantity is not None and unit_price is not None and amount is not None and abs(quantity * unit_price - amount) > Decimal("0.02"):
            errors.append({"code": "line_item_calculation_mismatch", "field": f"line_items[{index}].amount", "message": f"Quantity × unit price differs from line-item amount at row {index + 1}.", "expected_amount": float(quantity * unit_price), "actual_amount": float(amount)})
    if data.invoice_number and data.supplier_name:
        norm_num = data.invoice_number.strip().casefold()
        norm_supplier = data.supplier_name.strip().casefold()
        for existing in (existing_invoices or []):
            if str(existing.get("invoice_number") or "").strip().casefold() == norm_num and str(existing.get("supplier_name") or "").strip().casefold() == norm_supplier:
                warnings.append({"code": "possible_duplicate_invoice", "field": "invoice_number", "message": "Another processed document has the same supplier and invoice number.", "existing_document_id": existing.get("document_id")})
                break
    if data.total is not None and (data.subtotal is None or data.tax is None):
        warnings.append({"code": "partial_financial_breakdown", "field": "subtotal", "message": "Total is present but subtotal or tax is missing, so arithmetic could not be fully verified."})
    return errors, warnings

def compare_invoice_data(documents: list[tuple[str, InvoiceData]], fields: list[str]) -> dict[str, Any]:
    differences: list[dict[str, Any]] = []
    if len(documents) < 2:
        return {
            "matching": False,
            "documents": [document_id for document_id, _ in documents],
            "differences": [{"field": "identity", "values": [],
                "message": "At least two documents are required for cross-verification."}],
        }
    missing_identity = [
        {"document_id": document_id, "invoice_number": data.invoice_number,
         "supplier_name": data.supplier_name, "total": data.total}
        for document_id, data in documents
        if not data.invoice_number or not data.supplier_name or data.total is None
    ]
    valid_fields = set(InvoiceData.model_fields.keys())
    selected = [field for field in fields if field in valid_fields and field != "line_items"]
    for field in selected:
        values = [{"document_id": document_id, "value": getattr(data, field)} for document_id, data in documents]
        known = [item["value"] for item in values if item["value"] is not None and item["value"] != ""]
        normalized = {str(value).strip().casefold() if isinstance(value, str) else round(float(value), 2) if isinstance(value, (float, int)) else value for value in known}
        has_missing = len(known) != len(values)
        if len(normalized) > 1 or (known and has_missing):
            reason = "some documents are missing this value" if has_missing and len(normalized) <= 1 else f"documents disagree on '{field}'"
            differences.append({"field": field, "values": values, "message": f"Cross-verification issue: {reason}."})
    if "line_items" in fields:
        def normalized_items(data: InvoiceData):
            result = []
            for item in data.line_items:
                result.append((
                    (item.description or "").strip().casefold(),
                    round(item.quantity, 4) if item.quantity is not None else None,
                    round(item.unit_price, 2) if item.unit_price is not None else None,
                    round(item.amount, 2) if item.amount is not None else None,
                ))
            return sorted(result, key=lambda row: tuple("" if value is None else str(value) for value in row))
        item_values = [{"document_id": document_id, "value": data.model_dump(mode="json")["line_items"]} for document_id, data in documents]
        normalized = [normalized_items(data) for _, data in documents]
        if normalized and any(items != normalized[0] for items in normalized[1:]):
            differences.append({"field": "line_items", "values": item_values, "message": "Cross-verification issue: documents have different or missing line items."})
    if missing_identity:
        differences.insert(0, {
            "field": "identity", "values": missing_identity,
            "message": "Cross-verification cannot confirm a match because one or more documents are missing invoice number, supplier name, or total.",
        })
    return {"matching": len(differences) == 0, "documents": [document_id for document_id, _ in documents], "differences": differences}
