"""
Template fallback questions when AI providers fail.
Provides context-aware fallback questions for different question types.
Expanded pool with randomized selection to avoid repetition.
"""
from typing import List, Dict, Any
import random
import re


def _extract_keywords(jd_preview: str) -> List[str]:
    """Extract technology/domain keywords from job description for relevance matching."""
    if not jd_preview:
        return []
    # Common tech keywords to look for
    tech_terms = [
        "python", "javascript", "typescript", "react", "angular", "vue", "node",
        "django", "flask", "fastapi", "spring", "java", "c#", ".net", "ruby",
        "rails", "php", "laravel", "go", "golang", "rust", "swift", "kotlin",
        "sql", "nosql", "mongodb", "postgresql", "mysql", "fastapi", "docker",
        "kubernetes", "aws", "azure", "gcp", "api", "rest", "graphql",
        "microservices", "devops", "ci/cd", "testing", "agile", "scrum",
        "machine learning", "ai", "data science", "deep learning",
        "frontend", "backend", "fullstack", "full-stack", "mobile",
        "html", "css", "sass", "webpack", "git", "linux",
        "security", "authentication", "database", "cloud", "serverless"
    ]
    jd_lower = jd_preview.lower()
    found = [t for t in tech_terms if t in jd_lower]
    return found


# ============================================================
# EXPANDED TEMPLATE POOLS
# ============================================================

DESCRIPTIVE_TEMPLATES = [
    "Tell me about your experience with the tech stack required for this role.",
    "Describe a challenging technical problem you solved recently.",
    "How do you ensure code quality and maintainability in your projects?",
    "Explain a complex architectural decision you made and its impact.",
    "How do you handle disagreement within a technical team?",
    "What is your approach to learning new technologies quickly?",
    "Describe your experience with code reviews and how you give constructive feedback.",
    "How do you approach debugging a production issue under time pressure?",
    "Tell me about a time when you had to refactor a large codebase. What was your strategy?",
    "How do you balance technical debt with feature delivery?",
    "Describe how you would design a system to handle high traffic loads.",
    "What is your approach to writing testable and maintainable code?",
    "How do you stay updated with the latest industry trends and technologies?",
    "Describe a situation where you had to make a trade-off between performance and readability.",
    "How do you collaborate with non-technical stakeholders to gather requirements?",
]

MCQ_TEMPLATES = {
    "general": [
        {
            "question": "Which of these is a key principle of RESTful APIs?",
            "options": ["Statelessness", "Sticky Sessions", "Global Variables", "Manual Routing"],
            "correct_answer": 1,
            "explanation": "REST APIs are designed to be stateless."
        },
        {
            "question": "What is the primary purpose of a version control system like Git?",
            "options": ["Backup data to external drives", "Track changes and enable collaborative development", "Compile source code into binaries", "Run automated test suites"],
            "correct_answer": 2,
            "explanation": "Git is for tracking history and collaborative development."
        },
        {
            "question": "In Agile methodology, what is a 'Sprint'?",
            "options": ["A coffee break for the team", "A fixed time period for completing a set of work", "A long-term project planning phase", "A bug tracking and reporting tool"],
            "correct_answer": 2,
            "explanation": "A sprint is a time-boxed iteration in Scrum."
        },
        {
            "question": "What does the SOLID principle 'S' stand for?",
            "options": ["Single Responsibility Principle", "Secure Repository Principle", "System Resource Principle", "Standard Response Protocol"],
            "correct_answer": 1,
            "explanation": "S stands for Single Responsibility - a class should have one reason to change."
        },
        {
            "question": "Which HTTP status code indicates a resource was successfully created?",
            "options": ["200 OK", "201 Created", "204 No Content", "301 Moved Permanently"],
            "correct_answer": 2,
            "explanation": "201 Created indicates successful resource creation."
        },
        {
            "question": "What is the main advantage of using a NoSQL database over a relational database?",
            "options": ["It always provides ACID transactions", "It offers flexible schema design for unstructured data", "It requires SQL for all queries", "It does not support horizontal scaling"],
            "correct_answer": 2,
            "explanation": "NoSQL databases excel at handling unstructured and semi-structured data with flexible schemas."
        },
        {
            "question": "What is the purpose of a load balancer in a web architecture?",
            "options": ["To encrypt data at rest", "To distribute incoming network traffic across multiple servers", "To compress database queries", "To manage user authentication tokens"],
            "correct_answer": 2,
            "explanation": "Load balancers distribute traffic to prevent overloading individual servers."
        },
        {
            "question": "In software design, what is the Observer pattern used for?",
            "options": ["Managing database connections", "Defining a one-to-many dependency so when one object changes state, all dependents are notified", "Encrypting data in transit", "Compiling source code into machine code"],
            "correct_answer": 2,
            "explanation": "The Observer pattern establishes a subscription mechanism for state changes."
        },
        {
            "question": "What is the primary benefit of containerization using Docker?",
            "options": ["It eliminates the need for testing", "It provides consistent environments across development, staging, and production", "It replaces the need for version control", "It automatically scales applications"],
            "correct_answer": 2,
            "explanation": "Docker containers ensure environment consistency across the deployment pipeline."
        },
        {
            "question": "What is a JWT (JSON Web Token) commonly used for?",
            "options": ["Compressing large files for transmission", "Securely transmitting information between parties as a signed JSON object", "Formatting database queries", "Rendering HTML templates on the server"],
            "correct_answer": 2,
            "explanation": "JWTs are a compact, self-contained way for securely transmitting information between parties."
        },
    ],
    "frontend": [
        {
            "question": "What is the Virtual DOM in React?",
            "options": ["A direct manipulation of the browser's DOM", "A lightweight in-memory representation of the real DOM for efficient updates", "A server-side rendering technique", "A CSS optimization tool"],
            "correct_answer": 2,
            "explanation": "The Virtual DOM is React's strategy for efficient DOM updates."
        },
        {
            "question": "What does CSS Flexbox primarily solve?",
            "options": ["3D transformations", "One-dimensional layout distribution of space among items", "Database queries", "Server-side routing"],
            "correct_answer": 2,
            "explanation": "Flexbox is designed for one-dimensional layouts."
        },
    ],
    "backend": [
        {
            "question": "What is middleware in a web application framework?",
            "options": ["A database management system", "Software that sits between the request and response cycle to process or modify them", "A frontend JavaScript framework", "A CSS preprocessor"],
            "correct_answer": 2,
            "explanation": "Middleware intercepts and processes HTTP requests and responses."
        },
        {
            "question": "What is connection pooling in database management?",
            "options": ["Creating a new connection for every query", "Maintaining a cache of reusable database connections to reduce overhead", "Encrypting database connections", "Backing up database connections"],
            "correct_answer": 2,
            "explanation": "Connection pooling reuses existing connections to improve performance."
        },
    ],
    "data": [
        {
            "question": "What is the difference between supervised and unsupervised learning?",
            "options": ["Supervised learning uses labeled data while unsupervised learning finds patterns in unlabeled data", "There is no difference", "Unsupervised learning is always more accurate", "Supervised learning does not require training data"],
            "correct_answer": 1,
            "explanation": "Supervised learning uses labeled training data, while unsupervised learning discovers patterns without labels."
        },
    ]
}

