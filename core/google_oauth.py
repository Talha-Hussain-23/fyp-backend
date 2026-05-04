"""
Google OAuth 2.0 Web Client Integration
Handles OAuth flow, token storage, and refresh for Gmail and Calendar APIs
"""

import os
import json
from typing import Optional, Dict
from datetime import datetime, timedelta
from fastapi import HTTPException
from google_auth_oauthlib.flow import Flow
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
from google.auth.exceptions import RefreshError
from dotenv import load_dotenv
from bson import ObjectId

load_dotenv()

# OAuth 2.0 Scopes
# Note: openid is required when using userinfo.email and userinfo.profile
SCOPES = [
    'openid',
    'https://www.googleapis.com/auth/calendar',
    'https://www.googleapis.com/auth/calendar.events',
    'https://www.googleapis.com/auth/gmail.send',
    'https://www.googleapis.com/auth/userinfo.email',
    'https://www.googleapis.com/auth/userinfo.profile'
]

# OAuth Configuration
from core.config import settings

CLIENT_SECRETS_FILE = os.getenv("GOOGLE_CREDENTIALS_FILE", "credentials.json")
FRONTEND_URL = settings.active_frontend_url


def get_redirect_uri_from_credentials() -> str:
    """
    Read redirect URI from credentials.json file or environment
    Returns the first redirect URI from the web client configuration
    """
    try:
        creds_env = os.getenv("GOOGLE_CREDENTIALS_JSON")
        if creds_env:
            credentials_data = json.loads(creds_env)
        else:
            if not os.path.exists(CLIENT_SECRETS_FILE):
                raise HTTPException(
                    status_code=500,
                    detail=f"Google credentials file not found: {CLIENT_SECRETS_FILE}. Please ensure credentials.json is in the backend directory."
                )
            
            with open(CLIENT_SECRETS_FILE, 'r') as f:
                credentials_data = json.load(f)
        
        # Check for web client configuration
        if 'web' in credentials_data:
            redirect_uris = credentials_data['web'].get('redirect_uris', [])
            if redirect_uris:
                # Return the first redirect URI (usually the one configured in Google Cloud Console)
                return redirect_uris[0]
        
        # Fallback to environment variable or default
        return os.getenv("GOOGLE_REDIRECT_URI", "http://localhost:8000/auth/google/callback")
    except Exception as e:
        # Fallback to environment variable or default
        return os.getenv("GOOGLE_REDIRECT_URI", "http://localhost:8000/auth/google/callback")


def get_oauth_flow(redirect_uri: str = None) -> Flow:
    """
    Create and return OAuth 2.0 flow instance
    Uses redirect URI from environment or credentials.json if not provided
    """
    # Use provided redirect_uri, or get from credentials, or use default
    if not redirect_uri:
        redirect_uri = get_redirect_uri_from_credentials()
    
    creds_env = os.getenv("GOOGLE_CREDENTIALS_JSON")
    if creds_env:
        flow = Flow.from_client_config(
            json.loads(creds_env),
            scopes=SCOPES,
            redirect_uri=redirect_uri
        )
    else:
        if not os.path.exists(CLIENT_SECRETS_FILE):
            raise HTTPException(
                status_code=500,
                detail=f"Google credentials file not found: {CLIENT_SECRETS_FILE}. Please ensure credentials.json is in the backend directory."
            )
        
        flow = Flow.from_client_secrets_file(
            CLIENT_SECRETS_FILE,
            scopes=SCOPES,
            redirect_uri=redirect_uri
        )
    return flow


def get_authorization_url(state: str = None) -> tuple[str, str]:
    """
    Generate Google OAuth authorization URL
    Returns: (authorization_url, state)
    """
    try:
        flow = get_oauth_flow()
        authorization_url, returned_state = flow.authorization_url(
            access_type='offline',
            include_granted_scopes='true',
            prompt='consent',  # Force consent to get refresh token
            state=state
        )
        return authorization_url, returned_state
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to generate authorization URL: {str(e)}"
        )


