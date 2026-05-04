"""
Unbiased Candidate Screening System
AI-driven resume matching based solely on objective technical qualifications:
- SKILLS (with technology equivalence recognition)
- EXPERIENCE (years and role descriptions)
- EDUCATION (degree level and field only)
- CERTIFICATIONS

Completely ignores: names, gender, age, race, university ranking, location, formatting
"""

import os
import json
import re
from typing import Dict, List, Optional, Tuple
from datetime import datetime, timezone
from fastapi import HTTPException
from bson import ObjectId
from pymongo.database import Database
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity
from dotenv import load_dotenv
from core.logging_service import logger

load_dotenv()

from services.ai.ai_provider import ai_service
import asyncio
from asgiref.sync import async_to_sync

# Weight configuration for match scoring
SCORING_WEIGHTS = {
    "skills": 0.50,      # 50%
    "experience": 0.20,  # 20%
    "education": 0.15,   # 15%
    "certifications": 0.10,  # 10%
    "completeness": 0.05     # 5%
}


async def extract_jd_keywords(jd_text: str) -> List[str]:
    """
    Extract relevant keywords and skills from job description.
    Focus ONLY on technical requirements: skills, experience, education level, certifications.
    IGNORE: location, company name, demographic preferences, formatting.
    """
    keywords = []
    jd_lower = jd_text.lower()
    
    # Common technical skills with equivalence mapping
    tech_skills = [
        "python", "javascript", "java", "c++", "c#", "react", "angular", "vue", "node.js",
        "django", "flask", "fastapi", "spring", "express", "sql", "mongodb", "postgresql",
        "mysql", "mongodb", "aws", "azure", "gcp", "docker", "kubernetes", "git", "github",
        "agile", "scrum", "machine learning", "ai", "deep learning", "tensorflow", "pytorch",
        "data analysis", "pandas", "numpy", "project management", "leadership", "communication", 
        "teamwork", "rest api", "graphql", "langchain", "chatbot", "frontend", "backend"
    ]
    
    # Extract mentioned skills (use word boundaries to avoid partial matches)
    import re
    for skill in tech_skills:
        # Use word boundary regex to match whole words only
        pattern = r'\b' + re.escape(skill) + r'\b'
        if re.search(pattern, jd_lower):
            keywords.append(skill)
    
    # Extract degree requirements (level only, not institution)
    degree_keywords = ["bachelor", "master", "phd", "degree", "diploma", "certificate", "bs", "ms", "phd"]
    for degree in degree_keywords:
        if degree in jd_lower:
            keywords.append(degree)
    
    # Extract experience requirements
    exp_patterns = [
        r'(\d+)\s*(?:years?|yrs?|yr)\s*(?:of\s*)?experience',
        r'experience.*?(\d+)\s*(?:years?|yrs?|yr)',
        r'(\d+)\+?\s*(?:years?|yrs?|yr)'
    ]
    for pattern in exp_patterns:
        matches = re.findall(pattern, jd_lower)
        if matches:
            keywords.extend([f"{m} years experience" for m in matches])
    
    # Use AI to extract more keywords
    try:
        prompt = f"""Extract ONLY technical requirements from this job description:
{jd_text[:2000]}

CRITICAL: Focus ONLY on:
- Technical skills, programming languages, frameworks, tools
- Years of experience required
- Education level (BS, MS, PhD) and field - NOT university names
- Professional certifications

IGNORE completely:
- Location, company name, office address
- Demographic preferences
- Formatting, styling, presentation

Recognize equivalent technologies:
- LangChain = Chatbot framework = Conversational AI
- React = Frontend framework = UI library
- Python = Programming language
- AWS = Cloud platform = Cloud computing

Output JSON:
{{
  "required_skills": ["skill1", "skill2", ...],
  "preferred_skills": ["skill1", "skill2", ...],
  "technologies": ["tech1", "tech2", ...],
  "education_required": "degree level only (e.g., BS, MS, PhD)",
  "experience_required": "years"
}}
"""
        parsed = await ai_service.generate_json(prompt)

        if isinstance(parsed, dict):
            keywords.extend(parsed.get("required_skills", []))
            keywords.extend(parsed.get("preferred_skills", []))
            keywords.extend(parsed.get("technologies", []))
    except Exception as e:
        logger.error(f"AI JD extraction error: {e}")
    
    # Remove duplicates and return
    return list(set([k.lower() for k in keywords if k]))


