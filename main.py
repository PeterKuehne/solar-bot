import os
import logging
import requests
from fastapi import FastAPI, HTTPException, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from typing import Optional, Dict, Any
from pydantic import BaseModel
import uvicorn
from datetime import datetime
import pytz

from config import Settings
from services.orchestrator import Orchestrator
from services.openai_service import OpenAIService
from services.solar_calculator import SolarCalculator
from services.calendar_service import CalendarService
from logging_config import setup_logging

# Setup logging
setup_logging()
logger = logging.getLogger(__name__)

def validate_google_api():
    if not settings.google_cloud_api_key:
        logger.error("Google Cloud API Key nicht konfiguriert")
        raise ValueError("Google Cloud API Key fehlt in den Umgebungsvariablen")
    
    try:
        test_coordinates = requests.get(
            f"https://maps.googleapis.com/maps/api/geocode/json?address=Berlin&key={settings.google_cloud_api_key}"
        )
        if test_coordinates.status_code != 200:
            raise ValueError("Google API Key ungültig")
    except Exception as e:
        logger.error(f"Google API Test fehlgeschlagen: {str(e)}")
        raise

# Prüfe auf .env Datei nur in der Entwicklungsumgebung
if os.environ.get('ENVIRONMENT') != 'production':
    if not os.path.exists(".env"):
        raise FileNotFoundError("Lokale Entwicklung benötigt eine .env Datei")

# Initialize FastAPI app
app = FastAPI(
    title="Solar Bot API",
    description="Solar Bot API mit Cookbook-Style Agenten für Voiceflow Integration",
    version="1.0.0"
)

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Load settings
settings = Settings()
validate_google_api()

# Initialize services
openai_service = OpenAIService(settings.openai_api_key)
solar_calculator = SolarCalculator(settings.google_cloud_api_key)
calendar_service = CalendarService(
    credentials=settings.calendar_creds,
    calendar_id=settings.calendar_id
)
orchestrator = Orchestrator(openai_service, solar_calculator, calendar_service)

# Request Models
class SolarCalculationRequest(BaseModel):
    yearly_consumption: float
    address: str
    roof_area: Optional[float] = None
    roof_angle: Optional[float] = None
    orientation: Optional[str] = None
    user_id: Optional[str] = "default"

class AppointmentRequest(BaseModel):
    date: str
    time: str
    email: str
    name: str
    phone: Optional[str] = None
    notes: Optional[str] = None
    user_id: Optional[str] = "default"

class ChatRequest(BaseModel):
    message: str
    context: Optional[Dict[str, Any]] = None
    user_id: Optional[str] = "default"

@app.get("/health")
async def health_check():
    """Endpoint für Health-Checks"""
    return {
        "status": "healthy",
        "version": "1.0.0",
        "timestamp": datetime.now(pytz.UTC).isoformat()
    }

@app.post("/chat")
async def chat(request: ChatRequest):
    """
    Hauptendpoint für die Voiceflow-Integration.
    Verarbeitet Nachrichten durch das Agent-System.
    """
    try:
        response = await orchestrator.process_message(
            message=request.message,
            context=request.context,
            user_id=request.user_id
        )
        
        # Formatiere Antwort für Voiceflow
        return {
            "success": True,
            "response": response.get("content", ""),
            "agent": response.get("agent", "unknown"),
            "type": response.get("type", "message"),
            "context": response.get("context", {})
        }

    except Exception as e:
        logger.error(f"Error in chat endpoint: {str(e)}", exc_info=True)
        return JSONResponse(
            status_code=500,
            content={
                "success": False,
                "error": str(e)
            }
        )

@app.post("/calculate-solar")
async def calculate_solar(request: SolarCalculationRequest):
    """
    Endpoint für Solaranlagen-Berechnungen.
    Leitet direkt zum Solar-Agenten weiter.
    """
    try:
        message = (
            f"Berechne eine Solaranlage für einen Jahresverbrauch von {request.yearly_consumption} kWh "
            f"an der Adresse {request.address}"
        )
        if request.roof_area:
            message += f" mit einer Dachfläche von {request.roof_area}m²"
        if request.roof_angle:
            message += f" und einem Dachwinkel von {request.roof_angle}°"
        if request.orientation:
            message += f" in {request.orientation}-Ausrichtung"

        response = await orchestrator.process_message(
            message=message,
            context={"type": "calculation", "data": request.dict()},
            user_id=request.user_id
        )

        return {
            "success": True,
            "calculation": response.get("content", {}),
            "context": response.get("context", {})
        }

    except Exception as e:
        logger.error(f"Error in solar calculation: {str(e)}", exc_info=True)
        return JSONResponse(
            status_code=500,
            content={
                "success": False,
                "error": str(e)
            }
        )

@app.post("/book-appointment")
async def book_appointment(request: AppointmentRequest):
    """
    Endpoint für Terminbuchungen.
    Leitet direkt zum Calendar-Agenten weiter.
    """
    try:
        message = (
            f"Buche einen Termin für {request.name} am {request.date} um {request.time} "
            f"mit der E-Mail {request.email}"
        )
        if request.phone:
            message += f" und Telefonnummer {request.phone}"
        if request.notes:
            message += f". Notizen: {request.notes}"

        response = await orchestrator.process_message(
            message=message,
            context={"type": "appointment", "data": request.dict()},
            user_id=request.user_id
        )

        return {
            "success": True,
            "appointment": response.get("content", {}),
            "context": response.get("context", {})
        }

    except Exception as e:
        logger.error(f"Error in appointment booking: {str(e)}", exc_info=True)
        return JSONResponse(
            status_code=500,
            content={
                "success": False,
                "error": str(e)
            }
        )

@app.get("/conversation-summary/{user_id}")
async def get_conversation_summary(user_id: str = "default"):
    """
    Endpoint für Konversationszusammenfassungen.
    Nützlich für Debugging und Monitoring.
    """
    try:
        summary = orchestrator.get_conversation_summary(user_id)
        return {
            "success": True,
            "summary": summary
        }

    except Exception as e:
        logger.error(f"Error getting conversation summary: {str(e)}", exc_info=True)
        return JSONResponse(
            status_code=500,
            content={
                "success": False,
                "error": str(e)
            }
        )

@app.post("/reset-conversation/{user_id}")
async def reset_conversation(user_id: str = "default"):
    """
    Endpoint zum Zurücksetzen einer Konversation.
    Nützlich für neue Gesprächsanfänge.
    """
    try:
        orchestrator.reset_conversation(user_id)
        return {
            "success": True,
            "message": f"Conversation reset for user {user_id}"
        }

    except Exception as e:
        logger.error(f"Error resetting conversation: {str(e)}", exc_info=True)
        return JSONResponse(
            status_code=500,
            content={
                "success": False,
                "error": str(e)
            }
        )

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=port,
        workers=1  # Für Entwicklung
    )