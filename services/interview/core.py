from services.ai.ai_provider import ai_service
from services.ai.ai_provider import ExternalServiceError
from fastapi import HTTPException
from pydantic import BaseModel
from typing import Optional, List, Dict, Any
import time
from bson import ObjectId
from datetime import datetime as dt, timezone
from services.interview.evaluation import evaluate_interview_response, evaluate_with_fallback
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type
from services.email.email_logger import get_email_logger
import logging
import asyncio
from core.governance.prompts import PromptRegistry
from services.infrastructure.quality_gate import quality_gate
from core.constants import InterviewState

logger = logging.getLogger(__name__)

class InterviewResponse(BaseModel):
    response: str
    timeout: Optional[bool] = False

# Question generation functions extracted to services/interview/questions.py
from services.interview.questions import generate_mixed_questions, get_template_questions, generate_questions


async def create_interviews(jd_id: str, n: int, num_questions: int, difficulty_level: str, question_type: str, current_user, db):
    """Create interview sessions (Async)"""
    import secrets
    
    if not current_user.is_recruiter:
        raise HTTPException(status_code=403, detail="Not a recruiter")
    
    jd = await db.jds.find_one({"_id": ObjectId(jd_id), "recruiter_id": current_user.id})
    if not jd:
        raise HTTPException(status_code=404, detail="JD not found")
    
    if jd.get("apply_deadline"):
        try:
            deadline_dt = dt.fromisoformat(jd["apply_deadline"])
            if dt.now(timezone.utc) > deadline_dt:
                raise HTTPException(status_code=400, detail="Application deadline passed")
        except ValueError: pass
    
    resumes = await db.resumes.find().limit(n).to_list(length=n)
    if not resumes:
        return {"message": "No resumes found"}
    
    created_count = 0
    email_tasks = []
    selected_resume_ids = []
    
    for resume in resumes:
        resume_id_str = str(resume["_id"])
        selected_resume_ids.append(resume_id_str)
        
        existing = await db.interviews.find_one({"jd_id": jd_id, "resume_id": resume_id_str})
        
        if existing:
            interview_id = str(existing["_id"])
            interview_token = existing.get("interview_token") or secrets.token_urlsafe(32)
        else:
            if jd.get("interview_config"):
                from services.interview.sectioned_interview import prepare_sectioned_interview_doc
                interview_doc = await prepare_sectioned_interview_doc(jd, resume)
                result = await db.interviews.insert_one(interview_doc)
                interview_id = str(result.inserted_id)
                interview_token = interview_doc["interview_token"]
            else:
                questions_data = await generate_questions(jd["description"], resume["text"], num_questions, difficulty_level, question_type, job_title=jd.get("title"))
                interview_token = secrets.token_urlsafe(32)
                from core.models import create_interview_document
                interview_doc = create_interview_document(jd_id, resume_id_str, questions_data, interview_token, dt.now(timezone.utc).isoformat(), num_questions, difficulty_level, question_type)
                result = await db.interviews.insert_one(interview_doc)
                interview_id = str(result.inserted_id)

        recruiter = await db.users.find_one({"_id": ObjectId(current_user.id)})
        email_tasks.append({
            'interview_id': interview_id,
            'to_email': resume["email"],
            'candidate_name': resume.get("candidate_name", "Candidate"),
            'job_title': jd.get("title", "Position"),
            'interview_token': interview_token,
            'recruiter_name': recruiter.get("name", current_user.email) if recruiter else "Recruiter",
            'company_name': recruiter.get("organization", "Company") if recruiter else "Company",
            'user_id': current_user.id
        })
        created_count += 1
    
    # Bulk email logic (Async)
    try:
        from services.email.email_async import send_bulk_emails_parallel
        email_results = await send_bulk_emails_parallel(email_tasks, db, max_concurrent=10)
    except Exception as e:
        logger.error(f"Bulk email failed: {e}")
    
    await db.jds.update_one({"_id": ObjectId(jd_id)}, {"$set": {"status": "processed", "selected_resume_ids": selected_resume_ids}})
    return {"message": f"Created {created_count} interviews", "count": created_count}


