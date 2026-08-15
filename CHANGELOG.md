# Changelog

## 2.11.0 - 2026-08-15

- Make routing rules destination-only and remove legacy connector targets and per-rule endpoint overrides.
- Route Critical, High, Medium, Low, and Info alerts through destination lists, with empty severity policies inheriting the rule's default Alert destinations.
- Validate every default, resolved, and severity destination before saving a rule and include severity usage in destination deletion protection.
- Add a guarded production migration that refuses cleanup unless every rule has a valid Alert destination.
- Replace outdated routing documentation with current architecture, Destination-only API, migration, deployment, rollback, and Persian operator guidance.

## 2.10.0 - 2026-08-15

- Separate credential-bearing notification connectors from reusable Telegram chat/thread, Matrix room, webhook, and SMS destinations.
- Give every routing rule independent multi-select Alert and Resolved destination lists with legacy, copy, and move lifecycle modes.
- Support multiple Telegram threads through one bot without message-ID collisions by persisting destination-scoped message identities.
- Preserve existing severity overrides and legacy routing while providing an idempotent migration for current rule endpoint overrides.
- Retry failed destinations independently and remove active messages only after all required resolved destinations have delivered.
- Replace raw Resolution Profile JSON controls with explicit Chat ID, Thread ID, Room ID and endpoint selectors.

## 2.9.0 - 2026-08-15

- Add reusable, opt-in resolution profiles without changing legacy routing rules.
- Archive resolved incidents as new, size-bounded Telegram and Matrix cards containing the original problem, affected resources, lifecycle timestamps, duration, occurrence, merge, and suppression counts.
- Snapshot active and resolved routing when an incident opens so later configuration changes cannot move it unexpectedly.
- Delete or redact active messages only after the resolved archive is delivered; use an explicit tombstone when provider policy prevents removal.
- Retry partial resolved-archive delivery without rerunning AI, and retain the active message when delivery is exhausted into the DLQ.
- Add resolution profile management and per-rule behavior controls to the routing UI.

## 2.8.1 - 2026-08-15

- Treat storage claims inferred only from a Grafana DatasourceNoData rule name as unsupported until a concrete PVC, volume, pod, or node is present in the payload.

## 2.8.0 - 2026-08-15

- Ground AI claims in source evidence and prevent Grafana datasource UIDs from being presented as PVC or volume names.
- Canonicalize categories for known alert families while preserving generic AI support for new senders.
- Separate resolved event state from the original incident severity in Telegram, Matrix, API, and UI.
- Calibrate evidence confidence independently from model confidence and expose validation warnings to operators.
- Remove speed, date, and label fragments from extracted resources and strengthen Syncovery correlation identities.
- Retain a bounded, redacted 24-hour audit record for exact duplicate suppression.
- Export analysis quality and validation override metrics through JSON and Prometheus endpoints.
- Add production-derived regression coverage for Grafana, Veeam, Syncovery, lifecycle, and resource grounding.

## 2.7.0 - 2026-08-09

- Prevent stale retries from overwriting newer incident revisions and automatically retire recovered DLQ entries.
- Separate active DLQ failures from historical or superseded entries in the API, metrics, UI, and daily summary.
- Redact credentials from notification errors and fall back to plain text when Telegram rejects MarkdownV2.
- Add a bounded Telegram network circuit breaker for DNS, TLS, and timeout incidents.
- Add a no-notification synthetic canary for the configured fallback AI provider.
- Bound incident resource state and report omitted resource counts for noisy backup alerts.
- Reconcile accepted SMTP messages with processor intake and export the gap through operational metrics.
- Expand the daily summary with partial delivery, missed delivery, active DLQ, noisy incidents, fallback health, and superseded retries.
- Build immutable commit-tagged images and retain source plus release metadata for deterministic rollback.

## 2.6.1 - 2026-08-06

- Resolve legacy Telegram and Matrix message targets through current channel credentials.
- Deduplicate exhausted delivery groups before inserting repeated incident updates into the DLQ.
- Separate final alert delivery from individual delivery-attempt success in analytics.
- Persist AI provider and duration metadata for normal alerts.
- Remove bare URL schemes and timestamps from Uptime Kuma resource identities.
- Surface repeated or exhausted delivery failures in the incident workspace.

