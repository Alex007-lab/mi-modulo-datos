"""
models.py — Modelos Pydantic para validación de requests y responses.
"""

from datetime import datetime
from typing import Optional
from pydantic import BaseModel, Field, field_validator


# ─── Request models ───────────────────────────────────────────────────────────

class TransactionIn(BaseModel):
    """Schema de una transacción para el endpoint POST /transactions/batch."""
    transaction_id: str = Field(..., min_length=1, max_length=100)
    timestamp:      datetime
    user_id:        int  = Field(..., gt=0)
    merchant_id:    int  = Field(..., gt=0)
    amount:         float = Field(..., gt=0)
    category:       str  = Field(..., min_length=1)
    country_code:   str  = Field(..., min_length=2, max_length=2)
    status:         str  = Field(..., pattern="^(completed|failed|pending)$")

    @field_validator("amount")
    @classmethod
    def amount_must_be_positive(cls, v: float) -> float:
        if v <= 0:
            raise ValueError("amount debe ser mayor a 0")
        return round(v, 2)

    @field_validator("country_code")
    @classmethod
    def country_code_uppercase(cls, v: str) -> str:
        return v.upper()


class BatchRequest(BaseModel):
    """Body del POST /transactions/batch."""
    transactions: list[TransactionIn] = Field(
        ...,
        min_length=1,
        max_length=500,
        description="Lista de transacciones a insertar (máximo 500).",
    )


# ─── Response models ──────────────────────────────────────────────────────────

class CountryBreakdown(BaseModel):
    country_code:       str
    total_transactions: int
    total_amount:       float


class CategoryBreakdown(BaseModel):
    category:     str
    total_amount: float
    avg_amount:   float


class SummaryResponse(BaseModel):
    total_transactions: int
    total_amount:       float
    avg_amount:         float
    by_country:         list[CountryBreakdown]
    by_category:        list[CategoryBreakdown]


class MerchantEntry(BaseModel):
    merchant_id:        int
    total_amount:       float
    total_transactions: int


class TopMerchantsResponse(BaseModel):
    merchants: list[MerchantEntry]
    limit:     int
    country:   Optional[str]


class TransactionOut(BaseModel):
    transaction_id: str
    timestamp:      str
    user_id:        int
    merchant_id:    int
    amount:         float
    category:       str
    country_code:   str
    status:         str


class UserTransactionsResponse(BaseModel):
    user_id:      int
    page:         int
    page_size:    int
    transactions: list[TransactionOut]


class UserStatsResponse(BaseModel):
    user_id:            int
    total_amount:       float
    transaction_count:  int
    top_category:       str
    country_code:       str


class BatchResponse(BaseModel):
    inserted:    int
    duplicates:  int
    invalid:     int
    total_received: int


class HealthResponse(BaseModel):
    status:          str
    uptime_seconds:  float
    cache_hit_rate:  float
    cache_hits:      int
    cache_misses:    int
