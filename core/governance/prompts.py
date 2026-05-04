"""
AI Governance: Prompt Registry & Management
Centralized source of truth for all LLM interactions.
Enforces semantic versioning and strict parameter validation.
"""
from typing import Dict, Any, Optional, List
from pydantic import BaseModel
import logging

logger = logging.getLogger(__name__)

class PromptConfig(BaseModel):
    temperature: float = 0.7
    max_tokens: int = 1000
    model_preference: Optional[str] = None
    stop_sequences: Optional[List[str]] = None

class PromptTemplate(BaseModel):
    version: str
    template: str
    system_prompt: Optional[str] = None
    input_variables: List[str]
    config: PromptConfig
    description: str

class PromptRegistry:
    """
    Singleton registry for managing versioned prompts.
    """
    _REGISTRY: Dict[str, Dict[str, PromptTemplate]] = {}

    @classmethod
    def register(cls, task_id: str, version: str, template: PromptTemplate):
        if task_id not in cls._REGISTRY:
            cls._REGISTRY[task_id] = {}
        cls._REGISTRY[task_id][version] = template

    @classmethod
    def get(cls, task_id: str, version: str) -> PromptTemplate:
        """
        Retrieve a specific version of a prompt.
        Raises ValueError if not found.
        """
        if task_id not in cls._REGISTRY:
            raise ValueError(f"Prompt task '{task_id}' not found in registry.")
        if version not in cls._REGISTRY[task_id]:
            raise ValueError(f"Version '{version}' for task '{task_id}' not found.")
        return cls._REGISTRY[task_id][version]

    @classmethod
    def render(cls, task_id: str, version: str, **kwargs) -> str:
        """
        Safely render a prompt with the provided arguments.
        """
        prompt_obj = cls.get(task_id, version)
        
        # Validate arguments
        missing = [var for var in prompt_obj.input_variables if var not in kwargs]
        if missing:
            raise ValueError(f"Missing arguments for prompt '{task_id}@{version}': {missing}")
            
        try:
            return prompt_obj.template.format(**kwargs)
        except KeyError as e:
             raise ValueError(f"Prompt render failed: {e}")

# ==============================================================================
# PROMPT DEFINITIONS
# ==============================================================================

# 1. EVALUATION PROMPTS
# ---------------------
PromptRegistry.register(
    task_id="evaluation_scoring",
    version="v1.0.0",
    template=PromptTemplate(
        version="v1.0.0",
        description="Standard Interview Evaluation Logic",
        system_prompt="You are an expert technical interviewer. Evaluate the candidate's response objectively.",
        template="""
        Evaluate the following interview response.

        Context:
        - Job Title: {job_title}
        - Description: {job_description}
        - Question: {question}
        - Strictness: {strictness}

        Candidate Response:
        {response}

        Criteria to Evaluate: {criteria}

        Scoring Rules:
        1. Overall Score (0-100)
        2. Individual Criteria Scores (0-10)
        3. Be fair but critical.

        REQUIRED OUTPUT FORMAT (JSON ONLY):
        {{
            "overallScore": <float>,
            "criteria": {{
                "<criterion_name>": <score>,
                ...
            }},
            "feedback": "<string>",
            "reasoning": "<string>"
        }}
        """,
        input_variables=["job_title", "job_description", "question", "strictness", "response", "criteria"],
        config=PromptConfig(temperature=0.3, max_tokens=1500)
    )
)

# 2. QUESTION GENERATION PROMPTS
# ------------------------------

# 2a. GENERIC / DESCRIPTIVE
PromptRegistry.register(
    task_id="question_generation_descriptive",
    version="v1.0.0",
    template=PromptTemplate(
        version="v1.0.0",
        description="Descriptive Interview Questions",
        system_prompt="You are a senior hiring manager conducting technical interviews. Generate profound, scenario-based questions tailored to the specific role.",
        template="""
Generate {count} unique Descriptive interview questions for a {difficulty} "{job_title}" role.

Job Description:
{job_description}

Candidate Context: {resume_context}
Topic: {topic}

CRITICAL RULES:
1. Every question MUST be directly relevant to the job description and "{job_title}" role above.
2. Each question must be unique — no duplicates or near-duplicates.
3. Focus on real-world problem solving scenarios specific to this role.
4. Avoid generic trivia or questions that could apply to any job.
5. Custom Instructions: {custom_instructions}
6. Questions must differ from: {previous_questions}

Output strictly as a JSON array of strings:
["Question 1...", "Question 2..."]

No markdown, no explanation outside JSON.
        """,
        input_variables=["count", "difficulty", "job_title", "job_description", "resume_context", "topic", "previous_questions", "custom_instructions"],
        config=PromptConfig(temperature=0.7)
    )
)

