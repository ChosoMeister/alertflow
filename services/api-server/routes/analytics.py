"""
Analytics API - Aggregated alert statistics.
"""
import json
import time
from collections import defaultdict
from datetime import datetime, timedelta
from fastapi import APIRouter, Depends

from auth import User, get_current_user
from services.redis_service import get_redis_service

router = APIRouter(prefix="/analytics", tags=["analytics"])


@router.get("")
async def get_analytics(user: User = Depends(get_current_user)):
    """Compute analytics from all alerts in Redis.

    Returns severity distribution, daily trend, hourly distribution,
    top senders, status breakdown, and AI performance metrics.
    """
    redis_svc = get_redis_service()

    # Fetch all alerts (14-day retention means manageable dataset)
    all_alerts = redis_svc.list_alerts(limit=10000, offset=0)

    now = datetime.now()

    # Initialize accumulators
    severity_counts = defaultdict(int)
    status_counts = defaultdict(int)
    sender_stats = defaultdict(lambda: {"total": 0, "resolved": 0, "open": 0})
    daily_counts = defaultdict(int)  # "YYYY-MM-DD" -> count
    hourly_counts = defaultdict(int)  # hour (0-23) -> count
    ai_durations = []

    for alert in all_alerts:
        # Severity
        sev = alert.get("severity", "Unknown")
        severity_counts[sev] += 1

        # Status
        st = alert.get("status", "unknown")
        status_counts[st] += 1

        # Per-sender stats (total, resolved, open)
        sender = alert.get("from_email", "unknown")
        if sender:
            sender_stats[sender]["total"] += 1
            if st == "resolved":
                sender_stats[sender]["resolved"] += 1
            elif st in ("new", "acknowledged", "duplicate"):
                sender_stats[sender]["open"] += 1

        # Timestamp parsing for time-based charts
        ts = alert.get("created_at") or alert.get("timestamp") or alert.get("received_at", "")
        if ts:
            try:
                if isinstance(ts, (int, float)):
                    dt = datetime.fromtimestamp(float(ts))
                else:
                    # Try ISO format
                    dt = datetime.fromisoformat(str(ts).replace("Z", "+00:00").split("+")[0])

                # Daily trend (last 7 days)
                day_key = dt.strftime("%Y-%m-%d")
                daily_counts[day_key] += 1

                # Hourly distribution (last 24h only)
                if (now - dt).total_seconds() < 86400:
                    hourly_counts[dt.hour] += 1
            except (ValueError, TypeError, OSError):
                pass

        # AI duration
        ai_dur = alert.get("ai_duration")
        if ai_dur:
            try:
                ai_durations.append(float(ai_dur))
            except (ValueError, TypeError):
                pass

    # Build daily trend for last 7 days (fill gaps with 0)
    daily_trend = []
    for i in range(6, -1, -1):
        day = (now - timedelta(days=i)).strftime("%Y-%m-%d")
        daily_trend.append({
            "date": day,
            "label": (now - timedelta(days=i)).strftime("%a"),  # Mon, Tue, etc.
            "count": daily_counts.get(day, 0),
        })

    # Build hourly distribution (0-23, fill gaps)
    hourly_dist = []
    for h in range(24):
        hourly_dist.append({
            "hour": h,
            "label": f"{h:02d}:00",
            "count": hourly_counts.get(h, 0),
        })

    # Top senders (top 10 by total, with breakdown)
    top_senders = sorted(sender_stats.items(), key=lambda x: x[1]["total"], reverse=True)[:10]

    # Severity distribution (ordered)
    severity_order = ["Critical", "High", "Medium", "Low", "Info", "Unknown"]
    severity_dist = [
        {"severity": s, "count": severity_counts.get(s, 0)}
        for s in severity_order
        if severity_counts.get(s, 0) > 0
    ]

    # Status distribution
    status_dist = [
        {"status": s, "count": c}
        for s, c in sorted(status_counts.items(), key=lambda x: x[1], reverse=True)
    ]

    # AI performance
    avg_ai = round(sum(ai_durations) / len(ai_durations), 2) if ai_durations else 0

    return {
        "total_alerts": len(all_alerts),
        "resolved_count": status_counts.get("resolved", 0),
        "severity_distribution": severity_dist,
        "status_distribution": status_dist,
        "daily_trend": daily_trend,
        "hourly_distribution": hourly_dist,
        "top_senders": [
            {"email": email, "total": stats["total"], "resolved": stats["resolved"], "open": stats["open"]}
            for email, stats in top_senders
        ],
        "ai_performance": {
            "avg_duration": avg_ai,
            "total_analyzed": len(ai_durations),
        },
    }
