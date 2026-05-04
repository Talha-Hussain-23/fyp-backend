"""
Credentials Manager for Gmail API
Uses credentials.json directly without requiring recruiter OAuth
"""

import os
import json
from typing import Optional
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
from google_auth_oauthlib.flow import InstalledAppFlow
from google.oauth2 import service_account
from fastapi import HTTPException
import structlog

logger = structlog.get_logger()

# Gmail API scopes
SCOPES = ['https://www.googleapis.com/auth/gmail.send']

# Path to credentials file
_core_dir = os.path.dirname(os.path.abspath(__file__))
_backend_dir = os.path.dirname(_core_dir)
CREDENTIALS_FILE = os.getenv("GOOGLE_CREDENTIALS_FILE", os.path.join(_backend_dir, "credentials.json"))
TOKEN_FILE = os.path.join(_backend_dir, "token.json")


def get_credentials_from_file() -> Optional[Credentials]:
    """
    Get credentials from credentials.json file.
    Supports both OAuth 2.0 client credentials and service account.
    """
    creds_env = os.getenv("GOOGLE_CREDENTIALS_JSON")
    creds_data = None
    
    try:
        if creds_env:
            creds_data = json.loads(creds_env)
            logger.info("loaded_credentials_from_env")
        else:
            if not os.path.exists(CREDENTIALS_FILE):
                raise HTTPException(
                    status_code=500,
                    detail=f"Credentials file not found: {CREDENTIALS_FILE} and GOOGLE_CREDENTIALS_JSON not set. "
                           "Please ensure credentials are provided."
                )
            with open(CREDENTIALS_FILE, 'r') as f:
                creds_data = json.load(f)

        # ── Service Account ──────────────────────────────────
        if 'type' in creds_data and creds_data['type'] == 'service_account':
            try:
                credentials = service_account.Credentials.from_service_account_file(
                    CREDENTIALS_FILE,
                    scopes=SCOPES
                )
                logger.info("credentials_loaded", source="service_account", file=CREDENTIALS_FILE)
                return credentials
            except Exception as e:
                logger.error("service_account_load_failed", error=str(e))
                raise HTTPException(
                    status_code=500,
                    detail=f"Failed to load service account credentials: {str(e)}"
                )

        # ── OAuth 2.0 Client Credentials ─────────────────────
        oauth_config = None
        if 'installed' in creds_data:
            oauth_config = creds_data['installed']
        elif 'web' in creds_data:
            oauth_config = creds_data['web']

        if oauth_config:
            token_env = os.getenv("GOOGLE_TOKEN_JSON")
            if token_env:
                try:
                    logger.info("loading_oauth_token_from_env")
                    credentials = Credentials.from_authorized_user_info(json.loads(token_env), SCOPES)

                    if not credentials.valid:
                        logger.warning("credentials_not_valid", expired=credentials.expired)
                        if credentials.expired and credentials.refresh_token:
                            logger.info("refreshing_token")
                            credentials.refresh(Request())
                        else:
                            raise Exception("Credentials are not valid and cannot be refreshed.")
                    return credentials
                except HTTPException:
                    raise
                except Exception as e:
                    logger.error("token_load_from_env_failed", error=str(e))
            
            # Try to load existing token first
            token_files_to_check = [
                TOKEN_FILE,
                os.path.join(os.getcwd(), "token.json"),
                "token.json"
            ]

            token_file_found = None
            for token_file in token_files_to_check:
                if os.path.exists(token_file):
                    token_file_found = token_file
                    logger.debug("token_file_found", path=token_file)
                    break

            if token_file_found:
                try:
                    logger.info("loading_oauth_credentials", file=token_file_found)
                    credentials = Credentials.from_authorized_user_file(token_file_found, SCOPES)

                    if not credentials.valid:
                        logger.warning("credentials_not_valid", expired=credentials.expired)
                        if credentials.expired and credentials.refresh_token:
                            try:
                                logger.info("refreshing_token")
                                credentials.refresh(Request())
                                with open(TOKEN_FILE, 'w') as token:
                                    token.write(credentials.to_json())
                                logger.info("token_refreshed", saved_to=TOKEN_FILE)
                            except Exception as refresh_error:
                                logger.error("token_refresh_failed", error=str(refresh_error))
                                raise Exception(
                                    f"Token expired and refresh failed: {refresh_error}. "
                                    "Please re-run OAuth flow."
                                )
                        else:
                            logger.error("credentials_cannot_refresh", has_refresh_token=bool(credentials.refresh_token))
                            raise Exception(
                                "Credentials are not valid and cannot be refreshed. "
                                "Please re-run OAuth flow."
                            )
                    else:
                        logger.debug("credentials_valid")

                    logger.info("oauth_credentials_loaded", file=token_file_found)
                    return credentials
                except HTTPException:
                    raise
                except Exception as e:
                    logger.error("token_load_failed", file=token_file_found, error=str(e))
                    raise HTTPException(
                        status_code=500,
                        detail=f"Failed to load Gmail credentials: {str(e)}\n"
                               f"Token file: {token_file_found}\n"
                               "Please ensure token.json is valid or re-run OAuth flow."
                    )
            else:
                logger.warning("token_file_not_found", checked_paths=token_files_to_check)

            # No token.json — try refresh token from environment variable
            refresh_token = os.getenv("GMAIL_REFRESH_TOKEN")
            if refresh_token:
                try:
                    credentials = Credentials(
                        token=None,
                        refresh_token=refresh_token,
                        token_uri=oauth_config.get('token_uri', 'https://oauth2.googleapis.com/token'),
                        client_id=oauth_config.get('client_id'),
                        client_secret=oauth_config.get('client_secret'),
                        scopes=SCOPES
                    )
                    credentials.refresh(Request())
                    with open(TOKEN_FILE, 'w') as token:
                        token.write(credentials.to_json())
                    logger.info("oauth_credentials_from_env_loaded")
                    return credentials
                except Exception as e:
                    logger.error("env_refresh_token_failed", error=str(e))

            # Try embedded refresh_token in credentials.json
            if 'refresh_token' in creds_data:
                try:
                    credentials = Credentials(
                        token=None,
                        refresh_token=creds_data['refresh_token'],
                        token_uri=oauth_config.get('token_uri', 'https://oauth2.googleapis.com/token'),
                        client_id=oauth_config.get('client_id'),
                        client_secret=oauth_config.get('client_secret'),
                        scopes=SCOPES
                    )
                    credentials.refresh(Request())
                    with open(TOKEN_FILE, 'w') as token:
                        token.write(credentials.to_json())
                    logger.info("oauth_credentials_from_embedded_refresh_loaded")
                    return credentials
                except Exception as e:
                    logger.error("embedded_refresh_token_failed", error=str(e))

            # No token available
            logger.error(
                "no_token_available",
                token_path=TOKEN_FILE,
                token_exists=os.path.exists(TOKEN_FILE),
            )
            raise HTTPException(
                status_code=500,
                detail=f"OAuth client credentials file found but token.json is missing or invalid.\n"
                       f"Token file path: {TOKEN_FILE}\n"
                       "Please run the OAuth authorization flow once:\n"
                       "  python scripts/utils/setup_gmail_credentials.py\n"
                       "Or set GMAIL_REFRESH_TOKEN environment variable with a valid refresh token."
            )

        # Unknown format
        logger.error(
            "unknown_credentials_format",
            file=CREDENTIALS_FILE,
            keys=list(creds_data.keys())[:10],
        )
        raise HTTPException(
            status_code=500,
            detail="Unknown credentials file format. The credentials.json file should be either:\n"
                   "1. A service account JSON file (with 'type': 'service_account'), OR\n"
                   "2. An OAuth client credentials file (with 'installed' or 'web' keys)\n"
                   "   For OAuth credentials, you also need either:\n"
                   "   - A token.json file (run OAuth flow once), OR\n"
                   "   - GMAIL_REFRESH_TOKEN environment variable set"
        )

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to load credentials: {str(e)}"
        )


def get_gmail_credentials() -> Credentials:
    """
    Get valid Gmail API credentials.
    This is the main function to use for email sending.
    """
    credentials = get_credentials_from_file()

    if not credentials:
        raise HTTPException(
            status_code=500,
            detail="Failed to obtain Gmail API credentials"
        )

    return credentials