async def start_interview(interview_id: str, db, start_session: bool = True):
    """Start/Resume interview session (Async)"""
    from core.orchestrator import InterviewOrchestrator
    orchestrator = InterviewOrchestrator(db)
    
    if start_session:
        orch_state = await orchestrator.start_session(interview_id)
    else:
        orch_state = await orchestrator.get_state_snapshot(interview_id)
    
    interview = await db.interviews.find_one({"_id": ObjectId(interview_id)})
    if not interview: return {"error": "Interview not found"}
    
    resume = await db.resumes.find_one({"_id": ObjectId(interview["resume_id"])}) if interview.get("resume_id") else None
    
    sections = interview.get("sections", [])
    questions = interview.get("questions", [])
    if not questions and sections:
        flattened = []
        q_idx = 0
        for s in sections:
            if not s.get("enabled", True): continue
            for q_text in s.get("questions", []):
                q_item = q_text if isinstance(q_text, dict) else {"question": q_text}
                q_item.update({"id": q_idx, "type": s.get("type", "Descriptive"), "section_index": sections.index(s)})
                flattened.append(q_item)
                q_idx += 1
        await db.interviews.update_one({"_id": ObjectId(interview_id)}, {"$set": {"questions": flattened}})
        questions = flattened

    responses = interview.get("responses", [])
    curr_idx = interview.get("current_question_index", len(responses))
    
    questions_list = []
    for i, q in enumerate(questions or []):
        q_type = q.get("type", "Descriptive") if isinstance(q, dict) else "Descriptive"
        if isinstance(q, dict):
            q_content = q.copy()
            if q_type == "MCQ":
                q_content = {k: v for k, v in q_content.items() if k not in ["correct_answer", "explanation"]}
        else:
            q_content = q
        questions_list.append({"id": i, "type": q_type, "question": q_content, "answered": i < len(responses)})

    return {
        **orch_state,
        "candidate": resume.get("candidate_name", "Candidate") if resume else "Candidate",
        "questions": questions_list,
        "question_type": questions_list[curr_idx]["type"] if questions_list and curr_idx < len(questions_list) else "Descriptive",
        "responses": responses
    }


