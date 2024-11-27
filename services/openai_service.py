from typing import Dict, Any, List, Optional
import json
import logging
from datetime import datetime, timedelta
from openai import OpenAI

logger = logging.getLogger(__name__)

class OpenAIService:
    def __init__(self, api_key: str):
        self.client = OpenAI(api_key=api_key)
        self.model = "gpt-4o-mini"
        self.max_history_age = timedelta(minutes=5)
        self.max_history_length = 10
        self.conversations: Dict[str, Dict[str, Any]] = {}
        
        self.tools = [
            {
                "name": "calculate_solar_savings",
                "description": "Berechnet die potentiellen Einsparungen durch eine Solaranlage",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "address": {
                            "type": "string",
                            "description": "Vollständige Adresse des Gebäudes"
                        },
                        "monthly_bill": {
                            "type": "number",
                            "description": "Monatliche Stromkosten in Euro"
                        }
                    },
                    "required": ["address", "monthly_bill"]
                }
            },
            {
                "name": "create_event",
                "description": "Erstellt einen neuen Beratungstermin.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "start_time": {
                            "type": "string",
                            "description": "Startzeit im ISO-Format mit Zeitzone +01:00 (z.B. 2024-11-27T10:00:00+01:00)"
                        },
                        "email": {
                            "type": "string",
                            "description": "E-Mail-Adresse des Kunden"
                        }
                    },
                    "required": ["start_time", "email"]
                }
            },
            {
                "name": "check_availability",
                "description": "Prüft, ob ein bestimmter Termin verfügbar ist.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "date_time": {
                            "type": "string",
                            "description": "ISO 8601 Datumszeit"
                        }
                    },
                    "required": ["date_time"]
                }
            },
            {
                "name": "suggest_alternative",
                "description": "Schlägt eine alternative Zeit vor, wenn ein Termin nicht verfügbar ist.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "date_time": {
                            "type": "string",
                            "description": "ISO 8601 Datumszeit"
                        }
                    },
                    "required": ["date_time"]
                }
            }
        ]
        self.system_prompt = """Du bist Klaus, ein freundlicher und kompetenter Solaranlagen-Berater. 
        Deine Aufgabe ist es, Kunden bei der Planung ihrer Solaranlage zu unterstützen und Beratungstermine zu vereinbaren.

        Bei Terminanfragen:
        1. Stelle sicher, dass du die E-Mail-Adresse des Kunden hast
        2. Wenn die E-Mail-Adresse nicht im Text erwähnt wurde, frage explizit danach
        3. Wenn ein Kunde eine Uhrzeit nennt (z.B. "10:00 Uhr"), verwende GENAU diese Zeit im create_appointment
        4. Füge IMMER die Zeitzone +01:00 zum Termin hinzu (z.B. 2024-11-27T10:00:00+01:00)
        5. Kommuniziere Termine immer in deutscher Zeit
        6. Behandele jeden Termin als 60-minütige Beratung
        """

    def _cleanup_old_conversations(self):
        """Remove old conversations and trim history"""
        current_time = datetime.now()
        to_remove = []

        for user_id, conversation in self.conversations.items():
            # Remove conversations older than max_history_age
            last_update = conversation.get('last_update')
            if last_update and (current_time - last_update) > self.max_history_age:
                to_remove.append(user_id)
                continue

            # Trim conversation history to max_history_length
            messages = conversation.get('messages', [])
            if len(messages) > self.max_history_length:
                # Keep the first message (system prompt) and the most recent messages
                conversation['messages'] = [messages[0]] + messages[-self.max_history_length+1:]

        # Remove old conversations
        for user_id in to_remove:
            del self.conversations[user_id]

    def _get_conversation(self, user_id: str = "default") -> List[Dict[str, str]]:
        """Get or create conversation history for user"""
        self._cleanup_old_conversations()
        
        if user_id not in self.conversations:
            self.conversations[user_id] = {
                'messages': [{"role": "system", "content": self.system_prompt}],
                'last_update': datetime.now(),
                'user_data': {}
            }
        else:
            self.conversations[user_id]['last_update'] = datetime.now()
        
        return self.conversations[user_id]['messages']

    def _store_user_data(self, user_id: str, key: str, value: Any):
        """Store user-specific data like email"""
        if user_id not in self.conversations:
            self._get_conversation(user_id)
        self.conversations[user_id]['user_data'][key] = value

    def _get_user_data(self, user_id: str, key: str) -> Optional[Any]:
        """Retrieve user-specific data"""
        return self.conversations.get(user_id, {}).get('user_data', {}).get(key)

    async def process_message(self, conversation_history: List[Dict[str, str]], user_id: str = "default") -> Dict[str, Any]:
        try:
            # Get conversation history and update it
            messages = self._get_conversation(user_id)
            
            logger.info(f"Tools being sent to OpenAI API: {json.dumps(self.tools, indent=2)}")
            
            # Add new messages to history
            messages.extend(conversation_history[-2:] if len(conversation_history) > 2 else conversation_history)

            # Make the API call
            response = self.client.chat.completions.create(
                model=self.model,
                messages=messages,
                functions=self.tools  # Correctly pass the tools/functions
            )

            # Inspect the response for debugging
            logger.info(f"OpenAI API response: {response}")

            # Extract the assistant message
            assistant_message = response.choices[0].message

            # Handle function calls
            if isinstance(assistant_message, dict) and "function_call" in assistant_message:
                tool_call = assistant_message["function_call"]
                function_name = tool_call.get("name")
                arguments = json.loads(tool_call.get("arguments", "{}"))

                return {
                    "type": "function_call",
                    "function": function_name,
                    "arguments": arguments
                }
            elif "content" in assistant_message:
                # Standard message response
                return {
                    "type": "message",
                    "content": assistant_message["content"]
                }
            else:
                # Unexpected response format
                logger.error(f"Unexpected API response format: {assistant_message}")
                return {
                    "type": "error",
                    "message": "Ein unerwartetes Problem ist aufgetreten. Bitte versuchen Sie es erneut."
                }

        except Exception as e:
            logger.error(f"Error in process_message: {str(e)}")
            raise