CODE_TEMPLATES = {
    "general": [
        {
            "question": "Write a function to find the maximum number in a list without using built-in max().",
            "language": "python",
            "test_cases": [
                {"input": "[1, 5, 3, 9, 2]", "output": "9"},
                {"input": "[-1, -5, -3]", "output": "-1"}
            ],
            "hints": ["Iterate through the list keeping track of the largest value seen"]
        },
        {
            "question": "Implement a function to check if a string is a palindrome, ignoring case and non-alphanumeric characters.",
            "language": "python",
            "test_cases": [
                {"input": "'A man, a plan, a canal: Panama'", "output": "True"},
                {"input": "'race a car'", "output": "False"}
            ],
            "hints": ["Filter out non-alphanumeric characters first", "Compare the cleaned string with its reverse"]
        },
        {
            "question": "Write a function that takes a list of integers and returns a new list containing only the unique elements, preserving order.",
            "language": "python",
            "test_cases": [
                {"input": "[1, 2, 2, 3, 4, 4, 5]", "output": "[1, 2, 3, 4, 5]"},
                {"input": "[3, 3, 3]", "output": "[3]"}
            ],
            "hints": ["Use a set to track seen elements while preserving order"]
        },
        {
            "question": "Implement a function to flatten a nested list of arbitrary depth into a single flat list.",
            "language": "python",
            "test_cases": [
                {"input": "[[1, 2], [3, [4, 5]], 6]", "output": "[1, 2, 3, 4, 5, 6]"},
                {"input": "[1, [2, [3, [4]]]]", "output": "[1, 2, 3, 4]"}
            ],
            "hints": ["Consider using recursion to handle nested lists"]
        },
        {
            "question": "Write a function to count the frequency of each word in a given string and return a dictionary.",
            "language": "python",
            "test_cases": [
                {"input": "'hello world hello'", "output": "{'hello': 2, 'world': 1}"},
                {"input": "'one'", "output": "{'one': 1}"}
            ],
            "hints": ["Split the string by spaces and use a dictionary to count"]
        },
        {
            "question": "Implement a function that validates whether a string of parentheses, brackets, and braces is balanced.",
            "language": "python",
            "test_cases": [
                {"input": "'({[]})'", "output": "True"},
                {"input": "'({[})'", "output": "False"},
                {"input": "''", "output": "True"}
            ],
            "hints": ["Use a stack data structure", "Push opening brackets and pop for closing ones"]
        },
        {
            "question": "Write a function to merge two sorted lists into a single sorted list without using built-in sort.",
            "language": "python",
            "test_cases": [
                {"input": "[1, 3, 5], [2, 4, 6]", "output": "[1, 2, 3, 4, 5, 6]"},
                {"input": "[1, 2], [3]", "output": "[1, 2, 3]"}
            ],
            "hints": ["Use two pointers, one for each list", "Compare elements and add the smaller one"]
        },
        {
            "question": "Implement a function that converts a Roman numeral string to an integer.",
            "language": "python",
            "test_cases": [
                {"input": "'XIV'", "output": "14"},
                {"input": "'MCMXCIV'", "output": "1994"}
            ],
            "hints": ["Map each Roman numeral to its value", "Subtract when a smaller value precedes a larger one"]
        },
        {
            "question": "Write a function to find the two numbers in an array that add up to a given target and return their indices.",
            "language": "python",
            "test_cases": [
                {"input": "[2, 7, 11, 15], 9", "output": "[0, 1]"},
                {"input": "[3, 2, 4], 6", "output": "[1, 2]"}
            ],
            "hints": ["Use a hash map to store complements", "One pass through the array is sufficient"]
        },
        {
            "question": "Write a function that groups a list of strings by their anagrams and returns the groups.",
            "language": "python",
            "test_cases": [
                {"input": "['eat', 'tea', 'tan', 'ate', 'nat', 'bat']", "output": "[['eat', 'tea', 'ate'], ['tan', 'nat'], ['bat']]"},
                {"input": "['']", "output": "[['']]"}
            ],
            "hints": ["Sort the characters of each string to create a key", "Use a dictionary to group words by their sorted key"]
        },
    ],
    "web": [
        {
            "question": "Write a function that parses a URL query string (e.g., 'name=John&age=30') and returns a dictionary of key-value pairs.",
            "language": "python",
            "test_cases": [
                {"input": "'name=John&age=30&city=NYC'", "output": "{'name': 'John', 'age': '30', 'city': 'NYC'}"},
                {"input": "''", "output": "{}"}
            ],
            "hints": ["Split by '&' first, then split each pair by '='"]
        },
    ],
    "data": [
        {
            "question": "Write a function to calculate the moving average of a list of numbers with a given window size.",
            "language": "python",
            "test_cases": [
                {"input": "[1, 2, 3, 4, 5], 3", "output": "[2.0, 3.0, 4.0]"},
                {"input": "[10, 20, 30], 2", "output": "[15.0, 25.0]"}
            ],
            "hints": ["Use a sliding window approach", "Sum the window and divide by the window size"]
        },
    ]
}


