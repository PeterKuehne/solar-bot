import logging
from typing import Dict, Any, List
from openai import OpenAI
import json

logger = logging.getLogger(__name__)

class OpenAIService:
    def __init__(self, api_key: str):
        self.client = OpenAI(api_key=api_key)

    async def process_message(self, messages: List[Dict[str, str]], functions: List[Dict] = None) -> Dict[str, Any]:
        """Verarbeitet Chat-Nachrichten"""
        try:
            # Nicht-asynchroner Aufruf, da die neue OpenAI API kein async unterstützt
            if functions:
                response = self.client.chat.completions.create(
                    model="gpt-4o-mini",
                    messages=messages,
                    functions=functions
                )
            else:
                response = self.client.chat.completions.create(
                    model="gpt-4o-mini",
                    messages=messages
                )
            
            # Format der Antwort für unsere Verwendung anpassen
            return {
                "choices": [{
                    "message": {
                        "content": response.choices[0].message.content,
                        "function_call": response.choices[0].message.function_call if hasattr(response.choices[0].message, 'function_call') else None
                    }
                }]
            }
        except Exception as e:
            logger.error(f"OpenAI API Error: {str(e)}")
            raise

    async def process_query(self, prompt: str) -> str:
        """Verarbeitet eine einzelne Anfrage"""
        try:
            response = self.client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[{
                    "role": "system",
                    "content": """Du bist ein Experte für Solaranlagen und hilfst dabei, 
                    Informationen zu finden und zu interpretieren. 
                    Antworte präzise und basiere deine Antworten nur auf den gegebenen Dokumenten."""
                },
                {
                    "role": "user",
                    "content": prompt
                }]
            )
            return response.choices[0].message.content
        except Exception as e:
            logger.error(f"OpenAI API Error: {str(e)}")
            raise