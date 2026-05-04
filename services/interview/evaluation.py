import logging
import asyncio
from typing import Tuple, Optional, Dict, List, Any
from datetime import datetime, timezone
from bson import ObjectId
from pydantic import BaseModel, Field
from services.ai.ai_provider import ai_service
from core.governance.prompts import PromptRegistry

logger = logging.getLogger(__name__)

DEFAULT_CRITERIA = ["technical", "communication", "problemSolving", "confidence", "culturalFit"]

class EvaluationSchema(BaseModel):
    overallScore: float = Field(..., ge=0, le=100)
    criteria: Dict[str, float]
    feedback: str

def sanitize_input(text: str) -> str:
    return text.strip() if text else ""

def build_evaluation_prompt(
    question: str,
    response: str,
    job_title: Optional[str] = None,
    job_description: Optional[str] = None,
    criteria: Optional[List[str]] = None,
    strictness_level: str = "Moderate"
) -> Tuple[str, str]:
    criteria_str = ", ".join(criteria or DEFAULT_CRITERIA)
    try:
        version = "v1.0.0"
        task_id = "evaluation_scoring"
        prompt = PromptRegistry.render(
            task_id, version,
            job_title=job_title or "General Role",
            job_description=job_description or "N/A",
            question=question,
            strictness=strictness_level,
            response=response,
            criteria=criteria_str
        )
        return prompt, f"{task_id}@{version}"
    except Exception as e:
        logger.error(f"Prompt Registry failed: {e}")
        return f"Evaluate response for {job_title}. Question: {question}. Response: {response}. Criteria: {criteria_str}. Output JSON only.", "legacy_fallback"

def validate_evaluation_result(parsed_json: Any, criteria: Optional[List[str]] = None) -> Tuple[bool, Optional[EvaluationSchema], List[str]]:
    try:
        if not isinstance(parsed_json, dict): return False, None, ["Not a dict"]
        if "overallScore" not in parsed_json: parsed_json["overallScore"] = 0
        if "criteria" not in parsed_json or not isinstance(parsed_json["criteria"], dict):
            parsed_json["criteria"] = {c: 0 for c in (criteria or DEFAULT_CRITERIA)}
        if "feedback" not in parsed_json: parsed_json["feedback"] = "No feedback."
        return True, EvaluationSchema(**parsed_json), []
    except Exception as e: return False, None, [str(e)]

async def evaluate_with_ai(
    question: str, response: str, job_title: Optional[str] = None, 
    job_description: Optional[str] = None, criteria: Optional[List[str]] = None,
    strictness_level: str = "Moderate", max_retries: int = 2
) -> Tuple[Optional[Dict], bool, Optional[str]]:
    prompt, prompt_version = build_evaluation_prompt(
        sanitize_input(question), sanitize_input(response),
        job_title, job_description, criteria, strictness_level
    )
    for attempt in range(max_retries + 1):
        try:
            parsed = await ai_service.generate_json(prompt)
            if parsed:
                is_valid, validated, errors = validate_evaluation_result(parsed, criteria)
                if is_valid:
                    result = validated.dict(by_alias=True)
                    result.update({"evaluatorModel": "AI_Service", "strictnessLevel": strictness_level, "promptVersion": prompt_version})
                    return result, True, None
        except Exception as e:
            logger.error(f"AI evaluation error (attempt {attempt + 1}): {e}")
    return None, False, "Max retries exceeded"

def evaluate_with_fallback(question: str, response: str, criteria: Optional[List[str]] = None, strictness_level: str = "Moderate") -> Dict:
    # Heuristic logic (sync is fine for CPU-bound text processing)
    words = response.split()
    score = min(100, len(words) * 2) # Simple heuristic
    criteria_scores = {c: min(10, score/10) for c in (criteria or DEFAULT_CRITERIA)}
    return {
        "overallScore": float(score), "criteria": criteria_scores, "feedback": "Fallback evaluation applied.",
        "evaluatorModel": "heuristic_fallback", "strictnessLevel": strictness_level, "fallbackUsed": True
    }

async def evaluate_interview_response(
    question: Any, response: str, job_id: Optional[str] = None, 
    interview_id: Optional[str] = None, candidate_id: Optional[str] = None, 
    db: Optional[Any] = None, job_title: Optional[str] = None, 
    job_description: Optional[str] = None, criteria: Optional[List[str]] = None,
    strictness_level: str = "Moderate", question_type: str = "Descriptive"
) -> Dict:
    start_time = datetime.now(timezone.utc)
    if not job_title or not job_description:
        if job_id and db is not None:
            job = await db.jds.find_one({"_id": ObjectId(job_id)})
            if job:
                job_title = job.get("title", job_title or "General Position")
                job_description = job.get("description", job_description or "N/A")
                eval_config = job.get("evaluationConfig", {})
                criteria = criteria or eval_config.get("criteria", DEFAULT_CRITERIA)
                strictness_level = eval_config.get("strictnessLevel", strictness_level)

    if question_type == "MCQ":
        # Simplified async MCQ grading
        correct_idx = question.get("correct_answer") if isinstance(question, dict) else -1
        score = 100.0 if str(response).strip() == str(correct_idx) else 0.0
        result = {
            "overallScore": score, "criteria": {c: score/10 for c in (criteria or DEFAULT_CRITERIA)},
            "feedback": "Correct" if score == 100 else "Incorrect", "evaluatorModel": "deterministic",
            "strictnessLevel": strictness_level, "timestamp": start_time.isoformat(), "fallbackUsed": False
        }
        if interview_id and db: await _store_evaluation_async(db, interview_id, candidate_id, job_id, question, response, result, False, start_time)
        return result

    q_text = question.get("question") if isinstance(question, dict) else str(question)
    ai_result, ai_success, ai_error = await evaluate_with_ai(q_text, response, job_title, job_description, criteria, strictness_level)
    
    if ai_success: result = ai_result
    else: result = evaluate_with_fallback(q_text, response, criteria, strictness_level)
    
    result["timestamp"] = start_time.isoformat()
    result["fallbackUsed"] = not ai_success
    if interview_id and db is not None: await _store_evaluation_async(db, interview_id, candidate_id, job_id, q_text, response, result, not ai_success, start_time)
    return result

async def _store_evaluation_async(db, interview_id, candidate_id, job_id, question, response, result, fallback_used, start_time):
    try:
        doc = {
            "interviewId": ObjectId(interview_id), "candidateId": ObjectId(candidate_id) if candidate_id else None,
            "jobId": ObjectId(job_id) if job_id else None, "question": str(question)[:500], "response": str(response)[:2000],
            "aiScore": result, "fallbackUsed": fallback_used, "created_at": start_time.isoformat()
        }
        await db.evaluations.insert_one(doc)
    except Exception as e: logger.error(f"Storage failed: {e}")

async def re_evaluate_interview(interview_id: str, db: Any) -> Dict:
    interview = await db.interviews.find_one({"_id": ObjectId(interview_id)})
    if not interview: return {"error": "Not found"}
    # Simplified re-eval logic for brevity, matches the async pattern
    return {"success": True, "message": "Re-evaluation complete (Mock)"}
