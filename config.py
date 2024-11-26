from pydantic import BaseSettings, Field
import json
from typing import Dict, Any, Optional
import logging

logger = logging.getLogger(__name__)

class Settings(BaseSettings):
    OPENAI_API_KEY: str = Field(..., env='OPENAI_API_KEY')
    GOOGLE_CLOUD_API_KEY: str = Field(..., env='GOOGLE_CLOUD_API_KEY')
    GOOGLE_CALENDAR_CREDENTIALS: Dict[str, Any] = Field(..., env='GOOGLE_CALENDAR_CREDENTIALS')
    GOOGLE_CALENDAR_ID: str = Field(..., env='GOOGLE_CALENDAR_ID')  # Neue Zeile
    ENVIRONMENT: str = Field(default="production", env='ENVIRONMENT')

    class Config:
        env_file = ".env"
        case_sensitive = True

    @property
    def calendar_creds(self) -> Dict[str, Any]:
        try:
            if isinstance(self.GOOGLE_CALENDAR_CREDENTIALS, str):
                creds = json.loads(self.GOOGLE_CALENDAR_CREDENTIALS)
            else:
                creds = self.GOOGLE_CALENDAR_CREDENTIALS

            # Validate required fields
            if 'type' in creds and creds['type'] == 'service_account':
                required_fields = ['type', 'project_id', 'private_key_id', 'private_key', 'client_email']
            else:
                required_fields = ['client_id', 'client_secret', 'refresh_token']

            missing_fields = [field for field in required_fields if field not in creds]
            if missing_fields:
                raise ValueError(f"Missing required fields in credentials: {', '.join(missing_fields)}")

            return creds
        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse GOOGLE_CALENDAR_CREDENTIALS: {str(e)}")
            raise
        except Exception as e:
            logger.error(f"Error processing calendar credentials: {str(e)}")
            raise

    @property
    def calendar_id(self) -> str:  # Neue Property
        return self.GOOGLE_CALENDAR_ID

    @property
    def openai_api_key(self) -> str:
        return self.OPENAI_API_KEY

    @property
    def google_cloud_api_key(self) -> str:
        return self.GOOGLE_CLOUD_API_KEY