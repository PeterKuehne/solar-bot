from typing import Dict, Any, List, Optional
import logging
import json
import pytz
from datetime import datetime
import re
from .agents.solar_agent import SolarAgent
from .agents.calendar_agent import CalendarAgent

logger = logging.getLogger(__name__)

class Orchestrator:
    def __init__(self, openai_service, solar_calculator, calendar_service):
        self.timezone = pytz.timezone('Europe/Berlin')
        self.agents = {
            "solar_agent": SolarAgent(openai_service, solar_calculator),
            "calendar_agent": CalendarAgent(openai_service, calendar_service)
        }
        self.conversations = {}  # user_id -> conversation_history
        self.current_agent = {}  # user_id -> current_agent
        self.handoff_history = {}  # user_id -> handoff_history
        self.context = {}       # user_id -> last_context
        self.max_handoffs = 5

        self.calendar_keywords = [
            r'\btermin\b', r'\bbuchen\b', r'\bkalender\b', r'\bberatung\b',
            r'\btreffen\b', r'\buhr\b', r'\bdezember\b', r'\bjanuar\b',
            r'\bfebruar\b', r'\bmärz\b', r'\bapril\b', r'\bmai\b', r'\bjuni\b',
            r'\bjuli\b', r'\baugust\b', r'\bseptember\b', r'\boktober\b',
            r'\bnovember\b', r'\b9:00\b', r'\b10:00\b', r'\b11:00\b'
        ]

    def _detect_initial_agent(self, message: str) -> str:
        """Erkennt den passenden Agenten basierend auf der Nachricht"""
        message_lower = message.lower()
        
        # Prüfe auf Kalender-Schlüsselwörter
        for keyword in self.calendar_keywords:
            if re.search(keyword, message_lower):
                return "calendar_agent"
        
        return "solar_agent"

    def _get_conversation_history(self, user_id: str = "default") -> List[Dict[str, str]]:
        if user_id not in self.conversations:
            self.conversations[user_id] = []
        return self.conversations[user_id]

    def _get_current_agent(self, user_id: str = "default", message: str = "") -> str:
        if user_id not in self.current_agent:
            self.current_agent[user_id] = self._detect_initial_agent(message)
        return self.current_agent[user_id]

    def _save_context(self, user_id: str, context: Dict):
        """Speichert Kontext für einen Benutzer"""
        self.context[user_id] = context

    def _get_context(self, user_id: str) -> Optional[Dict]:
        """Holt den gespeicherten Kontext eines Benutzers"""
        return self.context.get(user_id)

    def _record_handoff(self, user_id: str, from_agent: str, to_agent: str, reason: str):
        if user_id not in self.handoff_history:
            self.handoff_history[user_id] = []
        
        self.handoff_history[user_id].append({
            "timestamp": datetime.now(self.timezone).isoformat(),
            "from_agent": from_agent,
            "to_agent": to_agent,
            "reason": reason
        })

    async def _handle_handoff(self, response: Dict[str, Any], user_id: str, 
                            current_agent_id: str, conversation_history: List[Dict[str, str]]) -> Dict[str, Any]:
        if len(self.handoff_history.get(user_id, [])) >= self.max_handoffs:
            logger.warning(f"Maximale Handoff-Anzahl erreicht für User {user_id}")
            return {
                "type": "error",
                "content": "Zu viele Agentenübergaben. Bitte starten Sie eine neue Anfrage."
            }
        
        new_agent_id = response["target_agent"]
        if new_agent_id not in self.agents:
            logger.error(f"Unbekannter Zielagent: {new_agent_id}")
            return {
                "type": "error",
                "content": "Interner Fehler bei der Agentenübergabe."
            }
        
        reason = response.get("reason", "Nicht spezifiziert")
        self._record_handoff(
            user_id=user_id,
            from_agent=current_agent_id,
            to_agent=new_agent_id,
            reason=reason
        )
        
        self.current_agent[user_id] = new_agent_id
        
        return {
            "type": "message",
            "content": f"Übergabe an {new_agent_id} wegen: {reason}",
            "agent": new_agent_id
        }

    def _extract_contact_info(self, message: str) -> Dict[str, str]:
        """Extrahiert Kontaktinformationen aus einer Nachricht"""
        contact_info = {}
        
        # Name extrahieren
        name_match = re.search(r'name:?\s*([^,\n]*)', message, re.I)
        if name_match:
            contact_info['name'] = name_match.group(1).strip()
            
        # Email extrahieren
        email_match = re.search(r'email:?\s*([^,\n]*)', message, re.I)
        if email_match:
            contact_info['email'] = email_match.group(1).strip()
            
        # Telefon extrahieren
        phone_match = re.search(r'(?:telefon|tel|phone):?\s*([^,\n]*)', message, re.I)
        if phone_match:
            contact_info['phone'] = phone_match.group(1).strip()
            
        return contact_info

    async def process_message(self, message: str, context: Optional[Dict] = None, 
                            user_id: str = "default") -> Dict[str, Any]:
        try:
            conversation_history = self._get_conversation_history(user_id)
            stored_context = self._get_context(user_id) or {}
            
            # Extrahiere Kontaktinformationen aus der Nachricht
            contact_info = self._extract_contact_info(message)
            if contact_info:
                stored_context.update(contact_info)
                self._save_context(user_id, stored_context)
            
            conversation_history.append({
                "role": "user",
                "content": message
            })
            
            current_agent_id = self._get_current_agent(user_id, message)
            current_agent = self.agents[current_agent_id]
            
            # Füge gespeicherten Kontext zum aktuellen Kontext hinzu
            if context:
                context.update(stored_context)
            else:
                context = stored_context
            
            response = await current_agent.process(
                message=message,
                conversation_history=conversation_history
            )
            
            if response["type"] == "handoff":
                handoff_response = await self._handle_handoff(
                    response, user_id, current_agent_id, conversation_history
                )
                
                conversation_history.append({
                    "role": "system",
                    "content": handoff_response["content"]
                })
                
                new_agent = self.agents[handoff_response["agent"]]
                new_response = await new_agent.process(
                    message=message,
                    conversation_history=conversation_history
                )
                
                conversation_history.append({
                    "role": "assistant",
                    "content": new_response.get("content", ""),
                    "agent": handoff_response["agent"]
                })
                
                return new_response
            
            conversation_history.append({
                "role": "assistant",
                "content": response.get("content", ""),
                "agent": current_agent_id
            })
            
            return {
                "type": response["type"],
                "content": response.get("content", ""),
                "agent": current_agent_id,
                "context": context
            }

        except Exception as e:
            logger.error(f"Fehler in process_message: {str(e)}", exc_info=True)
            return {
                "type": "error",
                "content": f"Ein Fehler ist aufgetreten: {str(e)}"
            }

    def get_conversation_summary(self, user_id: str = "default") -> Dict[str, Any]:
        return {
            "conversation_length": len(self.conversations.get(user_id, [])),
            "current_agent": self._get_current_agent(user_id),
            "handoff_count": len(self.handoff_history.get(user_id, [])),
            "handoff_history": self.handoff_history.get(user_id, []),
            "context": self._get_context(user_id)
        }

    def reset_conversation(self, user_id: str = "default"):
        self.conversations[user_id] = []
        self.current_agent[user_id] = "solar_agent"
        self.handoff_history[user_id] = []
        self.context[user_id] = {}