# 2b. MCQ GENERATION
PromptRegistry.register(
    task_id="question_generation_mcq",
    version="v1.0.0",
    template=PromptTemplate(
        version="v1.0.0",
        description="Multiple Choice Questions",
        system_prompt="You are a technical exam creator specializing in hiring assessments. Generate challenging, job-specific MCQs.",
        template="""
Generate {count} unique Multiple Choice Questions (MCQs) for a {difficulty} "{job_title}" role.

Job Description:
{job_description}

Topic Focus: {topic}
Custom Instructions: {custom_instructions}

CRITICAL RULES:
1. Every question MUST be directly relevant to the job description and role above.
2. Each of the 4 options MUST be a complete, meaningful answer text — NOT a single letter.
3. Every question must be unique — no duplicates or near-duplicates.
4. Include plausible distractors that test real understanding.
5. The correct_answer field is a 1-based index (1, 2, 3, or 4) indicating which option is correct.

Required JSON schema per question:
{{
    "question": "What is the purpose of React's useEffect hook?",
    "options": ["To manage component state", "To perform side effects after render", "To create new components", "To handle form submissions"],
    "correct_answer": 2,
    "explanation": "useEffect is used for side effects like data fetching, subscriptions, or DOM mutations after render."
}}

Output strictly as a JSON array of objects. No markdown, no explanation outside JSON.
        """,
        input_variables=["count", "difficulty", "job_title", "job_description", "topic", "custom_instructions"],
        config=PromptConfig(temperature=0.5)
    )
)

# 2c. CODING CHALLENGE
PromptRegistry.register(
    task_id="question_generation_code",
    version="v1.0.0",
    template=PromptTemplate(
        version="v1.0.0",
        description="Coding Challenges",
        system_prompt="You are a senior software engineer creating practical coding assessments for hiring. Generate challenges relevant to the actual job.",
        template="""
Create {count} unique Coding Challenge(s) for a {difficulty} "{job_title}" role.

Job Description:
{job_description}

Programming Language: {language}
Custom Instructions: {custom_instructions}

CRITICAL RULES:
1. Each challenge MUST be relevant to the skills and technologies mentioned in the job description.
2. Challenges should test practical skills a "{job_title}" would use daily, not abstract puzzles.
3. Each challenge must be unique — no duplicates.
4. Include at least 2 test cases per challenge with realistic inputs/outputs.
5. Hints should guide without revealing the solution.

Required JSON schema per question:
{{
    "question": "Write a function that validates an email address and returns True if valid, False otherwise. It should handle edge cases like missing @ symbol, multiple dots, and empty strings.",
    "language": "{language}",
    "test_cases": [{{"input": "'user@example.com'", "output": "True"}}, {{"input": "'invalid-email'", "output": "False"}}],
    "hints": ["Consider using regex or string methods", "Don't forget edge cases like empty strings"]
}}

Output strictly as a JSON array of objects. No markdown, no explanation outside JSON.
        """,
        input_variables=["count", "difficulty", "job_title", "topic", "job_description", "language", "custom_instructions"],
        config=PromptConfig(temperature=0.5)
    )
)

# 3. QUALITY GATE PROMPTS (THE CRITIC)
# ------------------------------------
PromptRegistry.register(
    task_id="question_quality_gate",
    version="v1.0.0",
    template=PromptTemplate(
        version="v1.0.0",
        description="AI Critic to validate generic questions",
        system_prompt="You are a Quality Assurance Auditor for an Interview Platform.",
        template="""
        Audit the following generated interview question for quality issues.

        Question: "{question}"
        Intended Role: {job_title}

        Checklist:
        1. Is it technically accurate?
        2. Is it free of bias (gender/cultural)?
        3. Is it clear and unambiguous?
        4. Is it relevant to the role?

        Respond in JSON:
        {{
            "is_valid": <bool>,
            "quality_score": <0-10>,
            "issues": ["<issue1>", "<issue2>"],
            "reason": "<summary>"
        }}
        """,
        input_variables=["question", "job_title"],
        config=PromptConfig(temperature=0.1)  # Low temp for strict logic
    )
)
