from typing import Dict, Any, List, Optional
from datetime import datetime
import json
from .base_agent import BaseAgent

class SolarAgent(BaseAgent):
    def __init__(self, openai_service, solar_calculator):
        super().__init__("solar_agent", openai_service)
        self.solar_calculator = solar_calculator
        self._last_calculation = None

    def _get_system_prompt(self) -> str:
        return """Du bist ein Solaranlagen-Experte. Beginne mit der Abfrage des jährlichen Stromverbrauchs (kWh) 
        und der Adresse/PLZ. Optional frage nach:
        - Dachfläche (m²)
        - Dachausrichtung
        - Dachneigung
        
        Ohne optionale Daten nutze vereinfachte Berechnung mit Standardwerten. Übergebe Terminanfragen an den Kalender-Agenten.
        
        Verwende diese Modelle für technische Antworten:
        Standard: 380Wp, 19,5% Wirkungsgrad
        Premium: 410Wp, 21% Wirkungsgrad 
        High-End: 440Wp, 22,5% Wirkungsgrad"""

    def _get_functions(self) -> List[Dict[str, Any]]:
        return [
            {
                "name": "calculate_solar_system",
                "description": "Berechnet die optimale Solaranlagengröße und potenzielle Einsparungen",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "yearly_consumption": {
                            "type": "number",
                            "description": "Jährlicher Stromverbrauch in kWh"
                        },
                        "address": {
                            "type": "string",
                            "description": "Adresse für Standortdaten"
                        },
                        "roof_area": {
                            "type": "number",
                            "description": "Verfügbare Dachfläche in m²"
                        },
                        "roof_angle": {
                            "type": "number",
                            "description": "Dachneigung in Grad"
                        },
                        "orientation": {
                            "type": "string",
                            "enum": ["north", "east", "south", "west", "unknown"]
                        }
                    },
                    "required": ["yearly_consumption", "address"]
                }
            },
            {
                "name": "analyze_efficiency",
                "description": "Analysiert die Effizienz verschiedener Anlagenkonfigurationen",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "system_size": {
                            "type": "number",
                            "description": "Gewünschte Anlagengröße in kWp"
                        },
                        "module_type": {
                            "type": "string",
                            "enum": ["standard", "premium", "high_end"]
                        },
                        "include_battery": {
                            "type": "boolean",
                            "description": "Batteriespeicher einbeziehen"
                        }
                    },
                    "required": ["system_size"]
                }
            },
            *self.get_handoff_functions()
        ]

    async def calculate_solar_system(self, 
                                   yearly_consumption: float,
                                   address: str,
                                   roof_area: Optional[float] = None,
                                   roof_angle: Optional[float] = None,
                                   orientation: Optional[str] = None) -> Dict[str, Any]:
        try:
            coordinates = await self.solar_calculator.get_coordinates(address)
            calculation = await self.solar_calculator.calculate_savings(
                consumption=yearly_consumption,
                location=coordinates,
                roof_angle=roof_angle if roof_angle is not None else 35,
                orientation=orientation if orientation else 'south'
            )
            
            is_simplified = not all([roof_area, roof_angle, orientation])
            calculation['calculation_type'] = 'simplified' if is_simplified else 'detailed'
            
            # Berechne Mindestdachfläche
            needed_area = calculation['system_size'] * 2.5
            if is_simplified:
                calculation['assumptions'] = {
                    'roof_angle': 35,
                    'orientation': 'south',
                    'minimum_roof_area': needed_area
                }
            else:
                if roof_area < needed_area:
                    return {
                        "success": False,
                        "error": f"Die verfügbare Dachfläche von {roof_area}m² ist zu klein für die benötigte Anlagengröße (Minimum: {needed_area}m²)"
                    }
                calculation['roof_parameters'] = {
                    'area': roof_area,
                    'angle': roof_angle,
                    'orientation': orientation
                }
            
            response_text = self._format_calculation_response(calculation)
            self._last_calculation = calculation
            return {
                "success": True,
                "calculation": {
                    "text_summary": response_text,
                    "results": calculation
                }
            }

        except Exception as e:
            return {
                "success": False,
                "error": str(e)
            }

    def _format_calculation_response(self, calculation: Dict[str, Any]) -> str:
        is_simplified = calculation['calculation_type'] == 'simplified'
        
        response = []
        if is_simplified:
            response.append(f"Basierend auf einer vereinfachten Berechnung mit Standardwerten (35° Dachneigung, Südausrichtung):")
        else:
            response.append("Basierend auf Ihren spezifischen Dachparametern:")
        
        response.append(f"• Anlagengröße: {calculation['system_size']} kWp")
        response.append(f"• Mindest-Dachfläche: {calculation['assumptions']['minimum_roof_area'] if is_simplified else calculation['roof_parameters']['area']}m²")
        response.append(f"• Jährliche Produktion: {calculation['yearly_production']} kWh")
        response.append(f"• Deckung des Verbrauchs: {round(calculation['consumption_coverage'], 1)}%")
        
        savings = calculation['financial_savings']
        response.append(f"• Jährliche Ersparnis: {savings['self_consumption_savings']}€")
        if savings['feed_in_revenue'] > 0:
            response.append(f"• Einspeisevergütung: {savings['feed_in_revenue']}€")
        response.append(f"• Gesamtersparnis pro Jahr: {savings['total_savings']}€")
        
        env = calculation['environmental_impact']
        response.append(f"• CO2-Einsparung: {env['co2_savings']} kg/Jahr")
        response.append(f"• Entspricht {env['trees_equivalent']} Bäumen")
        
        if is_simplified:
            response.append("\nFür eine genauere Berechnung können Sie uns Ihre spezifischen Dachparameter mitteilen.")
        
        return "\n".join(response)

    async def analyze_efficiency(self,
                               system_size: float,
                               module_type: str = "premium",
                               include_battery: bool = False) -> Dict[str, Any]:
        try:
            efficiency_data = {
                "standard": {
                    "efficiency": 0.195,
                    "degradation": 0.0055,
                    "performance_ratio": 0.85
                },
                "premium": {
                    "efficiency": 0.21,
                    "degradation": 0.005,
                    "performance_ratio": 0.86
                },
                "high_end": {
                    "efficiency": 0.225,
                    "degradation": 0.0035,
                    "performance_ratio": 0.88
                }
            }

            selected_config = efficiency_data[module_type]
            yearly_yield = system_size * 1000 * selected_config["performance_ratio"]
            
            if include_battery:
                battery_size = system_size * 1.0
                self_consumption = min(0.8, 0.35 + (battery_size * 0.05))
            else:
                self_consumption = 0.35
                battery_size = 0

            return {
                "success": True,
                "analysis": {
                    "yearly_yield": yearly_yield,
                    "efficiency": selected_config["efficiency"],
                    "degradation": selected_config["degradation"],
                    "performance_ratio": selected_config["performance_ratio"],
                    "self_consumption": self_consumption,
                    "includes_battery": include_battery,
                    "battery_size": battery_size
                }
            }

        except Exception as e:
            return {
                "success": False,
                "error": str(e)
            }