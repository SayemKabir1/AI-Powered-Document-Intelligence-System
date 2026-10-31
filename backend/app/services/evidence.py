from __future__ import annotations
import re
from typing import Any
from app.schemas import InvoiceData

LABELS: dict[str, str] = {
    "invoice_number": r"invoice\s*(?:number|no\.?|#|num(?:ber)?)|bill\s*(?:number|no\.?|#)",
    "invoice_date": r"invoice\s*date|bill\s*date|\bdate\b",
    "supplier_name": r"supplier|vendor|seller|\bfrom\b",
    "customer_name": r"customer|bill\s*to|buyer|\bto\b",
    "subtotal": r"sub\s*total|subtotal|net\s*amount|amount\s*before\s*tax",
    "tax": r"\b(?:tax|vat|gst)\b",
    "total": r"grand\s*total|invoice\s*total|total\s*due|amount\s*due|\btotal\b",
    "currency": r"\bcurrency\b|\b(?:USD|EUR|GBP|BDT|INR|JPY|CAD|AUD|SGD|CNY)\b",
}


def collect_field_evidence(text: str, data: InvoiceData) -> dict[str, Any]:
    """Return short source lines supporting extracted fields; never create synthetic evidence."""
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    result: dict[str, Any] = {}
    values = data.model_dump(mode="python")
    for field, value in values.items():
        if field == "line_items":
            snippets: list[str] = []
            for item in data.line_items:
                description = (item.description or "").strip()
                found = next((line for line in lines if description and description.casefold() in line.casefold()), None)
                if found:
                    snippets.append(found[:300])
                else:
                    standardized = next((line for line in lines if line.casefold().startswith("line item:")), None)
                    if standardized and standardized not in snippets:
                        snippets.append(standardized[:300])
            result[field] = snippets
            continue
        if value in (None, "", []):
            result[field] = None
            continue
        needle = str(value).strip().casefold()
        exact = next((line for line in lines if needle and needle in line.casefold()), None)
        if exact:
            result[field] = exact[:300]
            continue
        label_pattern = LABELS.get(field)
        label_line = next((line for line in lines if label_pattern and re.search(label_pattern, line, re.IGNORECASE)), None)
        result[field] = label_line[:300] if label_line else None
    return result
