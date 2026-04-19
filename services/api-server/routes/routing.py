"""
Routing Rules API - Full CRUD + test-match endpoint.
"""
from fastapi import APIRouter, Depends, HTTPException
from typing import List

from auth import User, get_current_user
from models import RoutingRuleCreate, RoutingRule, RoutingTestRequest, RoutingTestResponse
from services.redis_service import get_redis_service
from services.routing_service import get_routing_result

router = APIRouter(prefix="/routing-rules", tags=["routing"])


@router.get("", response_model=List[dict])
async def list_routing_rules(user: User = Depends(get_current_user)):
    """List all routing rules ordered by priority."""
    redis_svc = get_redis_service()
    return redis_svc.list_routing_rules()


@router.post("", response_model=dict)
async def create_routing_rule(rule: RoutingRuleCreate, user: User = Depends(get_current_user)):
    """Create a new routing rule."""
    redis_svc = get_redis_service()
    
    # Validation
    if not rule.email_pattern:
        raise HTTPException(status_code=400, detail="Email pattern is required")
    
    if rule.channels in ["telegram", "both"] and not rule.telegram_chat_id:
        raise HTTPException(status_code=400, detail="Telegram Chat ID is required for telegram/both channels")
    
    if rule.channels in ["matrix", "both"] and not rule.matrix_room_id:
        raise HTTPException(status_code=400, detail="Matrix Room ID is required for matrix/both channels")
    
    if rule.channels == "dynamic" and not rule.notification_channel_ids:
        raise HTTPException(status_code=400, detail="At least one notification channel is required for dynamic routing")
    
    rule_id = redis_svc.add_routing_rule(rule.model_dump())
    redis_svc.add_log("INFO", "api", f"Routing rule created: {rule.name} ({rule.email_pattern})")
    
    return {"id": rule_id, "message": "Routing rule created"}


@router.get("/{rule_id}", response_model=dict)
async def get_routing_rule(rule_id: str, user: User = Depends(get_current_user)):
    """Get a specific routing rule."""
    redis_svc = get_redis_service()
    rule = redis_svc.get_routing_rule(rule_id)
    if not rule:
        raise HTTPException(status_code=404, detail="Rule not found")
    return rule


@router.put("/{rule_id}", response_model=dict)
async def update_routing_rule(rule_id: str, rule: RoutingRuleCreate, user: User = Depends(get_current_user)):
    """Update an existing routing rule."""
    redis_svc = get_redis_service()
    
    if not rule.email_pattern:
        raise HTTPException(status_code=400, detail="Email pattern is required")
    
    if rule.channels in ["telegram", "both"] and not rule.telegram_chat_id:
        raise HTTPException(status_code=400, detail="Telegram Chat ID is required for telegram/both channels")
    
    if rule.channels in ["matrix", "both"] and not rule.matrix_room_id:
        raise HTTPException(status_code=400, detail="Matrix Room ID is required for matrix/both channels")
    
    if rule.channels == "dynamic" and not rule.notification_channel_ids:
        raise HTTPException(status_code=400, detail="At least one notification channel is required for dynamic routing")
    
    if not redis_svc.update_routing_rule(rule_id, rule.model_dump()):
        raise HTTPException(status_code=404, detail="Rule not found")
    
    redis_svc.add_log("INFO", "api", f"Routing rule updated: {rule.name}")
    return {"message": "Routing rule updated"}


@router.delete("/{rule_id}")
async def delete_routing_rule(rule_id: str, user: User = Depends(get_current_user)):
    """Delete a routing rule."""
    redis_svc = get_redis_service()
    
    if not redis_svc.delete_routing_rule(rule_id):
        raise HTTPException(status_code=404, detail="Rule not found")
    
    redis_svc.add_log("INFO", "api", f"Routing rule deleted: {rule_id}")
    return {"message": "Routing rule deleted"}


@router.post("/test-match", response_model=RoutingTestResponse)
async def test_routing_match(request: RoutingTestRequest, user: User = Depends(get_current_user)):
    """Test which routing rule matches an email address."""
    redis_svc = get_redis_service()
    rules = redis_svc.list_routing_rules()
    
    result = get_routing_result(request.email_address, request.match_field, rules)
    return result
