"""
Groq AI Service for Question Generation and Answer Evaluation
Primary AI provider with retry logic and error handling
"""

from groq import Groq
import os
import json
import logging
from typing import List, Dict, Optional
from datetime import datetime

logger = logging.getLogger(__name__)


class GroqService:
    """
    Groq AI service for interview questions and evaluation
    Uses Groq's LLM API for intelligent question generation and scoring
    """
    
    def __init__(self, api_key: str = None):
        self.api_key = api_key or os.getenv("GROQ_API_KEY")
        if not self.api_key:
            raise ValueError("GROQ_API_KEY not found in environment")
        
        self.client = Groq(api_key=self.api_key)
        self.model = "llama-3.3-70b-versatile"  # Best model for reasoning
        self.max_retries = 3
    
    async def generate_questions(
        self,
        job_description: str,
        difficulty: str = "medium",
        count: int = 5,
        categories: List[str] = None
    ) -> List[Dict]:
        """
        Generate interview questions using Groq
        
        Args:
            job_description: Job description text
            difficulty: easy, medium, hard
            count: Number of questions to generate
            categories: List of categories (technical, communication, etc.)
        
        Returns:
            List of question dictionaries
        """
        
        if categories is None:
            categories = ["technical", "communication", "problem_solving", "creativity"]
        
        # Calculate questions per category (balanced distribution)
        questions_per_category = self._distribute_questions(count, len(categories))
        
        all_questions = []
        
        for category, q_count in zip(categories, questions_per_category):
            prompt = self._build_question_prompt(
                job_description, 
                category, 
                difficulty, 
                q_count
            )
            
            try:
                questions = await self._call_groq_api(prompt, "questions")
                all_questions.extend(questions)
            except Exception as e:
                logger.error(f"Failed to generate {category} questions: {e}")
                # Continue with other categories
        
        return all_questions[:count]  # Ensure exact count
    
    async def evaluate_answer(
        self,
        question: str,
        answer: str,
        expected_keywords: List[str] = None
    ) -> Dict:
        """
        Evaluate answer using Groq AI
        
        Args:
            question: The interview question
            answer: Candidate's answer
            expected_keywords: Optional keywords for evaluation
        
        Returns:
            Evaluation dict with score, feedback, criteria scores
        """
        
        prompt = self._build_evaluation_prompt(question, answer, expected_keywords)
        
        try:
            evaluation = await self._call_groq_api(prompt, "evaluation")
            return evaluation
        except Exception as e:
            logger.error(f"Failed to evaluate answer: {e}")
            # Fallback to basic scoring
            return self._fallback_evaluation(answer)
    
    def _build_question_prompt(
        self,
        job_description: str,
        category: str,
        difficulty: str,
        count: int
    ) -> str:
        """Build prompt for question generation"""
        
        return f"""You are an expert technical interviewer. Generate {count} high-quality interview questions.

Job Description:
{job_description}

Requirements:
- Category: {category}
- Difficulty: {difficulty}
- Count: {count}
- Questions should be specific, clear, and relevant to the job
- Include a mix of theoretical and practical questions
- For technical questions, include coding scenarios
- For communication questions, include situational scenarios

Return ONLY a JSON array of questions in this exact format:
[
  {{
    "question": "Question text here",
    "type": "Descriptive" or "MCQ",
    "category": "{category}",
    "difficulty": "{difficulty}",
    "keywords": ["keyword1", "keyword2"],
    "expected_answer_length": 100-500,
    "options": ["A", "B", "C", "D"] (only for MCQ)
  }}
]

Generate questions now:"""
    
    def _build_evaluation_prompt(
        self,
        question: str,
        answer: str,
        expected_keywords: List[str] = None
    ) -> str:
        """Build prompt for answer evaluation"""
        
        keywords_text = ""
        if expected_keywords:
            keywords_text = f"\nExpected Keywords: {', '.join(expected_keywords)}"
        
        return f"""You are an expert interviewer evaluating a candidate's answer.

Question: {question}

Candidate's Answer:
{answer}
{keywords_text}

Evaluate the answer on these 4 criteria (0-10 scale):
1. Relevance: How well does the answer address the question?
2. Completeness: Does it cover all important aspects?
3. Accuracy: Is the information correct and precise?
4. Clarity: Is it well-structured and easy to understand?

Return ONLY a JSON object in this exact format:
{{
  "relevance": 8,
  "completeness": 7,
  "accuracy": 9,
  "clarity": 8,
  "overall_score": 8.0,
  "feedback": "Detailed feedback explaining the scores",
  "strengths": ["strength1", "strength2"],
  "improvements": ["improvement1", "improvement2"]
}}

Evaluate now:"""
    
    async def _call_groq_api(
        self,
        prompt: str,
        response_type: str
    ) -> any:
        """
        Call Groq API with retry logic
        
        Args:
            prompt: The prompt to send
            response_type: "questions" or "evaluation"
        
        Returns:
            Parsed response
        """
        
        for attempt in range(self.max_retries):
            try:
                response = self.client.chat.completions.create(
                    model=self.model,
                    messages=[
                        {
                            "role": "system",
                            "content": "You are a professional technical interviewer. Always respond with valid JSON only."
                        },
                        {
                            "role": "user",
                            "content": prompt
                        }
                    ],
                    temperature=0.7,
                    max_tokens=2000,
                    response_format={"type": "json_object"}
                )
                
                content = response.choices[0].message.content
                
                # Parse JSON response
                if response_type == "questions":
                    data = json.loads(content)
                    # Handle both array and object with array
                    if isinstance(data, list):
                        return data
                    elif isinstance(data, dict) and "questions" in data:
                        return data["questions"]
                    else:
                        raise ValueError("Invalid questions format")
                
                elif response_type == "evaluation":
                    return json.loads(content)
                
            except json.JSONDecodeError as e:
                logger.warning(f"JSON parse error (attempt {attempt + 1}): {e}")
                if attempt == self.max_retries - 1:
                    raise
            
            except Exception as e:
                logger.warning(f"Groq API error (attempt {attempt + 1}): {e}")
                if attempt == self.max_retries - 1:
                    raise
        
        raise Exception("Max retries exceeded")
    
    def _distribute_questions(self, total: int, categories: int) -> List[int]:
        """Distribute questions evenly across categories"""
        
        base = total // categories
        remainder = total % categories
        
        distribution = [base] * categories
        for i in range(remainder):
            distribution[i] += 1
        
        return distribution
    
    def _fallback_evaluation(self, answer: str) -> Dict:
        """Fallback evaluation if AI fails"""
        
        length = len(answer)
        
        # Basic heuristic scoring
        if length < 50:
            score = 3.0
        elif length < 150:
            score = 5.0
        elif length < 300:
            score = 7.0
        else:
            score = 8.0
        
        return {
            "relevance": score,
            "completeness": score,
            "accuracy": score,
            "clarity": score,
            "overall_score": score,
            "feedback": "Evaluation performed using fallback heuristic (AI unavailable)",
            "strengths": ["Answer provided"],
            "improvements": ["Unable to provide detailed feedback"]
        }


# Singleton instance
_groq_service = None

def get_groq_service() -> GroqService:
    """Get or create Groq service singleton"""
    global _groq_service
    if _groq_service is None:
        _groq_service = GroqService()
    return _groq_service
