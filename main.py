import os
import logging
from fastapi import FastAPI, HTTPException, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from typing import Optional
from pydantic import BaseModel
import uvicorn
import asyncio
from config import Settings
from services.orchestrator import Orchestrator
from services.openai_service import OpenAIService
from services.solar_calculator import SolarCalculator
from services.calendar_service import CalendarService
from logging_config import setup_logging

# Konstanten für Timeout-Handling
TIMEOUT_SECONDS = 25  # Unter Herokus 30-Sekunden-Limit
MAX_RETRIES = 2

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

# Timeout middleware
@app.middleware("http")
async def timeout_middleware(request, call_next):
    try:
        return await asyncio.wait_for(
            call_next(request),
            timeout=TIMEOUT_SECONDS
        )
    except asyncio.TimeoutError:
        logger.error("Global timeout in middleware")
        return JSONResponse(
            status_code=503,
            content={
                "error": "timeout",
                "detail": "Server timeout. Bitte versuchen Sie es erneut."
            }
        )
    except Exception as e:
        logger.error(f"Middleware error: {str(e)}")
        return JSONResponse(
            status_code=500,
            content={
                "error": "internal_error",
                "detail": str(e)
            }
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
    logger.info(f"Received chat request with email: {str(request.user_email)}")  # Korrigiert
    retries = 0
    while retries <= MAX_RETRIES:
        try:
            response = await asyncio.wait_for(
                orchestrator.process_message(
                    message=request.message,
                    user_email=request.user_email if request.user_email else None  # Korrigiert
                ),
                timeout=TIMEOUT_SECONDS
            )
            return JSONResponse(content={"response": response})
            
        except asyncio.TimeoutError:
            retries += 1
            if retries <= MAX_RETRIES:
                logger.warning(f"Timeout occurred, retrying ({retries}/{MAX_RETRIES})")
                await asyncio.sleep(1)
                continue
            else:
                logger.error("Final timeout after retries")
                return JSONResponse(
                    status_code=503,
                    content={
                        "error": "timeout",
                        "detail": "Die Anfrage hat zu lange gedauert. Bitte versuchen Sie es in ein paar Minuten erneut."
                    }
                )
                
        except Exception as e:
            logger.error(f"Error in chat endpoint: {str(e)}")
            return JSONResponse(
                status_code=500,
                content={
                    "error": "internal_error",
                    "detail": str(e)
                }
            )

if __name__ == "__main__":
    # Heroku setzt den PORT als Umgebungsvariable
    port = int(os.environ.get("PORT", 8000))
    
    # Wichtig: host muss "0.0.0.0" sein für Heroku
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=port,
        workers=1  
    )