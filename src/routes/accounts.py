from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload

from src.config import Settings, get_settings
from src.database import get_db
from src.exceptions import BaseSecurityError
from src.models.accounts import (
    ActivationTokenModel,
    PasswordResetTokenModel,
    RefreshTokenModel,
    UserGroupEnum,
    UserGroupModel,
    UserModel,
)
from src.schemas.accounts import (
    ChangePasswordRequestSchema,
    MessageResponseSchema,
    PasswordResetCompleteRequestSchema,
    PasswordResetRequestSchema,
    ResendActivationRequestSchema,
    UserActivationRequestSchema,
    UserLoginRequestSchema,
    UserLoginResponseSchema,
    UserRegistrationRequestSchema,
    TokenRefreshRequestSchema,
    TokenRefreshResponseSchema,
    UserRegistrationResponseSchema,
)
from src.security.dependencies import get_current_user, get_jwt_auth_manager
from src.security.jwt_manager import JWTAuthManager
from src.tasks import queue_task, send_activation_email, send_password_reset_email
from src.dates import as_utc

router = APIRouter(prefix="/accounts", tags=["accounts"])


@router.post(
    "/register/",
    response_model=UserRegistrationResponseSchema,
    status_code=status.HTTP_201_CREATED,
    summary="User Registration",
    description="Register a new user with an email and password.",
    responses={
        409: {"description": "A user with this email already exists."},
        500: {"description": "An error occurred during user creation."},
    },
)
async def register_user(
    user_data: UserRegistrationRequestSchema,
    db: AsyncSession = Depends(get_db),
) -> UserModel:
    email = str(user_data.email)

    existing_user_id = await db.scalar(select(UserModel.id).where(UserModel.email == email))
    if existing_user_id is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"A user with this email {email} already exists.",
        )

    group_id = await db.scalar(select(UserGroupModel.id).where(UserGroupModel.name == UserGroupEnum.USER))
    if group_id is None:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Default user group not found.",
        )

    try:
        new_user = UserModel.create(
            email=email,
            raw_password=user_data.password,
            group_id=group_id,
        )
        db.add(new_user)
        await db.flush()

        activation_token = ActivationTokenModel(user_id=new_user.id)
        db.add(activation_token)
        await db.commit()
    except IntegrityError as error:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"A user with this email {email} already exists.",
        ) from error
    except SQLAlchemyError as error:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An error occurred during user creation.",
        ) from error

    queue_task(send_activation_email, email, activation_token.token)

    return new_user


def _invalid_activation_token() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_400_BAD_REQUEST,
        detail="Invalid or expired activation token.",
    )


@router.post(
    "/activate/",
    response_model=MessageResponseSchema,
    status_code=status.HTTP_200_OK,
    summary="Activate User Account",
    description="Activate a user's account using their email and activation token.",
    responses={
        400: {"description": "Invalid or expired token, or the account is already active."},
        500: {"description": "An error occurred during account activation."},
    },
)
async def activate_account(
    activation_data: UserActivationRequestSchema,
    db: AsyncSession = Depends(get_db),
) -> MessageResponseSchema:
    stmt = (
        select(ActivationTokenModel)
        .options(joinedload(ActivationTokenModel.user))
        .join(UserModel)
        .where(
            UserModel.email == str(activation_data.email),
            ActivationTokenModel.token == activation_data.token,
        )
    )
    token_record = (await db.execute(stmt)).scalars().first()

    if token_record is None:
        raise _invalid_activation_token()

    user = token_record.user

    try:
        if as_utc(token_record.expires_at) < datetime.now(timezone.utc):
            await db.delete(token_record)
            await db.commit()
            raise _invalid_activation_token()

        if user.is_active:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="User account is already active.",
            )

        user.is_active = True
        await db.delete(token_record)
        await db.commit()
    except SQLAlchemyError as error:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An error occurred during account activation.",
        ) from error

    return MessageResponseSchema(message="User account activated successfully.")