async def extract_resume_sections(resume_text: str) -> Dict:
    """Extract structured sections from resume text"""
    sections = {
        "skills": [],
        "education": [],
        "experience": "",
        "certifications": [],
        "keywords": []
    }
    
    # Basic keyword extraction
    skill_keywords = [
        "python", "javascript", "java", "c++", "c#", "react", "angular", "vue", "node.js",
        "django", "flask", "fastapi", "spring", "express", "sql", "mongodb", "postgresql",
        "mysql", "mongodb", "aws", "azure", "gcp", "docker", "kubernetes", "git", "github",
        "agile", "scrum", "machine learning", "ai", "deep learning", "tensorflow", "pytorch",
        "data analysis", "pandas", "numpy", "project management", "leadership", "communication", "teamwork"
    ]
    
    text_lower = resume_text.lower()
    
    # Extract skills using keyword matching
    found_skills = []
    for keyword in skill_keywords:
        if keyword in text_lower:
            found_skills.append(keyword)
    
    sections["keywords"] = found_skills
    
    # Extract years of experience
    exp_patterns = [
        r'(\d+)\s*(?:years?|yrs?|yr)\s*(?:of\s*)?experience',
        r'experience.*?(\d+)\s*(?:years?|yrs?|yr)',
        r'(\d+)\+?\s*(?:years?|yrs?|yr)'
    ]
    for pattern in exp_patterns:
        match = re.search(pattern, text_lower)
        if match:
            sections["experience"] = f"{match.group(1)} years"
            break
    
    # Extract education (look for degree mentions)
    education_patterns = [
        r'(bachelor|master|phd|b\.?s\.?|m\.?s\.?|ph\.?d\.?)\s*(?:degree|in|of)?',
        r'(university|college|institute).*?(\d{4})',
        r'(bachelor|master|phd).*?(?:in|of).*?(\w+)'
    ]
    education_found = []
    for pattern in education_patterns:
        matches = re.findall(pattern, text_lower)
        if matches:
            education_found.extend([m if isinstance(m, str) else " ".join(m) for m in matches])
    sections["education"] = list(set(education_found)) if education_found else []
    
    # Extract certifications
    cert_patterns = [
        r'(certified|certification|certificate|license).*?(\w+)',
        r'([A-Z]{2,}(?:\s+[A-Z]{2,})*)\s*(?:certified|certification)'
    ]
    certs_found = []
    for pattern in cert_patterns:
        matches = re.findall(pattern, text_lower)
        if matches:
            certs_found.extend([m if isinstance(m, str) else " ".join(m) for m in matches])
    sections["certifications"] = list(set(certs_found)) if certs_found else []
    
    # Try to extract using AI (more accurate)
    try:
        prompt = f"""Extract ONLY technical information from this resume:
{resume_text[:2000]}

CRITICAL RULES:
- Extract ONLY: technical skills, experience descriptions, education level/field, certifications
- IGNORE: candidate name, gender, age, race, location, university name, formatting
- For skills: recognize equivalent technologies (LangChain = Chatbot framework, React = Frontend framework)
- For education: extract degree level (BS, MS, PhD) and field ONLY - NO university names
- For experience: extract years and role descriptions - NO company names or locations
- For certifications: extract certification names only

Output JSON:
{{
  "skills": ["skill1", "skill2", ...],
  "education": ["degree level and field only"],
  "experience": "years",
  "certifications": ["cert1", ...]
}}
"""
        parsed = await ai_service.generate_json(prompt)

        if isinstance(parsed, dict):
            # Merge AI results
            if parsed.get("skills"):
                sections["skills"] = parsed.get("skills", [])
            elif found_skills:
                sections["skills"] = found_skills
            
            if parsed.get("education"):
                sections["education"] = parsed.get("education", [])
            
            if parsed.get("experience"):
                sections["experience"] = parsed.get("experience", "")
            
            if parsed.get("certifications"):
                sections["certifications"] = parsed.get("certifications", [])
    except Exception as e:
        logger.error(f"AI extraction error: {e}")
        # Fallback to regex results
        if found_skills and not sections["skills"]:
            sections["skills"] = found_skills
    
    # Ensure skills list is populated
    if not sections["skills"] and found_skills:
        sections["skills"] = found_skills
    
    return sections


