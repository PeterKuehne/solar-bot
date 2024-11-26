import os
import sys
import json
from pathlib import Path

SCOPES = ['https://www.googleapis.com/auth/calendar']

def setup_google_calendar():
    """Generate Google Calendar tokens for authentication"""
    try:
        # Get the absolute path of the project directory
        project_dir = Path(__file__).parent.absolute()
        credentials_path = project_dir / 'credentials.json'
        
        print(f"Project directory: {project_dir}")
        print(f"Looking for credentials.json at: {credentials_path}")
        
        if not credentials_path.exists():
            print(f"Error: credentials.json not found at {credentials_path}!")
            print("\nPlease ensure credentials.json exists with this content:")
            print("""{
  "installed": {
    "client_id": "your-client-id",
    "project_id": "your-project-id",
    "auth_uri": "https://accounts.google.com/o/oauth2/auth",
    "token_uri": "https://oauth2.googleapis.com/token",
    "auth_provider_x509_cert_url": "https://www.googleapis.com/oauth2/v1/certs",
    "client_secret": "your-client-secret",
    "redirect_uris": ["http://localhost"]
  }
}""")
            return

        # Read and validate credentials file
        try:
            with credentials_path.open('r') as f:
                creds_content = json.load(f)
                if 'installed' not in creds_content:
                    print("Error: Invalid credentials.json format! Missing 'installed' key.")
                    return
                print("Successfully read credentials.json")
        except json.JSONDecodeError as e:
            print(f"Error: credentials.json contains invalid JSON: {str(e)}")
            return
        except Exception as e:
            print(f"Error reading credentials.json: {str(e)}")
            return

        # Import here to avoid errors if not installed
        try:
            from google_auth_oauthlib.flow import InstalledAppFlow
        except ImportError:
            print("Error: google-auth-oauthlib not installed!")
            print("Please install it with: pip install google-auth-oauthlib")
            return
        
        # Create flow
        try:
            flow = InstalledAppFlow.from_client_secrets_file(
                str(credentials_path),  # Convert Path to string
                SCOPES,
                redirect_uri='http://localhost'
            )
            
            print("\nStarting OAuth flow...")
            print("A browser window should open automatically.")
            print("If it doesn't, please check your terminal for the authorization URL.")
            creds = flow.run_local_server(port=0)
            print("OAuth flow completed successfully!")
            
            # Create credentials dict
            credentials_dict = {
                "token": creds.token,
                "refresh_token": creds.refresh_token,
                "token_uri": creds.token_uri,
                "client_id": creds.client_id,
                "client_secret": creds.client_secret,
                "scopes": creds.scopes
            }
            
            # Save tokens
            tokens_path = project_dir / 'google_tokens.json'
            with tokens_path.open('w') as f:
                json.dump(credentials_dict, f, indent=2)
            
            print("\nAuthentication successful!")
            print("\nAdd this to your .env file as GOOGLE_CALENDAR_CREDENTIALS:")
            print(json.dumps(credentials_dict, indent=2))
            print(f"\nTokens also saved to: {tokens_path}")
            
        except Exception as e:
            print(f"\nError during OAuth flow: {str(e)}")
            
    except Exception as e:
        print(f"\nUnexpected error: {str(e)}")
        print("\nDebug information:")
        print(f"Python version: {sys.version}")
        print(f"Script location: {__file__}")
        print("Python path:")
        for path in sys.path:
            print(f"  {path}")

if __name__ == "__main__":
    setup_google_calendar()
    