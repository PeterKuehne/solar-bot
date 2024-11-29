from typing import Dict, Any, List, Optional
import logging
import json
import pytz
from datetime import datetime
from .agents.solar_agent import SolarAgent
from .agents.calendar_agent import CalendarAgent

logger = logging.getLogger(__name__)

class Orchestrator:
    """
    Koordiniert die Kommunikation zwischen den spezialisierten Agenten.
    Verwaltet Handoffs und Kontextübergaben zwischen den Agenten.
    """
    
    def __init__(self, openai_service, solar_calculator, calendar_service):
        self.timezone = pytz.timezone('Europe/Berlin')
        
        # Initialisiere die spezialisierten Agenten
        self.agents = {
            "solar_agent": SolarAgent(openai_service, solar_calculator),
            "calendar_agent": CalendarAgent(openai_service, calendar_service)
        }
        
        # Speichert Konversationshistorien
        self.conversations: Dict[str, List[Dict[str, str]]] = {}
        
        # Tracking für Handoffs
        self.current_agent: Dict[str, str] = {}
        self.handoff_history: Dict[str, List[Dict[str, Any]]] = {}
        
        # Maximale Anzahl von Handoffs pro Konversation
        self.max_handoffs = 5

    def _get_conversation_history(self, user_id: str = "default") -> List[Dict[str, str]]:
        """Holt oder erstellt eine neue Konversationshistorie"""
        if user_id not in self.conversations:
            self.conversations[user_id] = []
        return self.conversations[user_id]

    def _get_current_agent(self, user_id: str = "default") -> str:
        """Ermittelt den aktuell zuständigen Agenten"""
        return self.current_agent.get(user_id, "solar_agent")

    def _record_handoff(self, user_id: str, from_agent: str, to_agent: str, reason: str):
        """Dokumentiert einen Handoff zwischen Agenten"""
        if user_id not in self.handoff_history:
            self.handoff_history[user_id] = []
        
        self.handoff_history[user_id].append({
            "timestamp": datetime.now(self.timezone).isoformat(),
            "from_agent": from_agent,
            "to_agent": to_agent,
            "reason": reason
        })

    async def process_message(self, message: str, context: Optional[Dict] = None, 
                            user_id: str = "default") -> Dict[str, Any]:
        """
        Verarbeitet eine Nachricht und koordiniert mögliche Handoffs zwischen Agenten.
        
        Args:
            message: Die Nutzernachricht
            context: Optionaler Kontext für die Verarbeitung
            user_id: Identifier für den Nutzer
            
        Returns:
            Dict mit der Antwort und möglichen Handoff-Informationen
        """
        try:
            # Hole oder erstelle Konversationshistorie
            conversation_history = self._get_conversation_history(user_id)
            
            # Füge Nutzernachricht zur Historie hinzu
            conversation_history.append({
                "role": "user",
                "content": message
            })
            
            # Hole aktuellen Agenten
            current_agent_id = self._get_current_agent(user_id)
            current_agent = self.agents[current_agent_id]
            
            # Verarbeite die Nachricht mit dem aktuellen Agenten
            response = await current_agent.process(
                message=message,
                conversation_history=conversation_history
            )
            
            # Prüfe auf Handoff-Anfrage
            if response["type"] == "handoff":
                # Prüfe maximale Handoff-Anzahl
                if len(self.handoff_history.get(user_id, [])) >= self.max_handoffs:
                    logger.warning(f"Maximale Handoff-Anzahl erreicht für User {user_id}")
                    return {
                        "type": "error",
                        "content": "Zu viele Agentenübergaben. Bitte starten Sie eine neue Anfrage."
                    }
                
                # Führe Handoff durch
                new_agent_id = response["target_agent"]
                if new_agent_id not in self.agents:
                    logger.error(f"Unbekannter Zielagent: {new_agent_id}")
                    return {
                        "type": "error",
                        "content": "Interner Fehler bei der Agentenübergabe."
                    }
                
                # Dokumentiere Handoff
                self._record_handoff(
                    user_id=user_id,
                    from_agent=current_agent_id,
                    to_agent=new_agent_id,
                    reason=response.get("reason", "Nicht spezifiziert")
                )
                
                # Aktualisiere aktuellen Agenten
                self.current_agent[user_id] = new_agent_id
                
                # Füge Handoff-Information zur Konversationshistorie hinzu
                conversation_history.append({
                    "role": "system",
                    "content": f"Übergabe an {new_agent_id} wegen: {response.get('reason')}"
                })
                
                # Verarbeite mit neuem Agenten
                return await self.agents[new_agent_id].process(
                    message=message,
                    conversation_history=conversation_history
                )
            
            # Normale Antwort
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
        """Erstellt eine Zusammenfassung der Konversation mit Handoff-Historie"""
        return {
            "conversation_length": len(self.conversations.get(user_id, [])),
            "current_agent": self._get_current_agent(user_id),
            "handoff_count": len(self.handoff_history.get(user_id, [])),
            "handoff_history": self.handoff_history.get(user_id, [])
        }

    def reset_conversation(self, user_id: str = "default"):
        """Setzt die Konversation zurück"""
        self.conversations[user_id] = []
        self.current_agent[user_id] = "solar_agent"
        self.handoff_history[user_id] = []