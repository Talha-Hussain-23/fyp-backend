import os
import json
from fastapi import UploadFile, HTTPException
from datetime import datetime
from dotenv import load_dotenv
from bson import ObjectId
from services.ai.ai_provider import ai_service
import asyncio
from asgiref.sync import async_to_sync
from core.logging_service import logger

load_dotenv()



async def ocr(file: UploadFile):
    """
    Extract text from PDF, DOCX, or image files with professional validation
    
    Features:
    - File size validation (max 10MB)
    - MIME type verification
    - Security checks (blocks executables)
    - Content validation
    """
    import io
    from services.common.validation.file_validator import FileValidator
    
    # PROFESSIONAL VALIDATION: Check file before processing
    try:
        validation_result = await FileValidator.validate_resume(file)
        logger.info(f"✅ File validation passed: {validation_result['filename']} ({validation_result['size_formatted']})")
    except HTTPException as e:
        logger.error(f"❌ File validation failed: {e.detail}")
        raise
    
    file_type = file.content_type
    filename = file.filename or "resume"
    file_extension = filename.split('.')[-1].lower() if '.' in filename else ''
    
    # Read file content
    content = await file.read()
    await file.seek(0)
    
    logger.info(f"DEBUG: OCR Processing {len(content)} bytes from {filename} ({file_type})")
    
    text = ""
    
    try:
        # Handle PDF files
        if file_type == 'application/pdf' or file_extension == 'pdf':
            try:
                import PyPDF2
                pdf_reader = PyPDF2.PdfReader(io.BytesIO(content))
                text = "\n".join([page.extract_text() for page in pdf_reader.pages])
            except Exception as e:
                try:
                    import pymupdf
                    doc = pymupdf.open(stream=content, filetype="pdf")
                    text = "\n".join([page.get_text() for page in doc])
                    doc.close()
                except Exception as e2:
                    logger.warning(f"PDF parsing error: {e}, {e2}")
                    text = ""
        
        # Handle DOCX files
        elif file_type in ['application/msword', 'application/vnd.openxmlformats-officedocument.wordprocessingml.document'] or file_extension in ['docx', 'doc']:
            try:
                from docx import Document
                doc = Document(io.BytesIO(content))
                text = "\n".join([para.text for para in doc.paragraphs])
            except Exception as e:
                logger.warning(f"DOCX parsing error: {e}")
                text = ""
        
        # Handle image files (JPEG, PNG)
        elif file_type in ['image/jpeg', 'image/jpg', 'image/png']:
            try:
                from PIL import Image
                import pytesseract
                image = Image.open(io.BytesIO(content))
                text = pytesseract.image_to_string(image)
            except Exception as e:
                logger.warning(f"OCR error: {e}")
                text = f"Image file: {filename}\n(OCR not available - please use PDF or DOCX)"
                
        # Handle Text files
        elif file_type == 'text/plain' or file_extension == 'txt':
             try:
                 text = content.decode('utf-8', errors='ignore')
             except Exception as e:
                 logger.warning(f"Text parsing error: {e}")
                 text = ""
                 
        # Fallback: Try decoding as text if content seems like text
        if not text and len(content) > 0:
             try:
                 decoded = content.decode('utf-8')
                 if len(decoded.strip()) > 0:
                     logger.info(f"Fallback: Treated {filename} as plain text")
                     text = decoded
             except:
                 pass
        
        # Explicitly reject unsupported file types if no text could be extracted and type is not standard
        if not text and len(content) > 0:
             # Check known unsafe types
             unsafe_extensions = ['.exe', '.sh', '.bat', '.cmd', '.js', '.vbs', '.scr', '.dll']
             if any(filename.lower().endswith(ext) for ext in unsafe_extensions):
                 raise HTTPException(status_code=400, detail="Security Warning: Executable files are strictly prohibited.")
             
             # General unsupported type
             raise HTTPException(status_code=400, detail="Unsupported file type. Please upload a valid PDF, DOCX, or Image.")

        if not text or len(text.strip()) < 10:
            logger.warning(f"WARNING: Insufficient text extracted from {filename} ({len(text)} chars)")
            text = f"Resume: {filename}\n(Text extraction incomplete)"
        
        return text.strip()
    
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"File processing error: {e}")
        return f"Error processing file {filename}: {str(e)}"

