# Architecture

## Components

### SMTP Ingestor

Accepts SMTP messages, parses MIME text/HTML, assigns trace metadata, and appends payloads to the Redis stream. SMTP acceptance is not equivalent to notification delivery; reconciliation metrics expose each stage.

### API Server

Provides JWT-authenticated CRUD, health, metrics, alert history, queue inspection, routing tests, log queries, and runtime settings. Redis is the authoritative configuration and incident-state store.

### Alert Processor

For every payload it normalizes the source, selects the configured AI provider/fallback, validates AI claims against source evidence, derives correlation identity and lifecycle action, applies deduplication/merge/storm control, snapshots destinations, dispatches bounded provider messages, and retries only failed destinations.

### Redis

Stores rules, connectors, destinations, providers, alerts, open incident sets, timelines, delivery identities, metrics, retries, and the DLQ. Persistence uses AOF plus release snapshots.

### Web UI, Alloy, and Loki

The UI manages operational state. Alloy collects container logs into a short-retention local Loki store. Loki is localhost-only and users query it through the authenticated API.

## Configuration objects

```text
Connector (credentials)
  └── Destination (endpoint coordinates)
        ├── Rule default Alert destinations
        ├── Rule severity destination policy
        └── Rule Resolved destinations
```

One connector may serve multiple destinations. Message identity is Destination-scoped, preventing collisions when one Telegram bot serves multiple threads.

## Incident lifecycle

- `NEW`: create open state, snapshot routing, and send new messages.
- `MERGE`/`UPDATE`: enrich state and edit known destination messages.
- exact duplicate: record suppression without over-notifying.
- `RESOLVE`: build a bounded card with problem, resources, complete timeline, duration, occurrence, merge, and suppression counts.
- orphan recovery: retain closed evidence without opening an outage.
- stale: mark inactivity; never fabricate resolution.

Open incidents retain the actual destination snapshots and message IDs used at creation. Later Rule changes do not silently move them.

## Reliability

- Multi-destination success requires every required destination.
- Partial failure retries only failed Destination IDs.
- `Move` never removes active messages before all resolved deliveries succeed.
- Exhausted active failures enter the DLQ with lifecycle/dedupe metadata.
- Telegram formatting errors receive plain-text fallback; transport failures participate in circuit breaking.
- AI fallback does not create an additional alert or incident.

## Security

- Secrets belong to `.env` or controlled runtime configuration, never Git.
- Redis and Loki bind to localhost.
- Operational API routes require JWT authentication.
- Notification errors are credential-redacted before logging.
- Connector and Destination deletion is blocked while referenced.
