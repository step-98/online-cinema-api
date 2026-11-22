from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict

from src.models.payments import PaymentStatusEnum


class CheckoutSessionSchema(BaseModel):
    checkout_url: str
    session_id: str


class PaymentSchema(BaseModel):
    id: int
    user_id: int
    order_id: int
    created_at: datetime
    status: PaymentStatusEnum
    amount: Decimal

    model_config = ConfigDict(from_attributes=True)
