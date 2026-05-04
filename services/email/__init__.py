"""
Email Services Package
Exports email-related services
"""
from .email_service import (
    send_email_verification_email,
    send_password_reset_email,
    send_password_changed_email,
    send_interview_invitation_email,
    send_application_submitted_email,
    send_cheating_warning_email,
    send_cheating_disqualification_email,
    send_result_selected_email,
    send_result_rejected_email,
    send_reclaim_approved_email,
    send_reclaim_rejected_email,
    send_status_update_email,
    send_templated_email,
    render_template,
    log_email,
    enqueue_templated_email,
    enqueue_email
)
from .email_logger import get_email_logger
from .email_worker import email_worker
from .gmail_utils import send_email_via_gmail, GmailAPIError

__all__ = [
    'send_email_verification_email',
    'send_password_reset_email',
    'send_password_changed_email',
    'send_interview_invitation_email',
    'send_application_submitted_email',
    'send_cheating_warning_email',
    'send_cheating_disqualification_email',
    'send_result_selected_email',
    'send_result_rejected_email',
    'send_reclaim_approved_email',
    'send_reclaim_rejected_email',
    'send_status_update_email',
    'send_templated_email',
    'render_template',
    'log_email',
    'enqueue_templated_email',
    'enqueue_email',
    'get_email_logger',
    'email_worker',
    'send_email_via_gmail',
    'GmailAPIError'
]
