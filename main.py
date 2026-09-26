"""
Financial Audio Intelligence — RAG Service
Main entry point for the FastAPI application.
"""

import logging
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from dotenv import load_dotenv
from app.api.routes import router

# Load environment variables from .env
load_dotenv()

# Configure root logger
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(name)-20s | %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("rag.main")

app = FastAPI(
    title="Financial Audio Intelligence — RAG Service",
    description="Call-centric risk grounding pipeline for financial call analysis",
    version="2.0.0",
)

# Allow all CORS requests
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Register API routes
app.include_router(router)

logger.info("RAG Service initialized v2.0.0")


@app.get("/health")
async def health_check():
    """Health check endpoint."""
    return {"status": "ok", "service": "rag-pipeline"}