async def submit_response_fast(interview_id: str, data: InterviewResponse, db):
    """Submit answer (Fast-Ack, Async)"""
    interview = await db.interviews.find_one({"_id": ObjectId(interview_id)})
    if not interview: raise HTTPException(404, "Interview not found")
    
    curr_idx = len(interview.get("responses", []))
    questions = interview.get("questions", [])
    if curr_idx >= len(questions): raise HTTPException(400, "Already completed")
    
    from core.orchestrator import InterviewOrchestrator
    orchestrator = InterviewOrchestrator(db)
    server_timeout = False
    try:
        await orchestrator.validate_submission(interview_id, curr_idx)
    except ValueError as e:
        if "Time limit exceeded" in str(e): server_timeout = True
        else: raise HTTPException(400, str(e))

    resp_text = data.response
    is_timeout = data.timeout or server_timeout
    if server_timeout: resp_text = f"TIMEOUT - {resp_text}"
    
    q_obj = questions[curr_idx]
    q_type = q_obj.get("type", "Descriptive") if isinstance(q_obj, dict) else "Descriptive"
    
    resp_entry = {
        "question_id": q_obj.get("id", curr_idx) if isinstance(q_obj, dict) else curr_idx,
        "type": q_type,
        "answer": resp_text,
        "timestamp": dt.now(timezone.utc).isoformat(),
        "timeout": is_timeout
    }
    
    score_entry = None
    if q_type == "MCQ" and not is_timeout:
        correct = q_obj.get("correct_answer")
        ans = int(resp_text) if resp_text.isdigit() else -1
        scr = 10.0 if ans == correct else 0.0
        score_entry = {"score": scr, "overallScore": scr*10, "feedback": "Auto-graded", "question": q_obj.get("question", ""), "timeout": False, "evaluatorModel": "deterministic"}
    elif is_timeout:
        score_entry = {"score": 0.0, "overallScore": 0, "feedback": "Timeout", "question": q_obj.get("question", ""), "timeout": True}

    update_q = {"_id": ObjectId(interview_id), "responses": {"$size": curr_idx}}
    atomic_upd = {"$push": {"responses": resp_entry}, "$set": {}}
    
    section_index = q_obj.get("section_index")
    if section_index is not None:
        atomic_upd["$push"][f"sections.{section_index}.responses"] = resp_entry
        atomic_upd["$set"][f"sections.{section_index}.status"] = "in_progress"
    
    needs_bg_eval = False
    if score_entry: 
        atomic_upd["$push"]["scores"] = score_entry
        if section_index is not None:
            atomic_upd["$push"][f"sections.{section_index}.scores"] = score_entry
    else: 
        atomic_upd["$set"]["evaluation_pending"] = True
        needs_bg_eval = True
    
    response_payload = {"status": "success", "next_idx": curr_idx+1}
    is_last = curr_idx + 1 >= len(questions)
    if is_last:
        atomic_upd["$set"]["state"] = InterviewState.COMPLETED.value
        if needs_bg_eval: atomic_upd["$set"]["completion_pending"] = True
        else: 
            # ✅ FIX: Compute final score and breakdown using ScoringEngine
            all_scores = interview.get("scores", [])
            if score_entry: all_scores.append(score_entry)
            
            # Simple average fallback (penalizing unattempted questions)
            total_q = len(questions) if questions else 1
            avg_score = round(sum(s.get("score", 0) for s in all_scores) / total_q, 1) if all_scores else 0
            final_score = avg_score
            
            # Try ScoringEngine for comprehensive updates (sections, weights, overall)
            try:
                from services.processing.scoring_engine import ScoringEngine
                engine = ScoringEngine()
                
                # Mock a complete responses array for the engine
                all_responses = interview.get("responses", []) + [resp_entry]
                
                breakdown = await engine.calculate_score_breakdown(
                    responses=all_responses,
                    questions=questions,
                    interview_config=interview.get("interview_config")
                )
                
                if "overall_score" in breakdown:
                    # Scoring engine returns a score out of 100, we need it out of 10
                    final_score = breakdown["overall_score"] / 10 if breakdown["overall_score"] > 10 else breakdown["overall_score"]
                
                atomic_upd["$set"]["score_breakdown"] = breakdown
                atomic_upd["$set"]["overall_score"] = final_score * 10
            except Exception as e:
                import logging
                logging.getLogger(__name__).error(f"ScoringEngine fast-eval failed: {e}")
            
            atomic_upd["$set"].update({
                "is_completed": True, 
                "status": "completed", 
                "completed_at": dt.now(timezone.utc).isoformat(),
                "avg_score": final_score,
                "final_score": final_score
            })
    else:
        await orchestrator.transition_next(interview_id)
        # Fetch new state to get timestamps for the next question
        new_state = await orchestrator.get_state_snapshot(interview_id)
        response_payload["question_expires_at"] = new_state.get("question_expires_at")
        response_payload["question_duration"] = new_state.get("time_limit_question")

    # ✅ FIX: Avoid PyMongo 500 crashes if $set is empty
    if not atomic_upd["$set"]:
        del atomic_upd["$set"]

    await db.interviews.update_one(update_q, atomic_upd)
    
    # ✅ FIX: Synchronize application score immediately if auto-graded as final
    if is_last and not needs_bg_eval:
        await _sync_interview_results_to_application(interview_id, db)
    
    job_context = {
        "job_id": str(interview["jd_id"]),
        "job_title": interview.get("job_title"),
    }
    
    # response_payload is initialized above
    if is_last:
        if not needs_bg_eval:
            response_payload["status"] = "completed"
            response_payload["final_score"] = avg_score
        else:
            response_payload["status"] = "evaluating"
            
    return {
        "ack": {
            "question_index": curr_idx,
            "response_entry": resp_entry,
            "question_obj": q_obj,
            "job_context": job_context,
            "needs_background_eval": needs_bg_eval,
            "sync_required": is_last and not needs_bg_eval
        },
        "response": response_payload
    }


