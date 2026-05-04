"""
Database Performance Optimizer
Creates indexes and optimizes MongoDB queries for maximum speed
"""

from pymongo import IndexModel, ASCENDING, DESCENDING, TEXT
from pymongo.database import Database
import structlog

logger = structlog.get_logger(__name__)


async def create_performance_indexes(db: Database):
    """
    Create indexes for all collections to speed up queries
    Run this once on startup or manually
    """
    try:
        # Users collection indexes
        await db.users.create_indexes([
            IndexModel([("email", ASCENDING)], unique=True, name="email_unique"),
            IndexModel([("is_recruiter", ASCENDING)], name="is_recruiter_idx"),
            IndexModel([("created_at", DESCENDING)], name="created_at_idx")
        ])
        logger.info("✅ Created indexes for users collection")
        
        # JDs (Jobs) collection indexes
        await db.jds.create_indexes([
            IndexModel([("recruiter_id", ASCENDING)], name="recruiter_id_idx"),
            IndexModel([("status", ASCENDING)], name="status_idx"),
            IndexModel([("apply_deadline", ASCENDING)], name="deadline_idx"),
            IndexModel([("created_at", DESCENDING)], name="created_at_idx"),
            IndexModel([("title", TEXT), ("description", TEXT)], name="text_search_idx")
        ])
        logger.info("✅ Created indexes for jds collection")
        
        # Resumes collection indexes
        await db.resumes.create_indexes([
            IndexModel([("email", ASCENDING)], name="email_idx"),
            IndexModel([("candidate_name", ASCENDING)], name="candidate_name_idx"),
            IndexModel([("created_at", DESCENDING)], name="created_at_idx"),
            IndexModel([("text", TEXT)], name="text_search_idx")
        ])
        logger.info("✅ Created indexes for resumes collection")
        
        # Interviews collection indexes
        await db.interviews.create_indexes([
            IndexModel([("jd_id", ASCENDING)], name="jd_id_idx"),
            IndexModel([("resume_id", ASCENDING)], name="resume_id_idx"),
            IndexModel([("recruiter_id", ASCENDING)], name="recruiter_id_idx"),
            IndexModel([("interview_token", ASCENDING)], name="token_idx"),
            IndexModel([("email_status.sent", ASCENDING)], name="email_sent_idx"),
            IndexModel([("started_at", DESCENDING)], name="started_at_idx"),
            IndexModel([("completed_at", DESCENDING)], name="completed_at_idx"),
            IndexModel([("jd_id", ASCENDING), ("resume_id", ASCENDING)], 
                      unique=True, name="jd_resume_unique"),
            # New index for status-based filtering
            IndexModel([("status", ASCENDING)], name="status_idx")
        ])
        logger.info("✅ Created indexes for interviews collection")
        
        # Email audit log indexes
        await db.email_audit_log.create_indexes([
            IndexModel([("interview_id", ASCENDING)], name="interview_id_idx"),
            IndexModel([("candidate_email", ASCENDING)], name="candidate_email_idx"),
            IndexModel([("status", ASCENDING)], name="status_idx"),
            IndexModel([("created_at", DESCENDING)], name="created_at_idx"),
            IndexModel([("email_type", ASCENDING)], name="email_type_idx")
        ])
        logger.info("✅ Created indexes for email_audit_log collection")
        
        # Email failures indexes
        await db.email_failures.create_indexes([
            IndexModel([("interview_id", ASCENDING)], name="interview_id_idx"),
            IndexModel([("created_at", DESCENDING)], name="created_at_idx")
        ])
        logger.info("✅ Created indexes for email_failures collection")
        
        # Email queue indexes
        await db.email_queue.create_indexes([
            IndexModel([("status", ASCENDING)], name="status_idx"),
            IndexModel([("priority", ASCENDING)], name="priority_idx"),
            IndexModel([("created_at", ASCENDING)], name="created_at_idx")
        ])
        logger.info("✅ Created indexes for email_queue collection")
        
        # Applications collection indexes
        try:
            await db.applications.create_indexes([
                IndexModel([("job_id", ASCENDING)], name="job_id_idx"),
                IndexModel([("candidate_email", ASCENDING)], name="candidate_email_idx"),
                IndexModel([("status", ASCENDING)], name="status_idx"),
                IndexModel([("created_at", DESCENDING)], name="created_at_idx"),
                IndexModel([("job_id", ASCENDING), ("status", ASCENDING)], name="job_status_compound_idx")
            ])
            logger.info("✅ Created indexes for applications collection")
        except Exception:
            pass
        
        # Audit logs indexes
        await db.audit_logs.create_indexes([
            IndexModel([("target_id", ASCENDING)], name="target_id_idx"),
            IndexModel([("user_id", ASCENDING)], name="user_id_idx"),
            IndexModel([("action", ASCENDING)], name="action_idx"),
            IndexModel([("timestamp", DESCENDING)], name="timestamp_idx"),
            IndexModel([("target_id", ASCENDING), ("timestamp", DESCENDING)], name="target_history_idx")
        ])
        logger.info("✅ Created indexes for audit_logs collection")
        
        # Enhanced interviews compound index for dashboard
        await db.interviews.create_indexes([
            IndexModel([("jd_id", ASCENDING), ("status", ASCENDING)], name="jd_status_compound_idx"),
            IndexModel([("recruiter_id", ASCENDING), ("completed_at", DESCENDING)], name="recruiter_completed_idx")
        ])
        
        logger.info("🚀 All database indexes created successfully (Async)!")
        return True
        
    except Exception as e:
        logger.error(f"❌ Failed to create indexes: {e}")
        return False


async def optimize_database_connection(db: Database):
    """
    Optimize database connection settings
    """
    try:
        stats = await db.command("dbStats")
        logger.info(f"📊 Database size: {stats.get('dataSize', 0) / 1024 / 1024:.2f} MB")
        return True
    except Exception as e:
        logger.error(f"❌ Failed to optimize database: {e}")
        return False
