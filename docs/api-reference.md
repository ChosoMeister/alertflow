# API reference

OpenAPI is available at `/docs` on the API service. Except health and explicitly configured webhook ingestion, operational routes require `Authorization: Bearer <JWT>`.

## Core routes

- Authentication: `POST /api/auth/login`
- Rules: `GET/POST /api/routing-rules`, `GET/PUT/DELETE /api/routing-rules/{id}`, `POST /api/routing-rules/test-match`
- Connectors: `GET/POST /api/notification-channels`, `GET/PUT/DELETE /api/notification-channels/{id}`, `POST /api/notification-channels/{id}/test`
- Destinations: `GET /api/notification-channels/destinations/list`, `POST /api/notification-channels/destinations`, `PUT/DELETE /api/notification-channels/destinations/{id}`
- AI providers: `/api/ai-providers/*`
- Alerts: `/api/alerts/*`
- Simulation: `/api/test-email/*`
- Health/metrics: `/api/health`, `/api/status`, `/api/metrics`, `/api/observability-health`
- Logs/analytics/SSE: `/api/logs/*`, `/api/analytics/*`, `/api/sse/*`
- Webhook ingestion: `/api/webhook/*`

## Destination-only Rule request

```json
{
  "name": "Grafana-Example",
  "enabled": true,
  "priority": 0,
  "match_field": "from",
  "email_pattern": "Grafana-Example@example.com",
  "ai_provider_id": null,
  "alert_destination_ids": ["default-tg", "default-mx"],
  "severity_destination_ids": {"critical": ["noc-tg", "noc-mx"]},
  "resolved_destination_ids": ["resolved-tg", "resolved-mx"],
  "resolution_mode": "move",
  "notes": ""
}
```

The API rejects missing/disabled destinations, unsupported severity keys, empty Alert lists, and Copy/Move without Resolved destinations. Destination deletion is refused while any default, severity, or resolved policy references it.

## AI provider example

An OpenAI-compatible provider such as vLLM uses a chat-completions URL and model name:

```text
base URL: https://ai.example.com/v1/chat/completions
model: gemma4:26b
```

Use generated OpenAPI as the exact source for optional fields, response shapes, and role requirements.
