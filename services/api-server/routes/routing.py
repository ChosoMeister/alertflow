"""
Routing Rules API - Full CRUD + test-match endpoint.
"""
from fastapi import APIRouter, Depends, HTTPException
from typing import List

from auth import User, get_current_user, require_admin
from models import RoutingRuleCreate, RoutingRule, RoutingTestRequest, RoutingTestResponse, ResolutionProfileCreate
from services.redis_service import get_redis_service
from services.routing_service import get_routing_result

router = APIRouter(prefix="/routing-rules", tags=["routing"])
profiles_router = APIRouter(prefix="/resolution-profiles", tags=["resolution-profiles"])


def _validate_resolution_profile(redis_svc, rule: RoutingRuleCreate):
    if not rule.resolution_profile_id:
        return
    profile = redis_svc.get_resolution_profile(rule.resolution_profile_id)
    if not profile or not profile.get("enabled"):
        raise HTTPException(status_code=400, detail="Resolution profile is missing or disabled")
    if not profile.get("notification_channel_ids"):
        raise HTTPException(status_code=400, detail="Resolution profile has no notification channels")


def _validate_destinations(redis_svc, rule: RoutingRuleCreate):
    severity_ids = [item for items in rule.severity_destination_ids.values() for item in items]
    for severity in rule.severity_destination_ids:
        if severity.lower() not in {"critical", "high", "medium", "low", "info"}:
            raise HTTPException(status_code=400, detail=f"Unsupported severity: {severity}")
    for destination_id in rule.alert_destination_ids + rule.resolved_destination_ids + severity_ids:
        item = redis_svc.get_notification_destination(destination_id)
        if not item or not item.get("enabled"):
            raise HTTPException(status_code=400, detail=f"Destination {destination_id} is missing or disabled")
    if not rule.alert_destination_ids:
        raise HTTPException(status_code=400, detail="At least one alert destination is required")
    if rule.resolution_mode != "legacy" and not rule.resolved_destination_ids:
        raise HTTPException(status_code=400, detail="Resolved destinations are required for copy/move mode")


@router.get("", response_model=List[dict])
async def list_routing_rules(user: User = Depends(get_current_user)):
    """List all routing rules ordered by priority."""
    redis_svc = get_redis_service()
    return redis_svc.list_routing_rules()


@router.post("", response_model=dict)
async def create_routing_rule(rule: RoutingRuleCreate, user: User = Depends(require_admin)):
    """Create a new routing rule."""
    redis_svc = get_redis_service()

    # Validation
    if not rule.email_pattern:
        raise HTTPException(status_code=400, detail="Email pattern is required")

    _validate_destinations(redis_svc, rule)

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
async def update_routing_rule(rule_id: str, rule: RoutingRuleCreate, user: User = Depends(require_admin)):
    """Update an existing routing rule."""
    redis_svc = get_redis_service()

    if not rule.email_pattern:
        raise HTTPException(status_code=400, detail="Email pattern is required")

    _validate_destinations(redis_svc, rule)

    if not redis_svc.update_routing_rule(rule_id, rule.model_dump()):
        raise HTTPException(status_code=404, detail="Rule not found")

    redis_svc.add_log("INFO", "api", f"Routing rule updated: {rule.name}")
    return {"message": "Routing rule updated"}


@router.delete("/{rule_id}")
async def delete_routing_rule(rule_id: str, user: User = Depends(require_admin)):
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


@profiles_router.get("", response_model=List[dict])
async def list_resolution_profiles(user: User = Depends(get_current_user)):
    return get_redis_service().list_resolution_profiles()


@profiles_router.post("", response_model=dict)
async def create_resolution_profile(profile: ResolutionProfileCreate, user: User = Depends(require_admin)):
    if not profile.notification_channel_ids:
        raise HTTPException(status_code=400, detail="At least one notification channel is required")
    return get_redis_service().add_resolution_profile(profile.model_dump())


@profiles_router.put("/{profile_id}", response_model=dict)
async def update_resolution_profile(profile_id: str, profile: ResolutionProfileCreate, user: User = Depends(require_admin)):
    if not profile.notification_channel_ids:
        raise HTTPException(status_code=400, detail="At least one notification channel is required")
    updated = get_redis_service().update_resolution_profile(profile_id, profile.model_dump())
    if not updated:
        raise HTTPException(status_code=404, detail="Resolution profile not found")
    return updated


@profiles_router.delete("/{profile_id}")
async def delete_resolution_profile(profile_id: str, user: User = Depends(require_admin)):
    redis_svc = get_redis_service()
    profile = redis_svc.get_resolution_profile(profile_id)
    if not profile:
        raise HTTPException(status_code=404, detail="Resolution profile not found")
    if not redis_svc.delete_resolution_profile(profile_id):
        raise HTTPException(status_code=409, detail="Resolution profile is still used by routing rules")
    return {"message": "Resolution profile deleted"}
