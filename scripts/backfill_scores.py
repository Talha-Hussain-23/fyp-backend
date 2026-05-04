import asyncio
import structlog
from motor.motor_asyncio import AsyncIOMotorClient
from core.config import settings

logger = structlog.get_logger(__name__)

async def sync_all_interviews():
    client = AsyncIOMotorClient(settings.MONGODB_URI)
    db = client[settings.DATABASE_NAME]
    
    interviews = await db.interviews.find({"status": "completed"}).to_list(None)
    logger.info("backfill_started", count=len(interviews))
    
    updated = 0
    for iv in interviews:
        app_query = {"job_id": str(iv["jd_id"]), "resume_id": str(iv["resume_id"])}
        application = await db.applications.find_one(app_query)
        if application:
            score = (iv.get("final_score") or 0) * 10
            await db.applications.update_one(
                {"_id": application["_id"]},
                {"$set": {
                    "interview_id": str(iv["_id"]),
                    "interview_score": score
                }}
            )
            updated += 1
            
    logger.info("backfill_complete", synced=updated)

if __name__ == "__main__":
    asyncio.run(sync_all_interviews())
