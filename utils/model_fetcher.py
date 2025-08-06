"""
Model fetcher - pobiera listy dostępnych modeli z API providers
"""
import asyncio
import time
import logging
from typing import List, Dict, Optional
import openai
import anthropic
import google.generativeai as genai
import httpx


class ModelCache:
    """Cache dla modeli z TTL (Time To Live)."""
    
    def __init__(self, ttl_minutes=10):
        self.cache = {}
        self.ttl = ttl_minutes * 60  # Convert to seconds
        
    def get(self, provider: str) -> Optional[List[str]]:
        """Pobiera modele z cache jeśli nie są expired."""
        if provider in self.cache:
            models, timestamp = self.cache[provider]
            if time.time() - timestamp < self.ttl:
                return models
        return None
    
    def set(self, provider: str, models: List[str]):
        """Zapisuje modele do cache z timestampem."""
        self.cache[provider] = (models, time.time())
    
    def clear(self):
        """Czyści cache."""
        self.cache.clear()


# Global cache instance
model_cache = ModelCache(ttl_minutes=10)

# Fallback models jeśli API nie działa
FALLBACK_MODELS = {
    "OpenAI": [
        "o4-mini",
        "gpt-4o",
        "gpt-4o-mini", 
        "gpt-4",
        "gpt-4-turbo",
        "gpt-3.5-turbo"
    ],
    "Anthropic": [
        "claude-3-7-sonnet-latest",
        "claude-sonnet-4-0", 
        "claude-3-5-sonnet-20241022",
        "claude-3-opus-20240229",
        "claude-3-haiku-20240307"
    ],
    "Gemini": [
        "gemini-2.5-flash-preview-04-17",
        "gemini-2.5-pro-preview-06-05",
        "gemini-2.0-flash-001",
        "gemini-1.5-pro",
        "gemini-1.5-flash"
    ],
    "DeepSeek": [
        "deepseek-chat",
        "deepseek-reasoner"
    ]
}


async def fetch_openai_models(api_key: str) -> List[str]:
    """Pobiera listę modeli OpenAI."""
    try:
        client = openai.AsyncOpenAI(api_key=api_key, timeout=5.0)
        response = await client.models.list()
        
        # Filter dla modeli chat completion (zawierają 'gpt' lub 'o4')
        chat_models = []
        for model in response.data:
            model_id = model.id.lower()
            if any(keyword in model_id for keyword in ['gpt', 'o4', 'o3', 'o1']):
                chat_models.append(model.id)
        
        # Sortuj - najpopularniejsze na początku
        priority_models = ['o4-mini', 'gpt-4o', 'gpt-4o-mini', 'gpt-4']
        sorted_models = []
        
        for priority in priority_models:
            if priority in chat_models:
                sorted_models.append(priority)
                chat_models.remove(priority)
        
        # Dodaj pozostałe alfabetycznie
        sorted_models.extend(sorted(chat_models))
        
        return sorted_models[:15]  # Maksymalnie 15 modeli
        
    except Exception as e:
        logging.warning(f"Nie można pobrać modeli OpenAI: {e}")
        return FALLBACK_MODELS["OpenAI"]


async def fetch_anthropic_models(api_key: str) -> List[str]:
    """Pobiera listę modeli Anthropic."""
    try:
        client = anthropic.AsyncAnthropic(api_key=api_key, timeout=5.0)
        
        # Anthropic nie ma publicznego endpoints dla list models jeszcze
        # Używamy znanych modeli z 2025
        known_models = [
            "claude-sonnet-4-0",
            "claude-3-7-sonnet-latest", 
            "claude-3-5-sonnet-20241022",
            "claude-3-opus-20240229",
            "claude-3-sonnet-20240229",
            "claude-3-haiku-20240307"
        ]
        
        return known_models
        
    except Exception as e:
        logging.warning(f"Nie można pobrać modeli Anthropic: {e}")
        return FALLBACK_MODELS["Anthropic"]


