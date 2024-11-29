from abc import ABC, abstractmethod
from typing import Dict, Any, List, Optional
import logging
import json
from datetime import datetime

logger = logging.getLogger(__name__)

class BaseAgent(ABC):
    """
    Basisklasse für spezialisierte Agenten.
    Implementiert die grundlegende Logik für Handoffs und Agentenkommunikation.
    """
    
    def __init__(self, name: str, openai_service):
        """
        Initialisiert einen neuen Agenten.
        
        Args:
            name (str): Name des Agenten
            openai_service: OpenAI Service für API-Interaktionen
        """
        self.name = name
        self.openai_service = openai_service
        self.functions = self._get_functions()
        self.max_interaction_depth = 5
        
    @abstractmethod
    def _get_functions(self) -> List[Dict[str, Any]]:
        """
        Definiert die verfügbaren Funktionen des Agenten.
        Muss von abgeleiteten Klassen implementiert werden.
        """
        pass

    @abstractmethod
    def _get_system_prompt(self) -> str:
        """
        Definiert den System-Prompt für den Agenten.
        Muss von abgeleiteten Klassen implementiert werden.
        """
        pass

    async def process(self, message: str, conversation_history: List[Dict[str, str]], depth: int = 0) -> Dict[str, Any]:
        """
        Verarbeitet eine Nachricht und entscheidet über mögliche Handoffs.
        
        Args:
            message: Die zu verarbeitende Nachricht
            conversation_history: Bisheriger Gesprächsverlauf
            depth: Aktuelle Verarbeitungstiefe
            
        Returns:
            Dict mit Verarbeitungsergebnis oder Handoff-Information
        """
        try:
            if depth >= self.max_interaction_depth:
                logger.warning(f"Maximale Interaktionstiefe erreicht für {self.name}")
                return {
                    "type": "error",
                    "content": "Maximale Verarbeitungstiefe erreicht."
                }

            # Erstelle vollständigen Kontext
            full_context = [
                {"role": "system", "content": self._get_system_prompt()},
                *conversation_history,
                {"role": "user", "content": message}
            ]
            
            # Hole Antwort von OpenAI mit Agent-spezifischen Funktionen
            response = await self.openai_service.process_message(
                messages=full_context,
                functions=self.functions
            )
            
            return await self._handle_response(response, conversation_history, depth)
            
        except Exception as e:
            logger.error(f"Fehler in {self.name}: {str(e)}", exc_info=True)
            return {
                "type": "error",
                "content": f"Verarbeitungsfehler: {str(e)}"
            }

    async def _handle_response(self, response: Dict[str, Any], conversation_history: List[Dict[str, str]], depth: int) -> Dict[str, Any]:
        try:
            message = response.get("choices", [{}])[0].get("message", {})
            
            if message.get("function_call") or getattr(message, "function_call", None):
                return await self._handle_function_call(
                    message.get("function_call") or message.function_call,
                    conversation_history,
                    depth
                )
            
            # Normale Nachricht
            return {
                "type": "message",
                "content": message.get("content", ""),
                "agent": self.name
            }
            
        except KeyError as e:
            logger.error(f"Unerwartetes Antwortformat: {str(e)}")
            return {
                "type": "error",
                "content": "Fehler beim Verarbeiten der Antwort"
            }

    async def _handle_function_call(self, function_call: Dict[str, Any], 
                                  conversation_history: List[Dict[str, str]], 
                                  depth: int) -> Dict[str, Any]:
        """
        Verarbeitet Funktionsaufrufe und Handoffs.
        """
        try:
            function_name = function_call.name if hasattr(function_call, 'name') else function_call.get('name')
            arguments = json.loads(function_call.arguments if hasattr(function_call, 'arguments') else function_call.get('arguments', '{}'))

            # Prüfe auf Handoff-Funktion
            if function_name.startswith("transfer_to_"):
                return {
                    "type": "handoff",
                    "target_agent": function_name.replace("transfer_to_", ""),
                    "reason": arguments.get("reason", "Nicht spezifiziert"),
                    "context": arguments.get("context", {})
                }

            # Führe normale Funktion aus
            if hasattr(self, function_name):
                function_result = await getattr(self, function_name)(**arguments)
                
                # Füge Funktionsergebnis zum Gesprächsverlauf hinzu
                conversation_history.append({
                    "role": "function",
                    "name": function_name,
                    "content": json.dumps(function_result)
                })

                # Verarbeite Ergebnis rekursiv
                return await self.process(
                    message=f"Verarbeite Ergebnis von {function_name}",
                    conversation_history=conversation_history,
                    depth=depth + 1
                )
            
            logger.error(f"Funktion {function_name} nicht gefunden bei {self.name}")
            return {
                "type": "error",
                "content": f"Funktion {function_name} nicht verfügbar"
            }

        except json.JSONDecodeError:
            logger.error("Ungültige Funktionsargumente")
            return {
                "type": "error",
                "content": "Fehler bei der Verarbeitung der Funktionsargumente"
            }
        except Exception as e:
            logger.error(f"Fehler bei Funktionsausführung: {str(e)}")
            return {
                "type": "error",
                "content": f"Fehler bei der Funktionsausführung: {str(e)}"
            }

    def get_handoff_functions(self) -> List[Dict[str, Any]]:
        """
        Liefert die verfügbaren Handoff-Funktionen des Agenten.
        """
        return [
            {
                "name": "transfer_to_solar_agent",
                "description": "Übergibt an den Solar-Experten für Berechnungen und technische Fragen",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "reason": {
                            "type": "string",
                            "description": "Grund für die Übergabe"
                        },
                        "context": {
                            "type": "object",
                            "description": "Relevante Informationen für den Solar-Agenten",
                            "properties": {
                                "technical_details": {
                                    "type": "object",
                                    "description": "Technische Informationen"
                                },
                                "calculation_params": {
                                    "type": "object",
                                    "description": "Parameter für Berechnungen"
                                }
                            }
                        }
                    },
                    "required": ["reason"]
                }
            },
            {
                "name": "transfer_to_calendar_agent",
                "description": "Übergibt an den Kalender-Agenten für Terminvereinbarungen",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "reason": {
                            "type": "string",
                            "description": "Grund für die Übergabe"
                        },
                        "context": {
                            "type": "object",
                            "description": "Relevante Informationen für den Kalender-Agenten",
                            "properties": {
                                "preferred_date": {
                                    "type": "string",
                                    "description": "Gewünschtes Datum"
                                },
                                "appointment_type": {
                                    "type": "string",
                                    "description": "Art des Termins"
                                }
                            }
                        }
                    },
                    "required": ["reason"]
                }
            }
        ]