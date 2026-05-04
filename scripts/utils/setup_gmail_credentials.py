"""
Helper script to set up Gmail API credentials
Run this once to generate token.json from credentials.json
"""

import os
import json
from google_auth_oauthlib.flow import InstalledAppFlow

SCOPES = ['https://www.googleapis.com/auth/gmail.send']

# Use same path resolution as credentials_manager
_backend_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CREDENTIALS_FILE = os.path.join(_backend_dir, "credentials.json")
TOKEN_FILE = os.path.join(_backend_dir, "token.json")


def setup_gmail_credentials():
    """Run OAuth flow to generate token.json"""
    if not os.path.exists(CREDENTIALS_FILE):
        print(f"❌ Error: {CREDENTIALS_FILE} not found")
        print(f"   Please ensure credentials.json is in the backend directory")
        return False
    
    # Check credentials file format
    try:
        with open(CREDENTIALS_FILE, 'r') as f:
            creds_data = json.load(f)
        
        # Check if it's a service account (doesn't need OAuth flow)
        if 'type' in creds_data and creds_data['type'] == 'service_account':
            print("✅ Service account credentials detected. No OAuth flow needed!")
            print("   Service accounts work directly with credentials.json")
            return True
        
        # Check if it's OAuth client credentials
        if 'installed' not in creds_data and 'web' not in creds_data:
            print("❌ Error: credentials.json doesn't appear to be a valid OAuth client credentials file")
            print("   Expected format: JSON with 'installed' or 'web' keys")
            print("   Or use a service account JSON file (with 'type': 'service_account')")
            return False
        
        print("✅ OAuth client credentials file detected")
    except Exception as e:
        print(f"❌ Error reading credentials.json: {e}")
        return False
    
    try:
        # Check if token already exists
        if os.path.exists(TOKEN_FILE):
            print(f"✅ {TOKEN_FILE} already exists")
            response = input("Do you want to regenerate it? (y/n): ")
            if response.lower() != 'y':
                print("Keeping existing token.json")
                return True
        
        print("\n" + "=" * 60)
        print("Starting OAuth flow...")
        print("A browser window will open. Please authorize the application.")
        print("=" * 60 + "\n")
        
        # Load client config and use from_client_config (matching user's working pattern)
        with open(CREDENTIALS_FILE, 'r') as f:
            client_config = json.load(f)
        
        flow = InstalledAppFlow.from_client_config(
            client_config, 
            SCOPES
        )
        # Use fixed port 8080 like user's working code (or port=0 for random)
        credentials = flow.run_local_server(port=8080)
        
        # Save the credentials
        with open(TOKEN_FILE, 'w') as token:
            token.write(credentials.to_json())
        
        print(f"\n✅ Successfully generated {TOKEN_FILE}")
        print("You can now use Gmail API for sending emails!")
        return True
        
    except Exception as e:
        print(f"❌ Error during OAuth flow: {e}")
        import traceback
        traceback.print_exc()
        return False


if __name__ == "__main__":
    print("=" * 60)
    print("Gmail API Credentials Setup")
    print("=" * 60)
    print()
    setup_gmail_credentials()

