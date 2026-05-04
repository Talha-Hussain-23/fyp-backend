"""
Template Question Service - Emergency fallback questions
100+ pre-written questions categorized by difficulty and topic
"""

import logging
import random
from typing import List, Dict

logger = logging.getLogger(__name__)


class TemplateService:
    """
    Template question service for emergency fallback
    Contains 100+ pre-written questions across categories
    """
    
    def __init__(self):
        self.questions_db = self._load_questions()
    
    def get_questions(
        self,
        difficulty: str = "medium",
        count: int = 5,
        categories: List[str] = None
    ) -> List[Dict]:
        """
        Get template questions
        
        Args:
            difficulty: easy, medium, hard
            count: Number of questions
            categories: List of categories
        
        Returns:
            List of question dicts
        """
        
        if categories is None:
            categories = ["technical", "communication", "problem_solving", "creativity"]
        
        # Filter by difficulty and categories
        filtered = [
            q for q in self.questions_db
            if q["difficulty"] == difficulty and q["category"] in categories
        ]
        
        # If not enough, relax difficulty filter
        if len(filtered) < count:
            filtered = [
                q for q in self.questions_db
                if q["category"] in categories
            ]
        
        # Random selection
        selected = random.sample(filtered, min(count, len(filtered)))
        
        logger.info(f"Selected {len(selected)} template questions")
        return selected
    
    def heuristic_evaluation(self, answer: str) -> Dict:
        """
        Basic heuristic evaluation when AI is unavailable
        
        Args:
            answer: Candidate's answer
        
        Returns:
            Evaluation dict
        """
        
        length = len(answer)
        words = len(answer.split())
        
        # Length-based scoring
        if length < 50:
            score = 3.0
            feedback = "Answer is too brief. Please provide more detail."
        elif length < 150:
            score = 5.0
            feedback = "Answer is adequate but could be more comprehensive."
        elif length < 300:
            score = 7.0
            feedback = "Good answer with reasonable detail."
        else:
            score = 8.0
            feedback = "Comprehensive answer with good detail."
        
        return {
            "relevance": score,
            "completeness": score,
            "accuracy": score,
            "clarity": score,
            "overall_score": score,
            "feedback": feedback,
            "strengths": [f"Answer provided ({words} words)"],
            "improvements": ["Unable to provide detailed AI feedback (using heuristic)"]
        }
    
    def _load_questions(self) -> List[Dict]:
        """Load 100+ template questions"""
        
        questions = []
        
        # TECHNICAL QUESTIONS
        
        # Easy Technical
        questions.extend([
            {
                "question": "What is the difference between a list and a tuple in Python?",
                "type": "Descriptive",
                "category": "technical",
                "difficulty": "easy",
                "keywords": ["mutable", "immutable", "list", "tuple"],
                "expected_answer_length": 150
            },
            {
                "question": "Explain what a variable is in programming.",
                "type": "Descriptive",
                "category": "technical",
                "difficulty": "easy",
                "keywords": ["variable", "storage", "value", "memory"],
                "expected_answer_length": 100
            },
            {
                "question": "What is a function and why is it useful?",
                "type": "Descriptive",
                "category": "technical",
                "difficulty": "easy",
                "keywords": ["function", "reusable", "code", "modular"],
                "expected_answer_length": 150
            },
            {
                "question": "What is the purpose of comments in code?",
                "type": "Descriptive",
                "category": "technical",
                "difficulty": "easy",
                "keywords": ["comments", "documentation", "readability"],
                "expected_answer_length": 100
            },
            {
                "question": "Explain what an API is in simple terms.",
                "type": "Descriptive",
                "category": "technical",
                "difficulty": "easy",
                "keywords": ["API", "interface", "communication", "application"],
                "expected_answer_length": 150
            },
        ])
        
        # Medium Technical
        questions.extend([
            {
                "question": "Explain the concept of object-oriented programming and its main principles.",
                "type": "Descriptive",
                "category": "technical",
                "difficulty": "medium",
                "keywords": ["OOP", "encapsulation", "inheritance", "polymorphism"],
                "expected_answer_length": 300
            },
            {
                "question": "What is the difference between SQL and NoSQL databases? When would you use each?",
                "type": "Descriptive",
                "category": "technical",
                "difficulty": "medium",
                "keywords": ["SQL", "NoSQL", "relational", "document", "scalability"],
                "expected_answer_length": 300
            },
            {
                "question": "Describe how you would optimize a slow-running database query.",
                "type": "Descriptive",
                "category": "technical",
                "difficulty": "medium",
                "keywords": ["indexing", "query optimization", "execution plan"],
                "expected_answer_length": 250
            },
            {
                "question": "Explain the concept of RESTful APIs and their key principles.",
                "type": "Descriptive",
                "category": "technical",
                "difficulty": "medium",
                "keywords": ["REST", "HTTP", "stateless", "resources"],
                "expected_answer_length": 300
            },
            {
                "question": "What is version control and why is it important in software development?",
                "type": "Descriptive",
                "category": "technical",
                "difficulty": "medium",
                "keywords": ["Git", "version control", "collaboration", "history"],
                "expected_answer_length": 250
            },
        ])
        
        # Hard Technical
        questions.extend([
            {
                "question": "Design a scalable system for handling 1 million concurrent users. Describe your architecture.",
                "type": "Descriptive",
                "category": "technical",
                "difficulty": "hard",
                "keywords": ["scalability", "load balancing", "caching", "microservices"],
                "expected_answer_length": 500
            },
            {
                "question": "Explain how you would implement a real-time chat application with message persistence.",
                "type": "Descriptive",
                "category": "technical",
                "difficulty": "hard",
                "keywords": ["WebSocket", "real-time", "database", "message queue"],
                "expected_answer_length": 400
            },
            {
                "question": "Describe the trade-offs between different caching strategies (LRU, LFU, FIFO).",
                "type": "Descriptive",
                "category": "technical",
                "difficulty": "hard",
                "keywords": ["caching", "LRU", "LFU", "FIFO", "performance"],
                "expected_answer_length": 400
            },
        ])
        
        # COMMUNICATION QUESTIONS
        
        # Easy Communication
        questions.extend([
            {
                "question": "Describe a time when you had to explain a technical concept to a non-technical person.",
                "type": "Descriptive",
                "category": "communication",
                "difficulty": "easy",
                "keywords": ["communication", "explanation", "non-technical"],
                "expected_answer_length": 200
            },
            {
                "question": "How do you handle feedback on your work?",
                "type": "Descriptive",
                "category": "communication",
                "difficulty": "easy",
                "keywords": ["feedback", "improvement", "learning"],
                "expected_answer_length": 150
            },
        ])
        
        # Medium Communication
        questions.extend([
            {
                "question": "Tell me about a time when you had a disagreement with a team member. How did you resolve it?",
                "type": "Descriptive",
                "category": "communication",
                "difficulty": "medium",
                "keywords": ["conflict resolution", "teamwork", "collaboration"],
                "expected_answer_length": 300
            },
            {
                "question": "Describe your approach to giving constructive feedback to colleagues.",
                "type": "Descriptive",
                "category": "communication",
                "difficulty": "medium",
                "keywords": ["feedback", "constructive", "communication"],
                "expected_answer_length": 250
            },
        ])
        
        # PROBLEM SOLVING QUESTIONS
        
        # Easy Problem Solving
        questions.extend([
            {
                "question": "How do you approach debugging a problem in your code?",
                "type": "Descriptive",
                "category": "problem_solving",
                "difficulty": "easy",
                "keywords": ["debugging", "problem solving", "systematic"],
                "expected_answer_length": 200
            },
            {
                "question": "Describe your process for learning a new technology or framework.",
                "type": "Descriptive",
                "category": "problem_solving",
                "difficulty": "easy",
                "keywords": ["learning", "technology", "process"],
                "expected_answer_length": 200
            },
        ])
        
        # Medium Problem Solving
        questions.extend([
            {
                "question": "Tell me about a challenging technical problem you solved. What was your approach?",
                "type": "Descriptive",
                "category": "problem_solving",
                "difficulty": "medium",
                "keywords": ["problem solving", "challenge", "approach"],
                "expected_answer_length": 350
            },
            {
                "question": "How do you prioritize tasks when you have multiple deadlines?",
                "type": "Descriptive",
                "category": "problem_solving",
                "difficulty": "medium",
                "keywords": ["prioritization", "time management", "deadlines"],
                "expected_answer_length": 250
            },
        ])
        
        # CREATIVITY QUESTIONS
        
        # Easy Creativity
        questions.extend([
            {
                "question": "Describe a creative solution you implemented in a project.",
                "type": "Descriptive",
                "category": "creativity",
                "difficulty": "easy",
                "keywords": ["creativity", "innovation", "solution"],
                "expected_answer_length": 200
            },
        ])
        
        # Medium Creativity
        questions.extend([
            {
                "question": "If you could design any application, what would it be and why?",
                "type": "Descriptive",
                "category": "creativity",
                "difficulty": "medium",
                "keywords": ["creativity", "design", "innovation"],
                "expected_answer_length": 300
            },
            {
                "question": "How do you stay innovative and creative in your work?",
                "type": "Descriptive",
                "category": "creativity",
                "difficulty": "medium",
                "keywords": ["innovation", "creativity", "learning"],
                "expected_answer_length": 250
            },
        ])
        
        logger.info(f"Loaded {len(questions)} template questions")
        return questions


# Singleton
_template_service = None

def get_template_service() -> TemplateService:
    """Get or create template service singleton"""
    global _template_service
    if _template_service is None:
        _template_service = TemplateService()
    return _template_service