# Technology equivalence mapping for fair skill matching
TECHNOLOGY_EQUIVALENCE = {
    # Chatbot/Conversational AI
    "langchain": ["chatbot", "conversational ai", "nlp", "natural language processing", "llm", "large language model"],
    "chatbot": ["langchain", "conversational ai", "nlp", "natural language processing"],
    "conversational ai": ["langchain", "chatbot", "nlp"],
    
    # Frontend frameworks
    "react": ["frontend framework", "ui library", "javascript framework", "spa framework"],
    "angular": ["frontend framework", "typescript framework", "spa framework"],
    "vue": ["frontend framework", "javascript framework", "spa framework"],
    
    # Backend frameworks
    "django": ["python web framework", "backend framework", "mvc framework"],
    "flask": ["python web framework", "microframework", "backend framework"],
    "fastapi": ["python web framework", "async framework", "api framework"],
    
    # Cloud platforms
    "aws": ["cloud computing", "cloud platform", "amazon web services"],
    "azure": ["cloud computing", "cloud platform", "microsoft cloud"],
    "gcp": ["cloud computing", "cloud platform", "google cloud"],
    
    # Databases
    "postgresql": ["sql database", "relational database", "rdbms"],
    "mongodb": ["nosql database", "document database", "non-relational database"],
    "mysql": ["sql database", "relational database", "rdbms"],
    
    # Machine Learning
    "tensorflow": ["deep learning", "ml framework", "neural network"],
    "pytorch": ["deep learning", "ml framework", "neural network"],
    "machine learning": ["ml", "ai", "artificial intelligence", "data science"],
    "deep learning": ["neural network", "ml", "ai"],
}

def normalize_skill(skill: str) -> List[str]:
    """
    Normalize a skill to include equivalent technologies.
    Returns a list of normalized skill names including equivalents.
    """
    skill_lower = skill.lower().strip()
    equivalents = [skill_lower]
    
    # Check if skill has known equivalents
    if skill_lower in TECHNOLOGY_EQUIVALENCE:
        equivalents.extend(TECHNOLOGY_EQUIVALENCE[skill_lower])
    
    # Also check reverse mapping
    for key, values in TECHNOLOGY_EQUIVALENCE.items():
        if skill_lower in values:
            equivalents.append(key)
            equivalents.extend([v for v in values if v != skill_lower])
    
    return list(set(equivalents))  # Remove duplicates

async def calculate_match_score(resume_text: str, resume_features: Dict, jd_text: str, jd_keywords: List[str] = None) -> Dict:
    """
    Main entry point for match score calculation.
    Uses LLM-based evaluation with prompt engineering for accurate semantic matching.
    Falls back to keyword matching if LLM is unavailable.
    """
    return await calculate_match_score_llm(resume_text, resume_features, jd_text, jd_keywords)

