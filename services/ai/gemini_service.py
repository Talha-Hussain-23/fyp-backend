"""
Gemini AI Service - Fallback for Question Generation and Evaluation
Secondary AI provider when Groq is unavailable
"""

from google import genai
import os
import json
import logging
from typing import List, Dict, Optional

logger = logging.getLogger(__name__)


class GeminiService:
    """
    Gemini AI service as fallback for interview questions and evaluation
    Uses Google's Gemini API when Groq is unavailable
    """
    
    def __init__(self, api_key: str = None):
        self.api_key = api_key or os.getenv("GEMINI_API_KEY")
        if not self.api_key:
            raise ValueError("GEMINI_API_KEY not found in environment")
        
        # New google.genai client
        self.client = genai.Client(api_key=self.api_key)
        self.model_name = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")
        self.max_retries = 3
    
    async def generate_questions(
        self,
        job_description: str,
        difficulty: str = "medium",
        count: int = 5,
        categories: List[str] = None
    ) -> List[Dict]:
        """
        Generate interview questions using Gemini
        
        Args:
            job_description: Job description text
            difficulty: easy, medium, hard
            count: Number of questions to generate
            categories: List of categories
        
        Returns:
            List of question dictionaries
        """
        
        if categories is None:
            categories = ["technical", "communication", "problem_solving", "creativity"]
        
        prompt = f"""Generate {count} interview questions for this job:

{job_description}

Requirements:
- Difficulty: {difficulty}
- Categories: {', '.join(categories)}
- Mix of theoretical and practical questions
- Clear and specific

Return ONLY valid JSON array:
[
  {{
    "question": "Question text",
    "type": "Descriptive",
    "category": "technical",
    "difficulty": "{difficulty}",
    "keywords": ["keyword1", "keyword2"],
    "expected_answer_length": 200
  }}
]"""
        
        try:
            response = self.client.models.generate_content(
                model=self.model_name,
                contents=prompt
            )
            text = response.text
            
            # Extract JSON from response
            if "```json" in text:
                text = text.split("```json")[1].split("```")[0].strip()
            elif "```" in text:
                text = text.split("```")[1].split("```")[0].strip()
            
            questions = json.loads(text)
            return questions[:count]
            
        except Exception as e:
            logger.error(f"Gemini question generation failed: {e}")
            raise
    
    async def evaluate_answer(
        self,
        question: str,
        answer: str,
        expected_keywords: List[str] = None
    ) -> Dict:
        """
        Evaluate answer using Gemini AI
        
        Args:
            question: The interview question
            answer: Candidate's answer
            expected_keywords: Optional keywords
        
        Returns:
            Evaluation dict
        """
        
        keywords_text = ""
        if expected_keywords:
            keywords_text = f"\nExpected Keywords: {', '.join(expected_keywords)}"
        
        prompt = f"""Evaluate this interview answer:

Question: {question}

Answer: {answer}
{keywords_text}

Rate on 4 criteria (0-10):
1. Relevance
2. Completeness
3. Accuracy
4. Clarity

Return ONLY valid JSON:
{{
  "relevance": 8,
  "completeness": 7,
  "accuracy": 9,
  "clarity": 8,
  "overall_score": 8.0,
  "feedback": "Detailed feedback",
  "strengths": ["strength1"],
  "improvements": ["improvement1"]
}}"""
        
        try:
            response = self.client.models.generate_content(
                model=self.model_name,
                contents=prompt
            )
            text = response.text
            
            # Extract JSON
            if "```json" in text:
                text = text.split("```json")[1].split("```")[0].strip()
            elif "```" in text:
                text = text.split("```")[1].split("```")[0].strip()
            
            return json.loads(text)
            
        except Exception as e:
            logger.error(f"Gemini evaluation failed: {e}")
            raise


# Singleton
_gemini_service = None

def get_gemini_service() -> GeminiService:
    """Get or create Gemini service singleton"""
    global _gemini_service
    if _gemini_service is None:
        _gemini_service = GeminiService()
    return _gemini_service
