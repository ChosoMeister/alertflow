# 🛡️ AlertFlow

[Persian Documentation / مستندات فارسی](#-مستندات-فارسی)

> An intelligent, AI-powered email alert processor, analyzer, and multi-channel notification dispatcher.

AlertFlow acts as a smart middleware between your infrastructure monitoring tools (e.g., Zabbix, Prometheus, Grafana, Backup tools, Cronjobs) and your team's communication channels (Telegram, Matrix, Webhooks, SMS). 

Instead of overwhelming your team with raw, noisy, and unstructured emails, Sentinel ingests email alerts via its built-in SMTP server, processes them using Large Language Models (LLMs) to extract structured insights (Severity, Category, System Name, Actionable Summary), and dynamically routes them to the correct channels based on customizable rules.

---

## ✨ Core Features

- 📧 **Built-in SMTP Ingestor:** A lightweight, asynchronous Python SMTP server that acts as a drop-in replacement for traditional mail transfer agents (like Postfix). It actively listens on port 25, parses incoming emails, and queues them in Redis.
- 🧠 **AI-Powered Log/Alert Analysis:** Connects to any OpenAI-compatible API or local LLM instances (like **Ollama**) to read messy logs/emails and extract structured JSON data, highlighting the core issue, severity, and context.
- 🔀 **Advanced Intelligent Routing:** Create dynamic rules based on Glob patterns (e.g., `*@db-servers.local` or `security-*@domain.com`). Map specific email addresses to specific channels (e.g., DB alerts to Telegram Thread A, Security to Matrix Room B).
- 🚨 **Severity-Based Overrides:** If the AI determines an alert is `CRITICAL`, Sentinel can override the standard routing rule and broadcast the alert to high-priority channels (like SMS) automatically.
- 📢 **Multi-Channel Dispatching:** Built-in seamless support for sending styled and formatted messages to **Telegram**, **Matrix**, generic **Webhooks**, and **SMS** providers.
- ♻️ **Enterprise Resiliency:** Built on Redis with advanced queue mechanics. Features an exponential backoff **Retry Queue** for failed dispatches, and a **Dead Letter Queue (DLQ)** for permanently failed messages. No alert is ever lost.
- 🛡️ **Mute & Filtering System:** Ability to mute noisy senders or domains entirely, dropping their alerts before they consume AI resources.
- 💻 **Modern Web Console (Dashboard):** A completely decoupled, beautiful **Next.js & TailwindCSS** UI for monitoring queue depths, viewing AI analysis results, configuring routing rules, and managing AI providers on the fly.

---

## 🏗️ Architecture & Data Flow

AlertFlow uses a heavily decoupled, microservices-oriented architecture orchestrated by Docker Compose:

1. **Generation:** Your infrastructure sends an email alert exactly as it normally would.
2. **Ingestion (`smtp-ingestor`):** Receives the email, strips attachments, extracts Text and HTML bodies, and pushes an `AlertPayload` to the Redis `alert_queue`.
3. **Processing (`alert-processor`):** A daemon continuously polls Redis. Once an alert is fetched:
   - **Mute Check:** Is the sender muted? If yes, discard.
   - **AI Analysis:** Sends the raw email body to the active AI Provider with a strict system prompt to return a structured JSON evaluation.
   - **Rule Evaluation:** Checks Redis for routing rules matching the `From` or `To` address.
   - **Dispatch:** Formats the AI's summary into a beautiful message and makes API calls to Telegram/Matrix/etc.
   - **Error Handling:** If sending fails, it moves the message to a sorted set `retry_queue`. If max retries are exceeded, it goes to `DLQ`.
4. **Management (`api-server` & `web-ui`):** Provides a RESTful API and a visual interface to monitor the system heartbeat, edit rules, and view the raw logs/alerts saved in Redis.

## 🛠️ Technology Stack

- **Backend:** Python 3.11, FastAPI (for API), aiosmtpd (for SMTP)
- **Database / Message Broker:** Redis 7 (Storage, Pub/Sub, Queues, Hashes, Sorted Sets)
- **Frontend / UI:** Next.js 14, React, TailwindCSS, shadcn/ui
- **AI Integration:** Support for Ollama, OpenAI, or any OpenAI-compatible endpoint.
- **Containerization:** Docker & Docker Compose

---

## 🚀 Quick Start Guide

### 1. Prerequisites
- Docker and Docker Compose (v2) installed.
- (Optional but recommended) A running instance of Ollama setup with a model like `llama3` or `gpt-oss`.

### 2. Installation
```bash
git clone https://github.com/ChosoMeister/alertflow.git
cd alertflow

# Copy the environment template
cp .env.example .env
```

### 3. Configuration
Edit the `.env` file to match your environment. Key variables:
- `JWT_SECRET`: Generate a secure random string for dashboard authentication.
- `OLLAMA_BASE_URL`: Pointer to your AI API (e.g., `http://localhost:11434/v1/chat/completions`).
- *(Optional)* Add default bot tokens for Telegram or Matrix if you don't plan to configure them via the UI.

### 4. Deployment
```bash
docker-compose up -d --build
```
This will spin up:
- **Redis:** (Internal)
- **SMTP Ingestor:** `0.0.0.0:25`
- **Alert Processor:** Background worker
- **API Server:** `http://localhost:8000`
- **Web UI:** `http://localhost:3000`

### 5. Accessing the Dashboard
Go to [http://localhost:3000](http://localhost:3000)
- **Default Username:** `admin`
- **Default Password:** `admin` (Change this immediately in settings!)

---

## 📖 System Services Breakdown

### `services/smtp-ingestor/`
Uses `aiosmtpd` to handle SMTP traffic. It acts as an unauthenticated open relay designed specifically to be placed inside a secure internal network (VLAN) where monitoring tools can freely drop emails.

### `services/alert-processor/`
The core engine. Contains logic for:
- `ai_service.py`: Crafting dynamic AI prompts and parsing JSON responses.
- `routing.py`: Matching `fnmatch` glob patterns against email addresses to resolve the correct channel override.
- `utils.py`: Contains API implementations for Webhooks, Matrix (Synapse), Telegram Bot API (with proxy support), and SMS.

### `services/api-server/`
FastAPI backend that interfaces with Redis. Handles JWT authentication, CRUD operations for settings, and provides metric aggregation for the frontend.

### `web-ui/`
Next.js application. Allows admins to visually track the state of the `alert_queue`, see AI breakdowns of recent alerts, and manage routing.

---
---

<div dir="rtl" align="right">

# 🇮🇷 مستندات فارسی (Persian Documentation)

**سنتینل هوش‌مصنوعی (AlertFlow)** یک دستیار هوشمند و پردازشگر هشدار است که هشدارهای سنتی و پیچیده‌ی ایمیلی را دریافت کرده، با استفاده از موتورهای هوش مصنوعی تحلیل می‌کند و در نهایت خروجی ساختاریافته و تمیز را به پیام‌رسان‌های مختلف ارسال می‌کند.

این سیستم اساساً یک لایه میانی (Middleware) بین ابزارهای مانیتورینگ شما (مانند زبیکس، پرومتئوس، بک‌آپ سرورها، و اسکریپت‌های کرون‌جاب) و تیم فنی شما (در تلگرام، ماتریکس یا SMS) است.

### 🎯 هدف پروژه و نحوه عملکرد

در محیط‌های سازمانی بزرگ، ابزارهای مختلف روزانه ده‌ها ایمیل هشدار ارسال می‌کنند که خواندن متن‌های طولانی آن‌ها خسته‌کننده است. عملکرد Sentinel به این شکل است:
1. ایمیل به پورت 25 سرور Sentinel ارسال می‌شود.
2. سرور `smtp-ingestor` ایمیل را دریافت کرده و به یک صف پیام در **Redis** می‌فرستد.
3. سرویس `alert-processor` پیام را برداشته و متن آن را به یک مدل هوش مصنوعی (مانند Ollama یا ChatGPT) پاس می‌دهد.
4. هوش مصنوعی متن باز و نامرتب را می‌خواند و به صورت هوشمند **شدت مشکل (Severity)**، **دسته‌بندی**، **نام سیستم درگیر** و **یک خلاصه‌ی کوتاه برای حل مشکل** را به صورت JSON برمی‌گرداند.
5. سیستم بر اساس یک سری متغیر از پیش تعیین شده (Routing Rules) تصمیم می‌گیرد این خطا به کدام گروه تلگرامی، کدام چت ماتریکس یا کدام شماره پیامک شود.
6. در نهایت پیام به شکلی بسیار خوانا، همراه با ایموجی و اولویت‌بندی شده برای تیم فنی ارسال می‌شود.

### ✨ امکانات و فیچرهای کلیدی

- **دریافت‌کننده اختصاصی SMTP:** نیازی به نصب Postfix یا Exim ندارید. این برنامه خودش مستقیماً نقش یک سرور ایمیل گیرنده را بازی می‌کند.
- **تحلیل با مدل‌های زبانی (LLM):** درک کامل متن خطاهای سیستمی و ترجمه‌ی آن‌ها به زبان ساده یا دیتای ساختاریافته به کمک هوش مصنوعی.
- **مسیریابی هوشمند (Smart Routing):** می‌توانید تعریف کنید که اگر خطایی از `*@db.local` آمد برود به گروه دیتابیس کاران در تلگرام و اگر از `network-*@op.local` آمد برود به چت ادمین‌های شبکه.
- **پشتیبانی از Override بر اساس شدت بحران:** قابلیتی که اگر هوش مصنوعی تشخیص داد پیام حاوی قطعی کامل سیستم (Critical) است، قوانین عادی را بشکند و به جای تلگرام، مستقیم به مدیران پیامک (SMS) بزند.
- **ارسال چند‌کاناله (Multi-Channel):** پشتیبانی نیتیو از Telegram (با قابلیت تنظیم پراکسی برای ایران)، Matrix، Webhook و پنل‌های پیامکی.
- **سیستم Retry و DLQ:** اگر سرور تلگرام قطع باشد، پیام گم نمی‌شود! سیستم با زمان‌بندی مکث صعودی (Exponential Backoff) مجددا تلاش می‌کند و اگر کلاً ناموفق بود، پیام را به صندوق Dead Letter Queue می‌فرستد تا مدیر سرور به صورت دستی رسیدگی کند.
- **داشبورد گرافیکی و مدرن:** پنل مدیریتی ایجاد شده با Next.js برای بررسی وضعیت لحظه‌ای صف‌ها، ویرایش Ruleها، اضافه کردن پرووایدرهای جدید AI و مشاهده لاگ‌ها در محیطی بسیار تمیز.

### 🏛️ اجزای تشکیل دهنده (معماری)
پروژه از میکروسرویس‌های زیر که توسط داکر کامپوز مدیریت می‌شوند تشکیل شده است:
- `redis`: به عنوان قلب تپنده‌ی پروژه، صف پیام‌ها و پایگاه داده سیستم.
- `smtp-ingestor`: با زبان Python و ماژول `aiosmtpd` ساخته شده.
- `alert-processor`: پردازشگر اصلی بک‌گراند با قابلیت پارس کردن لاگ‌ها و ارتباط با AI.
- `api-server`: پیاده‌سازی شده با FastAPI برای سرویس‌دهی API به داشبورد.
- `web-ui`: داشبورد کاربری مدرن با Next.js و TailwindCSS.

### 🚀 راهنمای راه‌اندازی سریع

۱. ابتدا ریپازیتوری را کلون کنید:
```bash
git clone https://github.com/ChosoMeister/alertflow.git
cd alertflow
```

۲. فایل پیکربندی (Environment Variables) را ایجاد و مقادیر دلخواه را وارد کنید:
```bash
cp .env.example .env
```
*(حتماً مقدار `JWT_SECRET` را در فایل تنظیم کنید و در صورت نیاز `OLLAMA_BASE_URL` را روی سرور ای‌آی خود تنظیم نمایید)*

۳. داکر کامپوز را بیلد و ران کنید:
```bash
docker-compose up -d --build
```

۴. دسترسی به سیستم:
- داشبورد پنل مدیریتی روی پورت `3000` بالا می‌آید `http://localhost:3000`.
- نام کاربری و رمز عبور پیش‌فرض: `admin / admin` (از داخل تنظیمات حتماً آن را تغییر دهید).
- دریافت کننده‌ی ایمیل، روی پورت `25` سرور شما منتظر دریافت هشدارهای سیستم‌های مانیتورینگ خواهد بود.

</div>
