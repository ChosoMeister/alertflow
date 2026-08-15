# Deployment and operations

## Checks

```bash
git diff --check
python3 -m compileall -q services scripts
cd web-ui && npm run build && npx tsc --noEmit
docker compose config
```

Run regression tests under Python 3.11. Routing changes require destination and partial-delivery coverage.

## Deploy

`scripts/deploy.sh` archives source without `.env`, snapshots Redis, records prior images, builds immutable commit-tagged images, starts services, and enforces API/Loki health gates.

```bash
cd /docker/alertflow
ALERTFLOW_GIT_COMMIT=$(git rev-parse HEAD) \
ALERTFLOW_RELEASE=$(cat VERSION) ./scripts/deploy.sh
```

On health failure it invokes `scripts/rollback.sh` with the release snapshot.

## Verify

```bash
curl -fsS http://127.0.0.1:8000/api/health
curl -fsS http://127.0.0.1:3100/ready
curl -sS -o /dev/null -w '%{http_code}\n' http://127.0.0.1:3000/fa/routing
docker ps --format '{{.Names}} {{.Status}} {{.Image}}'
docker compose logs --since=10m api-server alert-processor web-ui smtp-ingestor
```

Confirm every Rule has an Alert Destination, destination references are valid, retry/active-DLQ/pending counts are zero or explained, new containers have zero restarts, and routing preview selects the intended Rule.

Do not send live test notifications unless recipients are explicitly in scope.

## Rollback

```bash
./scripts/rollback.sh /docker/alertflow-backups/release-<version>-<timestamp>
```

Then verify API health, Redis, image tags, queues, and a known Rule through authenticated read-only calls.

## Triage

- Delivery failure: inspect destination-specific evidence.
- Over-notification: inspect correlation identity, duplicate audit, merge counts, and storm summaries.
- Missing notification: trace raw -> normalized -> AI -> validation -> incident action -> destination snapshot -> delivery.
- Resolve not moved: one or more required resolved deliveries failed; retention is intentional.
- Disk pressure: use `docker system df -v`; never blindly prune named volumes.

See [Observability runbook](observability-runbook.md) for Loki backup and recovery.
