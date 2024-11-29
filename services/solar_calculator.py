from typing import Dict, Any
import aiohttp
import logging
import requests
import ssl
import certifi

logger = logging.getLogger(__name__)

class SolarCalculator:
    def __init__(self, google_api_key: str):
        self.google_api_key = google_api_key
        self.base_url = "https://re.jrc.ec.europa.eu/api/v5_2/PVcalc"
        self.ssl_context = ssl.create_default_context(cafile=certifi.where())

    async def get_coordinates(self, address: str) -> Dict[str, float]:
        try:
            url = f"https://maps.googleapis.com/maps/api/geocode/json?address={address}&key={self.google_api_key}"
            response = requests.get(url, verify=True)
            if response.status_code == 200:
                data = response.json()
                if data['results']:
                    location = data['results'][0]['geometry']['location']
                    return {'lat': location['lat'], 'lon': location['lng']}
            raise Exception("Could not get coordinates for address")
        except Exception as e:
            logger.error(f"Error getting coordinates: {str(e)}")
            raise

    async def calculate_savings(self, 
                              consumption: float, 
                              location: Dict[str, float],
                              roof_angle: float = 35,
                              orientation: str = 'south') -> Dict[str, Any]:
        try:
            # Calculate system size based on consumption
            system_size = self._calculate_system_size(consumption)
            
            # Get solar production data from PVGIS with orientation parameters
            solar_data = await self._get_pvgis_data(
                location['lat'], 
                location['lon'], 
                system_size,
                roof_angle,
                self._convert_orientation(orientation)
            )
            
            # Calculate savings
            savings = self._calculate_financial_savings(solar_data['yearly_production'], consumption)
            
            return {
                'system_size': system_size,
                'yearly_production': solar_data['yearly_production'],
                'consumption_coverage': (solar_data['yearly_production'] / consumption) * 100 if consumption > 0 else 0,
                'financial_savings': savings,
                'environmental_impact': self._calculate_environmental_impact(solar_data['yearly_production'])
            }
        except Exception as e:
            logger.error(f"Error in calculate_savings: {str(e)}")
            raise

    def _calculate_system_size(self, consumption: float) -> float:
        """Calculate recommended system size in kWp based on yearly consumption"""
        return round(consumption / 1000, 2)

    def _convert_orientation(self, orientation: str) -> int:
        """Convert orientation string to PVGIS aspect angle"""
        orientation_map = {
            'south': 0,
            'southeast': -45,
            'southwest': 45,
            'east': -90,
            'west': 90,
            'northeast': -135,
            'northwest': 135,
            'north': 180
        }
        return orientation_map.get(orientation.lower(), 0)

    async def _get_pvgis_data(self, 
                             lat: float, 
                             lon: float, 
                             peak_power: float,
                             angle: float = 35,
                             aspect: int = 0) -> Dict[str, Any]:
        try:
            params = {
                'lat': str(lat),
                'lon': str(lon),
                'peakpower': str(peak_power),
                'loss': '14',
                'outputformat': 'json',
                'angle': str(angle),
                'aspect': str(aspect)
            }

            async with aiohttp.ClientSession() as session:
                async with session.get(self.base_url, params=params, ssl=self.ssl_context) as response:
                    if response.status == 200:
                        try:
                            data = await response.json(content_type=None)
                            yearly_production = data['outputs']['totals']['fixed']['E_y']
                            return {
                                'yearly_production': yearly_production,
                                'location': {'lat': lat, 'lon': lon}
                            }
                        except Exception as e:
                            logger.error(f"Error parsing PVGIS response: {str(e)}")
                            return self._calculate_fallback_production(peak_power)
                    else:
                        logger.error(f"PVGIS API error: {response.status}")
                        return self._calculate_fallback_production(peak_power)

        except Exception as e:
            logger.error(f"Error fetching PVGIS data: {str(e)}")
            return self._calculate_fallback_production(peak_power)

    def _calculate_fallback_production(self, peak_power: float) -> Dict[str, Any]:
        """Fallback calculation if PVGIS API fails"""
        yearly_production = peak_power * 1000
        return {
            'yearly_production': yearly_production
        }

    def _calculate_financial_savings(self, yearly_production: float, consumption: float) -> Dict[str, float]:
        electricity_price = 0.32  # €/kWh
        feed_in_tariff = 0.08    # €/kWh
        
        self_consumption = min(yearly_production, consumption)
        grid_feed_in = max(0, yearly_production - consumption)
        
        return {
            'self_consumption_savings': round(self_consumption * electricity_price, 2),
            'feed_in_revenue': round(grid_feed_in * feed_in_tariff, 2),
            'total_savings': round((self_consumption * electricity_price) + (grid_feed_in * feed_in_tariff), 2)
        }

    def _calculate_environmental_impact(self, yearly_production: float) -> Dict[str, float]:
        co2_factor = 0.420  # kg CO2/kWh
        
        return {
            'co2_savings': round(yearly_production * co2_factor, 2),
            'trees_equivalent': round((yearly_production * co2_factor) / 20, 1)
        }