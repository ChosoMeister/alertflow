#!/usr/bin/env python3
"""Idempotent Redis schema marker for AlertFlow 2.2.0."""
import os
import redis


client = redis.Redis(
    host=os.getenv("REDIS_HOST", "localhost"),
    port=int(os.getenv("REDIS_PORT", "6379")),
    password=os.getenv("REDIS_PASSWORD") or None,
    decode_responses=True,
)
client.hset("alertflow:schema", mapping={
    "version": "2.2.0",
    "storm_control": "enabled",
    "incident_timeline": "enabled",
    "slo_metrics": "enabled",
})
print("AlertFlow schema is at 2.2.0")
