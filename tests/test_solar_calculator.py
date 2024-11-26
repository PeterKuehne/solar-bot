import pytest
from unittest.mock import Mock, patch
from services.solar_calculator import SolarCalculator

@pytest.fixture
def solar_calculator():
    return SolarCalculator(pvgis_api_key="test_key")

@pytest.fixture
def mock_pvgis_response():
    return {
        'outputs': {
            'monthly': [
                {'E_m': 100} for _ in range(12)  # 100 kWh per month
            ]
        }
    }

@pytest.mark.asyncio
async def test_calculate_savings(solar_calculator, mock_pvgis_response):
    # Setup
    with patch('aiohttp.ClientSession.get') as mock_get:
        mock_get.return_value.__aenter__.return_value.status = 200
        mock_get.return_value.__aenter__.return_value.json = Mock(
            return_value=mock_pvgis_response
        )

        # Execute
        result = await solar_calculator.calculate_savings(
            consumption=4000,
            location={'lat': 52.52, 'lon': 13.405}
        )

        # Assert
        assert 'annual_production' in result
        assert 'financial_savings' in result
        assert 'environmental_impact' in result
        assert result['annual_production'] == 1200  # 12 months * 100 kWh

@pytest.mark.asyncio
async def test_pvgis_api_error(solar_calculator):
    # Setup
    with patch('aiohttp.ClientSession.get') as mock_get:
        mock_get.return_value.__aenter__.return_value.status = 404

        # Execute and Assert
        with pytest.raises(Exception):
            await solar_calculator.calculate_savings(
                consumption=4000,
                location={'lat': 52.52, 'lon': 13.405}
            )