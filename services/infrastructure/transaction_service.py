from datetime import datetime, timezone
from bson import ObjectId
from typing import List, Dict, Optional, Any
from fastapi import HTTPException, BackgroundTasks
from pymongo.errors import PyMongoError
from core.logging_service import logger

class TransactionService:
    """
    Centralized service for handling critical database transactions (Async).
    """

    @staticmethod
    async def terminate_interview_safe(
        interview_id: str,
        reason: str,
        final_score: float,
        scores: List[Dict],
        db
    ) -> Dict:
        """Atomically terminate an interview (Async)"""
        try:
            now_iso = datetime.now(timezone.utc).isoformat()
            
            result = await db.interviews.find_one_and_update(
                {
                    "_id": ObjectId(interview_id),
                    "is_completed": {"$ne": True}
                },
                {
                    "$set": {
                        "is_completed": True,
                        "status": "completed",
                        "termination_reason": reason,
                        "terminated_at": now_iso,
                        "avg_score": final_score,
                        "final_score": final_score,
                        "scores": scores,
                        "completed_at": now_iso
                    }
                },
                return_document=True
            )

            if not result:
                existing = await db.interviews.find_one({"_id": ObjectId(interview_id)})
                if not existing:
                    raise HTTPException(status_code=404, detail="Interview not found")
                
                if existing.get("is_completed"):
                    return {
                        "success": True,
                        "message": "Interview already completed",
                        "final_score": existing.get("avg_score", 0),
                        "status": "completed"
                    }
                raise HTTPException(status_code=409, detail="Conflict during termination")

            try:
                from core.logging_service import log_audit_event_async
                await log_audit_event_async(
                    db=db,
                    user_id=result.get("candidate_id") or "system",
                    action="terminate_interview",
                    entity_type="interview",
                    entity_id=interview_id,
                    details={"reason": reason, "score": final_score}
                )
            except Exception as e:
                logger.error(f"Audit failed: {e}")

            return {
                "success": True,
                "message": "Interview terminated",
                "final_score": final_score,
                "status": "completed"
            }
        except PyMongoError as e:
            logger.error(f"DB Error: {e}")
            raise HTTPException(status_code=500, detail="DB Error")
        except Exception as e:
            if isinstance(e, HTTPException): raise e
            raise HTTPException(status_code=500, detail=str(e))

    @staticmethod
    async def bulk_create_safe(
        interview_docs: List[Dict],
        email_tasks: List[Dict],
        db
    ) -> Dict:
        """Bulk create interviews and queue emails (Async)"""
        if not interview_docs:
            return {"db_success": True, "inserted_ids": []}

        try:
            result = await db.interviews.insert_many(interview_docs, ordered=False)
            inserted_ids = result.inserted_ids
        except PyMongoError as e:
            logger.error(f"Bulk insert error: {e}")
            raise HTTPException(status_code=500, detail="Bulk creation failed")

        # Handle emails asynchronously via background task or helper
        from services.email.email_async import send_bulk_emails_parallel
        try:
            # We don't await this if we want it to be truly background, 
            # but since TransactionService should be "safe", we might want to track it.
            # For now, let's keep it in bulk_create_interviews route.
            pass
        except Exception: pass

        return {
            "db_success": True,
            "inserted_ids": [str(nid) for nid in inserted_ids]
        }

    @staticmethod
    async def update_application_status_safe(
        application_id: str,
        update_data: Any,
        current_user: Any,
        db: Any,
        background_tasks: Optional[BackgroundTasks] = None
    ) -> Dict:
        """Atomically update application status and trigger side effects (Async)"""
        try:
            new_status = update_data.status
            now_iso = datetime.now(timezone.utc).isoformat()
            
            # Update application
            result = await db.applications.find_one_and_update(
                {"_id": ObjectId(application_id)},
                {"$set": {
                    "status": new_status,
                    "updated_at": now_iso
                }},
                return_document=True
            )
            
            if not result:
                raise HTTPException(status_code=404, detail="Application not found")
            
            # Audit log
            from core.logging_service import log_audit_event
            await log_audit_event(
                db=db,
                user_id=current_user.id,
                action="update_application_status",
                entity_type="application",
                entity_id=application_id,
                details={"new_status": new_status}
            )
            
            # Trigger evaluation email (Optimized with background tasks)
            from services.automation.job_automation import send_evaluation_emails_on_status_update
            
            send_email_flag = getattr(update_data, "send_email", True)
            
            if background_tasks:
                background_tasks.add_task(
                    send_evaluation_emails_on_status_update,
                    application_id=application_id,
                    new_status=new_status,
                    db=db,
                    current_user=current_user,
                    send_email=send_email_flag
                )
            else:
                await send_evaluation_emails_on_status_update(
                    application_id=application_id,
                    new_status=new_status,
                    db=db,
                    current_user=current_user,
                    send_email=send_email_flag
                )
            
            return {
                "success": True,
                "message": f"Status updated to {new_status}",
                "status": new_status
            }
        except Exception as e:
            logger.error(f"Failed to update status: {e}")
            if isinstance(e, HTTPException): raise e
            raise HTTPException(status_code=500, detail=str(e))
