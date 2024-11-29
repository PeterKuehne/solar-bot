from typing import Dict, Any, List, Optional
from datetime import datetime, timedelta
import json
import pytz
from .base_agent import BaseAgent

class CalendarAgent(BaseAgent):
    def __init__(self, openai_service, calendar_service):
        super().__init__("calendar_agent", openai_service)
        self.calendar_service = calendar_service
        self.timezone = pytz.timezone('Europe/Berlin')
        self.BUSINESS_START = 9  # 9:00
        self.BUSINESS_END = 17   # 17:00
        self.APPOINTMENT_DURATION = 60  # Minuten

    def _get_system_prompt(self) -> str:
        return """Du bist ein spezialisierter Terminplanungs-Agent für Solaranlagen-Beratungen.
        
        Deine Hauptaufgaben sind:
        1. Terminvereinbarungen koordinieren
        2. Verfügbarkeit prüfen
        3. Alternative Termine vorschlagen
        4. Termine ändern oder stornieren

        Wichtige Regeln:
        - Termine nur Montag bis Freitag zwischen 9:00 und 17:00 Uhr
        - Termine dauern standardmäßig 60 Minuten
        - Bei technischen Fragen → Solar-Agent
        - Immer E-Mail-Adresse für Bestätigung erfragen
        - Termine bestätigen und Details per E-Mail senden"""

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
                            "description": "Gewünschtes Datum (ISO 8601)"
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
                            "description": "Datum (ISO 8601)"
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
                        },
                        "notes": {
                            "type": "string",
                            "description": "Zusätzliche Notizen"
                        }
                    },
                    "required": ["date", "time", "email", "name"]
                }
            },
            {
                "name": "suggest_alternatives",
                "description": "Schlägt alternative Termine vor",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "reference_date": {
                            "type": "string",
                            "description": "Referenzdatum (ISO 8601)"
                        },
                        "preferred_time": {
                            "type": "string",
                            "enum": ["morning", "afternoon", "any"],
                            "description": "Bevorzugte Tageszeit"
                        },
                        "num_suggestions": {
                            "type": "integer",
                            "description": "Anzahl der Vorschläge",
                            "default": 3
                        }
                    },
                    "required": ["reference_date"]
                }
            },
            {
                "name": "modify_appointment",
                "description": "Ändert einen bestehenden Termin",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "email": {
                            "type": "string",
                            "description": "E-Mail des Kunden"
                        },
                        "old_datetime": {
                            "type": "string",
                            "description": "Bisheriger Termin (ISO 8601)"
                        },
                        "new_datetime": {
                            "type": "string",
                            "description": "Neuer Termin (ISO 8601)"
                        }
                    },
                    "required": ["email", "old_datetime", "new_datetime"]
                }
            },
            {
                "name": "cancel_appointment",
                "description": "Storniert einen Termin",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "email": {
                            "type": "string",
                            "description": "E-Mail des Kunden"
                        },
                        "datetime": {
                            "type": "string",
                            "description": "Zu stornierenden Termin (ISO 8601)"
                        },
                        "reason": {
                            "type": "string",
                            "description": "Grund der Stornierung"
                        }
                    },
                    "required": ["email", "datetime"]
                }
            },
            # Handoff-Funktionen vom BaseAgent
            *self.get_handoff_functions()
        ]

    def _validate_datetime(self, date_str: str, time_str: str) -> datetime:
        """Validiert und kombiniert Datum und Zeit"""
        try:
            # Kombiniere Datum und Zeit
            dt_str = f"{date_str}T{time_str}"
            dt = datetime.fromisoformat(dt_str)
            
            # Konvertiere in lokale Zeitzone
            if dt.tzinfo is None:
                dt = self.timezone.localize(dt)
            else:
                dt = dt.astimezone(self.timezone)
                
            return dt
        except ValueError as e:
            raise ValueError(f"Ungültiges Datum oder Zeit: {str(e)}")

    def _is_business_hours(self, dt: datetime) -> bool:
        """Prüft, ob der Zeitpunkt innerhalb der Geschäftszeiten liegt"""
        return (
            dt.weekday() < 5 and  # Montag-Freitag
            self.BUSINESS_START <= dt.hour < self.BUSINESS_END
        )

    async def check_availability(self, date: str, time: str) -> Dict[str, Any]:
        """Prüft die Verfügbarkeit eines Termins"""
        try:
            dt = self._validate_datetime(date, time)
            
            # Prüfe Geschäftszeiten
            if not self._is_business_hours(dt):
                return {
                    "available": False,
                    "reason": "Termin außerhalb der Geschäftszeiten (Mo-Fr 9:00-17:00)",
                    "alternatives": await self.suggest_alternatives(date)
                }

            # Prüfe Kalenderverfügbarkeit
            is_available = await self.calendar_service.check_availability(dt)
            if not is_available:
                return {
                    "available": False,
                    "reason": "Termin bereits vergeben",
                    "alternatives": await self.suggest_alternatives(date)
                }

            return {
                "available": True,
                "datetime": dt.isoformat()
            }

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
                             phone: Optional[str] = None,
                             notes: Optional[str] = None) -> Dict[str, Any]:
        """Bucht einen neuen Termin"""
        try:
            # Prüfe Verfügbarkeit
            availability = await self.check_availability(date, time)
            if not availability.get("available"):
                return availability

            dt = self._validate_datetime(date, time)
            
            # Buche Termin
            appointment = await self.calendar_service.create_appointment(
                datetime=dt,
                email=email,
                name=name,
                phone=phone,
                notes=notes or "Solar-Beratungstermin",
                duration=self.APPOINTMENT_DURATION
            )

            return {
                "success": True,
                "appointment": {
                    "datetime": dt.isoformat(),
                    "name": name,
                    "email": email,
                    "phone": phone,
                    "notes": notes,
                    "confirmation_sent": True
                }
            }

        except Exception as e:
            return {
                "success": False,
                "error": str(e)
            }

    async def suggest_alternatives(self, 
                                 reference_date: str,
                                 preferred_time: str = "any",
                                 num_suggestions: int = 3) -> Dict[str, Any]:
        """Schlägt alternative Termine vor"""
        try:
            ref_dt = datetime.fromisoformat(reference_date)
            if ref_dt.tzinfo is None:
                ref_dt = self.timezone.localize(ref_dt)
            
            suggestions = []
            current_dt = ref_dt
            
            # Definiere Zeitfenster basierend auf Präferenz
            if preferred_time == "morning":
                time_windows = [(self.BUSINESS_START, 12)]
            elif preferred_time == "afternoon":
                time_windows = [(13, self.BUSINESS_END)]
            else:
                time_windows = [(self.BUSINESS_START, 12), (13, self.BUSINESS_END)]

            # Suche verfügbare Termine
            while len(suggestions) < num_suggestions:
                if self._is_business_hours(current_dt):
                    for start_hour, end_hour in time_windows:
                        if start_hour <= current_dt.hour < end_hour:
                            is_available = await self.calendar_service.check_availability(current_dt)
                            if is_available:
                                suggestions.append(current_dt.isoformat())
                                if len(suggestions) >= num_suggestions:
                                    break
                
                current_dt += timedelta(hours=1)
                if len(suggestions) < num_suggestions and current_dt.hour >= self.BUSINESS_END:
                    current_dt = current_dt.replace(hour=self.BUSINESS_START) + timedelta(days=1)
                    while current_dt.weekday() >= 5:  # Überspringe Wochenenden
                        current_dt += timedelta(days=1)

            return {
                "success": True,
                "suggestions": suggestions
            }

        except Exception as e:
            return {
                "success": False,
                "error": str(e)
            }

    async def modify_appointment(self,
                               email: str,
                               old_datetime: str,
                               new_datetime: str) -> Dict[str, Any]:
        """Ändert einen bestehenden Termin"""
        try:
            # Konvertiere Strings zu datetime
            old_dt = datetime.fromisoformat(old_datetime)
            new_dt = datetime.fromisoformat(new_datetime)
            
            # Prüfe Verfügbarkeit des neuen Termins
            new_date = new_dt.strftime("%Y-%m-%d")
            new_time = new_dt.strftime("%H:%M")
            availability = await self.check_availability(new_date, new_time)
            
            if not availability.get("available"):
                return availability

            # Ändere Termin
            updated = await self.calendar_service.modify_appointment(
                email=email,
                old_datetime=old_dt,
                new_datetime=new_dt
            )

            return {
                "success": True,
                "appointment": {
                    "old_datetime": old_dt.isoformat(),
                    "new_datetime": new_dt.isoformat(),
                    "email": email,
                    "confirmation_sent": True
                }
            }

        except Exception as e:
            return {
                "success": False,
                "error": str(e)
            }

    async def cancel_appointment(self,
                               email: str,
                               datetime: str,
                               reason: Optional[str] = None) -> Dict[str, Any]:
        """Storniert einen Termin"""
        try:
            dt = datetime.fromisoformat(datetime)
            
            cancelled = await self.calendar_service.cancel_appointment(
                email=email,
                datetime=dt,
                reason=reason
            )

            return {
                "success": True,
                "cancelled": {
                    "datetime": dt.isoformat(),
                    "email": email,
                    "reason": reason,
                    "confirmation_sent": True
                }
            }

        except Exception as e:
            return {
                "success": False,
                "error": str(e)
            }