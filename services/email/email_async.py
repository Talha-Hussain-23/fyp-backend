"""
High-Performance Async Email Service
Optimized for speed with parallel processing and async operations
"""

import asyncio
from typing import Dict, List, Optional
from concurrent.futures import ThreadPoolExecutor
from services.email.email_logger import get_email_logger
from .email_service import send_interview_invitation_email
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type
from fastapi import HTTPException
import logging

logger = logging.getLogger(__name__)

async def send_email_async(
    to_email: str,
    candidate_name: str,
    job_title: str,
    interview_id: str,
    interview_token: str,
    recruiter_name: str,
    company_name: str,
    user_id: str,
    db
) -> Dict:
    """
    Send invitation email (Async Queueing)
    """
    # Simply await the async service function
    # It enqueues the email task which is a fast DB operation
    task_id = await send_interview_invitation_email(
        to_email,
        candidate_name,
        job_title,
        interview_id,
        interview_token,
        recruiter_name,
        company_name,
        db
    )
    
    return {"log_id": task_id, "success": task_id is not None}


async def send_bulk_emails_parallel(
    email_tasks: List[Dict],
    db,
    max_concurrent: int = 10
) -> Dict:
    """
    Send multiple emails in parallel with concurrency control
    
    Args:
        email_tasks: List of email task dictionaries
        db: Database connection
        max_concurrent: Maximum concurrent email sends
        
    Returns:
        Statistics about email sending
    """
    email_logger = get_email_logger(db)
    
    async def send_single_email(task: Dict) -> Dict:
        """Send single email with error handling"""
        try:
            # Log attempt (Await needed)
            await email_logger.log_attempt(
                interview_id=task['interview_id'],
                candidate_email=task['to_email'],
                email_type='interview_invitation',
                status='attempting',
                metadata={
                    'job_title': task['job_title'],
                    'recruiter_name': task['recruiter_name']
                }
            )
            
            # Send email with retry
            result = await send_email_async(
                to_email=task['to_email'],
                candidate_name=task['candidate_name'],
                job_title=task['job_title'],
                interview_id=task['interview_id'],
                interview_token=task['interview_token'],
                recruiter_name=task['recruiter_name'],
                company_name=task['company_name'],
                user_id=task['user_id'],
                db=db
            )
            
            # Log success (Await needed)
            await email_logger.log_success(
                interview_id=task['interview_id'],
                candidate_email=task['to_email'],
                email_type='interview_invitation',
                message_id=result.get('log_id'),
                metadata={'result': result}
            )
            
            return {
                'interview_id': task['interview_id'],
                'email': task['to_email'],
                'status': 'success',
                'result': result
            }
            
        except Exception as e:
            # Log failure (Await needed)
            await email_logger.log_failure(
                interview_id=task['interview_id'],
                candidate_email=task['to_email'],
                email_type='interview_invitation',
                error=str(e),
                attempt_number=1,
                metadata={'job_title': task['job_title']}
            )
            
            return {
                'interview_id': task['interview_id'],
                'email': task['to_email'],
                'status': 'failed',
                'error': str(e)
            }
    
    # Create semaphore for concurrency control
    semaphore = asyncio.Semaphore(max_concurrent)
    
    async def send_with_semaphore(task: Dict) -> Dict:
        """Send email with semaphore control"""
        async with semaphore:
            return await send_single_email(task)
    
    # Send all emails in parallel
    results = await asyncio.gather(
        *[send_with_semaphore(task) for task in email_tasks],
        return_exceptions=True
    )
    
    # Calculate statistics
    success_count = sum(1 for r in results if isinstance(r, dict) and r.get('status') == 'success')
    failure_count = len(results) - success_count
    
    return {
        'total': len(results),
        'success': success_count,
        'failed': failure_count,
        'results': [r for r in results if isinstance(r, dict)]
    }


def send_emails_in_background(email_tasks: List[Dict], db):
    """
    Send emails in background without blocking
    Returns immediately, emails sent asynchronously
    """
    async def _send_async():
        return await send_bulk_emails_parallel(email_tasks, db)
    
    # Create new event loop for background task
    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            # If loop is running, create task
            asyncio.create_task(_send_async())
        else:
            # If no loop, run in new loop
            asyncio.run(_send_async())
    except RuntimeError:
        # Create new loop if needed
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        loop.run_until_complete(_send_async())
        loop.close()
