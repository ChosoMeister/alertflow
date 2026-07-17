# AlertFlow

### AI-assisted alert correlation, incident lifecycle management, and multi-channel routing—built for teams that want to keep operational data under their control.

[![FastAPI](https://img.shields.io/badge/FastAPI-0.109-009688?logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com/)
[![Next.js](https://img.shields.io/badge/Next.js-14-black?logo=next.js)](https://nextjs.org/)
[![Redis](https://img.shields.io/badge/Redis-7-DC382D?logo=redis&logoColor=white)](https://redis.io/)
[![Python](https://img.shields.io/badge/Python-3.11-3776AB?logo=python&logoColor=white)](https://www.python.org/)
[![Docker](https://img.shields.io/badge/Deployment-Docker_Compose-2496ED?logo=docker&logoColor=white)](https://docs.docker.com/compose/)

**English** · [فارسی](#معرفی-alertflow)

AlertFlow is an open-source alert-processing platform for infrastructure and operations teams. It accepts alerts over SMTP or authenticated HTTP webhooks, normalizes and queues them in Redis, enriches them through an OpenAI-compatible model, correlates related events into incidents, and routes the result to Telegram, Matrix, generic webhooks, or Kavenegar SMS.

The product is designed for the gap between monitoring and incident response. Monitoring systems report symptoms; AlertFlow turns those symptoms into a compact operational record containing severity, affected resource, incident state, technical context, and recommended actions.

> AlertFlow is not a replacement for Prometheus, Zabbix, Grafana, or an ITSM platform. It is the intelligence and delivery layer between alert producers and the engineers who respond to them.

## What engineering teams get

- **Less duplicate noise:** byte-level duplicate detection and AI-assisted incident correlation reduce repeated notifications.
- **Incident-aware delivery:** updates and recovery events can edit the original Telegram or Matrix notification instead of producing disconnected messages.
- **Actionable AI output:** the analysis contract asks for severity, category, status, source host, target resource, a one-sentence diagnosis, relevant facts, and specific remediation steps.
- **Routing as configuration:** match sender or recipient addresses with ordered glob rules, select a model per route, and override delivery targets by severity.
- **Operational resilience:** failed deliveries enter a scheduled retry queue and eventually a dead-letter queue instead of disappearing.
- **Self-hosting:** the application and Redis run locally; the AI endpoint may also be a local Ollama or another OpenAI-compatible service.
- **A usable control plane:** the bilingual dashboard exposes alerts, incidents, analytics, queues, logs, providers, channels, routing rules, health, and administrative settings.

## Screenshots

![AlertFlow operations dashboard](docs/demo_dashboard.png)

| Alert investigation | Routing configuration |
| --- | --- |
| ![Alert details and operations](docs/demo_alerts.png) | ![Routing rules and targets](docs/demo_rules.png) |

## Core capabilities

### 1. Ingestion

AlertFlow provides two input paths that converge on the same Redis-backed processing pipeline:

- **SMTP ingest:** an asynchronous `aiosmtpd` service receives email envelopes, extracts text/HTML content and recipients, and pushes normalized payloads to `alert_queue`.
- **HTTP webhook ingest:** `POST /api/webhook/{source_name}` accepts arbitrary JSON or plain text, requires `X-Webhook-Token`, rejects payloads larger than 512 KB, and converts the request into the same internal message format as SMTP.

This makes it possible to connect traditional email-only products and modern webhook-capable systems without maintaining separate processing logic.

### 2. Structured AI analysis

The processor calls an OpenAI-compatible `/chat/completions` endpoint. Providers are managed dynamically in Redis through the UI/API; environment variables provide a fallback provider when none is configured.

The model is required to return JSON with this operational schema:

```json
{
  "analysis": {
    "severity": "Critical | High | Medium | Low | Info",
    "category": "Auth | Backup | Database | Network | System | Service | Storage | Hardware | DNS | Virtualization | Security | Phishing | Other",
    "status": "FIRING | RESOLVED | INFO",
    "action": "NEW | UPDATE | RESOLVE",
    "target_incident_id": "incident UUID or empty",
    "confidence": 0.95,
    "system_name": "monitoring or source system",
    "source_host": "originating host or address",
    "target_resource": "specific affected component",
    "main_message": "one-sentence diagnosis",
    "details": ["technical fact 1", "technical fact 2"],
    "recommended_actions": ["specific remediation step"],
    "emoji": "🔴"
  }
}
```

Only the first 4,000 characters of the alert body are sent for analysis. Provider timeout is configurable and defaults to 120 seconds. If AI analysis fails, AlertFlow can still dispatch a raw fallback notification; an AI outage does not have to become an alert-loss event.

### 3. Deduplication and incident correlation

AlertFlow uses two layers of noise reduction:

1. **Exact deduplication** hashes sender, normalized subject, and the first 200 body characters. Identical alerts are dropped inside a rolling 30-minute window.
2. **Incident correlation** loads up to 10 textually relevant open incidents from the sender domain and passes that context to the model. The model classifies the incoming event as `NEW`, `UPDATE`, or `RESOLVE` and points to a matching incident when applicable.

The internal incident transition is:

```text
NEW alert ───────────────► OPEN incident
                              │
related UPDATE ───────────────┤ increment occurrence count
                              │ edit existing notification
                              │
matching RESOLVE ─────────────┴► CLOSED incident
                                  edit existing notification
```

Open incident state and outbound message IDs are stored in Redis for seven days. This allows AlertFlow to update Telegram and Matrix messages when an incident repeats, is acknowledged, or resolves.

### 4. Routing engine

Routing rules are enabled/disabled records evaluated by ascending numeric priority. A rule can match either the SMTP sender (`from`) or any envelope recipient (`to`) using case-insensitive glob patterns:

```text
alert@monitoring.local
*@database.example
security-*@example.com
```

Each rule can define:

- legacy Telegram/Matrix destinations;
- one or more dynamic notification-channel IDs;
- per-channel chat, thread, room, receptor, or URL overrides;
- a preferred AI provider;
- a severity matrix that replaces the normal targets for selected severity levels.

The `/api/routing-rules/test-match` and `/api/test-email/preview` endpoints let engineers validate rule behavior before sending production traffic.

### 5. Notification channels

| Channel | Current behavior |
| --- | --- |
| Telegram | Send and edit messages, chat/topic targeting, optional proxy endpoint. |
| Matrix | Send and edit room events through a configured homeserver and access token. |
| Generic webhook | POST a structured payload to a configured URL. |
| Kavenegar SMS | Send a compact notification to the configured receptor and sender. |

Channel credentials and destinations are stored in Redis and managed through authenticated API/UI operations. Routing rules reference channel IDs, making channels reusable across multiple routes.

### 6. Delivery reliability

Failed outbound delivery is scheduled in a Redis sorted set. AlertFlow retries the already formatted message without rerunning AI analysis:

| Attempt | Delay |
| --- | ---: |
| 1 | 30 seconds |
| 2 | 5 minutes |
| 3 | 30 minutes |
| 4 | 2 hours |

After the fourth failed retry, the item moves to `alert_dead_letter_queue`. Operators can inspect retry/DLQ contents, flush the DLQ, or requeue individual entries through the API and dashboard.

### 7. Operations and observability

- Processor heartbeat every 5 seconds with a 15-second Redis TTL.
- Queue depth, retry depth, DLQ depth, processed/error/muted counters.
- Structured application logs stored in a capped Redis stream.
- Relay logs containing destination and delivery status.
- Live dashboard updates over authenticated Server-Sent Events.
- Analytics for open, duplicate, acknowledged, resolved, and sender-level activity.
- Configurable alert retention from 1 to 365 days; default is 14 days.
- Scheduled daily summaries with configurable Telegram bot, chat, thread, time, and timezone.

## System architecture

```text
┌──────────────────────── Alert producers ────────────────────────┐
│ Zabbix · Grafana · backup tools · cron jobs · custom services  │
└───────────────┬──────────────────────────────┬──────────────────┘
                │ SMTP                        │ HTTP + token
                ▼                             ▼
       ┌─────────────────┐          ┌────────────────────┐
       │ SMTP Ingestor   │          │ FastAPI Webhook    │
       │ envelope parser │          │ validation/limits  │
       └────────┬────────┘          └─────────┬──────────┘
                └──────────────┬──────────────┘
                               ▼
                    ┌─────────────────────┐
                    │ Redis 7            │
                    │ queue + state + AOF │
                    └───────┬─────────────┘
                            ▼
              ┌──────────────────────────────┐
              │ Alert Processor              │
              │ mute → dedup → route → AI   │
              │ → correlate → format → send │
              └───────┬───────────┬──────────┘
                      │           │
       ┌──────────────┘           └───────────────┐
       ▼                                          ▼
 Telegram · Matrix · Webhook · SMS       Retry queue → DLQ

                    ┌─────────────────────┐
                    │ FastAPI REST + SSE  │
                    └──────────┬──────────┘
                               ▼
                    ┌─────────────────────┐
                    │ Next.js dashboard   │
                    │ English / Persian   │
                    └─────────────────────┘
```

### Service map

| Component | Technology | Responsibility |
| --- | --- | --- |
| `smtp-ingestor` | Python, aiosmtpd | SMTP authentication, MIME extraction, queue producer. |
| `alert-processor` | Python, Redis, requests | Filtering, deduplication, routing, AI analysis, incident state, dispatch, retry, summaries. |
| `api-server` | FastAPI, Pydantic, JWT | Control-plane API, webhook intake, health, analytics, authentication, SSE. |
| `web-ui` | Next.js 14, React 18, next-intl, SWR | Bilingual operations and administration interface. |
| `redis` | Redis 7 with AOF | Queue, configuration, credentials, alert/incident state, metrics, logs, retry and DLQ. |

## Quick start

### Prerequisites

- Docker Engine and Docker Compose
- An OpenAI-compatible inference endpoint; a local Ollama deployment is supported
- Linux capability to bind port 25, or a reverse proxy/NAT rule mapping another port to SMTP
- At least one outbound channel if external notifications are required

### 1. Configure

```bash
git clone https://github.com/ChosoMeister/alertflow.git
cd alertflow
cp .env.example .env
```

Replace all example secrets before starting:

```env
REDIS_PASSWORD=generate-a-long-random-password
JWT_SECRET=generate-an-independent-random-secret
WEBHOOK_AUTH_TOKEN=generate-an-independent-webhook-token

OLLAMA_BASE_URL=http://host.docker.internal:11434/v1/chat/completions
OLLAMA_MODEL=your-model-name

CORS_ORIGINS=http://localhost:3000
NEXT_PUBLIC_API_URL=http://localhost:8000
```

Generate suitable values with `openssl rand -hex 32`. `NEXT_PUBLIC_API_URL` is embedded at web-image build time; rebuild `web-ui` after changing it.

SMTP authentication is disabled when `SMTP_USERNAME` and `SMTP_PASSWORD` are empty. Enable authentication before exposing the listener outside a trusted network.

### 2. Run

```bash
docker compose up -d --build
docker compose ps
```

| Endpoint | Default URL |
| --- | --- |
| Dashboard | [http://localhost:3000](http://localhost:3000) |
| OpenAPI / Swagger | [http://localhost:8000/docs](http://localhost:8000/docs) |
| API health | [http://localhost:8000/api/health](http://localhost:8000/api/health) |

The bootstrap accounts are `admin/admin` and `operator/operator`. They exist to make local evaluation possible. Change both passwords immediately before exposing the service.

### 3. Configure the control plane

From the dashboard:

1. Add and test an AI provider.
2. Add one or more notification channels.
3. Create routing rules and verify them with the preview tool.
4. Configure mute lists, retention, and summary delivery.
5. Send a test alert and inspect its processing trace.

### 4. Submit an HTTP alert

```bash
export WEBHOOK_AUTH_TOKEN='the-token-from-your-env-file'

curl -X POST http://localhost:8000/api/webhook/grafana \
  -H 'Content-Type: application/json' \
  -H "X-Webhook-Token: ${WEBHOOK_AUTH_TOKEN}" \
  -d '{
    "title": "PostgreSQL replication lag",
    "status": "firing",
    "host": "db-replica-02",
    "lag_seconds": 182,
    "description": "Replication lag exceeded the 120 second threshold"
  }'
```

To resolve the matching incident, send a related payload with `"status": "resolved"`. The webhook adapter prefixes the generated subject with `[RESOLVED]`, and the correlation stage attempts to match it with an open incident.

## API surface

All control-plane endpoints except login, health as implemented, and the token-protected ingest path use JWT authentication.

| Area | Base path | Purpose |
| --- | --- | --- |
| Alerts | `/api/alerts` | Search, count, inspect, change status, rerun AI, resend, force summary. |
| Routing | `/api/routing-rules` | CRUD and rule-match testing. |
| Channels | `/api/notification-channels` | Channel CRUD and connectivity tests. |
| Providers | `/api/ai-providers` | AI provider CRUD and health tests. |
| Integrations | `/api/integrations` | Legacy defaults, Telegram/Matrix tests, sender/domain mutes. |
| Operations | `/api/health`, `/api/status`, `/api/metrics` | Service state and processing metrics. |
| Queues | `/api/queue/*` | Retry and DLQ inspection/requeue operations. |
| Analytics | `/api/analytics` | Status, severity, sender, and resolution aggregates. |
| Events | `/api/sse/dashboard` | Authenticated real-time dashboard stream. |
| Ingest | `/api/webhook/{source_name}` | Token-authenticated JSON/plain-text alert intake. |
| Settings | `/api/settings` | Accounts, passwords, retention, and daily-summary settings. |

Use the generated OpenAPI document at `/docs` as the authoritative request/response reference.

## Security model

- JWT access tokens use configurable HS256 secrets and expiry.
- Passwords are stored with bcrypt; legacy SHA-256 hashes are upgraded after successful authentication.
- Administrative mutations use role checks; read and operational access require a valid user token.
- Redis requires a password and is bound to `127.0.0.1` on the host by the default Compose file.
- The inbound webhook has an independent shared secret and 512 KB body limit.
- CORS origins are configurable and should be explicit in production.
- SMTP authentication and STARTTLS are configurable but TLS certificate provisioning and reverse-proxy TLS termination remain deployment responsibilities.

For production, terminate HTTPS at Nginx, Traefik, Caddy, or another reverse proxy; restrict ports 25, 3000, 6379, and 8000 with host/network policy; rotate all bootstrap credentials; and treat the Redis volume as sensitive because it contains configuration and integration secrets.

## Data and operational characteristics

AlertFlow intentionally uses Redis as both its messaging layer and operational datastore. This keeps the deployment small and fast, but it also defines the current scaling and durability profile:

- Redis AOF is enabled in the supplied Compose configuration.
- Alert and relay-log cleanup runs hourly using the configured retention window.
- Incident correlation state expires after seven days.
- The processor currently consumes `alert_queue` as a single logical worker pipeline.
- The default Redis memory cap is 512 MB with `allkeys-lru` eviction.
- There is no external relational database or object store in the current architecture.

For high-volume or regulated environments, evaluate Redis persistence, backup, replication/Sentinel, secret management, network isolation, and retention requirements before production rollout.

## Development and validation

### Web UI

```bash
cd web-ui
npm ci
npm run dev
```

Production build and Playwright tests:

```bash
npm run build
npm run test:e2e
```

### Python services

Each Python service has an independent requirements file and Dockerfile. A lightweight syntax check for the complete backend is:

```bash
python3 -m compileall -q services
```

Validate the deployment configuration without starting containers:

```bash
docker compose --env-file .env.example config --quiet
```

## Current scope and limitations

- The supplied deployment is a single-host Docker Compose topology, not a Kubernetes or HA distribution.
- Redis is the primary operational datastore; multi-node persistence and failover are not configured automatically.
- AI correlation quality depends on the selected model and the clarity of incoming alerts.
- Exact deduplication is intentionally time-windowed and signature-based, not a general semantic deduplicator.
- The UI can test Telegram, Matrix, and webhook channels; the SMS channel test endpoint is currently informational.
- Secrets are stored in Redis rather than an external secrets manager.
- SMTP STARTTLS configuration is available, but certificate lifecycle automation is outside the project.

These boundaries are documented so teams can evaluate AlertFlow accurately rather than treating a compact self-hosted platform as a fully managed enterprise service.

---

# معرفی AlertFlow

### پلتفرم تحلیل، همبستگی و مسیریابی هشدار برای تیم‌های زیرساخت، SRE، NOC و عملیات

AlertFlow یک لایه پردازش هوشمند بین ابزارهای مانیتورینگ و تیم پاسخ‌گو است. سامانه هشدارها را از طریق SMTP یا webhook امن دریافت می‌کند، آن‌ها را در Redis صف‌بندی می‌کند، با یک مدل سازگار با OpenAI تحلیل ساختاریافته انجام می‌دهد، رخدادهای مرتبط را به یک incident واحد متصل می‌کند و خروجی را به Telegram، Matrix، webhook یا پیامک Kavenegar می‌فرستد.

مسئله‌ای که AlertFlow حل می‌کند صرفاً «ارسال پیام» نیست. در یک محیط واقعی، چند ابزار مختلف ممکن است برای یک اختلال ده‌ها پیام تکراری، ناقص یا بدون context تولید کنند. AlertFlow تلاش می‌کند این جریان خام را به یک رکورد عملیاتی تبدیل کند که مهندس بتواند در چند ثانیه بفهمد چه چیزی خراب شده، شدت آن چقدر است، کدام resource درگیر است، آیا رخداد جدید است یا ادامه یک incident قبلی، و قدم فنی بعدی چیست.

> AlertFlow جایگزین Zabbix، Prometheus، Grafana یا سامانه ITSM نیست؛ لایه intelligence، correlation و delivery بین alert producer و تیم پاسخ‌گو است.

## ارزش فنی برای تیم مصرف‌کننده

- **کاهش alert fatigue:** هشدارهای کاملاً یکسان پیش از مصرف منابع AI حذف می‌شوند و هشدارهای مرتبط در سطح incident با هم ادغام می‌شوند.
- **حفظ چرخه عمر رخداد:** پیام‌های `UPDATE` و `RESOLVE` می‌توانند همان اعلان قبلی در Telegram یا Matrix را ویرایش کنند؛ بنابراین timeline رخداد بین چند پیام پراکنده نمی‌شود.
- **خروجی قابل استفاده برای عملیات:** قرارداد prompt مدل را مجبور می‌کند severity، category، source host، target resource، علت کوتاه، facts فنی و remediation مشخص برگرداند.
- **مسیریابی قابل کنترل:** ruleها بر اساس فرستنده یا گیرنده، اولویت، glob pattern، provider هوش مصنوعی و severity قابل تنظیم هستند.
- **تحمل خطای ارسال:** شکست کانال خروجی وارد retry queue می‌شود و پس از چند تلاش ناموفق به DLQ می‌رود؛ پیام بدون trace حذف نمی‌شود.
- **کنترل محل داده:** کل stack قابل self-host است و می‌توان inference را نیز روی Ollama یا endpoint داخلی سازگار با OpenAI اجرا کرد.
- **control plane یکپارچه:** داشبورد فارسی/انگلیسی مدیریت alert، analytics، queue، log، provider، channel، routing و تنظیمات امنیتی را در اختیار تیم قرار می‌دهد.

## جریان پردازش هشدار

```text
SMTP / Webhook
      │
      ▼
Normalize + Validate
      │
      ▼
Redis alert_queue
      │
      ▼
Mute check
      │
      ▼
Exact deduplication (rolling 30 min)
      │
      ▼
Routing rule selection
      │
      ▼
AI analysis + open-incident context
      │
      ▼
NEW / UPDATE / RESOLVE decision
      │
      ▼
Format + Dispatch
      │
      ├──────── success ───────► alert/incident state + metrics
      │
      └──────── failure ───────► retry queue ───────► DLQ
```

### مرحله ۱: دریافت و normalize

سرویس `smtp-ingestor` با استفاده از `aiosmtpd` envelope و محتوای MIME ایمیل را دریافت می‌کند و فیلدهای sender، recipient، subject، text و HTML را به `alert_queue` می‌فرستد.

برای سیستم‌هایی که webhook دارند، endpoint زیر در دسترس است:

```text
POST /api/webhook/{source_name}
X-Webhook-Token: <shared-secret>
```

این endpoint ورودی JSON یا plain text را می‌پذیرد، body بزرگ‌تر از ۵۱۲ کیلوبایت را رد می‌کند و payload را به همان فرمت داخلی SMTP تبدیل می‌کند. به این ترتیب ادامه pipeline برای هر دو منبع یکسان است.

### مرحله ۲: حذف نویز و انتخاب route

قبل از فراخوانی مدل، mute list فرستنده/دامنه بررسی می‌شود. سپس یک signature از sender، subject نرمال‌شده و ۲۰۰ کاراکتر اول body ساخته می‌شود. duplicate دقیق در یک پنجره rolling سی‌دقیقه‌ای drop می‌شود.

ruleهای routing با priority صعودی بررسی می‌شوند؛ عدد کمتر اولویت بالاتری دارد. هر rule می‌تواند روی `from` یا هر یک از recipientهای `to` و با glob patternهای case-insensitive اعمال شود:

```text
alert@monitoring.local
*@database.example
security-*@example.com
```

خروجی rule علاوه بر مقصد می‌تواند provider مدل، channelهای پویا، override هر channel و severity matrix را تعیین کند. بنابراین برای مثال هشدار `Critical` می‌تواند مستقل از route عادی به مسیر escalation ارسال شود.

### مرحله ۳: تحلیل AI و correlation

AlertFlow حداکثر ۱۰ incident باز و مرتبط از domain فرستنده را بر اساس شباهت واژگان subject، body و target resource انتخاب می‌کند و به context مدل اضافه می‌کند. مدل باید یکی از actionهای زیر را برگرداند:

- `NEW`: رخداد جدید است و یک incident با UUID مستقل ساخته می‌شود.
- `UPDATE`: رخداد به incident باز موجود مربوط است؛ occurrence افزایش می‌یابد و اعلان موجود ویرایش می‌شود.
- `RESOLVE`: پیام recovery به incident باز مربوط است؛ incident بسته و اعلان قبلی با وضعیت resolved به‌روزرسانی می‌شود.

اگر مدل `UPDATE` یا `RESOLVE` بدهد ولی target معتبر وجود نداشته باشد، processor برای جلوگیری از اتصال اشتباه آن را به رخداد جدید تبدیل می‌کند یا در حالت resolve نامعتبر نادیده می‌گیرد.

state مربوط به correlation و message ID کانال‌ها با TTL هفت‌روزه در Redis نگه‌داری می‌شود. این message IDها امکان edit کردن اعلان‌های Telegram و Matrix را فراهم می‌کنند.

### مرحله ۴: ارسال و retry

AlertFlow در وضعیت فعلی از این channelها پشتیبانی می‌کند:

| کانال | قابلیت اجرایی |
| --- | --- |
| Telegram | ارسال و edit پیام، chat ID، topic/thread و proxy اختیاری |
| Matrix | ارسال و edit event در room با homeserver و access token |
| Webhook خروجی | ارسال POST به URL و headerهای تعریف‌شده |
| Kavenegar SMS | ارسال پیام به receptor با API key و sender |

در صورت شکست dispatch، متن format‌شده بدون اجرای مجدد AI طبق برنامه زیر retry می‌شود:

| تلاش | فاصله |
| --- | ---: |
| اول | ۳۰ ثانیه |
| دوم | ۵ دقیقه |
| سوم | ۳۰ دقیقه |
| چهارم | ۲ ساعت |

پس از شکست تلاش چهارم، payload به `alert_dead_letter_queue` منتقل می‌شود. محتویات retry queue و DLQ از API و UI قابل مشاهده است و اپراتور می‌تواند یک آیتم را requeue یا DLQ را پاک کند.

## اجزای معماری

| جزء | فناوری | مسئولیت |
| --- | --- | --- |
| `smtp-ingestor` | Python 3.11، aiosmtpd | دریافت SMTP، parse محتوا و تولید پیام صف |
| `alert-processor` | Python، Redis، requests | mute، dedup، routing، AI، correlation، dispatch، retry و summary |
| `api-server` | FastAPI، Pydantic، JWT | API مدیریتی، webhook ورودی، health، analytics و SSE |
| `web-ui` | Next.js 14، React 18، next-intl، SWR | داشبورد عملیاتی و مدیریتی فارسی/انگلیسی |
| `redis` | Redis 7 + AOF | صف، state، config، credential کانال‌ها، metric، log، retry و DLQ |

این معماری عمداً کوچک و قابل استقرار روی یک host طراحی شده است. Redis هم message broker و هم operational datastore است؛ بنابراین راه‌اندازی ساده می‌ماند، اما durability و scale نیز مستقیماً به طراحی Redis وابسته است.

## قابلیت‌های داشبورد و API

- مشاهده، جست‌وجو و فیلتر alertها بر اساس status و مشخصات رخداد
- مشاهده جزئیات تحلیل AI، incident key، duplicate و action history
- تغییر وضعیت به acknowledged/resolved و ثبت کاربر و زمان اقدام
- rerun تحلیل AI و resend دستی alert
- مدیریت AI providerهای متعدد و تست اتصال آن‌ها
- مدیریت channelها و تست Telegram، Matrix و webhook
- تعریف rule، preview و test-match قبل از ورود ترافیک واقعی
- مشاهده health سرویس‌ها، queue depth، retry، DLQ، metric و log
- داشبورد analytics بر اساس status، severity، sender و resolution
- به‌روزرسانی بلادرنگ داشبورد با SSE احرازشده
- تنظیم retention بین ۱ تا ۳۶۵ روز؛ مقدار پیش‌فرض ۱۴ روز
- تولید summary روزانه یا اجرای دستی آن از پنل

## امنیت و کنترل دسترسی

- احراز هویت control plane با JWT و secret قابل تنظیم
- hash رمز عبور با bcrypt و migration خودکار hashهای قدیمی SHA-256 پس از login موفق
- roleهای `admin` و `operator` و محدود کردن عملیات مدیریتی به admin
- رمز مستقل Redis و bind شدن port آن به `127.0.0.1` در Compose پیش‌فرض
- token مستقل برای webhook ورودی
- محدودیت اندازه payload ورودی webhook
- CORS قابل تنظیم برای deployment واقعی
- SMTP authentication و STARTTLS قابل تنظیم

اکانت‌های bootstrap برای ارزیابی محلی `admin/admin` و `operator/operator` هستند. پیش از دسترسی شبکه‌ای باید هر دو تغییر کنند.

Redis حاوی credential کانال‌ها و providerها است؛ volume آن داده حساس محسوب می‌شود و باید در backup، دسترسی host و secret rotation این موضوع در نظر گرفته شود.

## نصب و راه‌اندازی

### پیش‌نیازها

- Docker Engine و Docker Compose
- endpoint سازگار با OpenAI؛ Ollama محلی نیز قابل استفاده است
- امکان bind یا port-forward برای SMTP در صورت استفاده از ورودی ایمیل
- دست‌کم یک channel خروجی برای دریافت اعلان بیرون از داشبورد

```bash
git clone https://github.com/ChosoMeister/alertflow.git
cd alertflow
cp .env.example .env
```

حداقل متغیرهای زیر را با مقادیر واقعی جایگزین کنید:

```env
REDIS_PASSWORD=generate-a-long-random-password
JWT_SECRET=generate-an-independent-random-secret
WEBHOOK_AUTH_TOKEN=generate-an-independent-webhook-token

OLLAMA_BASE_URL=http://host.docker.internal:11434/v1/chat/completions
OLLAMA_MODEL=your-model-name

CORS_ORIGINS=http://localhost:3000
NEXT_PUBLIC_API_URL=http://localhost:8000
```

برای secret می‌توان از `openssl rand -hex 32` استفاده کرد. مقدار `NEXT_PUBLIC_API_URL` هنگام build شدن image رابط کاربری embed می‌شود؛ بعد از تغییر آن باید `web-ui` مجدداً build شود.

اگر `SMTP_USERNAME` و `SMTP_PASSWORD` خالی باشند، authentication سرویس SMTP غیرفعال است. listener بدون authentication نباید روی شبکه عمومی در دسترس قرار گیرد.

سپس stack را اجرا کنید:

```bash
docker compose up -d --build
docker compose ps
```

| سرویس | آدرس پیش‌فرض |
| --- | --- |
| داشبورد | [http://localhost:3000](http://localhost:3000) |
| Swagger / OpenAPI | [http://localhost:8000/docs](http://localhost:8000/docs) |
| Health API | [http://localhost:8000/api/health](http://localhost:8000/api/health) |

ترتیب پیشنهادی تنظیمات پس از اولین login:

1. تغییر رمز اکانت‌های bootstrap
2. اضافه و تست کردن AI provider
3. اضافه کردن channelهای اعلان
4. تعریف ruleهای routing و تست با preview
5. تنظیم mute list، retention و daily summary
6. ارسال test alert و بررسی trace، log و destination

## نمونه webhook

```bash
export WEBHOOK_AUTH_TOKEN='the-token-from-your-env-file'

curl -X POST http://localhost:8000/api/webhook/grafana \
  -H 'Content-Type: application/json' \
  -H "X-Webhook-Token: ${WEBHOOK_AUTH_TOKEN}" \
  -d '{
    "title": "PostgreSQL replication lag",
    "status": "firing",
    "host": "db-replica-02",
    "lag_seconds": 182,
    "description": "Replication lag exceeded the 120 second threshold"
  }'
```

برای اعلام recovery، payload مرتبط را با `"status": "resolved"` ارسال کنید. adapter ورودی subject را با `[RESOLVED]` علامت‌گذاری می‌کند و مرحله correlation تلاش می‌کند incident باز متناظر را پیدا کند.

## ملاحظات استقرار Production

- برای API و UI از reverse proxy دارای TLS مانند Nginx، Traefik یا Caddy استفاده کنید.
- portهای 25، 3000، 6379 و 8000 را با firewall و network policy محدود کنید.
- `CORS_ORIGINS` را به originهای واقعی محدود کنید و از `*` استفاده نکنید.
- secretهای Redis، JWT، webhook، provider و channel را مستقل و دوره‌ای rotate کنید.
- برای Redis، persistence، backup، replica/failover و ظرفیت حافظه را بر اساس حجم alert ارزیابی کنید.
- retention داده، محتوای prompt ارسالی به مدل و محل inference را با الزامات امنیتی سازمان تطبیق دهید.
- health، retry depth و DLQ را با monitoring خارجی پایش کنید؛ خود سامانه نباید تنها ناظر سلامت خودش باشد.

## ویژگی‌های عملیاتی و محدودیت‌های فعلی

- deployment آماده پروژه single-host و مبتنی بر Docker Compose است؛ Kubernetes یا HA به‌صورت آماده ارائه نشده است.
- Redis تنها datastore عملیاتی است و relational database یا object storage وجود ندارد.
- AOF در Compose فعال است، سقف حافظه پیش‌فرض ۵۱۲ مگابایت و policy برابر `allkeys-lru` است.
- پاک‌سازی alert و relay log هر ساعت و بر اساس retention تنظیم‌شده انجام می‌شود.
- processor در معماری فعلی یک pipeline منطقی مصرف‌کننده `alert_queue` است.
- کیفیت semantic correlation به مدل انتخابی و کیفیت alert ورودی وابسته است.
- تست SMS در UI/API فعلاً informational است، هرچند dispatch Kavenegar در processor پیاده‌سازی شده است.
- secretها در Redis نگه‌داری می‌شوند و integration آماده با Vault یا secrets manager خارجی وجود ندارد.
- provisioning و rotation گواهی TLS بر عهده لایه deployment است.

بیان این محدودیت‌ها بخشی از معرفی فنی محصول است: تیم مصرف‌کننده باید بتواند پیش از PoC یا rollout، مرز مسئولیت AlertFlow و الزامات زیرساختی خود را دقیق ارزیابی کند.

## توسعه و تست

رابط کاربری:

```bash
cd web-ui
npm ci
npm run dev
npm run build
npm run test:e2e
```

بررسی syntax سرویس‌های Python و اعتبار Compose:

```bash
python3 -m compileall -q services
docker compose --env-file .env.example config --quiet
```

تست‌های E2E موجود با Playwright مسیرهای login، navigation و i18n را پوشش می‌دهند. برای تغییرات pipeline پردازش، اضافه کردن تست‌های واحد و integration متناسب با سناریوی production توصیه می‌شود.

## مشارکت

Issue و Pull Request پذیرفته می‌شود. برای تغییرات معماری—به‌خصوص datastore، correlation، authentication یا semantics مربوط به delivery—بهتر است ابتدا مسئله و trade-offهای پیشنهادی در یک Issue ثبت شود.
