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
        self.BUSINESS_START = 9
        self.BUSINESS_END = 17
        self.APPOINTMENT_DURATION = 60

    def _get_system_prompt(self) -> str:
        return """Du bist ein Terminplanungs-Agent für Solaranlagen-Beratungen. Du verstehst natürliche Zeitangaben wie "nächster Dienstag" oder "morgen" und wandelst diese in konkrete Termine um.
        
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
        - Bei technischen Fragen zur Solaranlage zum Solar-Agent weiterleiten"""

    def _get_functions(self) -> List[Dict[str, Any]]:
        return [
            {
                "name": "parse_relative_date",
                "description": "Wandelt relative Zeitangaben in konkrete Daten um",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "text": {
                            "type": "string",
                            "description": "Die zu analysierende Zeitangabe (z.B. 'nächster Dienstag 9:00')"
                        }
                    },
                    "required": ["text"]
                }
            },
            {
                "name": "check_availability",
                "description": "Prüft die Verfügbarkeit eines Termins",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "date": {"type": "string", "description": "Datum (YYYY-MM-DD)"},
                        "time": {"type": "string", "description": "Uhrzeit (HH:MM)"}
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
                        "date": {"type": "string", "description": "Datum (YYYY-MM-DD)"},
                        "time": {"type": "string", "description": "Uhrzeit (HH:MM)"},
                        "email": {"type": "string", "description": "E-Mail-Adresse"},
                        "name": {"type": "string", "description": "Name des Kunden"},
                        "phone": {"type": "string", "description": "Telefonnummer (optional)"}
                    },
                    "required": ["date", "time", "email", "name"]
                }
            },
            *self.get_handoff_functions()
        ]

    async def parse_relative_date(self, text: str) -> Dict[str, Any]:
        """Wandelt relative Zeitangaben in konkrete Daten um"""
        try:
            # OpenAI aufrufen für die Interpretation der Zeitangabe
            prompt = f"""
            Wandle die folgende Zeitangabe in ein konkretes Datum um. 
            Zeitangabe: "{text}"
            Aktuelles Datum: {datetime.now(self.timezone).strftime('%Y-%m-%d')}
            
            Antworte nur mit dem Datum im Format YYYY-MM-DD und der Uhrzeit im Format HH:MM, 
            getrennt durch ein Leerzeichen. Beispiel: "2024-02-20 09:00"
            """
            
            response = await self.openai_service.chat_completion([
                {"role": "system", "content": prompt},
                {"role": "user", "content": text}
            ])
            
            # Antwort parsen
            date_time_str = response['content'].strip()
            date_str, time_str = date_time_str.split()
            
            # Validieren
            parsed_date = datetime.strptime(date_str, '%Y-%m-%d')
            parsed_time = datetime.strptime(time_str, '%H:%M').time()
            
            # Prüfen ob das Datum in der Vergangenheit liegt
            if parsed_date.date() < datetime.now().date():
                raise ValueError("Das Datum liegt in der Vergangenheit")
            
            return {
                "success": True,
                "date": date_str,
                "time": time_str
            }
            
        except Exception as e:
            return {
                "success": False,
                "error": str(e)
            }

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

    async def process_message(self, message: str, conversation_history: List[Dict[str, str]]) -> Dict[str, Any]:
        try:
            # Erst prüfen ob es eine Zeitangabe ist
            if any(keyword in message.lower() for keyword in ['termin', 'uhr', 'zeit', 'morgen', 'nächste']):
                # Relative Zeitangabe parsen
                date_time = await self.parse_relative_date(message)
                
                if date_time["success"]:
                    # Verfügbarkeit prüfen
                    availability = await self.check_availability(
                        date=date_time["date"],
                        time=date_time["time"]
                    )
                    
                    if availability.get("available"):
                        # Kontaktinformationen extrahieren
                        contact_info = self._extract_contact_info(conversation_history)
                        
                        if contact_info.get("email") and contact_info.get("name"):
                            # Termin buchen
                            booking = await self.book_appointment(
                                date=date_time["date"],
                                time=date_time["time"],
                                email=contact_info["email"],
                                name=contact_info["name"],
                                phone=contact_info.get("phone")
                            )
                            return booking
                        else:
                            return {
                                "type": "query",
                                "content": "Bitte teilen Sie mir Ihren Namen, Ihre E-Mail-Adresse und optional Ihre Telefonnummer mit."
                            }
                    else:
                        return {
                            "type": "message",
                            "content": f"Der gewünschte Termin ist leider nicht verfügbar. {availability.get('message', '')}"
                        }
            
            # Standardverarbeitung für andere Nachrichten
            return await super().process_message(message, conversation_history)
            
        except Exception as e:
            logger.error(f"Error in calendar agent: {str(e)}")
            return {
                "type": "error",
                "content": f"Ein Fehler ist aufgetreten: {str(e)}"
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