@router.post(
    "/login/",
    response_model=UserLoginResponseSchema,
    status_code=status.HTTP_200_OK,
    summary="User Login",
    description="Authenticate a user and return access and refresh tokens.",
    responses={
        401: {"description": "Invalid email or password."},
        403: {"description": "User account is not activated."},
        500: {"description": "An error occurred while processing the request."},
    },
)
async def login_user(
    login_data: UserLoginRequestSchema,
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
    jwt_manager: JWTAuthManager = Depends(get_jwt_auth_manager),
) -> UserLoginResponseSchema:
    user = await db.scalar(select(UserModel).where(UserModel.email == str(login_data.email)))

    if user is None or not user.verify_password(login_data.password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password.",
        )

    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="User account is not activated.",
        )

    refresh_token = jwt_manager.create_refresh_token({"user_id": user.id})

    try:
        db.add(
            RefreshTokenModel.create(
                user_id=user.id,
                days_valid=settings.REFRESH_TOKEN_EXPIRE_DAYS,
                token=refresh_token,
            )
        )
        await db.commit()
    except SQLAlchemyError as error:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An error occurred while processing the request.",
        ) from error

    access_token = jwt_manager.create_access_token({"user_id": user.id})

    return UserLoginResponseSchema(
        access_token=access_token,
        refresh_token=refresh_token,
    )


@router.post(
    "/refresh/",
    response_model=TokenRefreshResponseSchema,
    status_code=status.HTTP_200_OK,
    summary="Refresh Access Token",
    description="Get a new access token using a valid refresh token.",
    responses={
        401: {"description": "Refresh token is invalid, expired, revoked, or its user is inactive."},
    },
)
async def refresh_access_token(
    token_data: TokenRefreshRequestSchema,
    db: AsyncSession = Depends(get_db),
    jwt_manager: JWTAuthManager = Depends(get_jwt_auth_manager),
) -> TokenRefreshResponseSchema:
    try:
        jwt_manager.decode_refresh_token(token_data.refresh_token)
    except BaseSecurityError as error:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=error.message,
        ) from error

    token_record = await db.scalar(select(RefreshTokenModel).where(RefreshTokenModel.token == token_data.refresh_token))
    if token_record is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Refresh token not found.",
        )

    user = await db.get(UserModel, token_record.user_id)
    if user is None or not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found or not active.",
        )

    return TokenRefreshResponseSchema(access_token=jwt_manager.create_access_token({"user_id": user.id}))


@router.post(
    "/logout/",
    response_model=MessageResponseSchema,
    status_code=status.HTTP_200_OK,
    summary="User Logout",
    description="Revoke a refresh token so it can no longer be used.",
    responses={
        500: {"description": "An error occurred while processing the request."},
    },
)
async def logout_user(
    token_data: TokenRefreshRequestSchema,
    db: AsyncSession = Depends(get_db),
) -> MessageResponseSchema:
    try:
        await db.execute(delete(RefreshTokenModel).where(RefreshTokenModel.token == token_data.refresh_token))
        await db.commit()
    except SQLAlchemyError as error:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An error occurred while processing the request.",
        ) from error

    return MessageResponseSchema(message="Logged out successfully.")


@router.post(
    "/change-password/",
    response_model=MessageResponseSchema,
    status_code=status.HTTP_200_OK,
    summary="Change Password",
    description="Change the password of the current user by providing the old one.",
    responses={
        400: {"description": "The old password is incorrect."},
        401: {"description": "Not authenticated."},
        500: {"description": "An error occurred while changing the password."},
    },
)
async def change_password(
    data: ChangePasswordRequestSchema,
    user: UserModel = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> MessageResponseSchema:
    if not user.verify_password(data.old_password):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Old password is incorrect.",
        )

    try:
        user.password = data.new_password  # validated and hashed by the model
        await db.commit()
    except SQLAlchemyError as error:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An error occurred while changing the password.",
        ) from error

    return MessageResponseSchema(message="Password changed successfully.")


