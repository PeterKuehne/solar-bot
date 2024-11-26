import pytest
from datetime import datetime, timedelta
from unittest.mock import Mock, patch
from services.calendar_service import CalendarService

@pytest.fixture
def mock_google_calendar():
    with patch('services.calendar_service.build') as mock_build:
        calendar_service = mock_build.return_value
        events_service = Mock()
        calendar_service.events.return_value = events_service
        yield events_service

@pytest.fixture
def calendar_service(mock_google_calendar):
    credentials = {
        "token": "test_token",
        "refresh_token": "test_refresh_token",
        "client_id": "test_client_id",
        "client_secret": "test_client_secret"
    }
    return CalendarService(credentials)

@pytest.mark.asyncio
async def test_get_available_slots(calendar_service, mock_google_calendar):
    # Setup
    date = datetime(2024, 1, 15)
    mock_google_calendar.list.return_value.execute.return_value = {
        'items': [
            {
                'start': {'dateTime': '2024-01-15T10:00:00Z'},
                'end': {'dateTime': '2024-01-15T11:00:00Z'}
            }
        ]
    }

    # Execute
    slots = await calendar_service.get_available_slots(date)

    # Assert
    assert len(slots) > 0
    assert all('start' in slot and 'end' in slot for slot in slots)
    mock_google_calendar.list.assert_called_once()

@pytest.mark.asyncio
async def test_book_appointment(calendar_service, mock_google_calendar):
    # Setup
    mock_google_calendar.insert.return_value.execute.return_value = {
        'id': '123',
        'htmlLink': 'https://calendar.google.com/event?id=123',
        'start': {'dateTime': '2024-01-15T10:00:00Z'},
        'end': {'dateTime': '2024-01-15T11:00:00Z'}
    }

    # Execute
    result = await calendar_service.book_appointment(
        date='2024-01-15T10:00:00',
        email='test@example.com',
        description='Solar consultation'
    )

    # Assert
    assert result['id'] == '123'
    assert 'link' in result
    assert 'start' in result
    assert 'end' in result
    mock_google_calendar.insert.assert_called_once()