## 2.5.1 - 2026-08-04

- Render legacy Unix timeline timestamps correctly in the incident drawer.

## 2.5.0 - 2026-08-04

- Redesign the dashboard as an incident-centric operations command center.
- Add an in-context incident drawer with AI evidence, correlation reasoning, resources, timeline, and response actions.
- Add responsive mobile navigation, a command palette, saved incident views, and density controls.
- Modernize visual hierarchy, surfaces, severity states, empty states, telemetry and capacity panels.
- Feed the live dashboard enough active alerts for reliable incident grouping.

## 2.4.3 - 2026-08-04

- Measure host disk capacity through an empty read-only bind mount on the host filesystem.

## 2.4.2 - 2026-08-04

- Truncate Telegram summaries only at complete Markdown line boundaries.
- Rate-limit failed catch-up summary delivery attempts to once every five minutes.

## 2.4.1 - 2026-08-04

- Expire closed incidents and their timelines after retention and repair legacy records without TTL.
- Make daily summaries restart-safe and idempotent with a Redis delivery lock.
- Bound and expire the dead-letter queue and remove idle Redis Stream consumers safely.
- Report rolling 24-hour processing and error metrics alongside lifetime totals.
- Measure disk usage from the persistent host-backed observability volume.
- Authenticate dashboard SSE through the secure session cookie without URL credentials.
- Record release provenance on containers and prune old Docker build cache after healthy deploys.

## 2.4.0 - 2026-08-04

- Add deterministic two-stage correlation identities before AI fallback.
- Ignore volatile timestamps, counts, durations, status words, and transient measurements in incident identity.
- Keep shared pipelines separate by stable feed subject and concrete resource.
- Add an open-incident identity registry for reliable NEW, MERGE, and RESOLVE lifecycle decisions.
- Add a reversible production migration to consolidate only identical open incident groups.

## 2.3.2 - 2026-08-04

- Store unmatched recovery messages as closed orphan resolutions instead of new open incidents.
- Repair legacy incident context and supersede only exact semantic duplicates with reversible backups.
- Count exact duplicates as suppressed occurrences without re-analysis or notification.
- Normalize noisy resource identifiers while preserving exact VM, PVC, host, and path names.
- Make daily resolved/new counts incident-centric.
- Persist message IDs and delivery evidence after legacy retries.
- Verify manual Telegram/Matrix edits and retry failed destinations.

## 2.3.1 - 2026-08-04

- Route Daily and Storm summaries to the configured summary Telegram chat and thread.

## 2.3.0 - 2026-08-04

### Added

- Global disaster storm cap with Critical/RESOLVED/AlertFlow exemptions.
- Editable Storm Summary and a final recovery report.
- Incident-centric Daily Operational Summary with resources, SLA, occurrences, health, and required actions.
- Live Storm and incident SLA settings in the admin Settings page.

### Changed

- Repeated notifications can be suppressed without dropping alert storage, AI analysis, incident correlation, or timeline events.

## 2.2.0 - 2026-08-04

### Added

- Alert-storm grouping, rate limiting, cooldown tracking, and suppression metrics.
- Production SLO/SLA dashboard for availability, delivery, AI, MTTR, fallback, and storm control.
- Transition-based AI primary/fallback/all-providers-down monitoring.
- Unified incident timeline covering occurrences, delivery attempts, suppression, and operator actions.
- Versioned migration, validated deployment, and health-gated rollback tooling.

### Changed

- Dynamic Telegram delivery now honors saved default chat and thread destinations.
- Observability health includes the effective AI chain state.

### Upgrade

Run `python3 migrations/001_observability_v22.py`, then `scripts/deploy.sh` from the deployment host. The migration is idempotent.
## 2.6.0 - 2026-08-04

### Added

- Reliability Scorecard with operational coverage, delivery health, prevented-notification and correlation metrics.
- Explicit notification decision reasons for sent, updated, storm-suppressed and redundant alerts.
- Incident Impact View based on correlated resources and occurrence count.
- Secret-free Telegram and Matrix notification previews with per-channel delivery and retry state.

### Changed

- Persist correlation identity, target resources and exact rendered notification payloads with each new alert.
- Label the aggregate reliability score as operational health rather than semantic AI correctness.
