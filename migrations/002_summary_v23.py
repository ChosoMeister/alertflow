#!/usr/bin/env python3
"""Idempotent schema marker for AlertFlow summary and storm controls."""
import os
import redis

client = redis.Redis(
    host=os.getenv("REDIS_HOST", "localhost"),
    port=int(os.getenv("REDIS_PORT", "6379")),
    password=os.getenv("REDIS_PASSWORD") or None,
    decode_responses=True,
)
client.hset("alertflow:schema", mapping={
    "version": "2.3.0",
    "global_storm_summary": "enabled",
    "incident_daily_summary": "enabled",
})
print("AlertFlow schema is at 2.3.0")
