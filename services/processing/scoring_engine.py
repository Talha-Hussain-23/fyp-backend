"""
Scoring Engine for Interview Evaluation
Calculates detailed score breakdown for recruiter visibility
"""

from typing import Dict, List, Any
import logging

logger = logging.getLogger(__name__)


class ScoringEngine:
    """
    Production-grade scoring engine with detailed breakdown
    CRITICAL FIX #1: Provides score_breakdown for recruiter dashboard
    """
    
    def __init__(self):
        self.categories = [
            "technical",
            "communication",
            "problem_solving",
            "creativity"
        ]
    
    async def calculate_score_breakdown(
        self,
        responses: List[Dict],
        questions: List[Dict],
        interview_config: Dict = None # NEW: Optional config for weights
    ) -> Dict[str, Any]:
        """
        Calculate detailed score breakdown with optional weighted scoring
        """
        if not responses or not questions:
            logger.warning("No responses or questions provided for scoring")
            return self._get_default_breakdown()
        
        # 1. Calculate Individual Scores & Aggregate by Category / Type
        category_scores = {cat: [] for cat in self.categories}
        type_scores = {} # type -> [scores]
        
        for response in responses:
            question = self._find_question(questions, response.get("question_id"))
            if not question:
                continue
            
            # Determine Category (for qualitative feedback)
            category = question.get("category", "technical").lower()
            if category not in self.categories:
                category = "technical"
            
            # Determine Type (for weighted calculation)
            # Use 'type' from response (set by frontend/backend) or question
            q_type = response.get("type") or question.get("type") or "Descriptive"
            
            # Calculate Score
            score = await self._evaluate_response(response, question)
            
            # Aggregate
            category_scores[category].append(score)
            
            if q_type not in type_scores:
                type_scores[q_type] = []
            type_scores[q_type].append(score)
            
        # 2. Build Category Breakdown (Qualitative)
        breakdown = {}
        total_unweighted_score = 0
        active_categories = 0
        
        for category in self.categories:
            scores = category_scores[category]
            if scores:
                avg = sum(scores) / len(scores)
                breakdown[category] = {
                    "score": round(avg, 1),
                    "max": 10,
                    "feedback": self._generate_feedback(category, avg)
                }
                total_unweighted_score += avg
                active_categories += 1
            else:
                breakdown[category] = {
                    "score": 0, "max": 10, "feedback": "No questions in this category"
                }

        # 3. Calculate Overall Score (Weighted or Legacy)
        overall_score = 0.0
        
        if interview_config and "sections" in interview_config:
            # Weighted Calculation
            total_weight = 0
            weighted_sum = 0
            
            for section in interview_config["sections"]:
                if not section.get("enabled", True):
                    continue
                    
                s_type = section["type"]
                s_weight = float(section.get("weight", 0))
                s_num_questions = int(section.get("num_questions", 0))
                
                # Get average score for this section type
                s_scores = type_scores.get(s_type, [])
                if s_num_questions > 0:
                    s_avg = sum(s_scores) / s_num_questions
                    weighted_sum += s_avg * s_weight
                    total_weight += s_weight
                elif s_scores:
                    s_avg = sum(s_scores) / len(s_scores)
                    weighted_sum += s_avg * s_weight
                    total_weight += s_weight
                else:
                    # If section enabled but no answer, count weight but 0 score (penalty for skipping)
                    total_weight += s_weight
            
            if total_weight > 0:
                # Normalize. weights sum to e.g. 100 or 34+33+33=100
                overall_score = weighted_sum / total_weight
            else:
                overall_score = 0.0
                
            logger.info(f"✅ Weighted Scoring Used: {overall_score} (Total Weight: {total_weight})")
            
        else:
            # Legacy: Average of active categories
            if active_categories > 0:
                overall_score = total_unweighted_score / active_categories
            logger.info(f"ℹ️ Legacy Scoring Used: {overall_score}")

        breakdown["overall"] = round(overall_score, 1)
        breakdown["overall_score"] = round(overall_score, 1)
        return breakdown
    
    async def _evaluate_response(self, response: Dict, question: Dict) -> float:
        """
        Evaluates the candidate's response using AI (Groq/Gemini).
        
        Features:
        1. Semantic Analysis (Understanding meaning, not just keywords)
        2. Robust Error Handling (Fallback to heuristic if AI fails)
        3. Strict Rubric (Ensures 0-10 scale consistency)
        
        Returns:
            float: Score from 0.0 to 10.0
        """
        import re
        import os
        
        answer = response.get("answer", "")
        question_text = question.get("question", "")
        q_type = question.get("type", "Descriptive")
        keywords = question.get("keywords", [])
        
        # --- STEP 0: Deterministic Grading (MCQ) ---
        if q_type == "MCQ":
            # Extract nested question structure if needed
            q_content = question.get("question") # Could be dict or str
            
            # Case 1: The question object itself has correct_answer
            correct_idx = question.get("correct_answer")
            
            # Case 2: Nested structure (sometimes seen in legacy or weird formats)
            if correct_idx is None and isinstance(q_content, dict):
                correct_idx = q_content.get("correct_answer")
            
            if correct_idx is not None:
                # Check candidate answer (index or value)
                try:
                    # Candidate answer might be index (0) or string ("0")
                    if answer is None:
                        return 0.0
                    candidate_val = int(answer) if str(answer).isdigit() else -1
                    if candidate_val == int(correct_idx):
                        return 10.0
                    else:
                        return 0.0
                except:
                    return 0.0
            else:
                 # Fallback if structure is weird: Let AI handle it or 0
                 pass
        
        # --- STEP 1: Basic Validation ---
        # If answer is too short (e.g., "idk"), return 0 immediately
        if not answer or len(answer) < 5:
            return 0.0
        
        # --- STEP 2: AI Scoring (Primary Method) ---
        try:
            # Import Groq client
            from groq import Groq
            
            # Initialize client (use existing API key from environment)
            groq_api_key = os.getenv("GROQ_API_KEY")
            if groq_api_key:
                groq_client = Groq(api_key=groq_api_key)
                
                # Prompt Construction: Context + Strict Rubric
                prompt = f"""Act as a Senior Technical Interviewer. Rate this answer on a scale of 0.0 to 10.0.

Question: "{question_text}"
Candidate's Answer: "{answer}"
Required Concepts: {", ".join(keywords) if keywords else "General technical logic"}

Scoring Rubric:
- 9.0 - 10.0: Perfect. Comprehensive, accurate, clear examples.
- 7.0 - 8.9: Good. Correct logic but slightly verbose or missing minor nuance.
- 5.0 - 6.9: Average. Basic understanding, somewhat vague.
- 3.0 - 4.9: Weak. Misses the main point or has significant gaps.
- 0.0 - 2.9: Wrong/Irrelevant. Incorrect info or hallucinations.

OUTPUT RULE: Return ONLY the numerical score (e.g., 8.5). Do not write any text or explanation."""
                
                # API Call - Offload blocking sync call to thread
                from anyio.to_thread import run_sync
                
                def _do_groq_call():
                    return groq_client.chat.completions.create(
                        model=os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile"),
                        messages=[{"role": "user", "content": prompt}],
                        temperature=0.1,  # Low temperature for consistency
                        max_tokens=10
                    )
                
                completion = await run_sync(_do_groq_call)
                
                score_text = completion.choices[0].message.content.strip()
                
                # Smart Parsing: Extract number from text (handles "Score: 8.5" or just "8.5")
                match = re.search(r"(\d+(?:\.\d+)?)", score_text)
                if match:
                    ai_score = float(match.group(1))
                    # Safety Clamp: Keep score between 0-10
                    clamped_score = max(0.0, min(10.0, ai_score))
                    logger.info(f"✅ AI Scoring: {clamped_score}/10 for answer length {len(answer)}")
                    return clamped_score
                else:
                    logger.warning(f"⚠️ AI returned non-numeric response: {score_text}")
            
        except Exception as e:
            # If AI fails (Internet/Quota issue), log and use fallback
            logger.error(f"⚠️ AI Scoring Failed: {str(e)}. Switching to Fallback Heuristic.")
        
        # --- STEP 3: Fallback Logic (Safety Net) ---
        # This runs when AI is down or fails
        logger.info("Using fallback heuristic scoring")
        score = 4.0  # Base score (lower for fallback to differentiate from AI)
        
        # Keyword Matching logic
        if keywords:
            matches = sum(1 for kw in keywords if kw.lower() in answer.lower())
            # Max 4 points from keywords
            score += min(4.0, matches * 1.0)
        
        # Length bonus (Simple heuristic)
        if len(answer) > 100:
            score += 1.0
        if len(answer) > 200:
            score += 1.0
        
        return min(10.0, max(0.0, score))
    
    def _find_question(self, questions: List[Dict], question_id: Any) -> Dict:
        """Find question by ID"""
        for q in questions:
            if str(q.get("_id")) == str(question_id) or q.get("index") == question_id or q.get("id") == question_id:
                return q
        return None
    
    def _generate_feedback(self, category: str, score: float) -> str:
        """Generate feedback based on category and score"""
        
        feedback_templates = {
            "technical": {
                "excellent": "Demonstrates strong technical knowledge and problem-solving skills.",
                "good": "Shows good understanding of technical concepts with room for improvement.",
                "average": "Basic technical knowledge demonstrated, needs further development.",
                "poor": "Limited technical understanding, requires significant improvement."
            },
            "communication": {
                "excellent": "Excellent communication skills with clear and concise explanations.",
                "good": "Good communication with mostly clear responses.",
                "average": "Adequate communication but could be more clear and structured.",
                "poor": "Communication needs improvement for clarity and coherence."
            },
            "problem_solving": {
                "excellent": "Outstanding problem-solving approach with logical reasoning.",
                "good": "Good problem-solving skills with effective strategies.",
                "average": "Basic problem-solving demonstrated, could use more structured approach.",
                "poor": "Problem-solving skills need significant development."
            },
            "creativity": {
                "excellent": "Highly creative solutions with innovative thinking.",
                "good": "Shows creativity in approach with some original ideas.",
                "average": "Some creative elements but mostly conventional thinking.",
                "poor": "Limited creativity, relies on standard approaches."
            }
        }
        
        templates = feedback_templates.get(category, feedback_templates["technical"])
        
        if score >= 8:
            return templates["excellent"]
        elif score >= 6:
            return templates["good"]
        elif score >= 4:
            return templates["average"]
        else:
            return templates["poor"]
    
    def _get_default_breakdown(self) -> Dict:
        """Return default breakdown when no data available"""
        return {
            "technical": {"score": 0, "max": 10, "feedback": "No data available"},
            "communication": {"score": 0, "max": 10, "feedback": "No data available"},
            "problem_solving": {"score": 0, "max": 10, "feedback": "No data available"},
            "creativity": {"score": 0, "max": 10, "feedback": "No data available"},
            "overall": 0.0
        }
