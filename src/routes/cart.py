from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from src.database import get_db
from src.models.accounts import UserGroupEnum, UserModel
from src.models.cart import CartItemModel, CartModel
from src.models.movies import MovieModel
from src.models.orders import OrderItemModel, OrderModel, OrderStatusEnum
from src.schemas.accounts import MessageResponseSchema
from src.schemas.cart import CartItemSchema, CartSchema
from src.security.dependencies import get_current_user, require_group

router = APIRouter(prefix="/cart", tags=["cart"])


async def _find_cart(db: AsyncSession, user_id: int) -> CartModel | None:
    return await db.scalar(select(CartModel).where(CartModel.user_id == user_id))


async def _cart_contents(db: AsyncSession, cart: CartModel | None) -> CartSchema:
    if cart is None:
        return CartSchema(items=[])

    result = await db.scalars(
        select(CartItemModel)
        .where(CartItemModel.cart_id == cart.id)
        .options(selectinload(CartItemModel.movie).selectinload(MovieModel.genres))
        .order_by(CartItemModel.added_at, CartItemModel.id)
    )
    return CartSchema(
        items=[
            CartItemSchema(
                movie_id=item.movie.id,
                name=item.movie.name,
                price=item.movie.price,
                year=item.movie.year,
                genres=[genre.name for genre in item.movie.genres],
                added_at=item.added_at,
            )
            for item in result.all()
        ]
    )


@router.get("/", response_model=CartSchema, summary="My Cart")
async def get_my_cart(
    user: UserModel = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> CartSchema:
    return await _cart_contents(db, await _find_cart(db, user.id))


@router.post(
    "/movies/{movie_id}/",
    response_model=CartSchema,
    status_code=status.HTTP_201_CREATED,
    summary="Add Movie to Cart",
    responses={
        404: {"description": "Movie not found."},
        409: {"description": "The movie is already in the cart or already purchased."},
    },
)
async def add_movie_to_cart(
    movie_id: int,
    user: UserModel = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> CartSchema:
    if await db.get(MovieModel, movie_id) is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Movie not found.")

    already_purchased = await db.scalar(
        select(OrderItemModel.id)
        .join(OrderModel, OrderModel.id == OrderItemModel.order_id)
        .where(
            OrderModel.user_id == user.id,
            OrderModel.status == OrderStatusEnum.PAID,
            OrderItemModel.movie_id == movie_id,
        )
        .limit(1)
    )
    if already_purchased is not None:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            detail="The movie is already purchased. Repeat purchases are not allowed.",
        )

    cart = await _find_cart(db, user.id)
    if cart is None:
        cart = CartModel(user_id=user.id)
        db.add(cart)
        await db.flush()

    already_in_cart = await db.scalar(
        select(CartItemModel.id).where(CartItemModel.cart_id == cart.id, CartItemModel.movie_id == movie_id)
    )
    if already_in_cart is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, detail="The movie is already in the cart.")

    db.add(CartItemModel(cart_id=cart.id, movie_id=movie_id))
    try:
        await db.commit()
    except IntegrityError as error:
        await db.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, detail="The movie is already in the cart.") from error

    return await _cart_contents(db, cart)


@router.delete(
    "/movies/{movie_id}/",
    response_model=CartSchema,
    summary="Remove Movie from Cart",
    responses={404: {"description": "The movie is not in the cart."}},
)
async def remove_movie_from_cart(
    movie_id: int,
    user: UserModel = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> CartSchema:
    cart = await _find_cart(db, user.id)
    item = None
    if cart is not None:
        item = await db.scalar(
            select(CartItemModel).where(CartItemModel.cart_id == cart.id, CartItemModel.movie_id == movie_id)
        )
    if cart is None or item is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="The movie is not in the cart.")

    await db.delete(item)
    await db.commit()
    return await _cart_contents(db, cart)


@router.delete("/", response_model=MessageResponseSchema, summary="Clear Cart")
async def clear_cart(
    user: UserModel = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> MessageResponseSchema:
    cart = await _find_cart(db, user.id)
    if cart is not None:
        await db.execute(delete(CartItemModel).where(CartItemModel.cart_id == cart.id))
        await db.commit()
    return MessageResponseSchema(message="Cart cleared.")


@router.get(
    "/users/{user_id}/",
    response_model=CartSchema,
    summary="View a User's Cart",
    description="Moderators and admins only, for analysis and troubleshooting.",
    dependencies=[Depends(require_group(UserGroupEnum.MODERATOR))],
    responses={
        403: {"description": "Not enough permissions."},
        404: {"description": "User not found."},
    },
)
async def get_user_cart(user_id: int, db: AsyncSession = Depends(get_db)) -> CartSchema:
    if await db.get(UserModel, user_id) is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="User not found.")
    return await _cart_contents(db, await _find_cart(db, user_id))
