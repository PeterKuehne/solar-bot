from typing import Dict, Any, List, Optional
from datetime import datetime
import pytz
import logging
from .openai_service import OpenAIService
from .solar_calculator import SolarCalculator
from .calendar_service import CalendarService

logger = logging.getLogger(__name__)

class Orchestrator:
    def __init__(
        self,
        openai_service: OpenAIService,
        solar_calculator: SolarCalculator,
        calendar_service: CalendarService
    ):
        self.openai_service = openai_service
        self.solar_calculator = solar_calculator
        self.calendar_service = calendar_service
        self.conversations: Dict[str, List[Dict[str, str]]] = {}
        self.timezone = pytz.timezone('Europe/Berlin')

    def _get_conversation_history(self, user_id: str = "default") -> List[Dict[str, str]]:
        """Get or create conversation history for user"""
        if user_id not in self.conversations:
            self.conversations[user_id] = []
        return self.conversations[user_id]

    async def process_message(self, message: str, user_email: Optional[str] = None, user_id: str = "default") -> str:
        """Process a message and return the response"""
        try:
            # Get conversation history for this user
            conversation_history = self._get_conversation_history(user_id)
            
            # Add user message to conversation history
            conversation_history.append({"role": "user", "content": message})

            # Get response from OpenAI
            response = await self.openai_service.process_message(conversation_history)

            # Handle function calls
            if response.get("type") == "function_call":
                function_result = await self._handle_function_call(
                    response["function"],
                    response["arguments"],
                    user_email
                )
                
                # Format the response
                formatted_response = await self.openai_service.format_response(
                    function_result,
                    conversation_history
                )
                
                # Add assistant response to conversation history
                conversation_history.append({
                    "role": "assistant",
                    "content": formatted_response
                })
                
                return formatted_response
            else:
                # Add direct response to conversation history
                conversation_history.append({
                    "role": "assistant",
                    "content": response["content"]
                })
                
                return response["content"]

        except Exception as e:
            logger.error(f"Error in process_message: {str(e)}")
            raise

    async def _handle_function_call(
        self,
        function_name: str,
        arguments: Dict[str, Any],
        user_email: Optional[str]
    ) -> Dict[str, Any]:
        logger.info(f"Handling function call: {function_name} with arguments: {arguments}")
        try:
            if function_name == "calculate_solar_savings":
                try:
                    coordinates = await self.solar_calculator.get_coordinates(
                        arguments["address"]
                    )
                    result = await self.solar_calculator.calculate_savings(
                        float(arguments["monthly_bill"]) * 12,  # Convert to yearly consumption
                        coordinates
                    )
                    logger.info(f"Solar calculation result: {result}")
                    return result
                except Exception as e:
                    logger.error(f"Error in solar calculation: {str(e)}")
                    return {
                        "error": "calculation_failed",
                        "message": f"Fehler bei der Berechnung: {str(e)}"
                    }

            elif function_name == "create_appointment":
                try:
                    start_time = datetime.fromisoformat(arguments["start_time"].replace('Z', '+00:00'))
                    start_time = start_time.astimezone(self.timezone)
                except ValueError:
                    return {
                        "error": "invalid_date",
                        "message": "Ungültiges Datumsformat. Bitte geben Sie ein vollständiges Datum an."
                    }

                # First check availability
                availability = await self.calendar_service.get_available_slots(start_time)
                logger.info(f"Availability check: {availability}")
                
                if not availability.get("available"):
                    return {
                        "error": "slot_not_available",
                        "message": availability.get("message", "Dieser Termin ist nicht verfügbar.")
                    }

                # If available, try to book with email from arguments
                result = await self.calendar_service.book_appointment(
                    date=start_time.isoformat(),
                    email=arguments["email"]  # Email kommt direkt aus den arguments
                )

                logger.info(f"Booking result: {result}")
                return result

            elif function_name == "check_availability":
                try:
                    start_time = datetime.fromisoformat(arguments["start_time"].replace('Z', '+00:00'))
                    start_time = start_time.astimezone(self.timezone)
                except ValueError:
                    return {
                        "error": "invalid_date",
                        "message": "Ungültiges Datumsformat. Bitte geben Sie ein vollständiges Datum an."
                    }

                # Check availability using the calendar service
                availability = await self.calendar_service.get_available_slots(start_time)
                logger.info(f"Availability check result: {availability}")
                return availability

            else:
                logger.warning(f"Unknown function called: {function_name}")
                raise ValueError(f"Unknown function: {function_name}")

        except Exception as e:
            logger.error(f"Error in _handle_function_call: {str(e)}", exc_info=True)
            return {
                "error": "system_error",
                "message": f"Ein Systemfehler ist aufgetreten: {str(e)}"
            }