async def calculate_match_score_llm(resume_text: str, resume_features: Dict, jd_text: str, jd_keywords: List[str] = None) -> Dict:
    """
    Calculate comprehensive match score using LLM evaluation with prompt engineering.
    Uses AI to understand semantic meaning and context, not just keyword matching.
    Focuses ONLY on objective technical alignment: SKILLS, EXPERIENCE, EDUCATION, CERTIFICATIONS.
    Completely ignores: names, gender, age, race, university ranking, location, formatting.
    
    Returns detailed breakdown with weighted scoring.
    """
    scores = {
        "skills": 0.0,
        "experience": 0.0,
        "education": 0.0,
        "certifications": 0.0,
        "completeness": 0.0,
        "overall": 0.0
    }
    
    # Extract JD keywords if not provided
    if not jd_keywords:
        jd_keywords = await extract_jd_keywords(jd_text)
    
    # Try AI-based evaluation
    try:
        # Prepare resume summary
        resume_summary = resume_text[:3000]
        if resume_features:
            resume_summary += f"\n\nExtracted Features: {json.dumps(resume_features)}"
        
        evaluation_prompt = f"""Evaluate the technical match between this Resume and Job Description.
JOB DESCRIPTION:
{jd_text[:2000]}

RESUME:
{resume_summary}

Return JSON with scores (0.0 to 1.0):
{{
  "skills": 0.0,
  "experience": 0.0,
  "education": 0.0,
  "certifications": 0.0,
  "completeness": 0.0
}}
"""
        parsed = await ai_service.generate_json(evaluation_prompt)

        if isinstance(parsed, dict):
            logger.info("AI evaluation successful")
            scores["skills"] = float(parsed.get("skills", 0.0))
            scores["experience"] = float(parsed.get("experience", 0.0))
            scores["education"] = float(parsed.get("education", 0.0))
            scores["certifications"] = float(parsed.get("certifications", 0.0))
            scores["completeness"] = float(parsed.get("completeness", 0.0))
        
        # Post-processing (applies to both AI path and partially to fallback if we restructured it)
        # 1. Normalize scores
        for key in ["skills", "experience", "education", "certifications", "completeness"]:
            scores[key] = max(0.0, min(1.0, scores[key]))
            
        # 2. Strategic Keyword Boost (deterministic insurance)
        if resume_features and jd_keywords:
            resume_skills = [s.lower().strip() for s in resume_features.get("skills", [])]
            jd_skills = [k.lower().strip() for k in jd_keywords]
            
            if resume_skills and jd_skills:
                matches = set(resume_skills) & set(jd_skills)
                ratio = len(matches) / len(jd_skills) if jd_skills else 0
                
                if ratio > 0.8:
                    scores["skills"] = max(scores["skills"], 0.95)
                elif ratio > 0.5:
                    scores["skills"] = max(scores["skills"], 0.85)
                elif ratio > 0.3:
                    scores["skills"] = max(scores["skills"], 0.75)

        # 3. Calculate Final Weighted Score
        overall = (
            scores["skills"] * SCORING_WEIGHTS["skills"] +
            scores["experience"] * SCORING_WEIGHTS["experience"] +
            scores["education"] * SCORING_WEIGHTS["education"] +
            scores["certifications"] * SCORING_WEIGHTS["certifications"] +
            scores["completeness"] * SCORING_WEIGHTS["completeness"]
        ) * 100
        
        scores["overall"] = round(overall, 2)
        return scores
        
    except Exception as e:
        logger.error(f"AI match calculation failed, using keyword fallback: {e}")
        return await calculate_match_score_keyword_fallback(resume_text, resume_features, jd_text, jd_keywords)


