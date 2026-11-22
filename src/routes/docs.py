from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.openapi.docs import get_redoc_html, get_swagger_ui_html
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.database import get_db
from src.models.accounts import UserModel

basic_auth = HTTPBasic()


async def docs_user(
    credentials: HTTPBasicCredentials = Depends(basic_auth),
    db: AsyncSession = Depends(get_db),
) -> UserModel:
    user = await db.scalar(select(UserModel).where(UserModel.email == credentials.username.lower()))
    if user is None or not user.is_active or not user.verify_password(credentials.password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid e-mail or password.",
            headers={"WWW-Authenticate": "Basic"},
        )
    return user


router = APIRouter(include_in_schema=False, dependencies=[Depends(docs_user)])


@router.get("/openapi.json")
async def openapi_schema(request: Request) -> JSONResponse:
    return JSONResponse(request.app.openapi())


@router.get("/docs")
async def swagger_ui() -> HTMLResponse:
    return get_swagger_ui_html(openapi_url="/openapi.json", title="Online Cinema API - Swagger UI")


@router.get("/redoc")
async def redoc_ui() -> HTMLResponse:
    return get_redoc_html(openapi_url="/openapi.json", title="Online Cinema API - ReDoc")
