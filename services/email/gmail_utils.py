"""
Gmail API Integration
Sends emails using Gmail API instead of SMTP
Uses credentials.json directly for authentication
"""

import os
import sys
import base64
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from typing import Optional, Dict
from fastapi import HTTPException
from googleapiclient.discovery import build
from core.logging_service import logger

# Ensure current directory is in path for imports
_current_dir = os.path.dirname(os.path.abspath(__file__))
if _current_dir not in sys.path:
    sys.path.insert(0, _current_dir)


class GmailAPIError(HTTPException):
    """Custom exception for Gmail API errors"""
    def __init__(self, detail: str, status_code: int = 500):
        super().__init__(status_code=status_code, detail=detail)


def create_message(sender: str, to: str, subject: str, html_content: str, text_content: str = None, reply_to: str = None) -> Dict:
    """
    Create a message for Gmail API
    """
    message = MIMEMultipart('alternative')
    message['to'] = to
    message['from'] = sender
    message['subject'] = subject
    
    if reply_to:
        message['Reply-To'] = reply_to
    
    # Add text part if provided
    if text_content:
        text_part = MIMEText(text_content, 'plain')
        message.attach(text_part)
    
    # Add HTML part
    html_part = MIMEText(html_content, 'html')
    message.attach(html_part)
    
    # Encode message
    raw_message = base64.urlsafe_b64encode(message.as_bytes()).decode('utf-8')
    return {'raw': raw_message}


def send_email_via_gmail(
    to_email: str = None,
    subject: str = None,
    html_content: str = None,
    text_content: str = None,
    sender_email: str = None,
    reply_to: str = None,
    user_id: str = None,
    db = None
) -> Dict:
    """
    Send email using Gmail API
    Now uses credentials.json directly instead of requiring user OAuth
    """
    if not to_email or not subject or not html_content:
        raise HTTPException(
            status_code=400,
            detail="to_email, subject, and html_content are required"
        )
    
    try:
        # Use credentials from credentials.json file
        from core.credentials_manager import get_gmail_credentials
        credentials = get_gmail_credentials()
        
        # Build Gmail service
        service = build('gmail', 'v1', credentials=credentials)
        
        # Get sender email - use environment variable OR default
        if not sender_email:
            sender_email = os.getenv("GMAIL_USER", "mtalhahussain23@gmail.com")
            logger.info(f"✅ Using sender email: {sender_email}")
        
        # Create message
        message = create_message(sender_email, to_email, subject, html_content, text_content, reply_to)
        
        # Send message
        sent_message = service.users().messages().send(
            userId='me',
            body=message
        ).execute()
        
        return {
            'success': True,
            'message_id': sent_message.get('id'),
            'thread_id': sent_message.get('threadId'),
            'to': to_email,
            'from': sender_email
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to send email via Gmail API: {str(e)}"
        )


def send_interview_invitation_email_gmail(
    user_id: str,
    to_email: str,
    candidate_name: str,
    interview_datetime: str,
    interview_location: str,
    calendar_event_link: str = None,
    job_title: str = "Position",
    recruiter_name: str = None,
    db = None
) -> Dict:
    """
    Send interview invitation email via Gmail API with HTML template
    """
    html_content = f"""
    <!DOCTYPE html>
    <html>
        <head>
            <meta charset="UTF-8">
            <meta name="viewport" content="width=device-width, initial-scale=1.0">
            <title>Interview Invitation</title>
            <style>
                body {{
                    font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
                    line-height: 1.6;
                    color: #333;
                    background-color: #f5f5f5;
                    margin: 0;
                    padding: 0;
                }}
                .container {{
                    max-width: 600px;
                    margin: 20px auto;
                    background: white;
                    border-radius: 12px;
                    overflow: hidden;
                    box-shadow: 0 4px 20px rgba(0,0,0,0.1);
                }}
                .header {{
                    background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
                    color: white;
                    padding: 30px;
                    text-align: center;
                }}
                .content {{
                    padding: 40px;
                }}
                .button {{
                    background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
                    color: white;
                    padding: 15px 30px;
                    text-decoration: none;
                    border-radius: 8px;
                    display: inline-block;
                    font-weight: 600;
                    margin: 20px 0;
                }}
                .info-box {{
                    background: #f0f9ff;
                    padding: 20px;
                    border-left: 4px solid #3b82f6;
                    border-radius: 4px;
                    margin: 25px 0;
                }}
                .footer {{
                    background: #f8f9fa;
                    padding: 25px;
                    text-align: center;
                    font-size: 14px;
                    color: #6c757d;
                }}
            </style>
        </head>
        <body>
            <div class="container">
                <div class="header">
                    <h1>🎯 Interview Invitation</h1>
                    <p>You've been selected for an interview!</p>
                </div>
                
                <div class="content">
                    <h2>Hello {candidate_name},</h2>
                    
                    <p>Congratulations! We're excited to invite you for an interview for the <strong>{job_title}</strong> position.</p>
                    
                    <div class="info-box">
                        <h3 style="margin-top: 0;">📅 Interview Details</h3>
                        <p><strong>Date & Time:</strong> {interview_datetime}</p>
                        <p><strong>Location:</strong> {interview_location}</p>
                    </div>
                    
                    {f'<p style="text-align: center;"><a href="{calendar_event_link}" class="button">📅 Add to Calendar</a></p>' if calendar_event_link else ''}
                    
                    <p>Please confirm your attendance by replying to this email. If you need to reschedule, please let us know at least 24 hours in advance.</p>
                    
                    <p>We look forward to meeting you!</p>
                    
                    <p>Best regards,<br>
                    {recruiter_name or 'Recruitment Team'}</p>
                </div>
                
                <div class="footer">
                    <p>This is an automated invitation from the AI Resume Screener platform.</p>
                </div>
            </div>
        </body>
    </html>
    """
    
    text_content = f"""
    Interview Invitation
    
    Hello {candidate_name},
    
    Congratulations! We're excited to invite you for an interview for the {job_title} position.
    
    Interview Details:
    Date & Time: {interview_datetime}
    Location: {interview_location}
    
    Please confirm your attendance by replying to this email.
    
    Best regards,
    {recruiter_name or 'Recruitment Team'}
    """
    
    subject = f"🎯 Interview Invitation - {job_title}"
    
    return send_email_via_gmail(
        user_id=user_id,
        to_email=to_email,
        subject=subject,
        html_content=html_content,
        text_content=text_content,
        db=db
    )


