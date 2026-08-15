from datetime import datetime
from typing import Optional, List, Literal
from pydantic import BaseModel, Field


class RoutingRuleCreate(BaseModel):
    """Schema for creating/updating a routing rule."""
    name: str = Field(..., min_length=1, max_length=100)
    enabled: bool = True
    priority: int = Field(default=0, ge=0, le=1000)
    match_field: Literal["from", "to"] = "from"
    email_pattern: str = Field(..., min_length=1)  # Glob pattern: *@domain.tld, prefix-*@corp.com
    notes: str = ""
    ai_provider_id: Optional[str] = None  # If None, use default provider
    alert_destination_ids: List[str] = Field(default_factory=list)
    resolved_destination_ids: List[str] = Field(default_factory=list)
    severity_destination_ids: dict[str, List[str]] = Field(default_factory=dict)
    resolution_mode: Literal["legacy", "copy", "move"] = "legacy"


class ResolutionProfileCreate(BaseModel):
    """Reusable resolved-incident destination profile."""
    name: str = Field(..., min_length=1, max_length=100)
    enabled: bool = True
    notification_channel_ids: List[str] = Field(default_factory=list)
    channel_overrides: dict = Field(default_factory=dict)
    notes: str = ""


class RoutingRule(RoutingRuleCreate):
    """Full routing rule with ID and timestamps."""
    id: str
    created_at: str
    updated_at: str


class RoutingTestRequest(BaseModel):
    """Request for testing which rule matches an email."""
    email_address: str
    match_field: Literal["from", "to"] = "from"


class RoutingTestResponse(BaseModel):
    """Response for routing test."""
    matched: bool
    rule_id: Optional[str] = None
    rule_name: Optional[str] = None
    telegram_chat_id: str = ""
    telegram_thread_id: str = "0"
    matrix_room_id: str = ""
    channels: str = ""


class TestEmailRequest(BaseModel):
    """Request for sending a test email."""
    from_email: str = Field(..., min_length=1)
    to_email: str = Field(default="test@localhost")
    subject: str = Field(default="Test Alert")
    body: str = Field(default="This is a test alert from AlertFlow.")


class TestEmailResponse(BaseModel):
    """Response for test email with routing preview."""
    queued: bool
    trace_id: str
    routing_preview: RoutingTestResponse


class AlertCreate(BaseModel):
    """Schema for creating an alert from SMTP."""
    from_email: str
    to_email: str
    subject: str
    body: str
    html: str = ""
    rcpt_tos: List[str] = []


class Alert(BaseModel):
    """Full alert with analysis."""
    id: str
    from_email: str
    to_email: str
    subject: str
    body: str
    html: str = ""
    channel: str = "both"
    status: str = "new"  # new, acknowledged, resolved
    severity: str = ""
    category: str = ""
    confidence: str = ""
    system_name: str = ""
    main_message: str = ""
    details: str = ""
    ai_raw: str = ""
    incident_key: str = ""
    duplicate_of: str = ""
    telegram_message_id: str = ""
    created_at: str
    updated_at: str


class IntegrationSettings(BaseModel):
    """Telegram and Matrix integration settings."""
    telegram_enabled: bool = True
    telegram_default_chat_id: str = ""
    telegram_default_thread_id: str = "0"
    matrix_enabled: bool = False
    matrix_default_room_id: str = ""
    default_channel: str = "both"
    failover_enabled: bool = True
    message_verbosity: Literal["summary", "standard", "debug"] = "standard"


class SystemStatus(BaseModel):
    """System health status."""
    smtp_ingestor: str = "unknown"
    redis: str = "unknown"
    alert_processor: str = "unknown"
    ollama: str = "unknown"


class QueueMetrics(BaseModel):
    """Queue depth and processing metrics."""
    queue_depth: int = 0
    dlq_depth: int = 0
    processed_count: int = 0
    error_count: int = 0
    muted_count: int = 0


class GeneralSettings(BaseModel):
    """System-wide general configuration."""
    alert_retention_days: int = Field(default=14, ge=1, le=365)
    summary_telegram_chat_id: str = ""
    summary_telegram_thread_id: str = "0"
    summary_telegram_bot_token: str = ""
    summary_telegram_bot_token_configured: bool = False
    global_storm_max_notifications: int = Field(default=20, ge=5, le=500)
    global_storm_window_seconds: int = Field(default=300, ge=60, le=3600)
    storm_summary_interval_seconds: int = Field(default=300, ge=30, le=3600)
    incident_sla_minutes: int = Field(default=60, ge=5, le=10080)