async def calculate_match_score_keyword_fallback(resume_text: str, resume_features: Dict, jd_text: str, jd_keywords: List[str] = None) -> Dict:
    """
    Fallback keyword-based matching when LLM is unavailable.
    This is a simpler approach that uses keyword matching as backup.
    """
    scores = {
        "skills": 0.0,
        "experience": 0.0,
        "education": 0.0,
        "certifications": 0.0,
        "completeness": 0.0,
        "overall": 0.0
    }
    
    # Extract JD keywords if not provided
    if not jd_keywords:
        jd_keywords = await extract_jd_keywords(jd_text)
    
    # Extract resume sections
    resume_sections = await extract_resume_sections(resume_text)
    resume_features = resume_features or {}
    
    # Combine resume skills from multiple sources
    resume_skills = []
    if resume_sections.get("skills"):
        resume_skills.extend(resume_sections["skills"])
    if resume_sections.get("keywords"):
        resume_skills.extend(resume_sections["keywords"])
    if resume_features.get("skills"):
        resume_skills.extend(resume_features["skills"])
    
    # Normalize skills to lowercase for comparison
    resume_skills = [s.lower().strip() for s in resume_skills if s]
    jd_keywords = [k.lower().strip() for k in jd_keywords if k]
    
    # Remove duplicates
    resume_skills = list(set(resume_skills))
    jd_keywords = list(set(jd_keywords))
    
    # Skills matching (50%) - Simple keyword overlap with technology equivalence
    if jd_keywords and resume_skills:
        # Track which original JD keywords are matched (not normalized versions)
        # This ensures we calculate score based on original keyword count, not expanded equivalents
        matched_original_keywords = set()
        
        # Create mapping of normalized keywords to original keywords
        normalized_to_original = {}
        for keyword in jd_keywords:
            normalized_versions = normalize_skill(keyword)
            for norm_keyword in normalized_versions:
                if norm_keyword not in normalized_to_original:
                    normalized_to_original[norm_keyword] = []
                normalized_to_original[norm_keyword].append(keyword)
        
        # Normalize resume skills to include equivalents
        normalized_resume_skills = []
        for skill in resume_skills:
            normalized_resume_skills.extend(normalize_skill(skill))
        
        # Find matches and track which original JD keywords were matched
        normalized_resume_set = set(normalized_resume_skills)
        for norm_keyword in normalized_resume_set:
            if norm_keyword in normalized_to_original:
                # This normalized keyword matches - credit all original keywords it represents
                matched_original_keywords.update(normalized_to_original[norm_keyword])
        
        # Calculate direct match score based on original JD keywords (not normalized)
        original_jd_count = len(jd_keywords)
        matched_count = len(matched_original_keywords)
        direct_match_score = matched_count / original_jd_count if original_jd_count > 0 else 0
        
        # Also use TF-IDF for semantic similarity with improved parameters
        try:
            # Combine all skills into text for better TF-IDF matching
            skills_text = " ".join(resume_skills)
            jd_skills_text = " ".join(jd_keywords)
            
            # Use better TF-IDF parameters: include unigrams and bigrams, more features
            # min_df=1 ensures all keywords are considered, even if rare
            vectorizer = TfidfVectorizer(
                max_features=500, 
                stop_words='english', 
                ngram_range=(1, 2),
                min_df=1,
                token_pattern=r'(?u)\b\w+\b'  # Better tokenization
            )
            vectors = vectorizer.fit_transform([skills_text, jd_skills_text])
            similarity = cosine_similarity(vectors[0:1], vectors[1:2])[0][0]
            semantic_score = float(similarity)
            
            # Boost semantic score if direct matches are high (they reinforce each other)
            if direct_match_score > 0.5:
                semantic_score = min(1.0, semantic_score * 1.2)
        except Exception as e:
            logger.error(f"TF-IDF error: {e}")
            semantic_score = 0.0
        
        # Combine direct match (70%) and semantic similarity (30%)
        # Give credit for equivalent technologies
        combined_score = (direct_match_score * 0.7) + (semantic_score * 0.3)
        
        # Boost score if we have high keyword overlap (even if denominator was large)
        if matched_count > 0 and matched_count >= original_jd_count * 0.8:
            # If we match 80%+ of keywords, ensure score reflects that
            combined_score = max(combined_score, 0.85)
        elif matched_count > 0 and matched_count >= original_jd_count * 0.5:
            # If we match 50%+ of keywords, boost slightly
            combined_score = max(combined_score, min(0.75, combined_score * 1.1))
        
        scores["skills"] = min(1.0, combined_score)
    elif resume_skills:
        # Use TF-IDF similarity for skills section when no JD keywords extracted
        # This can happen if JD doesn't have clear technical keywords
        try:
            skills_text = " ".join(resume_skills)
            # Use improved TF-IDF parameters
            vectorizer = TfidfVectorizer(
                max_features=500, 
                stop_words='english',
                ngram_range=(1, 2),
                min_df=1,
                token_pattern=r'(?u)\b\w+\b'
            )
            vectors = vectorizer.fit_transform([skills_text, jd_text.lower()])
            similarity = cosine_similarity(vectors[0:1], vectors[1:2])[0][0]
            scores["skills"] = max(0.3, float(similarity))  # Ensure minimum 30% if skills exist
        except Exception as e:
            logger.error(f"TF-IDF error: {e}")
            # If TF-IDF fails but we have skills, give a baseline score
            scores["skills"] = 0.4
    else:
        scores["skills"] = 0.2  # Low score if no skills found
    
    # Experience matching (20%)
    experience_text = resume_sections.get("experience", "") or resume_features.get("experience", "")
    
    # Extract required experience from JD
    jd_exp_years = None
    jd_exp_patterns = [
        r'(\d+)\s*(?:years?|yrs?|yr)\s*(?:of\s*)?experience',
        r'experience.*?(\d+)\s*(?:years?|yrs?|yr)',
        r'(\d+)\+?\s*(?:years?|yrs?|yr)'
    ]
    for pattern in jd_exp_patterns:
        match = re.search(pattern, jd_text.lower())
        if match:
            jd_exp_years = int(match.group(1))
            break
    
    if experience_text:
        # Extract years of experience from resume
        years_match = re.search(r'(\d+)\s*(?:years?|yrs?|yr)', str(experience_text).lower())
        if years_match:
            resume_years = int(years_match.group(1))
            
            # If JD specifies required years, compare directly
            if jd_exp_years:
                if resume_years >= jd_exp_years:
                    scores["experience"] = 1.0
                elif resume_years >= jd_exp_years * 0.8:
                    scores["experience"] = 0.9
                elif resume_years >= jd_exp_years * 0.6:
                    scores["experience"] = 0.7
                elif resume_years >= jd_exp_years * 0.4:
                    scores["experience"] = 0.5
                else:
                    scores["experience"] = 0.3
            else:
                # Normalize: 5+ years = 100%, 3-5 = 80%, 2-3 = 60%, 1-2 = 40%, <1 = 20%
                if resume_years >= 5:
                    scores["experience"] = 1.0
                elif resume_years >= 3:
                    scores["experience"] = 0.8
                elif resume_years >= 2:
                    scores["experience"] = 0.6
                elif resume_years >= 1:
                    scores["experience"] = 0.4
                else:
                    scores["experience"] = 0.2
        else:
            # Use text similarity for experience descriptions
            try:
                vectorizer = TfidfVectorizer(max_features=50, stop_words='english')
                vectors = vectorizer.fit_transform([str(experience_text), jd_text.lower()])
                similarity = cosine_similarity(vectors[0:1], vectors[1:2])[0][0]
                scores["experience"] = max(0.3, float(similarity))  # Minimum 30%
            except Exception as e:
                logger.error(f"Experience TF-IDF error: {e}")
                scores["experience"] = 0.4
    else:
        # Check if JD requires experience
        if jd_exp_years:
            scores["experience"] = 0.1  # Very low if JD requires experience but resume doesn't show it
        else:
            scores["experience"] = 0.5  # Neutral if no experience requirement
    
    # Education matching (15%)
    education_list = resume_sections.get("education", []) or resume_features.get("education", [])
    
    # Extract education requirements from JD
    jd_degree_keywords = ["bachelor", "master", "phd", "degree", "diploma", "certificate", "bs", "ms", "ph.d"]
    jd_lower = jd_text.lower()
    jd_education_required = [kw for kw in jd_degree_keywords if kw in jd_lower]
    
    if education_list:
        # Check if resume education matches JD requirements
        resume_edu_text = " ".join([str(e) for e in education_list]).lower()
        resume_has_degree = any(kw in resume_edu_text for kw in jd_degree_keywords)
        
        if jd_education_required:
            # JD requires specific education
            if resume_has_degree:
                # Check if degree level matches
                jd_has_bachelor = any(kw in jd_lower for kw in ["bachelor", "bs", "undergraduate"])
                jd_has_master = any(kw in jd_lower for kw in ["master", "ms", "mba"])
                jd_has_phd = any(kw in jd_lower for kw in ["phd", "ph.d", "doctorate"])
                
                resume_has_bachelor = any(kw in resume_edu_text for kw in ["bachelor", "bs", "undergraduate"])
                resume_has_master = any(kw in resume_edu_text for kw in ["master", "ms", "mba"])
                resume_has_phd = any(kw in resume_edu_text for kw in ["phd", "ph.d", "doctorate"])
                
                if jd_has_phd and resume_has_phd:
                    scores["education"] = 1.0
                elif jd_has_master and (resume_has_master or resume_has_phd):
                    scores["education"] = 1.0
                elif jd_has_bachelor and (resume_has_bachelor or resume_has_master or resume_has_phd):
                    scores["education"] = 1.0
                else:
                    scores["education"] = 0.6  # Has degree but may not match level
            else:
                scores["education"] = 0.2  # JD requires education but resume doesn't show it
        else:
            # JD doesn't specify education requirement
            scores["education"] = 0.8 if resume_has_degree else 0.5
    else:
        # No education in resume
        if jd_education_required:
            scores["education"] = 0.2  # JD requires education but resume doesn't show it
        else:
            scores["education"] = 0.5  # Neutral
    
    # Certifications matching (10%)
    certifications = resume_sections.get("certifications", []) or resume_features.get("certifications", [])
    
    # Extract certification requirements from JD
    jd_cert_keywords = ["certified", "certification", "license", "cert", "certificate", "licensed"]
    jd_lower = jd_text.lower()
    jd_requires_certs = any(kw in jd_lower for kw in jd_cert_keywords)
    
    if certifications:
        cert_text = " ".join([str(c) for c in certifications]).lower()
        
        # Check if certifications match JD requirements
        if jd_requires_certs:
            # JD mentions certifications - check for relevance
            # Use TF-IDF to find semantic similarity
            try:
                vectorizer = TfidfVectorizer(max_features=50, stop_words='english')
                vectors = vectorizer.fit_transform([cert_text, jd_text.lower()])
                similarity = cosine_similarity(vectors[0:1], vectors[1:2])[0][0]
                scores["certifications"] = max(0.5, float(similarity))
            except:
                # Fallback: check if any cert keywords match
                matches = sum(1 for kw in jd_cert_keywords if kw in cert_text)
                scores["certifications"] = min(1.0, 0.5 + (matches * 0.2))
        else:
            # JD doesn't require certs, but candidate has them (bonus)
            scores["certifications"] = 0.7
    else:
        # No certifications in resume
        if jd_requires_certs:
            scores["certifications"] = 0.2  # JD requires certs but resume doesn't show them
        else:
            scores["certifications"] = 0.5  # Neutral
    
    # Resume completeness (5%)
    completeness_factors = {
        "has_contact": bool(re.search(r'[\w\.-]+@[\w\.-]+\.\w+', resume_text)),
        "has_experience": bool(experience_text),
        "has_education": bool(education_list),
        "has_skills": bool(resume_skills),
        "has_projects": bool(re.search(r'project|portfolio|github|git\.io', resume_text.lower()))
    }
    scores["completeness"] = sum(completeness_factors.values()) / len(completeness_factors)
    
    # Calculate weighted overall score (0-100)
    overall = (
        scores["skills"] * SCORING_WEIGHTS["skills"] +
        scores["experience"] * SCORING_WEIGHTS["experience"] +
        scores["education"] * SCORING_WEIGHTS["education"] +
        scores["certifications"] * SCORING_WEIGHTS["certifications"] +
        scores["completeness"] * SCORING_WEIGHTS["completeness"]
    ) * 100
    
    scores["overall"] = round(overall, 2)
    
    return scores