def send_interview_reminder_email_gmail(
    user_id: str,
    to_email: str,
    candidate_name: str,
    interview_datetime: str,
    interview_location: str,
    reminder_type: str = "24h",  # "24h", "1h", "15m"
    db = None
) -> Dict:
    """
    Send interview reminder email via Gmail API
    """
    reminder_texts = {
        "24h": "24 hours",
        "1h": "1 hour",
        "15m": "15 minutes"
    }
    
    html_content = f"""
    <!DOCTYPE html>
    <html>
        <head>
            <meta charset="UTF-8">
            <style>
                body {{
                    font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
                    line-height: 1.6;
                    color: #333;
                    background-color: #f5f5f5;
                    margin: 0;
                    padding: 20px;
                }}
                .container {{
                    max-width: 600px;
                    margin: 0 auto;
                    background: white;
                    border-radius: 12px;
                    padding: 30px;
                    box-shadow: 0 4px 20px rgba(0,0,0,0.1);
                }}
                .reminder-box {{
                    background: #fff3cd;
                    padding: 20px;
                    border-left: 4px solid #ffc107;
                    border-radius: 4px;
                    margin: 20px 0;
                }}
            </style>
        </head>
        <body>
            <div class="container">
                <h2>⏰ Interview Reminder</h2>
                <p>Hello {candidate_name},</p>
                <p>This is a friendly reminder that you have an interview scheduled in <strong>{reminder_texts.get(reminder_type, reminder_type)}</strong>.</p>
                
                <div class="reminder-box">
                    <p><strong>Date & Time:</strong> {interview_datetime}</p>
                    <p><strong>Location:</strong> {interview_location}</p>
                </div>
                
                <p>We look forward to meeting you!</p>
            </div>
        </body>
    </html>
    """
    
    subject = f"⏰ Interview Reminder - {reminder_type} before your interview"
    
    return send_email_via_gmail(
        user_id=user_id,
        to_email=to_email,
        subject=subject,
        html_content=html_content,
        db=db
    )


def send_selection_notification_gmail(
    user_id: str,
    to_email: str,
    candidate_name: str,
    job_title: str,
    db = None
) -> Dict:
    """
    Send selection/rejection notification via Gmail API
    """
    html_content = f"""
    <!DOCTYPE html>
    <html>
        <head>
            <meta charset="UTF-8">
            <style>
                body {{
                    font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
                    line-height: 1.6;
                    color: #333;
                    background-color: #f5f5f5;
                    margin: 0;
                    padding: 20px;
                }}
                .container {{
                    max-width: 600px;
                    margin: 0 auto;
                    background: white;
                    border-radius: 12px;
                    padding: 30px;
                    box-shadow: 0 4px 20px rgba(0,0,0,0.1);
                }}
                .success-box {{
                    background: #d4edda;
                    padding: 20px;
                    border-left: 4px solid #28a745;
                    border-radius: 4px;
                    margin: 20px 0;
                }}
            </style>
        </head>
        <body>
            <div class="container">
                <h2>🎉 Congratulations!</h2>
                <p>Hello {candidate_name},</p>
                
                <div class="success-box">
                    <p>We're pleased to inform you that you have been selected for the <strong>{job_title}</strong> position!</p>
                </div>
                
                <p>Our team will be in touch with you shortly regarding the next steps.</p>
                
                <p>Congratulations once again!</p>
            </div>
        </body>
    </html>
    """
    
    subject = f"🎉 Selection Update - {job_title}"
    
    return send_email_via_gmail(
        user_id=user_id,
        to_email=to_email,
        subject=subject,
        html_content=html_content,
        db=db
    )


def test_email_connection(user_id: str = None, db=None):
    """
    Test Gmail API connection via Google OAuth
    Requires user_id and database connection to check OAuth status
    """
    try:
        if user_id is None or db is None:
            return {
                "status": "error",
                "message": "Gmail API requires Google OAuth authentication. Please connect your Google account first."
            }
        
        # Check if user has Google OAuth connected
        try:
            from core.google_oauth import is_user_authenticated
            if is_user_authenticated(user_id, db):
                return {
                    "status": "success",
                    "message": "Gmail API connection successful via Google OAuth!",
                    "method": "Gmail API"
                }
            else:
                return {
                    "status": "error",
                    "message": "Google OAuth not connected. Please connect your Google account to use Gmail API.",
                    "tip": "Navigate to Email & Notifications section and click 'Connect Google Account'"
                }
        except ImportError:
            return {
                "status": "error",
                "message": "Google OAuth modules not available. Please install required packages."
            }
    except Exception as e:
        return {"status": "error", "message": f"Connection check failed: {str(e)}"}