async def evaluate_and_score_background(interview_id: str, question_index: int, response_entry: dict, question_obj: dict, job_context: dict, db):
    """Background evaluation (Async)"""
    logger.info(f"🔄 Background evaluation starting: interview={interview_id}, q_idx={question_index}")
    try:
        interview = await db.interviews.find_one({"_id": ObjectId(interview_id)})
        if not interview: return
        
        # Idempotency based on question content to avoid indexing bugs
        q_text = question_obj.get("question") if isinstance(question_obj, dict) else str(question_obj)
        existing_scores = interview.get("scores", [])
        if any(s.get("question") == q_text for s in existing_scores if isinstance(s, dict)):
            return
        
        eval_result = await evaluate_interview_response(
            question=question_obj,
            response=response_entry.get("answer", ""),
            job_id=job_context.get("job_id"),
            interview_id=interview_id,
            db=db,
            question_type=response_entry.get("type", "Descriptive")
        )
        
        score_entry = {
            "score": round(eval_result.get("overallScore", 0) / 10, 1),
            "overallScore": eval_result.get("overallScore", 0),
            "feedback": eval_result.get("feedback", ""),
            "question": question_obj.get("question") if isinstance(question_obj, dict) else str(question_obj),
            "timeout": response_entry.get("timeout", False),
            "timestamp": dt.now(timezone.utc).isoformat(),
            "evaluatorModel": eval_result.get("evaluatorModel", "ai")
        }
        
        bg_update = {"$push": {"scores": score_entry}, "$set": {"evaluation_pending": False}}
        section_idx = question_obj.get("section_index") if isinstance(question_obj, dict) else None
        if section_idx is not None:
            bg_update["$push"][f"sections.{section_idx}.scores"] = score_entry
        
        is_last = question_index + 1 >= len(interview.get("questions", []))
        if is_last:
            # Re-calculate final score
            scores = list(interview.get("scores", []))
            scores.append(score_entry)
            avg_score = round(sum(s.get("score", 0) for s in scores) / len(scores), 1) if scores else 0
            bg_update["$set"].update({
                "avg_score": avg_score,
                "final_score": avg_score,
                "is_completed": True,
                "status": "completed",
                "completed_at": dt.now(timezone.utc).isoformat(),
                "completion_pending": False
            })

        # ✅ FIX: Removed legacy "$size: question_index" concurrency lock to allow slow AI evaluation to append even if fast MCQs pushed arrays ahead.
        await db.interviews.update_one({"_id": ObjectId(interview_id)}, bg_update)
        
        if is_last:
            await _sync_interview_results_to_application(interview_id, db)
            
    except Exception as e:
        logger.error(f"Background evaluation failed: {e}")
        await db.interviews.update_one({"_id": ObjectId(interview_id)}, {"$set": {"evaluation_pending": False}})


async def _sync_interview_results_to_application(interview_id: str, db):
    """Sync final interview score to the application document (Async).
    
    Scale contract:
    - interviews.final_score / avg_score: stored on 0-10 scale
    - applications.interview_score:       stored on 0-100 scale
    - Both dashboard pipelines ($addFields) already read interview.final_score and multiply * 10
      as their FALLBACK. The application.interview_score is the PRIMARY source.
    """
    interview = await db.interviews.find_one({"_id": ObjectId(interview_id)})
    if not interview: return
    
    # Use final_score if set, fall back to avg_score
    raw_score = interview.get("final_score") or interview.get("avg_score") or 0
    
    # FIX: Guard against already-100-scale values (e.g., ScoringEngine stores overall_score on 0-100)
    # If the score is > 10, it's already on the 0-100 scale — don't multiply again
    if raw_score <= 10:
        interview_score_100 = round(raw_score * 10, 1)
    else:
        interview_score_100 = round(raw_score, 1)
    
    app_query = {"job_id": str(interview["jd_id"]), "resume_id": str(interview["resume_id"])}
    application = await db.applications.find_one(app_query)
    if application:
        await db.applications.update_one(
            {"_id": application["_id"]}, 
            {"$set": {
                "interview_id": str(interview["_id"]),
                "interview_score": interview_score_100,      # 0-100 scale
                "interview_score_synced_at": dt.now(timezone.utc).isoformat(),
                "updated_at": dt.now(timezone.utc).isoformat()
            }}
        )
        logger.info(f"Score synced: interview={interview_id}, raw={raw_score}, stored_100scale={interview_score_100}")