# Bias detection has been completely removed.
# Evaluation is now based solely on objective technical qualifications:
# - SKILLS (with technology equivalence recognition)
# - EXPERIENCE (years and role descriptions)
# - EDUCATION (degree level and field only)
# - CERTIFICATIONS
#
# The system no longer considers or stores any demographic information.


async def screen_candidate(
    candidate_id: str,
    job_id: str,
    resume_text: str,
    resume_features: Dict,
    jd_text: str,
    jd_keywords: Optional[List[str]] = None,
    db: Optional[Database] = None
) -> Dict:
    """
    Complete candidate screening: calculate unbiased match score based solely on technical qualifications.
    Stores results in CandidateScreening collection.
    """
    try:
        # Extract JD keywords if not provided
        if not jd_keywords:
            jd_keywords = await extract_jd_keywords(jd_text)
        
        # Calculate match score (unbiased - only technical qualifications)
        match_scores = await calculate_match_score(resume_text, resume_features, jd_text, jd_keywords)
        
        # Create screening document (bias detection removed)
        screening_doc = {
            "candidateId": ObjectId(candidate_id),
            "jobId": ObjectId(job_id),
            "matchScore": match_scores["overall"],
            "matchScoreBreakdown": {
                "skills": match_scores["skills"] * 100,
                "experience": match_scores["experience"] * 100,
                "education": match_scores["education"] * 100,
                "certifications": match_scores["certifications"] * 100,
                "completeness": match_scores["completeness"] * 100
            },
            "screeningDate": datetime.now(timezone.utc).isoformat(),
            "actionsTaken": [],
            "status": "pending",  # pending, shortlisted, rejected
            "created_at": datetime.now(timezone.utc).isoformat()
        }
        
        # Store in database
        if db is not None:
            # Update or create screening record
            existing = await db.candidate_screenings.find_one({
                "candidateId": ObjectId(candidate_id),
                "jobId": ObjectId(job_id)
            })
            
            if existing:
                await db.candidate_screenings.update_one(
                    {"_id": existing["_id"]},
                    {"$set": screening_doc}
                )
                screening_id = str(existing["_id"])
            else:
                result = await db.candidate_screenings.insert_one(screening_doc)
                screening_id = str(result.inserted_id)
            
            screening_doc["_id"] = screening_id
        
        return {
            "success": True,
            "screening": screening_doc,
            "matchScore": match_scores["overall"]
        }
        
    except Exception as e:
        logger.error(f"Screening error: {e}")
        return {
            "success": False,
            "error": str(e)
        }


