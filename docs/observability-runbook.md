# Observability backup and recovery runbook

AlertFlow's log path is `Docker -> Alloy -> Loki -> authenticated API -> Logs panel`. Loki is localhost-only and retains three days. The processor checks disk usage, readiness, volume growth, and a synthetic canary.

Notification and ingestion safeguards:

- Telegram errors are credential-redacted before Docker and Loki receive them. MarkdownV2 parse failures receive one plain-text retry.
- Repeated Telegram transport failures open a short local circuit; normal retry backoff remains responsible for recovery.
- The selected fallback AI provider is probed without creating an alert, incident, or notification.
- `alertflow_smtp_accepted_total` and `alertflow_smtp_processed_total` expose internal SMTP-to-processor reconciliation. Comparing against upstream sender counters still requires source-side metrics.
- `alertflow_dlq_active_depth` excludes historical entries superseded by a newer successful incident delivery.

## Health checks

- Dashboard Observability cards and authenticated `GET /api/observability-health`.
- Prometheus `GET /api/metrics` (`alertflow_observability_*`).
- Host: `curl -fsS http://127.0.0.1:3100/ready`.
- Alloy: `docker exec alertflow-processor python -c 'import requests; print(requests.get("http://alloy:12345/-/ready", timeout=3).text)'`.

Defaults in `.env` are disk warning `70%`, critical `85%`, and Loki growth warning `250 MiB/hour`. Alerts are emitted only on transitions.

## Backup

Run from `/docker/alertflow`. For a consistent snapshot, briefly stop Loki; Alloy will buffer and resume.

```bash
backup_dir=/docker/alertflow-backups/$(date +%F-%H%M%S)
mkdir -p "$backup_dir"
docker compose stop loki
docker run --rm -v alertflow_loki_data:/source:ro -v "$backup_dir":/backup redis:7-alpine tar -C /source -czf /backup/loki-data.tar.gz .
docker compose start loki
tar -tzf "$backup_dir/loki-data.tar.gz" >/dev/null
curl -fsS http://127.0.0.1:3100/ready
```

Also preserve Compose/Loki/Alloy configuration. Never export `.env` outside the server.

## Restore

Restore replaces current log data and requires an approved maintenance window and a fresh pre-restore backup.

```bash
cd /docker/alertflow
docker compose stop loki
docker run --rm -v alertflow_loki_data:/target -v /absolute/backup/directory:/backup:ro redis:7-alpine sh -c 'find /target -mindepth 1 -delete && tar -C /target -xzf /backup/loki-data.tar.gz'
docker compose start loki
curl -fsS http://127.0.0.1:3100/ready
```

Then verify observability health, query a known marker via `/api/logs/search`, and render it in the panel. If it fails, keep Loki stopped and restore the pre-maintenance archive.

## Triage

- Disk: inspect `docker system df -v`; never blindly prune named volumes.
- Loki/Alloy: inspect the corresponding container's last 30 minutes of logs.
- Canary failure with healthy services: query its marker directly and inspect Alloy discovery labels.
- Growth warning: identify noisy containers with LogQL rates before changing retention or filters.
