from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from src.database import get_db
from src.models.accounts import UserGroupEnum, UserModel
from src.models.cart import CartItemModel, CartModel
from src.models.orders import OrderItemModel, OrderModel, OrderStatusEnum
from src.schemas.accounts import MessageResponseSchema
from src.schemas.orders import OrderCreatedSchema, OrderSchema
from src.security.dependencies import get_current_user, require_group

router = APIRouter(prefix="/orders", tags=["orders"])

_ORDER_OPTIONS = selectinload(OrderModel.items).selectinload(OrderItemModel.movie)


def _to_schema(order: OrderModel) -> OrderSchema:
    return OrderSchema(
        id=order.id,
        user_id=order.user_id,
        created_at=order.created_at,
        status=order.status,
        total_amount=order.total_amount,
        items=[
            {"movie_id": item.movie_id, "name": item.movie.name, "price": item.price_at_order} for item in order.items
        ],
    )


async def _load_orders(db: AsyncSession, *filters) -> list[OrderSchema]:
    result = await db.scalars(
        select(OrderModel)
        .where(*filters)
        .options(_ORDER_OPTIONS)
        .order_by(OrderModel.created_at.desc(), OrderModel.id.desc())
    )
    return [_to_schema(order) for order in result.all()]


@router.post(
    "/",
    response_model=OrderCreatedSchema,
    status_code=status.HTTP_201_CREATED,
    summary="Place an Order from the Cart",
    description="Movies the user has already purchased are left out and listed in "
    "excluded_movies. Payment is a separate step.",
    responses={
        400: {"description": "The cart is empty or everything in it is already purchased."},
        409: {"description": "Some movies are already in a pending order."},
    },
)
async def create_order(
    user: UserModel = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> OrderCreatedSchema:
    cart_items = (
        await db.scalars(
            select(CartItemModel)
            .join(CartModel, CartModel.id == CartItemModel.cart_id)
            .where(CartModel.user_id == user.id)
            .options(selectinload(CartItemModel.movie))
            .order_by(CartItemModel.id)
        )
    ).all()
    if not cart_items:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="The cart is empty.")

    movie_ids = [item.movie_id for item in cart_items]

    purchased_ids = set(
        await db.scalars(
            select(OrderItemModel.movie_id)
            .join(OrderModel, OrderModel.id == OrderItemModel.order_id)
            .where(
                OrderModel.user_id == user.id,
                OrderModel.status == OrderStatusEnum.PAID,
                OrderItemModel.movie_id.in_(movie_ids),
            )
        )
    )
    excluded_movies = [i.movie.name for i in cart_items if i.movie_id in purchased_ids]
    movies = [i.movie for i in cart_items if i.movie_id not in purchased_ids]
    if not movies:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            detail="All movies in the cart are already purchased.",
        )

    pending_ids = set(
        await db.scalars(
            select(OrderItemModel.movie_id)
            .join(OrderModel, OrderModel.id == OrderItemModel.order_id)
            .where(
                OrderModel.user_id == user.id,
                OrderModel.status == OrderStatusEnum.PENDING,
                OrderItemModel.movie_id.in_([m.id for m in movies]),
            )
        )
    )
    if pending_ids:
        names = ", ".join(m.name for m in movies if m.id in pending_ids)
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            detail=f"These movies are already in a pending order: {names}.",
        )

    order = OrderModel(
        user_id=user.id,
        status=OrderStatusEnum.PENDING,
        total_amount=sum((m.price for m in movies), Decimal("0")),
        items=[OrderItemModel(movie_id=m.id, price_at_order=m.price) for m in movies],
    )
    db.add(order)
    await db.commit()

    (created,) = await _load_orders(db, OrderModel.id == order.id)
    return OrderCreatedSchema(**created.model_dump(), excluded_movies=excluded_movies)


@router.get("/", response_model=list[OrderSchema], summary="My Orders")
async def list_my_orders(
    user: UserModel = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[OrderSchema]:
    return await _load_orders(db, OrderModel.user_id == user.id)


@router.get(
    "/all/",
    response_model=list[OrderSchema],
    summary="All Orders (moderators)",
    description="Moderators and admins only. Filter by user, status and creation date.",
    dependencies=[Depends(require_group(UserGroupEnum.MODERATOR))],
    responses={403: {"description": "Not enough permissions."}},
)
async def list_all_orders(
    user_id: int | None = Query(None),
    order_status: OrderStatusEnum | None = Query(None, alias="status"),
    date_from: date | None = Query(None, description="Created on or after this date (UTC)"),
    date_to: date | None = Query(None, description="Created on or before this date (UTC)"),
    db: AsyncSession = Depends(get_db),
) -> list[OrderSchema]:
    filters = []
    if user_id is not None:
        filters.append(OrderModel.user_id == user_id)
    if order_status is not None:
        filters.append(OrderModel.status == order_status)
    if date_from is not None:
        filters.append(OrderModel.created_at >= datetime.combine(date_from, time.min, timezone.utc))
    if date_to is not None:
        filters.append(OrderModel.created_at < datetime.combine(date_to + timedelta(days=1), time.min, timezone.utc))
    return await _load_orders(db, *filters)


@router.post(
    "/{order_id}/cancel/",
    response_model=MessageResponseSchema,
    summary="Cancel an Order",
    description="Only a pending order can be canceled. A paid order needs a refund request.",
    responses={
        400: {"description": "The order is already paid or already canceled."},
        404: {"description": "Order not found."},
    },
)
async def cancel_order(
    order_id: int,
    user: UserModel = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> MessageResponseSchema:
    order = await db.get(OrderModel, order_id)
    if order is None or order.user_id != user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Order not found.")
    if order.status == OrderStatusEnum.PAID:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            detail="A paid order can only be canceled through a refund request.",
        )
    if order.status == OrderStatusEnum.CANCELED:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="The order is already canceled.")

    order.status = OrderStatusEnum.CANCELED
    await db.commit()
    return MessageResponseSchema(message="Order canceled.")