async def evaluate_terminated_interview_background(interview_id: str, db):
    """
    Evaluates all pending responses when an interview is terminated (e.g., due to proctoring warnings).
    """
    logger.info(f"🚨 Background evaluation for terminated interview starting: {interview_id}")
    try:
        interview = await db.interviews.find_one({"_id": ObjectId(interview_id)})
        if not interview:
            return
            
        responses = interview.get("responses", [])
        questions = interview.get("questions", [])
        scores = interview.get("scores", [])
        
        job_id = str(interview.get("jd_id")) if interview.get("jd_id") else None
        job_title = interview.get("job_title", "General Position")
        
        scores_added = False
        
        for idx, response_entry in enumerate(responses):
            req_q_id = response_entry.get("question_id", idx)
            question_obj = None
            if idx < len(questions):
                question_obj = questions[idx]
            else:
                for q in questions:
                    if (isinstance(q, dict) and q.get("id") == req_q_id) or str(q) == req_q_id:
                        question_obj = q
                        break
                        
            if not question_obj:
                continue

            q_text = question_obj.get("question") if isinstance(question_obj, dict) else str(question_obj)
            has_score = any(s.get("question") == q_text for s in scores if isinstance(s, dict))
                
            if has_score:
                continue  # Already scored
                
            logger.info(f"Evaluating pending response for q_idx={idx} in terminated interview")
            
            # Use existing evaluation logic
            eval_result = await evaluate_interview_response(
                question=question_obj,
                response=response_entry.get("answer", ""),
                job_id=job_id,
                interview_id=interview_id,
                db=db,
                question_type=response_entry.get("type", "Descriptive")
            )
            
            score_entry = {
                "score": round(eval_result.get("overallScore", 0) / 10, 1),
                "overallScore": eval_result.get("overallScore", 0),
                "feedback": eval_result.get("feedback", ""),
                "question": q_text,
                "timeout": response_entry.get("timeout", False),
                "timestamp": dt.now(timezone.utc).isoformat(),
                "evaluatorModel": eval_result.get("evaluatorModel", "ai")
            }
            
            scores.append(score_entry)
            scores_added = True
            
            section_idx = question_obj.get("section_index") if isinstance(question_obj, dict) else None
            if section_idx is not None:
                # Append to memory representation
                if "sections" in interview and section_idx < len(interview["sections"]):
                    interview["sections"][section_idx].setdefault("scores", []).append(score_entry)
            
        # Re-calculate averages and overall structures (penalizing unattempted questions)
        total_q = len(questions) if questions else 1
        avg_score = round(sum(s.get("score", 0) for s in scores) / total_q, 1) if scores else 0
        final_score = avg_score
        
        update_doc = {
            "$set": {
                "scores": scores,
                "avg_score": avg_score,
                "final_score": avg_score,
                "evaluation_pending": False,
                "completion_pending": False
            }
        }
        
        # Integrate ScoringEngine to guarantee accurate structure synchronization
        try:
            from services.processing.scoring_engine import ScoringEngine
            engine = ScoringEngine()
            breakdown = await engine.calculate_score_breakdown(
                responses=responses,
                questions=questions,
                interview_config=interview.get("interview_config")
            )
            if "overall_score" in breakdown:
                final_score = breakdown["overall_score"] / 10 if breakdown["overall_score"] > 10 else breakdown["overall_score"]
            update_doc["$set"]["score_breakdown"] = breakdown
            update_doc["$set"]["overall_score"] = final_score * 10
            update_doc["$set"]["avg_score"] = final_score
            update_doc["$set"]["final_score"] = final_score
        except Exception as e:
            logger.error(f"ScoringEngine integration in background evaluation failed: {e}")

        # Update sections in DB
        if "sections" in interview:
            update_doc["$set"]["sections"] = interview["sections"]
        
        await db.interviews.update_one({"_id": ObjectId(interview_id)}, update_doc)
        
        # ✅ FIX: Always sync applications score on manual background evaluations, not just when newly appended scores exist
        await _sync_interview_results_to_application(interview_id, db)
            
        logger.info(f"✅ Terminated interview {interview_id} evaluation completed. Final Score: {avg_score}")
        
    except Exception as e:
        logger.error(f"Failed to evaluate terminated interview: {e}", exc_info=True)
        await db.interviews.update_one({"_id": ObjectId(interview_id)}, {"$set": {"evaluation_pending": False}})

async def create_interview_for_candidate(jd_id: str, resume_id: str, num_questions: int, difficulty_level: str, question_type: str, current_user, db):
    """Manual invite (Async)"""
    jd = await db.jds.find_one({"_id": ObjectId(jd_id)})
    resume = await db.resumes.find_one({"_id": ObjectId(resume_id)})
    if not jd or not resume: raise HTTPException(404, "Not found")
    
    from services.interview.sectioned_interview import prepare_sectioned_interview_doc
    interview_doc = await prepare_sectioned_interview_doc(jd, resume)
    interview_doc["recruiter_id"] = current_user.id
    result = await db.interviews.insert_one(interview_doc)
    
    # Send email asynchronously
    from services.email.email_async import send_email_async
    try:
        await send_email_async(
            to_email=resume["email"],
            candidate_name=resume.get("candidate_name", "Candidate"),
            job_title=jd.get("title", "Position"),
            interview_id=str(result.inserted_id),
            interview_token=interview_doc["interview_token"],
            recruiter_name=current_user.email, # Simplified
            company_name="SmartHiring",
            user_id=current_user.id,
            db=db
        )
    except Exception as e:
        logger.error(f"Manual invite email failed: {e}")
        
    return {"success": True, "interview_id": str(result.inserted_id)}
