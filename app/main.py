"""Ponto de entrada do monolito."""
from fastapi import FastAPI

from app.api.routes import router

app = FastAPI(title="T1 Monolith")
app.include_router(router)
