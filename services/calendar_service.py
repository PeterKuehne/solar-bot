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

    def _validate_datetime(self, date_str: str, time_str: str) -> datetime:
        try:
            # Kombiniere Datum und Zeit
            dt_str = f"{date_str}T{time_str}"
            dt = datetime.fromisoformat(dt_str)
            
            # Stelle sicher, dass das Jahr nicht in der Vergangenheit liegt
            current_year = datetime.now().year
            if dt.year < current_year:
                dt = dt.replace(year=current_year)
                if dt < datetime.now():
                    dt = dt.replace(year=current_year + 1)
            
            # Konvertiere in lokale Zeitzone
            if dt.tzinfo is None:
                dt = self.timezone.localize(dt)
            else:
                dt = dt.astimezone(self.timezone)
                
            return dt
        except ValueError as e:
            raise ValueError(f"Ungültiges Datum oder Zeit: {str(e)}")

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

            # Ensure timezone
            if not start_time.tzinfo:
                start_time = self.timezone.localize(start_time)

            end_time = start_time + timedelta(minutes=60)
            
            # Query existing events with buffer
            buffer_start = start_time - timedelta(minutes=30)
            buffer_end = end_time + timedelta(minutes=30)
            
            events_result = self.service.events().list(
                calendarId=self.calendar_id,
                timeMin=buffer_start.isoformat(),
                timeMax=buffer_end.isoformat(),
                singleEvents=True,
                orderBy='startTime'
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

    async def create_appointment(self,
                               datetime: datetime,
                               email: str,
                               name: str,
                               phone: Optional[str] = None,
                               notes: Optional[str] = None,
                               duration: int = 60) -> Dict[str, Any]:
        """Create a new appointment"""
        description = f"""
Solar-Beratungstermin

Kunde: {name}
Tel: {phone if phone else 'Nicht angegeben'}
Notizen: {notes if notes else 'Keine'}

Agenda:
- Analyse des Stromverbrauchs
- Berechnung des Solarpotentials
- Wirtschaftlichkeitsberechnung
- Fördermöglichkeiten
- Nächste Schritte

Hinweis: Sie können diesen Termin über den Link in der Bestätigungsmail verwalten, ändern oder stornieren.
"""
        return await self.create_event(
            date=datetime.isoformat(),
            email=email,
            description=description
        )

    async def create_event(
        self,
        date: str,
        email: str,
        description: str = None
    ) -> Dict[str, Any]:
        """Book an appointment with availability check"""
        try:
            start_time = datetime.fromisoformat(date)
            if not start_time.tzinfo:
                start_time = self.timezone.localize(start_time)
                
            logger.debug(f"Attempting to book appointment for {email} at {start_time}")

            # Check availability first
            availability = await self.check_availability(start_time)
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

Hinweis: Sie können diesen Termin über den Link in der Bestätigungsmail verwalten, ändern oder stornieren.
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
                    {'email': email}
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
                availability = await self.check_availability(current_time)
                if availability.get("available"):
                    return current_time
                current_time += timedelta(hours=1)  # Increment by 1 hour
        except Exception as e:
            logger.error(f"Error suggesting alternative time: {str(e)}")
            return None