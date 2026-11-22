from fastapi import FastAPI
from src.routes import accounts, admin, movies, comments, genres, notifications, stars, cart, orders, payments, docs

app = FastAPI(title="Online Cinema", description="Description", docs_url=None, redoc_url=None, openapi_url=None)

app.include_router(accounts.router)
app.include_router(admin.router)
app.include_router(movies.router)
app.include_router(genres.router)
app.include_router(stars.router)
app.include_router(comments.router)
app.include_router(notifications.router)
app.include_router(cart.router)
app.include_router(orders.router)
app.include_router(payments.router)
app.include_router(docs.router)
