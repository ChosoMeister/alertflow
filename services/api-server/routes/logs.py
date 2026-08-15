"""
Logs API - Access to system logs.
"""
from datetime import datetime, timezone
import json
import os
import re
import time

import httpx
from fastapi import APIRouter, Depends, Query
from typing import Optional, List

from auth import User, get_current_user
from services.redis_service import get_redis_service

router = APIRouter(prefix="/logs", tags=["logs"])

LOKI_URL = os.getenv("LOKI_URL", "http://loki:3100").rstrip("/")
LOKI_SERVICES = {
    "alertflow-api", "alertflow-processor", "alertflow-smtp", "alertflow-ui", "alertflow-redis"
}
LEVEL_PATTERNS = {
    "error": r"(?i)(error|critical|traceback|exception|failed)",
    "warning": r"(?i)(warning|warn)",
    "info": r"(?i)(info)",
    "debug": r"(?i)(debug)",
}


def _detect_level(line: str, labels: dict) -> str:
    detected = str(labels.get("detected_level", "")).upper()
    if detected in {"ERROR", "CRITICAL", "WARNING", "WARN", "INFO", "DEBUG"}:
        if detected == "CRITICAL":
            return "ERROR"
        return "WARNING" if detected == "WARN" else detected
    if re.search(LEVEL_PATTERNS["error"], line):
        return "ERROR"
    if re.search(LEVEL_PATTERNS["warning"], line):
        return "WARNING"
    if re.search(LEVEL_PATTERNS["debug"], line):
        return "DEBUG"
    return "INFO"


def _is_ui_startup_line(item: dict) -> bool:
    if item.get("service") != "alertflow-ui":
        return False
    line = str(item.get("message", "")).strip()
    return bool(re.match(r"^(?:✓|▲|-\s+Local:|>\s+(?:next start|alertflow-ui@))", line))


def _collapse_ui_startup(logs: List[dict]) -> List[dict]:
    """Join adjacent Next.js startup lines while preserving newest-first records."""
    collapsed: List[dict] = []
    for item in logs:
        if collapsed and _is_ui_startup_line(item) and _is_ui_startup_line(collapsed[-1]):
            current_ts = datetime.fromisoformat(item["timestamp"])
            previous_ts = datetime.fromisoformat(collapsed[-1]["timestamp"])
            if abs((previous_ts - current_ts).total_seconds()) <= 2:
                collapsed[-1]["message"] = f'{item["message"].strip()}\n{collapsed[-1]["message"]}'
                continue
        collapsed.append(item)
    return collapsed


def _redis_fallback(limit: int, service: Optional[str], level: Optional[str], query: str) -> List[dict]:
    service_map = {
        "alertflow-api": "api",
        "alertflow-processor": "alert-processor",
        "alertflow-smtp": "smtp-ingestor",
    }
    logs = get_redis_service().get_recent_logs(
        count=min(limit, 500), service=service_map.get(service) if service else None
    )
    result = []
    for item in logs:
        if level and str(item.get("level", "")).lower() != level.lower():
            continue
        if query and query.lower() not in str(item.get("message", "")).lower():
            continue
        result.append(item)
    return result[:limit]


@router.get("", response_model=List[dict])
async def get_logs(
    limit: int = Query(default=100, le=500),
    service: Optional[str] = None,
    user: User = Depends(get_current_user)
):
    """Get recent logs with optional service filter."""
    redis_svc = get_redis_service()
    return redis_svc.get_recent_logs(count=limit, service=service)


@router.get("/search")
async def search_logs(
    limit: int = Query(default=200, ge=1, le=500),
    service: Optional[str] = Query(default=None),
    level: Optional[str] = Query(default=None),
    q: str = Query(default="", max_length=200),
    since_minutes: int = Query(default=60, ge=1, le=4320),
    user: User = Depends(get_current_user),
):
    """Query authenticated Loki logs, falling back to the existing Redis log stream."""
    if service and service not in LOKI_SERVICES:
        service = None
    level = level.lower() if level and level.lower() in LEVEL_PATTERNS else None

    selector = '{job="alertflow"'
    if service:
        selector += f',container={json.dumps(service)}'
    selector += "}"
    logql = selector
    if level and level != "info":
        logql += f" |~ {json.dumps(LEVEL_PATTERNS[level])}"
    if q.strip():
        logql += f" |= {json.dumps(q.strip())}"

    now_ns = time.time_ns()
    params = {
        "query": logql,
        "start": now_ns - since_minutes * 60 * 1_000_000_000,
        "end": now_ns,
        "direction": "backward",
        "limit": min(limit * 4, 2000) if level == "info" else limit,
    }
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            response = await client.get(f"{LOKI_URL}/loki/api/v1/query_range", params=params)
            response.raise_for_status()
            payload = response.json()
        logs = []
        for stream in payload.get("data", {}).get("result", []):
            labels = stream.get("stream", {})
            for timestamp_ns, line in stream.get("values", []):
                if not str(line).strip():
                    continue
                timestamp = datetime.fromtimestamp(int(timestamp_ns) / 1_000_000_000, tz=timezone.utc).isoformat()
                normalized_level = _detect_level(line, labels)
                if level and normalized_level.lower() != level:
                    continue
                logs.append({
                    "timestamp": timestamp,
                    "level": normalized_level,
                    "service": labels.get("container", labels.get("service_name", "unknown")),
                    "message": line,
                })
        logs.sort(key=lambda item: item["timestamp"], reverse=True)
        logs = _collapse_ui_startup(logs)
        return {"source": "loki", "available": True, "logs": logs[:limit]}
    except (httpx.HTTPError, ValueError, KeyError):
        return {
            "source": "redis",
            "available": False,
            "logs": _redis_fallback(limit, service, level, q.strip()),
        }


@router.get("/relay", response_model=List[dict])
async def get_relay_logs(
    limit: int = Query(default=100, le=500),
    user: User = Depends(get_current_user)
):
    """Get recent relay logs (notification dispatch history)."""
    redis_svc = get_redis_service()
    return redis_svc.get_relay_logs(limit=limit)
