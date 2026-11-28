import asyncio
import json
import logging
from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal

import stripe
from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request, status
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from src.config import Settings, get_settings
from src.database import get_db
from src.models.accounts import UserGroupEnum, UserModel
from src.models.cart import CartItemModel, CartModel
from src.models.orders import OrderItemModel, OrderModel, OrderStatusEnum
from src.models.payments import PaymentItemModel, PaymentModel, PaymentStatusEnum
from src.schemas.accounts import MessageResponseSchema
from src.schemas.payments import CheckoutSessionSchema, PaymentSchema
from src.security.dependencies import get_current_user, require_group
from src.tasks import queue_task, send_payment_confirmation_email

router = APIRouter(prefix="/payments", tags=["payments"])
logger = logging.getLogger(__name__)

_ORDER_OPTIONS = selectinload(OrderModel.items).selectinload(OrderItemModel.movie)


def _to_cents(amount: Decimal) -> int:
    return int((amount * 100).to_integral_value())


async def _create_checkout_session(settings: Settings, order: OrderModel):
    return await asyncio.to_thread(
        stripe.checkout.Session.create,
        api_key=settings.STRIPE_SECRET_KEY,
        mode="payment",
        line_items=[
            {
                "quantity": 1,
                "price_data": {
                    "currency": settings.STRIPE_CURRENCY,
                    "unit_amount": _to_cents(item.price_at_order),
                    "product_data": {"name": item.movie.name},
                },
            }
            for item in order.items
        ],
        success_url=settings.PAYMENT_SUCCESS_URL,
        cancel_url=settings.PAYMENT_CANCEL_URL,
        client_reference_id=str(order.id),
        metadata={"order_id": str(order.id)},
    )


async def _create_refund(settings: Settings, payment_intent_id: str):
    return await asyncio.to_thread(
        stripe.Refund.create,
        api_key=settings.STRIPE_SECRET_KEY,
        payment_intent=payment_intent_id,
    )


async def _load_order(db: AsyncSession, order_id: int) -> OrderModel | None:
    return await db.scalar(select(OrderModel).where(OrderModel.id == order_id).options(_ORDER_OPTIONS))


def _new_payment(order: OrderModel, payment_status: PaymentStatusEnum, external_id: str) -> PaymentModel:
    return PaymentModel(
        user_id=order.user_id,
        order_id=order.id,
        status=payment_status,
        amount=order.total_amount,
        external_payment_id=external_id,
        items=[PaymentItemModel(order_item_id=item.id, price_at_payment=item.price_at_order) for item in order.items],
    )


async def _already_recorded(db: AsyncSession, external_id: str) -> bool:
    found = await db.scalar(select(PaymentModel.id).where(PaymentModel.external_payment_id == external_id))
    return found is not None


def _order_id_of(session: dict) -> int | None:
    try:
        return int((session.get("metadata") or {})["order_id"])
    except (KeyError, TypeError, ValueError):
        return None


@router.post(
    "/orders/{order_id}/checkout/",
    response_model=CheckoutSessionSchema,
    summary="Pay for an Order (Stripe Checkout)",
    description="Returns the Stripe page where the user pays. The order becomes paid only "
    "after Stripe confirms the payment through the webhook.",
    responses={
        400: {"description": "The order is not pending or has no movies left."},
        404: {"description": "Order not found."},
        502: {"description": "The payment service is unavailable."},
    },
)
async def create_checkout_session(
    order_id: int,
    user: UserModel = Depends(get_current_user),
    settings: Settings = Depends(get_settings),
    db: AsyncSession = Depends(get_db),
) -> CheckoutSessionSchema:
    order = await _load_order(db, order_id)
    if order is None or order.user_id != user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Order not found.")
    if order.status != OrderStatusEnum.PENDING:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            detail=f"Only a pending order can be paid (this order is {order.status.value}).",
        )
    if not order.items:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            detail="This order has no movies left (they were removed from the catalog).",
        )

    total = sum((item.price_at_order for item in order.items), Decimal("0"))
    if order.total_amount != total:
        order.total_amount = total
        await db.commit()

    try:
        session = await _create_checkout_session(settings, order)
    except stripe.StripeError as error:
        logger.error("Stripe checkout failed for order %s: %s", order.id, error)
        raise HTTPException(
            status.HTTP_502_BAD_GATEWAY,
            detail="The payment service is unavailable. Please try again later.",
        ) from error

    return CheckoutSessionSchema(checkout_url=session.url, session_id=session.id)


async def _handle_paid(db: AsyncSession, session: dict) -> None:
    order_id = _order_id_of(session)
    if order_id is None:
        return
    external_id = session.get("payment_intent") or session["id"]
    if await _already_recorded(db, external_id):
        return

    order = await _load_order(db, order_id)
    if order is None or order.status == OrderStatusEnum.PAID:
        return

    paid = Decimal(session["amount_total"]) / 100
    if paid != order.total_amount:
        logger.error("Order %s: paid %s but the order total is %s", order_id, paid, order.total_amount)
        return

    db.add(_new_payment(order, PaymentStatusEnum.SUCCESSFUL, external_id))
    order.status = OrderStatusEnum.PAID

    await db.execute(
        delete(CartItemModel).where(
            CartItemModel.movie_id.in_([item.movie_id for item in order.items]),
            CartItemModel.cart_id.in_(select(CartModel.id).where(CartModel.user_id == order.user_id)),
        )
    )
    await db.commit()

    email = await db.scalar(select(UserModel.email).where(UserModel.id == order.user_id))
    if email:
        queue_task(send_payment_confirmation_email, email, order.id, str(order.total_amount))


