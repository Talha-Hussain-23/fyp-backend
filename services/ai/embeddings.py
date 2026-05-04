"""
LLM-based Embeddings Service
Generates embeddings for job descriptions and resumes using Groq or Gemini
"""

import os
import json
import numpy as np
from typing import List, Optional, Tuple
from dotenv import load_dotenv
from core.logging_service import logger

load_dotenv()

from services.ai.ai_provider import ai_service
import asyncio
from asgiref.sync import async_to_sync

# Default embedding dimension
EMBEDDING_DIM = 3072  # Gemini embedding model dimension

async def get_embedding(text: str) -> List[float]:
    """
    Get embedding for text using the unified AI service (Async).
    Automatically handles provider fallbacks (Gemini -> Groq -> Hash).
    """
    try:
        return await ai_service.embed(text)
    except Exception as e:
        logger.error(f"Embedding service failed: {e}")
        # Final safety fallback 
        import hashlib
        h = hashlib.sha256(text.encode()).hexdigest()
        return [float(int(h[i:i+2], 16))/255.0 for i in range(0, 64, 2)] * 12


def cosine_similarity(vec1: List[float], vec2: List[float]) -> float:
    """
    Calculate cosine similarity between two vectors
    """
    try:
        # Convert to numpy arrays
        v1 = np.array(vec1)
        v2 = np.array(vec2)
        
        # Normalize vectors
        norm1 = np.linalg.norm(v1)
        norm2 = np.linalg.norm(v2)
        
        if norm1 == 0 or norm2 == 0:
            return 0.0
        
        # Calculate cosine similarity
        dot_product = np.dot(v1, v2)
        similarity = dot_product / (norm1 * norm2)
        
        # Ensure result is between -1 and 1
        return float(np.clip(similarity, -1.0, 1.0))
        
    except Exception as e:
        logger.error(f"Cosine similarity error: {e}")
        return 0.0


def match_resume_to_job(resume_embedding: List[float], job_embedding: List[float]) -> float:
    """
    Match resume to job using cosine similarity
    Returns a score between -1 and 1, which can be converted to 0-100
    """
    similarity = cosine_similarity(resume_embedding, job_embedding)
    
    # Convert to 0-100 scale
    # Cosine similarity is between -1 and 1, map to 0-100
    score = ((similarity + 1) / 2) * 100
    
    return round(score, 2)

