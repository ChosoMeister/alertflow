# Routing and notifications

## Objects

| Object | Contains | Example |
|---|---|---|
| Connector | credentials/transport | Telegram bot token or Matrix homeserver/token |
| Destination | endpoint coordinates | Telegram chat/thread or Matrix room |
| Rule | Destination IDs | Alert, severity-specific, and Resolved lists |

Never duplicate tokens per Rule. Use one connector with multiple reusable destinations.

Destination fields:

- Telegram: `channel_id`, `chat_id`, optional `thread_id` (`0` means no topic).
- Matrix: `channel_id`, `room_id`.
- Webhook: `channel_id`, `url`.
- SMS: `channel_id`, `receptor`.

## Rule evaluation

Rules match sender (`from`) or recipients (`to`) with case-insensitive globs. Lower priority runs first. Equal-priority rules prefer the more specific pattern and then stable ID ordering.

Every Rule requires at least one enabled Alert Destination. All default, severity, and resolved references must exist and be enabled.

## Severity policy

Supported values are `critical`, `high`, `medium`, `low`, and `info`.

- Unchecked: inherit default Alert destinations.
- Checked with destinations: replace defaults for that severity.
- Each list stays collapsed until its checkbox is enabled.

```json
{
  "alert_destination_ids": ["team-tg", "team-mx"],
  "severity_destination_ids": {
    "critical": ["noc-tg", "noc-mx"],
    "high": ["team-tg"]
  }
}
```

Medium, Low, and Info inherit both defaults in this example.

## Resolve policy

- `legacy`: edit the known active incident message in place.
- `copy`: send a complete card to Resolved destinations and retain active messages.
- `move`: deliver to every Resolved destination, then delete or tombstone active messages.

Copy and Move require a Resolved Destination. Cards preserve the original problem and complete timeline and stay inside provider character limits.

## Partial failure

Each Destination has independent delivery identity, retry status, and message ID. If Telegram succeeds and Matrix fails, Telegram success is persisted, only Matrix retries, AI/correlation are not rerun, and Move retains active messages until Matrix succeeds.

## Pre-2.11 migration

```bash
# dry-run; must report no blockers
docker compose run --rm --no-deps -v "$PWD:/workspace" -w /workspace \
  api-server python scripts/migrate_rules_destination_only.py

# apply after a Redis snapshot
docker compose run --rm --no-deps -v "$PWD:/workspace" -w /workspace \
  api-server python scripts/migrate_rules_destination_only.py --apply
```

The migration refuses cleanup if a Rule lacks an Alert Destination or references a missing Destination.

## راهنمای فارسی

ساختار نهایی سه بخش دارد: Connector اطلاعات اتصال را نگه می‌دارد، Destination آدرس واقعی گروه/ترد/اتاق را مشخص می‌کند و Rule فقط Destinationها را انتخاب می‌کند.

تیک Severity را فقط وقتی فعال کنید که مقصد آن باید با Alert Destination اصلی فرق داشته باشد. Severity بدون تیک از مقصد اصلی ارث می‌برد.

- `Keep in place`: همان پیام Incident رفع‌شده می‌شود.
- `Copy`: کارت کامل Resolve در مقصد جدید ساخته و پیام فعال نگه داشته می‌شود.
- `Move`: ابتدا کارت به همه مقصدهای Resolve می‌رسد و بعد پیام فعال حذف می‌شود.
