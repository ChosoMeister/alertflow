"""
AI Providers API - CRUD for AI models and providers.
"""
from typing import List, Optional, Literal
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from auth import User, get_current_user, require_admin
from services.redis_service import get_redis_service

router = APIRouter(prefix="/ai-providers", tags=["ai-providers"])


class AIProviderConfig(BaseModel):
    name: str
    type: Literal["ollama", "openai", "vllm", "custom"] = "ollama"
    base_url: str
    model: str
    api_key: Optional[str] = None
    timeout: int = 120
    is_default: bool = False
    is_fallback: bool = False


class AIProviderResponse(AIProviderConfig):
    id: str
    api_key_configured: bool = False


def _public_provider(provider: dict) -> dict:
    """Return provider metadata without exposing credentials."""
    public = dict(provider)
    public["api_key_configured"] = bool(public.get("api_key"))
    public["api_key"] = None
    return public


@router.get("", response_model=List[AIProviderResponse])
async def list_ai_providers(user: User = Depends(get_current_user)):
    """List all AI providers."""
    redis_svc = get_redis_service()
    providers = redis_svc.get_ai_providers()
    return [_public_provider(provider) for provider in providers]


@router.post("", response_model=AIProviderResponse)
async def create_ai_provider(
    provider: AIProviderConfig,
    user: User = Depends(require_admin)
):
    """Create a new AI provider."""
    redis_svc = get_redis_service()

    if provider.is_default and provider.is_fallback:
        raise HTTPException(status_code=400, detail="A provider cannot be both default and fallback")

    if provider.is_default:
        redis_svc.unset_default_ai_provider()
    if provider.is_fallback:
        redis_svc.unset_fallback_ai_provider()

    new_provider = redis_svc.add_ai_provider(provider.model_dump())
    return _public_provider(new_provider)


@router.get("/{provider_id}", response_model=AIProviderResponse)
async def get_ai_provider(
    provider_id: str,
    user: User = Depends(get_current_user)
):
    """Get a specific AI provider."""
    redis_svc = get_redis_service()
    provider = redis_svc.get_ai_provider(provider_id)
    if not provider:
        raise HTTPException(status_code=404, detail="Provider not found")
    return _public_provider(provider)


@router.put("/{provider_id}", response_model=AIProviderResponse)
async def update_ai_provider(
    provider_id: str,
    provider: AIProviderConfig,
    user: User = Depends(require_admin)
):
    """Update an AI provider."""
    redis_svc = get_redis_service()

    existing = redis_svc.get_ai_provider(provider_id)
    if not existing:
        raise HTTPException(status_code=404, detail="Provider not found")

    if provider.is_default and provider.is_fallback:
        raise HTTPException(status_code=400, detail="A provider cannot be both default and fallback")

    if provider.is_default:
        redis_svc.unset_default_ai_provider()
    if provider.is_fallback:
        redis_svc.unset_fallback_ai_provider()

    provider_data = provider.model_dump()
    if not provider_data.get("api_key"):
        provider_data["api_key"] = existing.get("api_key", "")
    updated = redis_svc.update_ai_provider(provider_id, provider_data)
    return _public_provider(updated)


@router.delete("/{provider_id}")
async def delete_ai_provider(
    provider_id: str,
    user: User = Depends(require_admin)
):
    """Delete an AI provider."""
    redis_svc = get_redis_service()

    existing = redis_svc.get_ai_provider(provider_id)
    if not existing:
        raise HTTPException(status_code=404, detail="Provider not found")

    redis_svc.delete_ai_provider(provider_id)
    return {"message": "Provider deleted"}


@router.post("/{provider_id}/test")
def test_ai_provider(
    provider_id: str,
    user: User = Depends(require_admin)
):
    """Test an AI provider connection."""
    import requests

    redis_svc = get_redis_service()
    provider = redis_svc.get_ai_provider(provider_id)
    if not provider:
        raise HTTPException(status_code=404, detail="Provider not found")

    try:
        headers = {"Content-Type": "application/json"}
        if provider.get("api_key"):
            headers["Authorization"] = f"Bearer {provider['api_key']}"

        payload = {
            "model": provider["model"],
            "messages": [{"role": "user", "content": "ping"}],
            "max_tokens": 5
        }

        response = requests.post(
            provider["base_url"],
            json=payload,
            headers=headers,
            timeout=provider.get("timeout", 120)
        )

        if response.status_code == 200:
            return {"status": "success", "message": "Provider is reachable"}
        else:
            return {"status": "error", "message": f"API returned {response.status_code}"}

    except requests.exceptions.Timeout:
        return {"status": "error", "message": "Connection timeout"}
    except requests.exceptions.RequestException as e:
        return {"status": "error", "message": str(e)}