_RESEND_ACTIVATION_MESSAGE = "If the account exists and is not activated yet, a new activation link has been sent."
_PASSWORD_RESET_MESSAGE = "If you are registered, you will receive an e-mail with instructions."


@router.post(
    "/activate/resend/",
    response_model=MessageResponseSchema,
    summary="Resend the Activation Link",
    description="For an account that is not activated yet: replaces the activation token "
    "with a new one (valid for 24 hours) and sends it by e-mail.",
    responses={500: {"description": "An error occurred while creating the token."}},
)
async def resend_activation(
    data: ResendActivationRequestSchema,
    db: AsyncSession = Depends(get_db),
) -> MessageResponseSchema:
    email = str(data.email).lower()
    user = await db.scalar(select(UserModel).where(UserModel.email == email))

    if user is not None and not user.is_active:
        try:
            await db.execute(delete(ActivationTokenModel).where(ActivationTokenModel.user_id == user.id))
            token = ActivationTokenModel(user_id=user.id)
            db.add(token)
            await db.commit()
        except SQLAlchemyError as error:
            await db.rollback()
            raise HTTPException(
                status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="An error occurred while creating the token.",
            ) from error
        queue_task(send_activation_email, email, token.token)

    return MessageResponseSchema(message=_RESEND_ACTIVATION_MESSAGE)


@router.post(
    "/password-reset/request/",
    response_model=MessageResponseSchema,
    summary="Request a Password Reset",
    description="For an active account: creates a reset token (valid for 24 hours, replaces "
    "any earlier one) and sends the link by e-mail. The answer is the same for any e-mail.",
    responses={500: {"description": "An error occurred while creating the token."}},
)
async def request_password_reset(
    data: PasswordResetRequestSchema,
    db: AsyncSession = Depends(get_db),
) -> MessageResponseSchema:
    email = str(data.email).lower()
    user = await db.scalar(select(UserModel).where(UserModel.email == email))

    if user is not None and user.is_active:
        try:
            await db.execute(delete(PasswordResetTokenModel).where(PasswordResetTokenModel.user_id == user.id))
            token = PasswordResetTokenModel(user_id=user.id)
            db.add(token)
            await db.commit()
        except SQLAlchemyError as error:
            await db.rollback()
            raise HTTPException(
                status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="An error occurred while creating the token.",
            ) from error
        queue_task(send_password_reset_email, email, token.token)

    return MessageResponseSchema(message=_PASSWORD_RESET_MESSAGE)


def _invalid_reset_token() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_400_BAD_REQUEST,
        detail="Invalid or expired password reset token.",
    )


@router.post(
    "/password-reset/complete/",
    response_model=MessageResponseSchema,
    summary="Set a New Password with a Reset Token",
    description="No old password needed. The token is deleted after use.",
    responses={
        400: {"description": "Invalid or expired token."},
        500: {"description": "An error occurred while resetting the password."},
    },
)
async def complete_password_reset(
    data: PasswordResetCompleteRequestSchema,
    db: AsyncSession = Depends(get_db),
) -> MessageResponseSchema:
    token_record = (
        (
            await db.execute(
                select(PasswordResetTokenModel)
                .options(joinedload(PasswordResetTokenModel.user))
                .join(UserModel)
                .where(
                    UserModel.email == str(data.email).lower(),
                    PasswordResetTokenModel.token == data.token,
                )
            )
        )
        .scalars()
        .first()
    )

    if token_record is None:
        raise _invalid_reset_token()

    user = token_record.user
    try:
        if as_utc(token_record.expires_at) < datetime.now(timezone.utc) or not user.is_active:
            await db.delete(token_record)
            await db.commit()
            raise _invalid_reset_token()

        user.password = data.password
        await db.delete(token_record)
        await db.commit()
    except SQLAlchemyError as error:
        await db.rollback()
        raise HTTPException(
            status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An error occurred while resetting the password.",
        ) from error

    return MessageResponseSchema(message="Password reset successfully.")
