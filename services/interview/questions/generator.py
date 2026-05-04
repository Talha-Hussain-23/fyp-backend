"""
AI-powered question generation for interviews (Async).
Handles question generation with AI fallback and quality validation.
"""
from typing import List, Dict, Any, Optional
import logging
import hashlib

from services.ai.ai_provider import ai_service
from core.governance.prompts import PromptRegistry
from .templates import get_template_questions

logger = logging.getLogger(__name__)

def _build_schema(question_type: str) -> Any:
    """Build question schema based on type"""
    if question_type == "MCQ":
        return [{
            "question": "string",
            "options": ["string (4 options)"],
            "correct_answer": "integer (1-4)",
            "explanation": "string"
        }]
    elif question_type == "Code":
        return [{
            "question": "string",
            "language": "string",
            "test_cases": [{"input": "string", "output": "string"}],
            "hints": ["string"]
        }]
    else:
        return ["string"]


def _build_prompt(
    jd: str,
    resume_text: str,
    num_questions: int,
    difficulty_level: str,
    question_type: str,
    ai_instructions: str = None,
    language: str = None,
    job_title: str = None
) -> str:
    """Build AI prompt using PromptRegistry"""
    jd_preview = jd[:2000] if jd else "General position"
    resume_preview = resume_text[:1500] if resume_text else "Candidate profile"
    custom_instr = ai_instructions or "Focus on core competencies and job relevance."
    title = job_title or "General Position"
    
    # Select specific prompt task based on type
    task_id = "question_generation_descriptive"
    if question_type == "MCQ":
        task_id = "question_generation_mcq"
    elif question_type == "Code":
        task_id = "question_generation_code"
        
    try:
        # Render prompt
        render_kwargs = {
            "count": num_questions + 2,
            "difficulty": difficulty_level,
            "job_title": title,
            "job_description": jd_preview,
            "topic": question_type,
            "custom_instructions": custom_instr
        }
        
        if task_id == "question_generation_descriptive":
            render_kwargs["resume_context"] = resume_preview
            render_kwargs["previous_questions"] = "None"
        elif task_id == "question_generation_code":
            render_kwargs["language"] = language or "Python"
            
        return PromptRegistry.render(task_id, "v1.0.0", **render_kwargs)
    except Exception as e:
        logger.error(f"Prompt rendering failed: {e}")
        return (
            f"Generate {num_questions} unique {difficulty_level} {question_type} interview questions "
            f"for a '{title}' role.\n\n"
            f"Job Description:\n{jd_preview}\n\n"
            f"Instructions: {custom_instr}\n\n"
            f"Output strictly as a JSON array."
        )


def _validate_and_format(response_data: List, question_type: str, num_questions: int) -> List:
    """Validate and format AI response with deduplication"""
    validated_data = []
    seen_hashes = set()
    
    if not isinstance(response_data, list) or len(response_data) == 0:
        return validated_data
    
    for item in response_data:
        if question_type == "MCQ":
            if not isinstance(item, dict): continue
            if "question" not in item or not item["question"].strip(): continue
            
            options = item.get("options", [])
            if not options or len(options) < 4 or options == ["Option A", "Option B", "Option C", "Option D"]:
                continue
            
            item["options"] = [str(o) for o in options[:4]]
            if "correct_answer" not in item: item["correct_answer"] = 1
            else:
                try: item["correct_answer"] = max(1, min(4, int(item["correct_answer"])))
                except: item["correct_answer"] = 1
                
        elif question_type == "Code":
            if not isinstance(item, dict): continue
            if "question" not in item or not item["question"].strip(): continue
            if "test_cases" not in item: item["test_cases"] = []
            if "language" not in item: item["language"] = "python"
        
        q_text = item if isinstance(item, str) else item.get("question", "")
        q_hash = hashlib.md5(str(q_text).lower().strip().encode()).hexdigest()
        if q_hash in seen_hashes: continue
        seen_hashes.add(q_hash)
        validated_data.append(item)
    
    return validated_data[:num_questions]


async def generate_questions(
    jd: str,
    resume_text: str,
    num_questions: int,
    difficulty_level: str,
    question_type: str = "Descriptive",
    ai_instructions: str = None,
    language: str = None,
    job_title: str = None
) -> List:
    """Generate AI questions (Async)"""
    try:
        prompt = _build_prompt(
            jd, resume_text, num_questions, difficulty_level,
            question_type, ai_instructions, language, job_title
        )
        
        try:
            logger.info(f"Calling AI service for {num_questions} {question_type} questions")
            response_data = await ai_service.generate_json(prompt)
        except Exception as ai_error:
            logger.warning(f"AI provider failed: {ai_error}")
            response_data = []

        validated_data = _validate_and_format(response_data, question_type, num_questions)
        if validated_data:
            return validated_data
            
    except Exception as e:
        logger.error(f"AI Generation failed: {e}")

    return get_template_questions(jd[:1000] if jd else "General", num_questions, question_type, difficulty_level)


async def generate_mixed_questions(
    jd: str,
    resume_text: str,
    num_questions: int,
    difficulty_level: str,
    question_types: list,
    ai_instructions: str = None,
    job_title: str = None
) -> List[Dict]:
    """Generate a mixed set of questions (Async)"""
    if not question_types:
        question_types = ["Descriptive"]
    
    questions_per_type = num_questions // len(question_types)
    remainder = num_questions % len(question_types)
    
    all_questions = []
    question_id = 0
    
    for idx, q_type in enumerate(question_types):
        num_for_type = questions_per_type + (1 if idx < remainder else 0)
        if num_for_type > 0:
            generated = await generate_questions(
                jd, resume_text, num_for_type, difficulty_level, q_type,
                ai_instructions=ai_instructions, job_title=job_title
            )
            for q in generated:
                all_questions.append({"id": question_id, "type": q_type, "question": q})
                question_id += 1
    
    return all_questions
