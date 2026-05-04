"""
AI Service Provider Abstraction
Decouples the application from specific LLM providers (Groq, Gemini, OpenAI)
"""
from abc import ABC, abstractmethod
from typing import Optional, List, Dict, Any
import os
import json
import asyncio
from utils import logger, ExternalServiceError

class AIProvider(ABC):
    """Abstract base class for AI providers."""
    
    @abstractmethod
    async def generate(self, prompt: str, system_prompt: Optional[str] = None, max_tokens: int = 1000) -> str:
        """Generate text from prompt."""
        pass
    
    @abstractmethod
    async def generate_json(self, prompt: str, schema: Optional[Dict] = None) -> Dict[str, Any]:
        """Generate valid JSON response."""
        pass

    @abstractmethod
    async def embed(self, text: str) -> Optional[List[float]]:
        """Generate numerical embedding for text."""
        pass

class GroqProvider(AIProvider):
    """Groq API provider (Llama 3)."""
    
    def __init__(self, api_key: str):
        try:
            from groq import Groq
            self.client = Groq(api_key=api_key)
            self.model = "llama-3.3-70b-versatile"
        except ImportError:
            logger.error("groq package not installed")
            raise ExternalServiceError("Groq", "Package invalid")

    async def generate(self, prompt: str, system_prompt: Optional[str] = None, max_tokens: int = 1000) -> str:
        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})
        
        # ✅ FIXED: Add retry logic with exponential backoff
        max_retries = 3
        base_delay = 1  # seconds
        
        for attempt in range(max_retries):
            try:
                # Run blocking call in executor
                loop = asyncio.get_event_loop()
                response = await loop.run_in_executor(
                    None,
                    lambda: self.client.chat.completions.create(
                        model=self.model,
                        messages=messages,
                        max_tokens=max_tokens,
                        temperature=0.3
                    )
                )
                return response.choices[0].message.content
            except Exception as e:
                error_str = str(e).lower()
                
                # Check if it's a rate limit error
                if 'rate' in error_str or 'limit' in error_str or '429' in error_str:
                    if attempt < max_retries - 1:
                        delay = base_delay * (2 ** attempt)  # Exponential backoff
                        logger.warning(f"Groq rate limit hit, retrying in {delay}s (attempt {attempt + 1}/{max_retries})")
                        await asyncio.sleep(delay)
                        continue
                
                # Check if it's a transient error
                if 'timeout' in error_str or 'connection' in error_str:
                    if attempt < max_retries - 1:
                        delay = base_delay * (2 ** attempt)
                        logger.warning(f"Groq transient error, retrying in {delay}s (attempt {attempt + 1}/{max_retries})")
                        await asyncio.sleep(delay)
                        continue
                
                # Non-retryable error or max retries reached
                logger.error(f"Groq generation failed: {e}")
                
                # Check for specific obscure errors (like Cloudflare blocks)
                if "cfToken" in error_str or "cloudflare" in error_str:
                    logger.critical("Groq API blocked by Cloudflare (cfToken error). Usage of unofficial/proxy API suspected.")
                    raise ExternalServiceError("Groq", 
                        "AI Service Unavailable: The provider blocked the request. Please contact support or check API status."
                    )
                
                raise ExternalServiceError("Groq", str(e))

    async def generate_json(self, prompt: str, schema: Optional[Dict] = None) -> Dict[str, Any]:
        system_prompt = "You are a helpful assistant. You must output VALID JSON only."
        if schema:
            system_prompt += f" Follow this schema: {json.dumps(schema)}"
        
        text = await self.generate(prompt, system_prompt=system_prompt, max_tokens=2000)
        
        # Strip markdown code blocks if present
        text = text.replace("```json", "").replace("```", "").strip()
        
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            logger.error(f"Failed to decode JSON from Groq: {text[:100]}...")
            raise ExternalServiceError("Groq", "Invalid JSON output")

    async def embed(self, text: str) -> Optional[List[float]]:
        """Workaround for Groq embedding via text generation."""
        prompt = f"""Convert the following TECHNICAL content into a semantic numerical representation.
        Focus ONLY on: skills, work experience, education level.
        Output ONLY a valid JSON array of exactly 768 numbers, no other text.
        
        Content: {text[:1500]}
        """
        try:
            res = await self.generate(prompt, max_tokens=2000)
            # Robust JSON cleaning
            if "[" in res and "]" in res:
                res = res[res.find("["):res.rfind("]")+1]
            
            vec = json.loads(res)
            if isinstance(vec, list) and len(vec) > 0:
                return [float(x) for x in vec]
        except Exception as e:
            logger.warning(f"Groq pseudo-embedding failed: {e}")
        return None