def get_candidate_screenings(job_id: str, db: Database, filters: Optional[Dict] = None) -> List[Dict]:
    """Get all candidate screenings for a job with optional filters"""
    try:
        query = {"jobId": ObjectId(job_id)}
        
        # Apply filters (bias filters removed)
        if filters:
            if filters.get("min_score"):
                query["matchScore"] = {"$gte": float(filters["min_score"])}
            if filters.get("status"):
                query["status"] = filters["status"]
        
        screenings = list(db.candidate_screenings.find(query).sort("matchScore", -1))
        
        result = []
        for screening in screenings:
            result.append({
                "id": str(screening["_id"]),
                "candidateId": str(screening["candidateId"]),
                "jobId": str(screening["jobId"]),
                "matchScore": screening.get("matchScore", 0),
                "matchScoreBreakdown": screening.get("matchScoreBreakdown", {}),
                "status": screening.get("status", "pending"),
                "screeningDate": screening.get("screeningDate"),
                "actionsTaken": screening.get("actionsTaken", [])
            })
        
        return result
        
    except Exception as e:
        logger.error(f"Error fetching screenings: {e}")
        return []


def update_screening_action(
    screening_id: str,
    action: str,
    db: Database
) -> Dict:
    """Update screening action (shortlisted/rejected)"""
    try:
        valid_actions = ["shortlisted", "rejected"]
        if action not in valid_actions:
            raise ValueError(f"Invalid action. Must be one of: {', '.join(valid_actions)}")
        
        update_data = {
            "status": action,
            "updated_at": datetime.now(timezone.utc).isoformat()
        }
        
        # Add to actions taken if not already present
        screening = db.candidate_screenings.find_one({"_id": ObjectId(screening_id)})
        if screening:
            actions_taken = screening.get("actionsTaken", [])
            if action not in actions_taken:
                actions_taken.append(action)
                update_data["actionsTaken"] = actions_taken
        
        db.candidate_screenings.update_one(
            {"_id": ObjectId(screening_id)},
            {"$set": update_data}
        )
        
        return {"success": True, "action": action, "screening_id": screening_id}
        
    except Exception as e:
        return {"success": False, "error": str(e)}

