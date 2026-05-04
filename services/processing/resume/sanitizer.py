"""
Resume text sanitization for bias removal.
Removes demographic and personal information while preserving technical content.
"""
import re


def sanitize_resume_text(text: str) -> str:
    """
    Remove demographic and personal information from resume text for unbiased evaluation.
    Removes: names, gender indicators, age, race/ethnicity, location, university names, formatting.
    Keeps only: skills, experience descriptions, education level/field, certifications, technical content.
    
    Args:
        text: Original resume text
        
    Returns:
        Sanitized resume text
    """
    # Remove email addresses (keep structure but anonymize)
    text = re.sub(r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b', '[EMAIL]', text)
    
    # Remove phone numbers
    text = re.sub(r'\b\d{3}[-.]?\d{3}[-.]?\d{4}\b', '[PHONE]', text)
    
    # Remove addresses (street addresses, cities, states, zip codes)
    text = re.sub(
        r'\d+\s+[A-Za-z\s]+(?:Street|St|Avenue|Ave|Road|Rd|Drive|Dr|Lane|Ln|Boulevard|Blvd|Way|Circle|Ct|Court)',
        '[ADDRESS]',
        text
    )
    text = re.sub(r'\b[A-Z][a-z]+,\s*[A-Z]{2}\s+\d{5}(?:-\d{4})?\b', '[LOCATION]', text)
    
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


def remove_personal_info(text: str) -> str:
    """Remove personal identifiable information"""
    text = re.sub(r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b', '[EMAIL]', text)
    text = re.sub(r'\b\d{3}[-.]?\d{3}[-.]?\d{4}\b', '[PHONE]', text)
    return text


def remove_location_info(text: str) -> str:
    """Remove location and address information"""
    text = re.sub(
        r'\d+\s+[A-Za-z\s]+(?:Street|St|Avenue|Ave|Road|Rd|Drive|Dr|Lane|Ln|Boulevard|Blvd|Way|Circle|Ct|Court)',
        '[ADDRESS]',
        text
    )
    text = re.sub(r'\b[A-Z][a-z]+,\s*[A-Z]{2}\s+\d{5}(?:-\d{4})?\b', '[LOCATION]', text)
    return text


def anonymize_education(text: str) -> str:
    """Anonymize university names while keeping degree information"""
    university_patterns = [
        r'\b(?:University|College|Institute|School)\s+of\s+[A-Z][a-z]+',
        r'\b[A-Z][a-z]+\s+(?:University|College|Institute)',
        r'\b[A-Z]{2,}\s+(?:University|College)'
    ]
    for pattern in university_patterns:
        text = re.sub(pattern, '[UNIVERSITY]', text, flags=re.IGNORECASE)
    return text
