"""
Notification Manager
Centralized manager for handling multi-channel notifications (In-App, Email, Push)
"""
from datetime import datetime, timezone
from typing import Optional, Dict, Any, List
from bson import ObjectId
from utils import logger
from services.email.email_service import send_templated_email
from .notification_service import insert_notification_db  # Low-level insert
import asyncio

class NotificationManager:
    def __init__(self, db):
        self.db = db

    async def send(
        self,
        user_id: str,
        type: str,  # 'application', 'interview', 'system', 'job'
        title: str,
        message: str,
        channels: List[str] = ['in_app'],  # ['in_app', 'email']
        link: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
        email_template: Optional[str] = None,
        email_variables: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """
        Send a notification through multiple channels based on user preferences.
        """
        results = {}
        
        # 1. Check User Preferences (Async)
        user_prefs = await self.get_user_preferences(user_id)
        
        # Determine effective channels based on prefs
        email_enabled = user_prefs.get('email_enabled', True)
        in_app_enabled = user_prefs.get('in_app_enabled', True)
        categories = user_prefs.get('categories', {})
        
        # Check category specific preference
        type_category_map = {
            'application': 'applications',
            'interview': 'interviews',
            'job': 'job_updates',
            'system': 'system',
            'success': 'system',
            'error': 'system'
        }
        category = type_category_map.get(type, 'system')
        category_allowed = categories.get(category, True)
        
        if not category_allowed:
            logger.info(f"Notification suppressed due to category preference: {category}")
            return {'status': 'suppressed', 'reason': f'Category {category} disabled'}

        # 2. In-App Notification (Awaited)
        if 'in_app' in channels and in_app_enabled:
            try:
                notif_id = await insert_notification_db(
                    self.db,
                    user_id=user_id,
                    title=title,
                    message=message,
                    notification_type=self._map_type_to_ui_type(type),
                    link=link,
                    metadata=metadata
                )
                results['in_app'] = {'success': True, 'id': notif_id}
            except Exception as e:
                logger.error(f"In-App notification failed: {e}")
                results['in_app'] = {'success': False, 'error': str(e)}
        elif 'in_app' in channels and not in_app_enabled:
             results['in_app'] = {'success': False, 'status': 'suppressed', 'reason': 'User disabled in-app'}

        # 3. Email Notification (Awaited)
        if 'email' in channels and email_template and email_variables and email_enabled:
            try:
                # Fetch user email if not provided in variables
                user = await self.db.users.find_one({"_id": ObjectId(user_id)})
                if user and user.get('email'):
                    # ENHANCED: Use durable queue for 100% reliability
                    from services.email.email_service import enqueue_templated_email
                    await enqueue_templated_email(
                        db=self.db,
                        to_email=user['email'],
                        template_name=email_template,
                        variables=email_variables,
                        subject=title
                    )
                    results['email'] = {'success': True, 'status': 'queued'}
                else:
                    logger.warning(f"No email found for user {user_id}")
                    results['email'] = {'success': False, 'error': 'User email not found'}
            except Exception as e:
                logger.error(f"Email notification failed: {e}")
                results['email'] = {'success': False, 'error': str(e)}
        elif 'email' in channels and not email_enabled:
            results['email'] = {'success': False, 'status': 'suppressed', 'reason': 'User disabled email'}

        return results

    def _map_type_to_ui_type(self, type: str) -> str:
        mapping = {
            'application': 'info',
            'interview': 'warning',
            'job': 'info',
            'system': 'info',
            'success': 'success',
            'error': 'error'
        }
        return mapping.get(type, 'info')

    async def get_user_preferences(self, user_id: str) -> Dict:
        """
        Fetch user notification preferences from DB (Async)
        """
        try:
            user = await self.db.users.find_one({"_id": ObjectId(user_id)}, {"notification_preferences": 1})
            if user and "notification_preferences" in user:
                return user["notification_preferences"]
        except Exception as e:
            logger.error(f"Failed to fetch user prefs: {e}")
        
        # Defaults
        return {
            "email_enabled": True,
            "in_app_enabled": True,
            "categories": {
                "applications": True,
                "interviews": True,
                "job_updates": True,
                "system": True
            }
        }