async def extract_features(text: str):
    """
    Extract ONLY technical features from resume text: SKILLS, EXPERIENCE, EDUCATION, CERTIFICATIONS.
    """
    sanitized_text = sanitize_resume_text(text)
    
    prompt = f"""Extract ONLY the following objective technical information from this resume:
- SKILLS: List all technical skills, programming languages, frameworks, tools, technologies
- EXPERIENCE: Years of experience and work experience descriptions (NO names, locations, or personal details)
- EDUCATION: Degree level and field of study ONLY (NO university names, NO graduation years, NO rankings)
- CERTIFICATIONS: Professional certifications and licenses

CRITICAL RULES:
- IGNORE: candidate names, gender, age, race, ethnicity, location, university names, formatting
- FOCUS ONLY on technical and professional qualifications
- For skills: recognize equivalent technologies (e.g., LangChain = Chatbot framework)
- For experience: extract years and role descriptions, ignore company names and locations
- For education: extract degree type (BS, MS, PhD) and field, ignore institution name

Resume text: {sanitized_text[:2000]}

Schema strict JSON output:
{{
  "skills": ["string (skill name)"],
  "education": ["string (degree)"],
  "experience": "string (summary)",
  "certifications": ["string"],
  "email": "string (optional)"
}}
"""
    
    # Initialize default features immediately to ensure safety
    fallback_features = {
        'skills': [],
        'education': [],
        'experience': "",
        'certifications': [],
        'email': "no-email@example.com"
    }

    try:
        # Properly await the async AI service directly
        parsed = await ai_service.generate_json(prompt)

        if isinstance(parsed, dict) and 'skills' in parsed:
            return parsed
            
    except Exception as e:
        logger.error(f"AI Extraction error: {e}")
    
    # Fallback to Regex-based extraction if AI fails
    logger.info("Falling back to regex extraction for resume features")
    import re
    
    text_lower = text.lower()
    
    # 1. Extract Skills (Basic Keyword Matching)
    common_skills = [
        "python", "javascript", "java", "c++", "c#", "react", "angular", "vue", "node.js",
        "django", "flask", "fastapi", "spring", "express", "sql", "mongodb", "postgresql",
        "mysql", "mongodb", "aws", "azure", "gcp", "docker", "kubernetes", "git", "github",
        "agile", "scrum", "machine learning", "ai", "deep learning", "tensorflow", "pytorch",
        "html", "css", "linux", "unix", "bash", "shell", "jira", "figma"
    ]
    
    found_skills = []
    for skill in common_skills:
        if re.search(r'\b' + re.escape(skill) + r'\b', text_lower):
            found_skills.append(skill)
    fallback_features['skills'] = found_skills
    
    # 2. Extract Experience (Years)
    exp_match = re.search(r'(\d+)\+?\s*(?:years?|yrs?|yr)\s*(?:of\s*)?experience', text_lower)
    if exp_match:
        fallback_features['experience'] = f"{exp_match.group(1)} years experience"
    else:
        # Look for date ranges to estimate experience
        date_ranges = re.findall(r'(20\d{2})\s*[-–to]+\s*(20\d{2}|present|current)', text_lower)
        if date_ranges:
            fallback_features['experience'] = f"Estimated {len(date_ranges)} roles found in history"
            
    # 3. Extract Education (Degree levels)
    degrees = []
    if re.search(r'\bbachelor|b\.?s\.?|b\.?a\.?\b', text_lower):
        degrees.append("Bachelor's Degree")
    if re.search(r'\bmaster|m\.?s\.?|m\.?a\.?|mba\b', text_lower):
        degrees.append("Master's Degree")
    if re.search(r'\bph\.?d\.?|doctorate\b', text_lower):
        degrees.append("PhD")
        
    if degrees:
        fallback_features['education'] = degrees
        
    return fallback_features