async def fetch_gemini_models(api_key: str) -> List[str]:
    """Pobiera listę modeli Gemini."""
    try:
        # Configure Gemini API
        genai.configure(api_key=api_key)
        
        # List models - synchronous call wrapped in async
        loop = asyncio.get_event_loop()
        models_response = await loop.run_in_executor(None, list, genai.list_models())
        
        # Filter dla generative models
        generative_models = []
        for model in models_response:
            if 'generateContent' in model.supported_generation_methods:
                # Extract model name from full path
                model_name = model.name.split('/')[-1]  # models/gemini-pro -> gemini-pro
                generative_models.append(model_name)
        
        # Sortuj według priorytetu
        priority_models = ['gemini-2.5-flash', 'gemini-2.5-pro', 'gemini-2.0-flash']
        sorted_models = []
        
        for priority in priority_models:
            matches = [m for m in generative_models if priority in m]
            if matches:
                sorted_models.extend(sorted(matches, reverse=True))  # Newest first
        
        # Dodaj pozostałe
        other_models = [m for m in generative_models if not any(p in m for p in priority_models)]
        sorted_models.extend(sorted(other_models, reverse=True))
        
        return sorted_models[:15]
        
    except Exception as e:
        logging.warning(f"Nie można pobrać modeli Gemini: {e}")
        return FALLBACK_MODELS["Gemini"]


async def fetch_deepseek_models(api_key: str) -> List[str]:
    """Pobiera listę modeli DeepSeek."""
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            response = await client.get(
                "https://api.deepseek.com/v1/models",
                headers={"Authorization": f"Bearer {api_key}"}
            )
            response.raise_for_status()
            
            data = response.json()
            models = [model["id"] for model in data["data"]]
            
            # Sortuj - deepseek-chat najpierw
            if "deepseek-chat" in models:
                models.remove("deepseek-chat")
                models.insert(0, "deepseek-chat")
            
            return models
            
    except Exception as e:
        logging.warning(f"Nie można pobrać modeli DeepSeek: {e}")
        return FALLBACK_MODELS["DeepSeek"]


async def fetch_models_for_provider(provider: str, api_key: str) -> List[str]:
    """Pobiera modele dla konkretnego providera."""
    if not api_key or not api_key.strip():
        return FALLBACK_MODELS.get(provider, [])
    
    # Sprawdź cache
    cached_models = model_cache.get(provider)
    if cached_models:
        logging.info(f"Using cached models for {provider}")
        return cached_models
    
    # Fetch from API
    try:
        if provider == "OpenAI":
            models = await fetch_openai_models(api_key)
        elif provider == "Anthropic":
            models = await fetch_anthropic_models(api_key)
        elif provider == "Gemini":
            models = await fetch_gemini_models(api_key)
        elif provider == "DeepSeek":
            models = await fetch_deepseek_models(api_key)
        else:
            models = FALLBACK_MODELS.get(provider, [])
        
        # Cache wyniki
        if models:
            model_cache.set(provider, models)
            logging.info(f"Fetched and cached {len(models)} models for {provider}")
        
        return models
        
    except Exception as e:
        logging.error(f"Error fetching models for {provider}: {e}")
        return FALLBACK_MODELS.get(provider, [])


def get_default_model(provider: str) -> str:
    """Zwraca domyślny model dla providera."""
    defaults = {
        "OpenAI": "o4-mini",
        "Anthropic": "claude-3-7-sonnet-latest",
        "Gemini": "gemini-2.5-flash-preview-04-17", 
        "DeepSeek": "deepseek-chat"
    }
    return defaults.get(provider, "")


async def fetch_all_models(api_keys: Dict[str, str]) -> Dict[str, List[str]]:
    """Pobiera modele dla wszystkich providerów równocześnie."""
    tasks = []
    providers = ["OpenAI", "Anthropic", "Gemini", "DeepSeek"]
    
    for provider in providers:
        api_key = api_keys.get(provider, "")
        task = fetch_models_for_provider(provider, api_key)
        tasks.append((provider, task))
    
    results = {}
    for provider, task in tasks:
        try:
            models = await task
            results[provider] = models
        except Exception as e:
            logging.error(f"Failed to fetch models for {provider}: {e}")
            results[provider] = FALLBACK_MODELS.get(provider, [])
    
    return results