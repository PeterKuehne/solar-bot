import pytest
from unittest.mock import Mock, patch
from services.orchestrator import Orchestrator

@pytest.fixture
def mock_services():
    return {
        'openai_service': Mock(),
        'solar_calculator': Mock(),
        'calendar_service': Mock()
    }

@pytest.fixture
def orchestrator(mock_services):
    return Orchestrator(
        mock_services['openai_service'],
        mock_services['solar_calculator'],
        mock_services['calendar_service']
    )

@pytest.mark.asyncio
async def test_solar_calculation_intent(orchestrator, mock_services):
    # Setup
    mock_services['openai_service'].analyze_intent.return_value = {"type": "solar_calculation"}
    mock_services['openai_service'].extract_solar_params.return_value = {
        "consumption": 4000,
        "location": {"lat": 52.52, "lon": 13.405}
    }
    mock_services['solar_calculator'].calculate_savings.return_value = {
        "annual_production": 3800,
        "financial_savings": {"total_savings": 1200}
    }

    # Execute
    result = await orchestrator.process_message("Calculate solar savings for Berlin")

    # Assert
    assert mock_services['openai_service'].analyze_intent.called
    assert mock_services['solar_calculator'].calculate_savings.called
    assert mock_services['openai_service'].format_solar_response.called

@pytest.mark.asyncio
async def test_appointment_booking_intent(orchestrator, mock_services):
    # Setup
    mock_services['openai_service'].analyze_intent.return_value = {"type": "appointment_booking"}
    mock_services['openai_service'].extract_booking_params.return_value = {
        "date": "2024-01-15T10:00:00",
        "description": "Solar consultation"
    }
    mock_services['calendar_service'].book_appointment.return_value = {
        "id": "123",
        "link": "https://calendar.google.com/event?id=123"
    }

    # Execute
    result = await orchestrator.process_message(
        "Book an appointment for tomorrow at 10 AM",
        user_email="test@example.com"
    )

    # Assert
    assert mock_services['openai_service'].analyze_intent.called
    assert mock_services['calendar_service'].book_appointment.called
    assert mock_services['openai_service'].format_booking_confirmation.called