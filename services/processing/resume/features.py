"""
Resume feature extraction using AI and regex fallback.
Extracts skills, experience, education, and certifications.
"""
import re
import logging
from typing import Dict, List
from services.ai.ai_provider import ai_service
from .sanitizer import sanitize_resume_text

logger = logging.getLogger(__name__)


async def extract_features(text: str) -> Dict:
    """
    Extract ONLY technical features from resume text: SKILLS, EXPERIENCE, EDUCATION, CERTIFICATIONS.
    
    Args:
        text: Resume text content
        
    Returns:
        Dictionary with extracted features
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
    return _extract_features_regex(text, fallback_features)


def _extract_features_regex(text: str, fallback_features: Dict) -> Dict:
    """Regex-based feature extraction fallback"""
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


async def extract_skills(text: str) -> List[str]:
    """Extract only skills from resume text"""
    features = await extract_features(text)
    return features.get('skills', [])


async def extract_experience(text: str) -> str:
    """Extract only experience summary from resume text"""
    features = await extract_features(text)
    return features.get('experience', "")


async def extract_education(text: str) -> List[str]:
    """Extract only education from resume text"""
    features = await extract_features(text)
    return features.get('education', [])