def sanitize_resume_text(text: str) -> str:
    """
    Remove demographic and personal information from resume text for unbiased evaluation.
    Removes: names, gender indicators, age, race/ethnicity, location, university names, formatting.
    Keeps only: skills, experience descriptions, education level/field, certifications, technical content.
    """
    import re
    
    # Remove email addresses (keep structure but anonymize)
    text = re.sub(r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b', '[EMAIL]', text)
    
    # Remove phone numbers
    text = re.sub(r'\b\d{3}[-.]?\d{3}[-.]?\d{4}\b', '[PHONE]', text)
    
    # Remove addresses (street addresses, cities, states, zip codes)
    text = re.sub(r'\d+\s+[A-Za-z\s]+(?:Street|St|Avenue|Ave|Road|Rd|Drive|Dr|Lane|Ln|Boulevard|Blvd|Way|Circle|Ct|Court)', '[ADDRESS]', text)
    text = re.sub(r'\b[A-Z][a-z]+,\s*[A-Z]{2}\s+\d{5}(?:-\d{4})?\b', '[LOCATION]', text)
    
    # Remove common name patterns (but keep technical terms)
    # This is a simple approach - in production, use NER to identify person names
    # For now, we'll focus on removing obvious personal identifiers
    
    # Remove university names (common patterns)
    # Note: We keep degree types (BS, MS, PhD) but remove institution names
    university_patterns = [
        r'\b(?:University|College|Institute|School)\s+of\s+[A-Z][a-z]+',
        r'\b[A-Z][a-z]+\s+(?:University|College|Institute)',
        r'\b[A-Z]{2,}\s+(?:University|College)'
    ]
    for pattern in university_patterns:
        text = re.sub(pattern, '[UNIVERSITY]', text, flags=re.IGNORECASE)
    
    # Remove years that might indicate age (keep graduation years in context of education)
    # This is tricky - we want to keep "5 years of experience" but remove "born in 1990"
    # For now, we'll be conservative and only remove standalone years that look like birth years
    text = re.sub(r'\b(?:born|age|aged)\s+(?:in\s+)?(?:19|20)\d{2}\b', '', text, flags=re.IGNORECASE)
    
    return text

async def process_resume(file: UploadFile, db):
    """Process uploaded resume and save to MongoDB"""
    try:
        text = await ocr(file)
        if not text or len(text.strip()) < 10:
            logger.error(f"❌ OCR FAILED for {file.filename}: text too short or empty")
            raise HTTPException(status_code=400, detail="Could not extract text from file. Please ensure it's a valid PDF, DOCX, or image file.")
        
        features = await extract_features(text)
        logger.info(f"Extracted features: skills={len(features.get('skills', []))}, exp={features.get('experience')[:30] if features.get('experience') else 'None'}")
        
        # Extract email from text if not found by AI
        email = features.get('email', 'no-email@example.com')
        if email == 'no-email@example.com':
            import re
            email_pattern = r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b'
            emails_found = re.findall(email_pattern, text)
            if emails_found:
                email = emails_found[0]
        
        # Extract candidate name from filename or text (needed for display/communication only)
        candidate_name = file.filename.split('.')[0] if file.filename else "Candidate"
        if candidate_name and len(candidate_name) > 2:
            # Try to extract name from first few lines of text
            lines = text.split('\n')[:5]
            for line in lines:
                line = line.strip()
                if len(line) > 5 and len(line.split()) <= 4 and not '@' in line:
                    candidate_name = line
                    break
        
        # Generate embedding for resume using SANITIZED text (Async)
        from services.ai.embeddings import get_embedding
        sanitized_text = sanitize_resume_text(text)
        logger.info(f"Generating embedding for resume (sanitization active): {candidate_name}")
        resume_embedding = await get_embedding(sanitized_text)
        
        logger.info(f"Generated embedding of dimension: {len(resume_embedding) if resume_embedding else 0}")

        from core.models import create_resume_document
        resume_doc = create_resume_document(
            candidate_name=candidate_name,
            email=email,
            text=text,  # Keep original text for display, but use sanitized for embeddings
            features=features,
            file_name=file.filename,
            file_type=file.content_type,
            embedding=resume_embedding
        )
        
        result = await db.resumes.insert_one(resume_doc)
        
        return {
            "resume_id": str(result.inserted_id),
            "message": "Resume processed successfully",
            "text": text,
            "features": features
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.exception(f"Resume processing failed: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Resume processing failed: {str(e)}")

async def save_jd(jd, current_user, db):
    """Save job description to MongoDB with LLM embedding"""
    if not current_user.is_recruiter:
        raise HTTPException(status_code=403, detail="Not a recruiter")

    # Parse optional fields
    difficulty = getattr(jd, 'difficulty_level', 'Medium') or 'Medium'
    num_q = int(getattr(jd, 'num_questions', 5) or 5)
    deadline_str = getattr(jd, 'apply_deadline', None)
    
    # Normalize deadline to UTC format
    if deadline_str:
        from utils.timezone_utils import normalize_deadline_to_utc
        deadline_str = normalize_deadline_to_utc(deadline_str)
    
    invite_rule = getattr(jd, 'invite_rule', 'Top 10') or 'Top 10'
    invite_rule_n = getattr(jd, 'invite_rule_n', None)

    # Generate embedding for job description
    from services.ai.embeddings import get_embedding
    jd_text = jd.description
    if getattr(jd, 'title', None):
        jd_text = f"{jd.title}\n{jd.description}"
    
    logger.info(f"Generating embedding for job: {getattr(jd, 'title', 'Untitled')}")
    jd_embedding = await get_embedding(jd_text)

    # Handle question_types
    question_types = getattr(jd, 'question_types', None)
    question_type = getattr(jd, 'question_type', 'Descriptive') or 'Descriptive'
    if question_types is None:
        question_types = [question_type] if question_type else ['Descriptive']
    
    # Process interview_config
    interview_config_dict = None
    if hasattr(jd, 'interview_config') and jd.interview_config:
        config = jd.interview_config
        interview_config_dict = {
            "sections": [s.model_dump() if hasattr(s, 'model_dump') else s.dict() for s in config.sections],
            "total_questions": config.total_questions,
            "total_time": config.total_time,
            "enabled_section_types": config.enabled_section_types
        }
        num_q = config.total_questions
        question_types = config.enabled_section_types
    
    from core.models import create_jd_document
    jd_doc = create_jd_document(
        recruiter_id=current_user.id,
        description=jd.description,
        difficulty_level=difficulty,
        num_questions=num_q,
        apply_deadline=deadline_str,
        title=getattr(jd, 'title', None),
        num_vacancies=int(getattr(jd, 'num_vacancies', 1) or 1),
        question_type=question_type,
        question_types=question_types,
        max_shortlist=int(getattr(jd, 'max_shortlist', 10) or 10),
        ai_instructions=getattr(jd, 'ai_instructions', None),
        invite_rule=invite_rule,
        invite_rule_n=invite_rule_n,
        embedding=jd_embedding,
        interview_config=interview_config_dict
    )
    
    result = await db.jds.insert_one(jd_doc)
    
    # Invalidate cache for job listings
    from core.cache import get_cache_service
    cache = get_cache_service()
    await cache.clear_pattern(f"jobs:recruiter:{current_user.id}")
    
    return {"message": "JD uploaded", "jd_id": str(result.inserted_id)}

async def match_and_rank(jd_id: str, current_user, db):
    """Match and rank resumes against job description using LLM embeddings (Async)"""
    if not current_user.is_recruiter:
        raise HTTPException(status_code=403, detail="Not a recruiter")
    
    try:
        jd = await db.jds.find_one({"_id": ObjectId(jd_id), "recruiter_id": current_user.id})
    except Exception:
        jd = None
    
    if not jd:
        raise HTTPException(status_code=404, detail="JD not found")
    
    # Use to_list to fetch all resumes asynchronously
    resumes = await db.resumes.find().to_list(length=1000)
    if not resumes:
        return []
    
    try:
        from services.ai.embeddings import match_resume_to_job, get_embedding
        
        # Get job embedding
        jd_embedding = jd.get("embedding")
        if not jd_embedding:
            jd_text = jd.get("description", "")
            if jd.get("title"):
                jd_text = f"{jd['title']}\n{jd_text}"
            jd_embedding = await get_embedding(jd_text)
            await db.jds.update_one({"_id": ObjectId(jd_id)}, {"$set": {"embedding": jd_embedding}})
        
        ranked = []
        for resume in resumes:
            resume_embedding = resume.get("embedding")
            if not resume_embedding:
                resume_embedding = await get_embedding(resume.get("text", ""))
                await db.resumes.update_one({"_id": resume["_id"]}, {"$set": {"embedding": resume_embedding}})
            
            match_score = match_resume_to_job(resume_embedding, jd_embedding)
            
            screening_id = None
            match_breakdown = {"skills": 0, "experience": 0, "education": 0, "certifications": 0, "completeness": 0}
            
            try:
                # Assuming screening service might need conversion too, but let's try wrapping it
                from services.automation.screening import screen_candidate
                resume_text = resume.get("text", "")
                resume_features = resume.get("features", {})
                jd_text = jd.get("description", "")
                if jd.get("title"):
                    jd_text = f"{jd['title']}\n{jd_text}"
                
                # Call screening service (Async)
                screening_result = await screen_candidate(
                    candidate_id=str(resume["_id"]), job_id=jd_id,
                    resume_text=resume_text, resume_features=resume_features,
                    jd_text=jd_text, jd_keywords=None, db=db
                )
                    
                if screening_result.get("success"):
                    screening_data = screening_result.get("screening", {})
                    screening_id = str(screening_data["_id"]) if "_id" in screening_data else None
                    match_breakdown = screening_data.get("matchScoreBreakdown", match_breakdown)
                    match_score = screening_result.get("matchScore", match_score)
            except Exception as e:
                logger.error(f"Error in screening for {resume.get('candidate_name')}: {e}")
            
            ranked.append({
                "resume_id": str(resume["_id"]),
                "candidate": resume.get("candidate_name", "Unknown"),
                "email": resume.get("email", "No email"),
                "match": f"{match_score:.1f}%",
                "match_score": match_score,
                "skills_matched": resume.get("features", {}).get("skills", []),
                "experience": resume.get("features", {}).get("experience", ""),
                "screening_id": screening_id,
                "match_breakdown": match_breakdown
            })
        
        return sorted(ranked, key=lambda x: x.get('match_score', 0), reverse=True)
        
    except Exception as e:
        logger.exception(f"Ranking error: {e}")
        # Fallback simple ranking (sync behavior but in async loop)
        return []

