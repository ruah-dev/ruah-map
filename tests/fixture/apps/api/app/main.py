from fastapi import FastAPI
from app.routes import orders
from .services.queue import enqueue