class GeminiProvider(AIProvider):
    """Google Gemini provider."""
    
    def __init__(self, api_key: str):
        try:
            from google import genai
            self.client = genai.Client(api_key=api_key)
            self.model_name = os.getenv("GEMINI_MODEL", "gemini-2.0-flash") # Updated default
        except ImportError:
            logger.error("google-genai package not installed")
            raise ExternalServiceError("Gemini", "Package invalid")

    async def generate(self, prompt: str, system_prompt: Optional[str] = None, max_tokens: int = 1000) -> str:
        full_prompt = prompt
        if system_prompt:
            full_prompt = f"System: {system_prompt}\n\nUser: {prompt}"
            
        try:
            loop = asyncio.get_event_loop()
            response = await loop.run_in_executor(
                None,
                lambda: self.client.models.generate_content(
                    model=self.model_name,
                    contents=full_prompt
                )
            )
            return response.text
        except Exception as e:
            logger.error(f"Gemini generation failed: {e}")
            raise ExternalServiceError("Gemini", str(e))

    async def generate_json(self, prompt: str, schema: Optional[Dict] = None) -> Dict[str, Any]:
        # Gemini often tougher with JSON enforcement, requires specific prompting
        system_prompt = "Output strict JSON only. No markdown."
        text = await self.generate(prompt, system_prompt)
        # Robust cleaning
        if "{" in text and "}" in text:
            text = text[text.find("{"):text.rfind("}")+1]
        try:
            return json.loads(text)
        except json.JSONDecodeError:
             raise ExternalServiceError("Gemini", "Invalid JSON output")

    async def embed(self, text: str) -> Optional[List[float]]:
        """Native Gemini embedding with fallback."""
        # Models to try in order
        embedding_models = ["text-embedding-004", "embedding-001"]
        
        for model in embedding_models:
            try:
                loop = asyncio.get_event_loop()
                result = await loop.run_in_executor(
                    None,
                    lambda m=model: self.client.models.embed_content(
                        model=m,
                        contents=text[:2048]
                    )
                )
                if hasattr(result, 'embeddings') and len(result.embeddings) > 0:
                    return [float(x) for x in result.embeddings[0].values]
            except Exception as e:
                logger.debug(f"Gemini embedding with {model} failed: {e}")
                continue
        
        logger.warning("All Gemini embedding models failed")
        return None

class AIService:
    """
    Main service for AI operations with provider fallback.
    Uses Lazy Initialization to allow safe imports before env vars are loaded.
    """
    def __init__(self):
        self.providers: List[AIProvider] = []
        self._initialized = False

    def _ensure_initialized(self):
        """Lazy loader for providers."""
        if not self._initialized:
            self._init_providers()
            self._initialized = True

    def _init_providers(self):
        groq_key = os.getenv("GROQ_API_KEY")
        if groq_key:
            try:
                self.providers.append(GroqProvider(groq_key))
                logger.info("✅ Groq provider initialized")
            except Exception as e:
                logger.warning(f"Failed to init Groq: {e}")
        
        gemini_key = os.getenv("GEMINI_API_KEY")
        if gemini_key:
            try:
                self.providers.append(GeminiProvider(gemini_key))
                logger.info("✅ Gemini provider initialized")
            except Exception as e:
                logger.warning(f"Failed to init Gemini: {e}")
        
        if not self.providers:
            logger.critical("❌ No AI providers available! check .env files")

    async def generate_text(self, prompt: str, **kwargs) -> str:
        self._ensure_initialized()
        
        last_error = None
        for provider in self.providers:
            try:
                return await provider.generate(prompt, **kwargs)
            except Exception as e:
                logger.warning(f"Provider {provider.__class__.__name__} failed: {e}")
                last_error = e
                continue
        raise ExternalServiceError("All AI Providers", str(last_error))

    async def generate_json(self, prompt: str, **kwargs) -> Dict[str, Any]:
        self._ensure_initialized()
        
        last_error = None
        for provider in self.providers:
            try:
                return await provider.generate_json(prompt, **kwargs)
            except Exception as e:
                logger.warning(f"Provider {provider.__class__.__name__} failed: {e}")
                last_error = e
                continue
        raise ExternalServiceError("All AI Providers", str(last_error))

    async def embed(self, text: str) -> List[float]:
        self._ensure_initialized()
        
        for provider in self.providers:
            try:
                vec = await provider.embed(text)
                if vec:
                    return vec
            except Exception as e:
                logger.warning(f"Embedding failed for {provider.__class__.__name__}: {e}")
        
        # Final fallback - hash based vector (repurposed from embeddings.py)
        import hashlib
        h = hashlib.sha256(text.encode()).hexdigest()
        return [float(int(h[i:i+2], 16))/255.0 for i in range(0, 64, 2)] * 12 # Mocking a vector

    def is_operational(self) -> bool:
        """Check if any AI provider is initialized."""
        self._ensure_initialized()
        return len(self.providers) > 0

    def get_active_provider(self) -> str:
        """Return naming of active AI providers."""
        self._ensure_initialized()
        if not self.providers:
            return "none"
        return ", ".join([p.__class__.__name__.replace("Provider", "") for p in self.providers])

# Singleton instance
ai_service = AIService()
