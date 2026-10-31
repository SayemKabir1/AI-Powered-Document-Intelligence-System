from app.schemas import InvoiceData, LineItem
from app.services.validation import validate_invoice, compare_invoice_data

def test_valid_invoice_has_no_errors():
    data = InvoiceData(invoice_number="INV-1", invoice_date="2026-01-02", supplier_name="Acme Ltd", customer_name="Client", subtotal=100, tax=15, total=115, currency="USD", line_items=[LineItem(description="Service", quantity=2, unit_price=50, amount=100)])
    errors, warnings = validate_invoice(data)
    assert errors == []
    assert warnings == []

def test_financial_mismatch_is_flagged():
    data = InvoiceData(invoice_number="INV-2", supplier_name="Acme", subtotal=100, tax=10, total=120, line_items=[LineItem(description="Item", quantity=1, unit_price=100, amount=100)])
    errors, warnings = validate_invoice(data)
    assert any(error["code"] == "subtotal_tax_total_mismatch" for error in errors)
    assert any(warning["code"] == "missing_required_field" for warning in warnings)

def test_line_item_math_is_flagged():
    data = InvoiceData(invoice_number="INV-3", supplier_name="Acme", subtotal=100, tax=0, total=100, line_items=[LineItem(description="Item", quantity=2, unit_price=60, amount=100)])
    errors, _ = validate_invoice(data)
    assert any(error["code"] == "line_item_calculation_mismatch" for error in errors)

def test_duplicate_supplier_and_number_warning():
    data = InvoiceData(invoice_number="INV-9", supplier_name="Acme")
    _, warnings = validate_invoice(data, [{"invoice_number": "inv-9", "supplier_name": "ACME", "document_id": "abc"}])
    assert any(warning["code"] == "possible_duplicate_invoice" for warning in warnings)

def test_compare_documents_reports_conflict():
    first = InvoiceData(invoice_number="INV-1", supplier_name="Acme", total=100)
    second = InvoiceData(invoice_number="INV-2", supplier_name="Acme", total=120)
    result = compare_invoice_data([("a", first), ("b", second)], ["invoice_number", "total"])
    assert result["matching"] is False
    assert {entry["field"] for entry in result["differences"]} == {"invoice_number", "total"}


def test_compare_documents_flags_missing_value_against_known_value():
    first = InvoiceData(invoice_number="INV-1", supplier_name="Acme", total=100)
    second = InvoiceData(invoice_number="INV-1", supplier_name="Acme", total=None)
    result = compare_invoice_data([("a", first), ("b", second)], ["invoice_number", "total"])
    assert result["matching"] is False
    total_difference = next(entry for entry in result["differences"] if entry["field"] == "total")
    assert "missing" in total_difference["message"]


def test_non_finite_amount_is_rejected_by_schema():
    import pytest
    with pytest.raises(Exception):
        InvoiceData(total=float("inf"))


def test_compare_documents_reports_line_item_difference():
    first = InvoiceData(invoice_number="INV-1", supplier_name="Acme", total=10, line_items=[LineItem(description="Paper", quantity=1, unit_price=10, amount=10)])
    second = InvoiceData(invoice_number="INV-1", supplier_name="Acme", total=10, line_items=[LineItem(description="Ink", quantity=1, unit_price=10, amount=10)])
    result = compare_invoice_data([("a", first), ("b", second)], ["invoice_number", "line_items"])
    assert result["matching"] is False
    assert any(entry["field"] == "line_items" for entry in result["differences"])


def test_unresolved_invoice_date_is_flagged_for_manual_review():
    data = InvoiceData(invoice_number="INV-DATE", invoice_date="04/05/2026", supplier_name="Example", total=10)
    _, warnings = validate_invoice(data)
    assert any(warning["code"] == "invoice_date_needs_review" for warning in warnings)
def test_unsupported_currency_is_flagged_for_manual_review():
    data = InvoiceData(currency="BOT")

    _, warnings = validate_invoice(data)

    warning = next(
        (
            item
            for item in warnings
            if item.get("code") == "unsupported_currency"
            and item.get("field") == "currency"
        ),
        None,
    )

    assert warning is not None
    assert "BOT" in warning["message"]


def test_supported_currency_is_not_flagged_as_unsupported():
    for currency in ("BDT", "USD", "bdt"):
        data = InvoiceData(currency=currency)

        _, warnings = validate_invoice(data)

        assert not any(
            item.get("code") == "unsupported_currency"
            and item.get("field") == "currency"
            for item in warnings
        )


def test_comparison_with_missing_identity_never_reports_matching():
    from app.schemas import InvoiceData
    from app.services.validation import compare_invoice_data
    result = compare_invoice_data([
        ("doc-a", InvoiceData()),
        ("doc-b", InvoiceData(invoice_number="INV-2", supplier_name="Supplier", total=10)),
    ], ["invoice_number", "supplier_name", "total"])
    assert result["matching"] is False
    assert result["differences"][0]["field"] == "identity"

def test_negative_line_item_unit_price_is_flagged():
    data = InvoiceData(
        invoice_number="INV-NEG-PRICE",
        supplier_name="Acme Ltd",
        line_items=[
            LineItem(
                description="Test Item",
                quantity=1,
                unit_price=-5,
                amount=-5,
            )
        ],
    )

    errors, _ = validate_invoice(data)

    error = next(
        (
            item
            for item in errors
            if item.get("code") == "negative_line_item_unit_price"
        ),
        None,
    )

    assert error is not None
    assert error["field"] == "line_items[0].unit_price"