from datetime import datetime
from typing import Any, Literal
from pydantic import BaseModel, ConfigDict, Field, field_validator

class LineItem(BaseModel):
    description: str | None = Field(default=None, max_length=500)
    quantity: float | None = Field(default=None, allow_inf_nan=False)
    unit_price: float | None = Field(default=None, allow_inf_nan=False)
    amount: float | None = Field(default=None, allow_inf_nan=False)

class InvoiceData(BaseModel):
    invoice_number: str | None = Field(default=None, max_length=100)
    invoice_date: str | None = Field(default=None, max_length=40)
    supplier_name: str | None = Field(default=None, max_length=200)
    customer_name: str | None = Field(default=None, max_length=200)
    subtotal: float | None = Field(default=None, allow_inf_nan=False)
    tax: float | None = Field(default=None, allow_inf_nan=False)
    total: float | None = Field(default=None, allow_inf_nan=False)
    currency: str | None = Field(default=None, max_length=10)
    line_items: list[LineItem] = Field(default_factory=list, max_length=500)

class DocumentResponse(BaseModel):
    id: str
    original_filename: str
    file_type: str
    file_size: int
    status: str
    page_count: int | None = None
    ocr_confidence: float | None = None
    extraction_method: str | None = None
    processing_error: str | None = None
    created_at: datetime
    updated_at: datetime
    version: int = 1
    model_config = ConfigDict(from_attributes=True)

class DocumentResultResponse(DocumentResponse):
    extracted_data: InvoiceData | None = None
    field_evidence: dict[str, Any] | None = None
    validation_errors: list[dict[str, Any]] | None = None
    validation_warnings: list[dict[str, Any]] | None = None
    extracted_text: str | None = None

class CorrectionRequest(BaseModel):
    fields: dict[str, Any] = Field(min_length=1)
    expected_version: int = Field(ge=1)
    corrected_by: str | None = Field(default="reviewer", max_length=100)

class CompareRequest(BaseModel):
    document_ids: list[str] = Field(min_length=2, max_length=10)
    fields: list[str] = Field(default_factory=lambda: ["invoice_number", "invoice_date", "supplier_name", "customer_name", "subtotal", "tax", "total", "currency", "line_items"], min_length=1, max_length=9)

    @field_validator("fields")
    @classmethod
    def validate_fields(cls, value: list[str]) -> list[str]:
        allowed = set(InvoiceData.model_fields.keys())
        invalid = sorted(set(value) - allowed)
        if invalid:
            raise ValueError(f"Unsupported comparison fields: {', '.join(invalid)}")
        if len(set(value)) != len(value):
            raise ValueError("Comparison fields must be unique")
        return value

class CompareResult(BaseModel):
    matching: bool
    documents: list[str]
    differences: list[dict[str, Any]]

class UploadResponse(BaseModel):
    accepted: list[DocumentResponse]
    rejected: list[dict[str, str]]


class ProcessingStatusResponse(BaseModel):
    document_id: str
    document_status: str
    queue_status: str | None = None
    job_id: str | None = None
    attempt_count: int = 0
    max_attempts: int = 0
    queue_created_at: datetime | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None
    last_error: str | None = None