def _select_domain(keywords: List[str]) -> str:
    """Determine the most relevant template domain based on JD keywords."""
    frontend_kw = {"react", "angular", "vue", "frontend", "css", "html", "javascript", "typescript"}
    backend_kw = {"django", "flask", "fastapi", "spring", "node", "backend", "api", "rest", "graphql", "microservices"}
    data_kw = {"machine learning", "ai", "data science", "deep learning", "data", "analytics"}
    web_kw = {"web", "fullstack", "full-stack"}

    kw_set = set(keywords)
    if kw_set & frontend_kw:
        return "frontend"
    if kw_set & data_kw:
        return "data"
    if kw_set & backend_kw:
        return "backend"
    if kw_set & web_kw:
        return "web"
    return "general"


def get_template_questions(
    jd_preview: str,
    num_questions: int,
    question_type: str,
    difficulty: str
) -> List:
    """
    Fallback template questions when AI providers fail.
    Returns job-relevant, non-repeating questions based on JD analysis.
    
    Args:
        jd_preview: Preview of job description
        num_questions: Number of questions needed
        question_type: Type of questions (Descriptive, MCQ, Code)
        difficulty: Difficulty level
        
    Returns:
        List of template questions
    """
    keywords = _extract_keywords(jd_preview)
    domain = _select_domain(keywords)
    
    if question_type == "Descriptive":
        pool = list(DESCRIPTIVE_TEMPLATES)
        random.shuffle(pool)
        # Return unique questions up to num_questions, no cycling
        return pool[:num_questions] if num_questions <= len(pool) else pool + pool[:num_questions - len(pool)]
    
    elif question_type == "MCQ":
        # Combine domain-specific + general, prioritize domain-specific
        domain_qs = list(MCQ_TEMPLATES.get(domain, []))
        general_qs = list(MCQ_TEMPLATES["general"])
        # Remove duplicates (domain items that are also in general)
        domain_texts = {q["question"] for q in domain_qs}
        general_filtered = [q for q in general_qs if q["question"] not in domain_texts]
        pool = domain_qs + general_filtered
        random.shuffle(pool)
        return pool[:num_questions] if num_questions <= len(pool) else pool + pool[:num_questions - len(pool)]
    
    elif question_type == "Code":
        domain_qs = list(CODE_TEMPLATES.get(domain, []))
        general_qs = list(CODE_TEMPLATES["general"])
        domain_texts = {q["question"] for q in domain_qs}
        general_filtered = [q for q in general_qs if q["question"] not in domain_texts]
        pool = domain_qs + general_filtered
        random.shuffle(pool)
        return pool[:num_questions] if num_questions <= len(pool) else pool + pool[:num_questions - len(pool)]
    
    else:
        # Unknown type, fallback to descriptive
        pool = list(DESCRIPTIVE_TEMPLATES)
        random.shuffle(pool)
        return pool[:num_questions]