async def _handle_expired(db: AsyncSession, session: dict) -> None:
    order_id = _order_id_of(session)
    if order_id is None or await _already_recorded(db, session["id"]):
        return

    order = await _load_order(db, order_id)
    if order is None or order.status != OrderStatusEnum.PENDING:
        return

    db.add(_new_payment(order, PaymentStatusEnum.CANCELED, session["id"]))
    await db.commit()


@router.post(
    "/webhook/",
    response_model=MessageResponseSchema,
    summary="Stripe Webhook",
    description="Called by Stripe, not by users. The signature is verified before anything is done.",
    responses={400: {"description": "Invalid payload or signature."}},
)
async def stripe_webhook(
    request: Request,
    stripe_signature: str | None = Header(None, alias="Stripe-Signature"),
    settings: Settings = Depends(get_settings),
    db: AsyncSession = Depends(get_db),
) -> MessageResponseSchema:
    payload = await request.body()

    try:
        stripe.WebhookSignature.verify_header(
            payload.decode("utf-8"),
            stripe_signature,
            settings.STRIPE_WEBHOOK_SECRET,
            tolerance=stripe.Webhook.DEFAULT_TOLERANCE,
        )
        event = json.loads(payload)
    except (ValueError, stripe.SignatureVerificationError) as error:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="Invalid webhook payload or signature.") from error

    session = event["data"]["object"]
    if event["type"] == "checkout.session.completed" and session.get("payment_status") == "paid":
        await _handle_paid(db, session)
    elif event["type"] == "checkout.session.expired":
        await _handle_expired(db, session)

    return MessageResponseSchema(message="ok")


@router.get("/", response_model=list[PaymentSchema], summary="My Payments")
async def list_my_payments(
    user: UserModel = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[PaymentModel]:
    result = await db.scalars(
        select(PaymentModel)
        .where(PaymentModel.user_id == user.id)
        .order_by(PaymentModel.created_at.desc(), PaymentModel.id.desc())
    )
    return list(result.all())


@router.get(
    "/all/",
    response_model=list[PaymentSchema],
    summary="All Payments (moderators)",
    description="Moderators and admins only. Filter by user, status and creation date.",
    dependencies=[Depends(require_group(UserGroupEnum.MODERATOR))],
    responses={403: {"description": "Not enough permissions."}},
)
async def list_all_payments(
    user_id: int | None = Query(None),
    payment_status: PaymentStatusEnum | None = Query(None, alias="status"),
    date_from: date | None = Query(None, description="Created on or after this date (UTC)"),
    date_to: date | None = Query(None, description="Created on or before this date (UTC)"),
    db: AsyncSession = Depends(get_db),
) -> list[PaymentModel]:
    filters = []
    if user_id is not None:
        filters.append(PaymentModel.user_id == user_id)
    if payment_status is not None:
        filters.append(PaymentModel.status == payment_status)
    if date_from is not None:
        filters.append(PaymentModel.created_at >= datetime.combine(date_from, time.min, timezone.utc))
    if date_to is not None:
        filters.append(PaymentModel.created_at < datetime.combine(date_to + timedelta(days=1), time.min, timezone.utc))
    result = await db.scalars(
        select(PaymentModel).where(*filters).order_by(PaymentModel.created_at.desc(), PaymentModel.id.desc())
    )
    return list(result.all())


@router.post(
    "/{payment_id}/refund/",
    response_model=PaymentSchema,
    summary="Refund a Payment (moderators)",
    description="Moderators and admins only. Refunds the payment in Stripe, marks it refunded "
    "and cancels the order, so the user can buy the movies again.",
    dependencies=[Depends(require_group(UserGroupEnum.MODERATOR))],
    responses={
        400: {"description": "Only a successful payment can be refunded."},
        403: {"description": "Not enough permissions."},
        404: {"description": "Payment not found."},
        502: {"description": "The payment service is unavailable."},
    },
)
async def refund_payment(
    payment_id: int,
    settings: Settings = Depends(get_settings),
    db: AsyncSession = Depends(get_db),
) -> PaymentModel:
    payment = await db.get(PaymentModel, payment_id)
    if payment is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Payment not found.")
    if payment.status != PaymentStatusEnum.SUCCESSFUL or not payment.external_payment_id:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="Only a successful payment can be refunded.")

    try:
        await _create_refund(settings, payment.external_payment_id)
    except stripe.StripeError as error:
        logger.error("Stripe refund failed for payment %s: %s", payment.id, error)
        raise HTTPException(
            status.HTTP_502_BAD_GATEWAY,
            detail="The payment service is unavailable. Please try again later.",
        ) from error

    payment.status = PaymentStatusEnum.REFUNDED
    order = await db.get(OrderModel, payment.order_id)
    if order is not None:
        order.status = OrderStatusEnum.CANCELED
    await db.commit()
    return payment
