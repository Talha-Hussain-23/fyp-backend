"""
Feedback Routes (Async)
Handle candidate feedback after interviews
"""
from fastapi import APIRouter, Depends, HTTPException, Body
from datetime import datetime
from bson import ObjectId
from utils import get_db, logger

router = APIRouter()

@router.post("/")
async def submit_feedback(
    body: dict = Body(...),
    db = Depends(get_db)
):
    """Submit candidate feedback after interview (Async)"""
    try:
        interview_id = body.get("interview_id")
        rating = body.get("rating")
        
        if not interview_id or not rating:
            raise HTTPException(status_code=400, detail="Interview ID and rating are required")
        
        if not isinstance(rating, (int, float)) or rating < 1 or rating > 5:
            raise HTTPException(status_code=400, detail="Valid rating (1-5) is required")
        
        if not ObjectId.is_valid(interview_id):
            raise HTTPException(status_code=400, detail="Invalid interview ID format")
        
        # Verify interview exists
        interview = await db.interviews.find_one({"_id": ObjectId(interview_id)})
        if not interview:
            raise HTTPException(status_code=404, detail="Interview not found")
        
        # Check if feedback already exists
        existing = await db.interview_feedback.find_one({"interview_id": interview_id})
        if existing:
            raise HTTPException(status_code=400, detail="Feedback already submitted")
        
        # Create feedback document
        feedback_doc = {
            "interview_id": interview_id,
            "rating": rating,
            "difficulty_rating": body.get("difficulty_rating"),
            "experience_rating": body.get("experience_rating"),
            "comments": body.get("comments", ""),
            "technical_issues": body.get("technical_issues", ""),
            "suggestions": body.get("suggestions", ""),
            "submitted_at": datetime.utcnow().isoformat()
        }
        
        result = await db.interview_feedback.insert_one(feedback_doc)
        logger.info(f"Feedback submitted for interview: {interview_id}")
        
        return {
            "success": True,
            "message": "Thank you for your feedback!",
            "feedback_id": str(result.inserted_id)
        }
    except HTTPException: raise
    except Exception as e:
        logger.error(f"Failed to submit feedback: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")

@router.get("/interview/{interview_id}")
async def get_interview_feedback(
    interview_id: str,
    db = Depends(get_db)
):
    """Get feedback for a specific interview (Async)"""
    try:
        feedback = await db.interview_feedback.find_one({"interview_id": interview_id})
        if not feedback:
            return {"has_feedback": False}
        
        feedback["_id"] = str(feedback["_id"])
        feedback["has_feedback"] = True
        return feedback
    except Exception as e:
        logger.error(f"Failed to get feedback: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")

@router.get("/stats")
async def get_feedback_stats(
    db = Depends(get_db)
):
    """Get aggregated feedback statistics (Async)"""
    try:
        # Use aggregation for better performance since it's now async
        pipeline = [
            {
                "$group": {
                    "_id": None,
                    "total": {"$sum": 1},
                    "avg_rating": {"$avg": "$rating"},
                    "avg_difficulty": {"$avg": "$difficulty_rating"},
                    "avg_experience": {"$avg": "$experience_rating"}
                }
            }
        ]
        stats_list = await db.interview_feedback.aggregate(pipeline).to_list(length=1)
        
        if not stats_list:
            return {"total_feedbacks": 0, "avg_rating": 0, "avg_difficulty": 0, "avg_experience": 0}
        
        s = stats_list[0]
        return {
            "total_feedbacks": s["total"],
            "avg_rating": round(s.get("avg_rating") or 0, 2),
            "avg_difficulty": round(s.get("avg_difficulty") or 0, 2),
            "avg_experience": round(s.get("avg_experience") or 0, 2)
        }
    except Exception as e:
        logger.error(f"Failed to get feedback stats: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")