def exchange_code_for_tokens(code: str, redirect_uri: str = None) -> Dict:
    """
    Exchange authorization code for access and refresh tokens
    """
    try:
        flow = get_oauth_flow(redirect_uri)
        flow.fetch_token(code=code)
        credentials = flow.credentials
        
        return {
            'token': credentials.token,
            'refresh_token': credentials.refresh_token,
            'token_uri': credentials.token_uri,
            'client_id': credentials.client_id,
            'client_secret': credentials.client_secret,
            'scopes': credentials.scopes,
            'expiry': credentials.expiry.isoformat() if credentials.expiry else None
        }
    except Exception as e:
        raise HTTPException(
            status_code=400,
            detail=f"Failed to exchange code for tokens: {str(e)}"
        )


def save_user_tokens(user_id: str, tokens: Dict, db) -> bool:
    """
    Save or update OAuth tokens for a user in MongoDB
    """
    try:
        token_doc = {
            'user_id': user_id,
            'access_token': tokens['token'],
            'refresh_token': tokens.get('refresh_token'),
            'token_uri': tokens.get('token_uri'),
            'client_id': tokens.get('client_id'),
            'client_secret': tokens.get('client_secret'),
            'scopes': tokens.get('scopes', []),
            'expiry': tokens.get('expiry'),
            'updated_at': datetime.utcnow().isoformat()
        }
        
        # Upsert token document
        db.google_oauth_tokens.update_one(
            {'user_id': user_id},
            {'$set': token_doc},
            upsert=True
        )
        
        return True
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to save tokens: {str(e)}"
        )


def get_user_credentials(user_id: str, db) -> Optional[Credentials]:
    """
    Get valid Google OAuth credentials for a user
    Automatically refreshes token if expired
    """
    try:
        token_doc = db.google_oauth_tokens.find_one({'user_id': user_id})
        if not token_doc:
            return None
        
        # Reconstruct credentials
        credentials = Credentials(
            token=token_doc.get('access_token'),
            refresh_token=token_doc.get('refresh_token'),
            token_uri=token_doc.get('token_uri', 'https://oauth2.googleapis.com/token'),
            client_id=token_doc.get('client_id'),
            client_secret=token_doc.get('client_secret'),
            scopes=token_doc.get('scopes', SCOPES)
        )
        
        # Check if token is expired and refresh if needed
        if credentials.expired and credentials.refresh_token:
            try:
                credentials.refresh(Request())
                # Save refreshed token
                save_user_tokens(user_id, {
                    'token': credentials.token,
                    'refresh_token': credentials.refresh_token,
                    'token_uri': credentials.token_uri,
                    'client_id': credentials.client_id,
                    'client_secret': credentials.client_secret,
                    'scopes': credentials.scopes,
                    'expiry': credentials.expiry.isoformat() if credentials.expiry else None
                }, db)
            except RefreshError as e:
                # Token refresh failed, user needs to re-authenticate
                db.google_oauth_tokens.delete_one({'user_id': user_id})
                raise HTTPException(
                    status_code=401,
                    detail="Google OAuth token expired and refresh failed. Please re-authenticate."
                )
        
        return credentials
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to get user credentials: {str(e)}"
        )


def revoke_user_tokens(user_id: str, db) -> bool:
    """
    Revoke and delete OAuth tokens for a user
    """
    try:
        token_doc = db.google_oauth_tokens.find_one({'user_id': user_id})
        if token_doc and token_doc.get('access_token'):
            try:
                credentials = Credentials(token=token_doc['access_token'])
                credentials.revoke(Request())
            except:
                pass  # Continue even if revoke fails
        
        db.google_oauth_tokens.delete_one({'user_id': user_id})
        return True
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to revoke tokens: {str(e)}"
        )


def is_user_authenticated(user_id: str, db) -> bool:
    """
    Check if user has valid Google OAuth tokens
    """
    try:
        credentials = get_user_credentials(user_id, db)
        return credentials is not None
    except:
        return False

