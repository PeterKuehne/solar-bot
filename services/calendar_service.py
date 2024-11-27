import logging
from typing import Dict, Any, Optional
from datetime import datetime, timedelta
import pytz
import asyncio
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

logger = logging.getLogger(__name__)

class CalendarService:
    def __init__(self, credentials: Dict[str, Any], calendar_id: str):
        logger.info(f"Initializing CalendarService with calendar_id: {calendar_id}")
        try:
            self.credentials = Credentials.from_authorized_user_info(credentials)
            self.calendar_id = calendar_id
            self.service = build('calendar', 'v3', credentials=self.credentials)
            self.timezone = pytz.timezone('Europe/Berlin')
            self._locks = {}
            logger.info("Calendar Service successfully initialized")
        except Exception as e:
            logger.error(f"Failed to initialize Calendar Service: {str(e)}")
            raise

    async def check_availability(self, start_time: datetime) -> Dict[str, Any]:
        """Check if a time slot is available"""
        logger.debug(f"Checking availability for time slot: {start_time}")
        try:
            # Check business hours (9:00 - 17:00)
            if not (9 <= start_time.hour < 17):
                logger.info(f"Time {start_time} is outside business hours")
                return {
                    "available": False,
                    "message": "Termine sind nur zwischen 9:00 und 17:00 Uhr möglich."
                }
            
            # Check if it's a business day
            if start_time.weekday() >= 5:
                logger.info(f"Date {start_time} is not a business day")
                return {
                    "available": False,
                    "message": "Termine sind nur von Montag bis Freitag möglich."
                }

            end_time = start_time + timedelta(minutes=60)
            
            # Query existing events
            events_result = self.service.events().list(
                calendarId=self.calendar_id,
                timeMin=start_time.isoformat(),
                timeMax=end_time.isoformat(),
                singleEvents=True
            ).execute()
            
            events = events_result.get('items', [])
            
            if events:
                logger.info(f"Found conflicting events for time slot {start_time}")
                return {
                    "available": False,
                    "message": "Dieser Termin ist bereits vergeben."
                }
                
            logger.info(f"Time slot {start_time} is available")
            return {
                "available": True,
                "start": start_time.isoformat(),
                "end": end_time.isoformat()
            }

        except Exception as e:
            logger.error(f"Error checking availability: {str(e)}")
            raise

    async def create_event(
        self,
        date: str,
        email: str,
        description: str = None
    ) -> Dict[str, Any]:
        """Book an appointment with thread-safe checking"""
        try:
            start_time = datetime.fromisoformat(date)
            if not start_time.tzinfo:
                start_time = self.timezone.localize(start_time)
                
            logger.debug(f"Attempting to book appointment for {email} at {start_time}")

            # Check availability
            availability = await self.get_available_slots(start_time)
            if not availability.get("available"):
                logger.warning(f"Slot not available: {availability.get('message')}")
                return availability

            end_time = start_time + timedelta(minutes=60)
            
            event = {
                'summary': 'Solar Beratungstermin',
                'description': description or """
Beratungsgespräch für Ihre Solaranlage

Agenda:
- Analyse Ihres Stromverbrauchs
- Berechnung des Solarpotentials
- Individuelle Wirtschaftlichkeitsberechnung
- Fördermöglichkeiten und Finanzierung
- Konkrete nächste Schritte
""",
                'start': {
                    'dateTime': start_time.isoformat(),
                    'timeZone': 'Europe/Berlin',
                },
                'end': {
                    'dateTime': end_time.isoformat(),
                    'timeZone': 'Europe/Berlin',
                },
                'attendees': [
                    {'email': email}  # Verwende die übergebene E-Mail statt der hartcodierten
                ],
                'reminders': {
                    'useDefault': False,
                    'overrides': [
                        {'method': 'email', 'minutes': 24 * 60},
                        {'method': 'popup', 'minutes': 30},
                    ],
                },
                'sendUpdates': 'all'
            }

            try:
                created_event = self.service.events().insert(
                    calendarId=self.calendar_id,
                    body=event,
                    sendUpdates='all'
                ).execute()
                
                logger.info(f"Successfully created event with ID: {created_event.get('id')}")
                
                return {
                    'success': True,
                    'id': created_event.get('id'),
                    'link': created_event.get('htmlLink'),
                    'start': created_event['start']['dateTime'],
                    'end': created_event['end']['dateTime']
                }
                
            except HttpError as e:
                logger.error(f"Google Calendar API error: {str(e)}")
                return {
                    "success": False,
                    "error": "calendar_api_error",
                    "message": f"Fehler bei der Kalendererstellung: {str(e)}"
                }
                
            except Exception as e:
                logger.error(f"Unexpected error creating calendar event: {str(e)}")
                return {
                    "success": False,
                    "error": "unexpected_error",
                    "message": "Ein unerwarteter Fehler ist aufgetreten."
                }
                
        except Exception as e:
            logger.error(f"Error in book_appointment: {str(e)}")
            return {
                "success": False,
                "error": "booking_failed",
                "message": f"Fehler bei der Terminbuchung: {str(e)}"
            }
    async def suggest_alternative(self, date_time: datetime) -> Optional[datetime]:
        """Suggest the next available time slot asynchronously."""
        try:
            current_time = date_time
            while True:
                availability = await self.get_available_slots(current_time)
                if availability["available"]:
                    return current_time
                current_time += timedelta(hours=1)  # Increment by 1 hour
        except Exception as e:
            logger.error(f"Error suggesting alternative time: {str(e)}")
            return None