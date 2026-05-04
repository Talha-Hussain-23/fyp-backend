"""
Sectioned Interview Generation (Async)
Generates interview with independent sections for each question type
"""
import secrets
from datetime import datetime, timezone
from bson import ObjectId
from core.logging_service import logger


async def prepare_sectioned_interview_doc(jd: dict, resume: dict) -> dict:
    """
    Prepare a sectioned interview document (Async)
    Does NOT insert into database.
    """
    jd_id = str(jd["_id"])
    resume_id = str(resume["_id"])
    
    interview_config = jd.get("interview_config")
    if not interview_config:
        return await prepare_legacy_interview_doc(jd, resume)
    
    logger.info(f"🎯 Preparing sectioned interview doc for JD {jd_id}, Resume {resume_id}")
    
    sections = []
    all_questions = []
    section_configs = interview_config.get("sections", [])
    
    question_id_counter = 0
    for s_idx, section_config in enumerate(section_configs):
        if not section_config.get("enabled", True):
            continue
        
        section_type = section_config["type"]
        num_questions = section_config["num_questions"]
        difficulty = section_config.get("difficulty", "Moderate")
        
        from services.interview.questions import generate_questions
        job_title = jd.get("title", "Position")
        questions_data = await generate_questions(
            jd=jd["description"],
            resume_text=resume["text"],
            num_questions=num_questions,
            difficulty_level=difficulty,
            question_type=section_type,
            ai_instructions=jd.get("ai_instructions"),
            language=section_config.get("language"),
            job_title=job_title
        )
        
        formatted_section_questions = []
        for q in questions_data:
            q_obj = q if isinstance(q, dict) else {"question": q}
            q_obj.update({
                "section_index": s_idx,
                "type": section_type,
                "id": question_id_counter
            })
            formatted_section_questions.append(q_obj)
            all_questions.append(q_obj)
            question_id_counter += 1
            
        section = {
            "type": section_type,
            "enabled": True,
            "status": "not_started",
            "current_question_index": 0,
            "num_questions": num_questions,
            "weight": section_config["weight"],
            "difficulty": difficulty,
            "time_per_question": section_config["time_per_question"],
            "questions": formatted_section_questions,
            "responses": [],
            "scores": [],
            "section_score": 0.0,
            "completion_percentage": 0,
            "time_spent": 0,
            "started_at": None,
            "completed_at": None,
            "language": section_config.get("language")
        }
        sections.append(section)
    
    return {
        "jd_id": jd_id,
        "resume_id": resume_id,
        "interview_token": secrets.token_urlsafe(32),
        "questions": all_questions, 
        "num_questions": len(all_questions),
        "question_type": "Mixed" if len(sections) > 1 else (sections[0]["type"] if sections else "Descriptive"),
        "sections": sections,
        "current_section_index": 0,
        "overall_status": "not_started",
        "overall_score": 0.0,
        "responses": [],
        "scores": [],
        "is_completed": False,
        "is_terminated": False,
        "total_strikes": 0,
        "proctoring_warning_count": 0,
        "proctoring_violations": [],
        "created_at": datetime.now(timezone.utc).isoformat(),
        "started_at": None,
        "completed_at": None,
        "state": "CREATED",  # Standardize on CREATED for orchestrator compatibility
        "status": "CREATED",
        "interview_config": interview_config
    }


async def create_sectioned_interview(jd_id: str, resume_id: str, db):
    """Create and insert a sectioned interview (Async)"""
    try:
        jd = await db.jds.find_one({"_id": ObjectId(jd_id)})
        resume = await db.resumes.find_one({"_id": ObjectId(resume_id)})
    except Exception as e:
        logger.error(f"Error fetching JD or resume: {e}")
        raise
    
    if not jd or not resume:
        raise ValueError("JD or Resume not found")
        
    interview_doc = await prepare_sectioned_interview_doc(jd, resume)
    result = await db.interviews.insert_one(interview_doc)
    return str(result.inserted_id)


async def prepare_legacy_interview_doc(jd: dict, resume: dict) -> dict:
    """Prepare a legacy format interview document (Async)"""
    from services.interview.questions import generate_questions
    from core.models import create_interview_document
    
    num_questions = jd.get("num_questions", 5)
    difficulty = jd.get("difficulty_level", "Moderate")
    question_type = jd.get("question_type", "Descriptive")
    
    questions = await generate_questions(
        jd=jd["description"],
        resume_text=resume["text"],
        num_questions=num_questions,
        difficulty_level=difficulty,
        question_type=question_type,
        ai_instructions=jd.get("ai_instructions"),
        job_title=jd.get("title", "Position")
    )
    
    return create_interview_document(
        jd_id=str(jd["_id"]),
        resume_id=str(resume["_id"]),
        questions=questions,
        interview_token=secrets.token_urlsafe(32),
        started_at=datetime.now(timezone.utc).isoformat(),
        num_questions=num_questions,
        difficulty_level=difficulty,
        question_type=question_type
    )


async def create_legacy_interview(jd_id: str, resume_id: str, jd: dict, resume: dict, db):
    """Create and insert legacy interview (Async)"""
    interview_doc = await prepare_legacy_interview_doc(jd, resume)
    result = await db.interviews.insert_one(interview_doc)
    return str(result.inserted_id)
