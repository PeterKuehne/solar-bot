from typing import Dict, Any, List, Optional
from datetime import datetime, timedelta
import json
import pytz
import re
import logging
from .base_agent import BaseAgent

logger = logging.getLogger(__name__)

class CalendarAgent(BaseAgent):
    def __init__(self, openai_service, calendar_service):
        super().__init__("calendar_agent", openai_service)
        self.calendar_service = calendar_service
        self.timezone = pytz.timezone('Europe/Berlin')
        self.BUSINESS_START = 9  # 9:00
        self.BUSINESS_END = 17   # 17:00
        self.APPOINTMENT_DURATION = 60  # Minuten

    def _get_system_prompt(self) -> str:
        return """Du bist ein Terminplanungs-Agent für Solaranlagen-Beratungen. 
        
        Terminregeln:
        - Montag bis Freitag
        - Zwischen 9:00 und 17:00 Uhr
        - Dauer: 60 Minuten
        
        Erforderliche Daten:
        - Name
        - E-Mail-Adresse
        - Optional: Telefonnummer
        
        Besonderheiten:
        - Termin-Management erfolgt über Link in der Bestätigungsmail
        - Informiere Kunden, dass sie über diesen Link Termine ändern oder stornieren können
        - Bei technischen Fragen zur Solaranlage zum Solar-Agent weiterleiten
        
        Terminbestätigung soll nur enthalten:
        - Datum und Uhrzeit des Termins
        - Name des Kunden
        - Hinweis auf die Bestätigungsmail mit dem Verwaltungslink
        - Keine weiteren Verweise oder Hinweise"""

    def _get_functions(self) -> List[Dict[str, Any]]:
        return [
            {
                "name": "check_availability",
                "description": "Prüft die Verfügbarkeit eines Termins",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "date": {
                            "type": "string",
                            "description": "Gewünschtes Datum (YYYY-MM-DD)"
                        },
                        "time": {
                            "type": "string",
                            "description": "Gewünschte Uhrzeit (HH:MM)"
                        }
                    },
                    "required": ["date", "time"]
                }
            },
            {
                "name": "book_appointment",
                "description": "Bucht einen neuen Beratungstermin",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "date": {
                            "type": "string",
                            "description": "Datum (YYYY-MM-DD)"
                        },
                        "time": {
                            "type": "string",
                            "description": "Uhrzeit (HH:MM)"
                        },
                        "email": {
                            "type": "string",
                            "description": "E-Mail-Adresse für Bestätigung"
                        },
                        "name": {
                            "type": "string",
                            "description": "Name des Kunden"
                        },
                        "phone": {
                            "type": "string",
                            "description": "Telefonnummer (optional)"
                        }
                    },
                    "required": ["date", "time", "email", "name"]
                }
            },
            *self.get_handoff_functions()
        ]

    def _format_booking_confirmation(self, date: str, time: str, name: str, email: str) -> str:
        dt = datetime.fromisoformat(date)
        formatted_date = dt.strftime("%d. %B %Y")
        return f"""Ihr Termin wurde erfolgreich gebucht!

Details:
- Datum: {formatted_date}
- Uhrzeit: {time} Uhr
- Name: {name}

Eine Bestätigungsmail wurde an {email} gesendet. 
In der E-Mail finden Sie einen Link, über den Sie den Termin bei Bedarf ändern oder stornieren können."""

    def _extract_date_time(self, message: str) -> Optional[Dict[str, str]]:
        try:
            # Suche nach Uhrzeiten
            time_match = re.search(r'(\d{1,2}):(\d{2})', message)
            if time_match:
                hours, minutes = time_match.groups()
                time = f"{int(hours):02d}:{minutes}"

            # Suche nach Datum
            date_patterns = [
                r'(\d{1,2})\.?\s?(dezember|januar|februar|märz|april|mai|juni|juli|august|september|oktober|november)',
                r'(\d{4})-(\d{2})-(\d{2})'
            ]
            
            for pattern in date_patterns:
                date_match = re.search(pattern, message.lower())
                if date_match:
                    if len(date_match.groups()) == 2:  # Format: Tag + Monat
                        day, month = date_match.groups()
                        month_map = {
                            'januar': '01', 'februar': '02', 'märz': '03', 'april': '04',
                            'mai': '05', 'juni': '06', 'juli': '07', 'august': '08',
                            'september': '09', 'oktober': '10', 'november': '11', 'dezember': '12'
                        }
                        month_num = month_map[month]
                        year = datetime.now().year
                        if datetime.now().month > int(month_num):
                            year += 1
                        date = f"{year}-{month_num}-{int(day):02d}"
                    else:  # Format: YYYY-MM-DD
                        date = f"{date_match.group(1)}-{date_match.group(2)}-{date_match.group(3)}"
                    
                    return {"date": date, "time": time}
            
            return None
            
        except Exception as e:
            logger.error(f"Error extracting date/time: {str(e)}")
            return None

    def _extract_contact_info(self, conversation_history: List[Dict[str, str]]) -> Dict[str, str]:
        """Extrahiert Kontaktinformationen aus der Konversationshistorie"""
        contact_info = {}
        for message in conversation_history:
            content = message.get('content', '').lower()
            if 'name:' in content:
                name_match = re.search(r'name:\s*([^,\n]*)', content, re.I)
                if name_match:
                    contact_info['name'] = name_match.group(1).strip()
            if 'email:' in content:
                email_match = re.search(r'email:\s*([^,\n]*)', content, re.I)
                if email_match:
                    contact_info['email'] = email_match.group(1).strip()
            if 'telefon:' in content or 'tel:' in content or 'phone:' in content:
                phone_match = re.search(r'(?:telefon|tel|phone):\s*([^,\n]*)', content, re.I)
                if phone_match:
                    contact_info['phone'] = phone_match.group(1).strip()
        return contact_info

    async def check_availability(self, date: str, time: str) -> Dict[str, Any]:
        """Prüft die Verfügbarkeit eines Termins"""
        try:
            # Stelle sicher, dass das Datum das richtige Jahr hat
            if len(date.split('-')) == 3:
                year = int(date.split('-')[0])
                if year < datetime.now().year:
                    date = f"{datetime.now().year}-{date.split('-')[1]}-{date.split('-')[2]}"
                    if datetime.fromisoformat(f"{date}T{time}") < datetime.now():
                        date = f"{datetime.now().year + 1}-{date.split('-')[1]}-{date.split('-')[2]}"

            # Prüfe Verfügbarkeit
            dt = self.calendar_service._validate_datetime(date, time)
            availability = await self.calendar_service.check_availability(dt)
            
            if not availability.get("available"):
                # Hole alternative Termine
                alternatives = await self.suggest_alternatives(date)
                availability["alternatives"] = alternatives

            return availability

        except Exception as e:
            return {
                "available": False,
                "error": str(e)
            }

    async def book_appointment(self, 
                             date: str,
                             time: str,
                             email: str,
                             name: str,
                             phone: Optional[str] = None) -> Dict[str, Any]:
        """Bucht einen neuen Termin"""
        try:
            # Stelle sicher, dass das Datum das richtige Jahr hat
            if len(date.split('-')) == 3:
                year = int(date.split('-')[0])
                if year < datetime.now().year:
                    date = f"{datetime.now().year}-{date.split('-')[1]}-{date.split('-')[2]}"
                    if datetime.fromisoformat(f"{date}T{time}") < datetime.now():
                        date = f"{datetime.now().year + 1}-{date.split('-')[1]}-{date.split('-')[2]}"

            # Validiere und buche den Termin
            dt = self.calendar_service._validate_datetime(date, time)
            appointment = await self.calendar_service.create_appointment(
                datetime=dt,
                email=email,
                name=name,
                phone=phone,
                notes="Solar-Beratungstermin"
            )

            if appointment.get('success'):
                return {
                    "success": True,
                    "response": self._format_booking_confirmation(date, time, name, email)
                }
            return appointment

        except Exception as e:
            return {
                "success": False,
                "error": str(e)
            }

    async def suggest_alternatives(self, reference_date: str) -> Dict[str, Any]:
        try:
            # Stelle sicher, dass das Datum das richtige Jahr hat
            if len(reference_date.split('-')) == 3:
                year = int(reference_date.split('-')[0])
                if year < datetime.now().year:
                    reference_date = f"{datetime.now().year}-{reference_date.split('-')[1]}-{reference_date.split('-')[2]}"
                    dt = datetime.fromisoformat(reference_date)
                    if dt < datetime.now():
                        reference_date = f"{datetime.now().year + 1}-{reference_date.split('-')[1]}-{reference_date.split('-')[2]}"

            # Finde alternative Termine
            ref_dt = self.calendar_service._validate_datetime(reference_date, "09:00")
            current_dt = ref_dt
            suggestions = []
            
            for _ in range(3):  # 3 Alternative Termine finden
                availability = await self.calendar_service.check_availability(current_dt)
                if availability.get("available"):
                    suggestions.append(current_dt.strftime("%Y-%m-%d %H:%M"))
                current_dt += timedelta(hours=1)

            return {
                "success": True,
                "alternatives": suggestions
            }

        except Exception as e:
            return {
                "success": False,
                "error": str(e)
            }