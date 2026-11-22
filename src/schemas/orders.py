from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel

from src.models.orders import OrderStatusEnum


class OrderItemSchema(BaseModel):
    movie_id: int
    name: str
    price: Decimal


class OrderSchema(BaseModel):
    id: int
    user_id: int
    created_at: datetime
    status: OrderStatusEnum
    total_amount: Decimal | None
    items: list[OrderItemSchema]


class OrderCreatedSchema(OrderSchema):
    excluded_movies: list[str]
