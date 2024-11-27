import os
import logging
import asyncio
from fastapi import FastAPI, HTTPException, BackgroundTasks, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from typing import Optional
from pydantic import BaseModel, EmailStr, validator
from datetime import datetime
import re
from config import Settings
from services.orchestrator import Orchestrator
from services.openai_service import OpenAIService
from services.solar_calculator import SolarCalculator
from services.calendar_service import CalendarService
from logging_config import setup_logging

# Konstanten
TIMEOUT_SECONDS = 25  # Unter Herokus 30-Sekunden-Limit

# Setup logging
setup_logging()
logger = logging.getLogger(__name__)

# Initialize FastAPI app
app = FastAPI(
    title="Solar Bot API",
    description="API for Solar Bot with appointment booking and solar calculations",
    version="1.0.0"
)

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Load settings with error handling
try:
    settings = Settings()
    logger.info("Settings loaded successfully")
    
    # Initialize services
    openai_service = OpenAIService(settings.openai_api_key)
    solar_calculator = SolarCalculator(settings.google_cloud_api_key)
    calendar_service = CalendarService(
        credentials=settings.calendar_creds,
        calendar_id=settings.calendar_id
    )
    orchestrator = Orchestrator(openai_service, solar_calculator, calendar_service)
    
except Exception as e:
    logger.error(f"Failed to load settings: {str(e)}")
    logger.error("Environment variables:")
    for key, value in os.environ.items():
        if not any(secret in key.lower() for secret in ['key', 'token', 'secret', 'password']):
            logger.error(f"{key}: {value}")
        else:
            logger.error(f"{key}: ***")
    raise

class ChatRequest(BaseModel):
    message: str
    user_email: Optional[str] = None

    @validator('message')
    def validate_message(cls, v):
        if not v or not v.strip():
            raise ValueError("Nachricht darf nicht leer sein")
        return v.strip()

    @validator('user_email')
    def validate_email(cls, v):
        if v is None:
            return v
        # Einfache E-Mail-Validierung
        if v and not re.match(r"[^@]+@[^@]+\.[^@]+", v):
            raise ValueError("Ungültige E-Mail-Adresse")
        return v

@app.exception_handler(422)
async def validation_exception_handler(request, exc):
    error_messages = []
    for error in exc.errors():
        field = error["loc"][-1]
        msg = error["msg"]
        error_messages.append(f"{field}: {msg}")
    
    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        content={
            "detail": "Validierungsfehler",
            "errors": error_messages
        },
    )

@app.get("/")
async def root():
    return {
        "status": "healthy",
        "version": "1.0.0",
        "environment": os.getenv("ENVIRONMENT", "production")
    }

@app.get("/health")
async def health_check():
    return {"status": "healthy"}

@app.post("/chat")
async def chat(request: ChatRequest, background_tasks: BackgroundTasks):
    try:
        logger.info(f"Received chat request with message: {request.message[:50]}...")
        if request.user_email:
            logger.info(f"User email provided: {request.user_email}")

        response = await asyncio.wait_for(
            orchestrator.process_message(
                message=request.message,
                user_email=request.user_email
            ),
            timeout=TIMEOUT_SECONDS
        )
        return JSONResponse(content={"response": response})
        
    except asyncio.TimeoutError:
        logger.error("Request timeout")
        return JSONResponse(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            content={
                "error": "timeout",
                "detail": "Die Anfrage hat zu lange gedauert. Bitte versuchen Sie es in ein paar Minuten erneut."
            }
        )
    except Exception as e:
        logger.error(f"Error in chat endpoint: {str(e)}")
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content={
                "error": "internal_error",
                "detail": str(e)
            }
        )

if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=port,
        workers=1
    )