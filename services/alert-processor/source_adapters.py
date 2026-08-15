"""Optional source-specific enrichment with a generic fallback for every sender."""
import json
import hashlib
import re
from typing import Any, Dict, List


def _unique(values: List[str]) -> List[str]:
    seen = set()
    result = []
    for value in values:
        clean = str(value).strip().strip("'\"`[]{}")
        clean = re.sub(r"[\\\"',;]+$", "", clean).strip()
        lowered = clean.lower()
        if (
            not clean
            or lowered in {"http://", "https://", "http:", "https:"}
            or lowered in {"resolved", "/resolved", "firing", "/firing", "/s"}
            or lowered in {"/sec", "/slowest", "/datastore:", "/s)"}
            or re.fullmatch(r"/?\d{1,2}/\d{4}", clean)
            or re.fullmatch(r"/?\d{1,2}/\d{1,2}/\d{4}", clean)
            or re.fullmatch(r"/?\d{1,2}/\d{4}\)?", clean)
            or re.fullmatch(r"\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:?\d{2})?", clean)
        ):
            continue
        if clean and clean.lower() not in seen:
            seen.add(clean.lower())
            result.append(clean)
    return result


def normalize_resource_identifiers(values: List[str]) -> List[str]:
    """Remove status/date fragments while preserving exact host, VM, PVC and path names."""
    return _unique(values or [])


def _slug(value: str) -> str:
    value = re.sub(r"\d{1,2}/\d{1,2}/\d{4}(?:\s+\d{1,2}:\d{2}:\d{2}\s*[AP]M)?", " ", value or "", flags=re.I)
    value = re.sub(r"\[(?:FIRING|RESOLVED)(?::\d+)?(?:\s*,\s*(?:FIRING|RESOLVED):\d+)?\]", " ", value, flags=re.I)
    value = re.sub(r"\b(?:firing|resolved|reset|warning|error|critical|high|medium|low)\b", " ", value, flags=re.I)
    value = re.sub(r"\b(?:duration|observed)\s*[:=]?\s*\d{1,3}:\d{2}(?::\d{2})?", " ", value, flags=re.I)
    return re.sub(r"[^a-z0-9._$:/\\-]+", "-", value.lower()).strip("-")


def build_correlation_identity(sender: str, subject: str, body: str, analysis: Dict[str, Any] = None) -> Dict[str, str]:
    """Build a stable source/resource/condition identity; return empty when ambiguous."""
    analysis = analysis or {}
    normalized = normalize_alert(sender, subject, body)
    source_type = normalized.get("source_type", "generic")
    analysis_text = " ".join([
        str(analysis.get("main_message", "")),
        " ".join(str(item) for item in analysis.get("details", []) if item),
    ])
    text = f"{subject}\n{body}\n{analysis_text}"
    identity = ""

    if source_type == "syncovery":
        profile = subject.split(":", 1)[0].strip()
        conditions = []
        if re.search(r"writing problems|disk.{0,12}full|error\s*112|insufficient (?:disk )?space", text, re.I):
            conditions.append("disk-full")
        if re.search(r"\bconflict", text, re.I):
            conditions.append("conflict")
        if re.search(r"inaccessible|access denied|cannot access", text, re.I):
            conditions.append("inaccessible")
        if re.search(r"error\s*29|cannot write to the specified device|writing problems", text, re.I):
            conditions.append("write-failure")
        if re.search(r"\bincomplete\b|\berrors? with\b", text, re.I) and not conditions:
            conditions.append("incomplete")
        if profile and conditions:
            identity = f"syncovery|{_slug(profile)}|{'+'.join(sorted(set(conditions)))}"
    elif source_type == "veeam":
        quoted = re.search(r"(?:Virtual Machine|Datastore|Host|Computer|Infrastructure Tree)\s*[\"']([^\"']+)", subject, re.I)
        metric = re.split(r"\d{1,2}/\d{1,2}/\d{4}", subject, maxsplit=1)[0]
        metric = re.sub(r"\b(?:warning|error|reset/resolved)\b.*$", "", metric, flags=re.I)
        if quoted:
            identity = f"veeam|{_slug(metric)}|{_slug(quoted.group(1))}"
    elif source_type == "grafana":
        base = re.sub(r"^\s*\[[^]]+\]\s*", "", subject).strip()
        paren = re.search(r"\(([^)]+)\)\s*$", base)
        stable_target = ""
        if paren:
            tokens = [token for token in re.split(r"\s+", paren.group(1)) if token]
            stable_target = "-".join(tokens[:4])
            base = base[:paren.start()].strip()
        identity = f"grafana|{_slug(base)}"
        if stable_target:
            identity += f"|{_slug(stable_target)}"
    elif source_type == "uptime-kuma":
        resources = normalized.get("target_resources", [])
        if resources:
            identity = f"uptime-kuma|{_slug(resources[0])}"
    else:
        resources = normalize_resource_identifiers(analysis.get("target_resources", []))
        preferred = next((value for value in resources if re.search(r"(?:_dag|dag_|pipeline|pvc|pod|vm|host|database|nas|storage\s+pool|https?://)", value, re.I)), "")
        if preferred:
            stable_subject = re.sub(r"^[^a-z0-9]+", "", subject, flags=re.I)
            identity = f"generic|{_slug(stable_subject)}|{_slug(preferred)}"

    if not identity:
        return {"correlation_identity": "", "correlation_key": ""}
    return {
        "correlation_identity": identity,
        "correlation_key": hashlib.sha256(identity.encode()).hexdigest()[:32],
    }


def _grafana(sender: str, subject: str, body: str) -> Dict[str, Any]:
    if "grafana" not in sender.lower() and not re.search(r"\[(?:FIRING|RESOLVED):", subject, re.I):
        return {}

    resources = []
    for match in re.finditer(r"\bPVCs?\s*:\s*([^\n\]\}]+)", body, re.I):
        resources.extend(part.strip() for part in match.group(1).split(","))
    for match in re.finditer(
        r"\b(?:pvc|persistentvolumeclaim|volume(?:_name)?)\s*[=:]\s*['\"]?([a-z0-9][a-z0-9._-]+)",
        body,
        re.I,
    ):
        resources.append(match.group(1))

    firing = re.search(r"FIRING:(\d+)", subject, re.I)
    resolved = re.search(r"RESOLVED:(\d+)", subject, re.I)
    alertname = re.search(r"\balertname\s*[=:]?\s*\n?\s*([^\n,]+)", body, re.I)
    return {
        "source_type": "grafana",
        "alert_name": alertname.group(1).strip() if alertname else "",
        "target_resources": _unique(resources),
        "firing_count": int(firing.group(1)) if firing else None,
        "resolved_count": int(resolved.group(1)) if resolved else None,
        "mixed_state": bool(firing and resolved),
    }


def _kuma(sender: str, subject: str, body: str) -> Dict[str, Any]:
    if "kuma" not in sender.lower() and "uptime kuma" not in body.lower():
        return {}
    resources = []
    for pattern in (
        r"(?:monitor|name)\s*[=:]\s*([^\n,]+)",
        r"https?://[^\s<>\]\)]+",
    ):
        resources.extend(re.findall(pattern, body, re.I))
    return {"source_type": "uptime-kuma", "target_resources": _unique(resources)}


def _backup(sender: str, subject: str, body: str) -> Dict[str, Any]:
    text = f"{sender} {subject}"
    if not re.search(r"syncovery|veeam", text, re.I):
        return {}
    resources = []
    for pattern in (
        r"(?:profile|job|computer|vm|object)\s*(?:name)?\s*[=:]\s*([^\n,;]+)",
        r"(?:\\\\|/)[^\s<>]+",
    ):
        resources.extend(re.findall(pattern, body, re.I))
    source_type = "syncovery" if "syncovery" in text.lower() else "veeam"
    return {"source_type": source_type, "target_resources": _unique(resources)}


def normalize_alert(sender: str, subject: str, body: str) -> Dict[str, Any]:
    """Return deterministic facts when available; unknown sources remain supported."""
    normalized: Dict[str, Any] = {
        "source_type": "generic",
        "target_resources": [],
    }
    for adapter in (_grafana, _kuma, _backup):
        facts = adapter(sender, subject, body)
        if facts:
            normalized.update({k: v for k, v in facts.items() if v is not None})
            normalized["target_resources"] = _unique(
                normalized.get("target_resources", []) + facts.get("target_resources", [])
            )
            break
    stable_parts = [normalized.get("source_type", "generic")]
    if normalized.get("alert_name"):
        stable_parts.append(normalized["alert_name"].lower())
    stable_parts.extend(sorted(value.lower() for value in normalized.get("target_resources", [])))
    if len(stable_parts) > 1:
        normalized["source_fingerprint"] = hashlib.sha256("|".join(stable_parts).encode()).hexdigest()[:24]
    return normalized


def prompt_context(normalized: Dict[str, Any]) -> str:
    """Compact, model-readable facts; never replaces the original alert body."""
    useful = {k: v for k, v in normalized.items() if v not in (None, "", [], False)}
    return json.dumps(useful, ensure_ascii=False, separators=(",", ":"))


def preserve_resources(ai_result: Dict[str, Any], normalized: Dict[str, Any]) -> Dict[str, Any]:
    """Ensure deterministic resource identifiers cannot be dropped by the model."""
    if not ai_result or not normalized.get("target_resources"):
        return ai_result
    analysis = ai_result.setdefault("analysis", {})
    if normalized.get("source_fingerprint"):
        analysis["source_fingerprint"] = normalized["source_fingerprint"]
    resources = analysis.get("target_resources", [])
    if not isinstance(resources, list):
        resources = [resources] if resources else []
    analysis["target_resources"] = normalize_resource_identifiers(resources + normalized["target_resources"])
    if not analysis.get("target_resource") and analysis["target_resources"]:
        analysis["target_resource"] = analysis["target_resources"][0]
    return ai_result


def _metric(client, field: str, amount: int = 1) -> None:
    """Best-effort quality telemetry; validation must never block alert handling."""
    if client is None:
        return
    try:
        client.hincrby("metrics:analysis_quality", field, amount)
    except Exception:
        pass


def validate_analysis(ai_result: Dict[str, Any], sender: str, subject: str, body: str,
                      normalized: Dict[str, Any], metrics_client=None) -> Dict[str, Any]:
    """Ground model output in source evidence while keeping unknown senders flexible."""
    if not ai_result or not isinstance(ai_result.get("analysis"), dict):
        return ai_result
    analysis = ai_result["analysis"]
    warnings: List[str] = []
    overrides: List[str] = []
    source_type = normalized.get("source_type", "generic")
    evidence = f"{subject}\n{body}"

    raw_resources = analysis.get("target_resources", [])
    if not isinstance(raw_resources, list):
        raw_resources = [raw_resources] if raw_resources else []
    combined_resources = raw_resources + normalized.get("target_resources", [])
    cleaned = normalize_resource_identifiers(combined_resources)
    if len(cleaned) < len(combined_resources):
        overrides.append("resource_cleanup")
    analysis["target_resources"] = cleaned

    # A Grafana datasource UID is an observation source, never a PVC/volume name.
    datasource_match = re.search(r"DatasourceNoData[^\n]*\(([a-z0-9]+)\s+", subject, re.I)
    explicit_storage = normalized.get("target_resources", [])
    if source_type == "grafana" and datasource_match:
        uid = datasource_match.group(1)
        has_named_storage = any(value.lower() != uid.lower() for value in explicit_storage)
        target = str(analysis.get("target_resource", ""))
        claim_text = " ".join([
            target, str(analysis.get("main_message", "")),
            " ".join(str(item) for item in analysis.get("details", []) if item),
            " ".join(
                str(item.get("text", "") if isinstance(item, dict) else item)
                for item in analysis.get("recommended_actions", [])
            ),
        ])
        false_storage_claim = bool(re.search(rf"\b(?:pvc|volume)\s+{re.escape(uid)}\b", target, re.I))
        unsupported_storage_claim = bool(re.search(
            r"\b(?:pvc|persistentvolumeclaim|volume)\b.{0,80}\b(?:detach|unavailable|full|reattach)",
            claim_text, re.I,
        ))
        if (false_storage_claim or unsupported_storage_claim) and not has_named_storage:
            analysis["target_resource"] = f"Grafana datasource {uid}"
            analysis["target_resources"] = [
                value for value in cleaned
                if not re.fullmatch(rf"(?:PVC|volume)\s+{re.escape(uid)}", value, re.I)
            ]
            if not any(uid.lower() in value.lower() for value in analysis["target_resources"]):
                analysis["target_resources"].insert(0, f"datasource_uid:{uid}")
            rule = re.search(r"\([^)]*\sA\s+([^)]*)\)", subject, re.I)
            rule_name = rule.group(1).strip() if rule and rule.group(1).strip() else "the affected rule"
            state = "returned no data"
            analysis["main_message"] = f"Grafana datasource {uid} {state} for rule {rule_name}; the affected storage resource is not identified in this alert."
            analysis["details"] = [
                f"Datasource UID: {uid}", f"Rule: {rule_name}",
                "Concrete PVC, volume, pod, or node name is absent from the payload",
            ]
            analysis["recommended_actions"] = [{
                "text": f"Inspect datasource {uid} and the Grafana query for rule {rule_name} to identify the concrete affected resource",
                "type": "diagnostic", "requires_approval": False,
            }]
            warnings.append("datasource_uid_misclassified_as_storage_resource")
            overrides.append("grafana_datasource_grounding")

    # Canonical categories for known, unambiguous alert families.
    canonical = None
    lowered = evidence.lower()
    if source_type == "syncovery":
        canonical = "System" if "low available system memory" in lowered else "Backup"
    elif source_type == "veeam":
        if "possible ransomware activity" in lowered:
            canonical = "Security"
        elif "guest disk space" in lowered or "datastore " in lowered:
            canonical = "Storage"
        elif "orphaned vm backup snapshot" in lowered:
            canonical = "Backup"
        else:
            canonical = "Virtualization"
    elif source_type == "grafana":
        if re.search(r"longhorn|pvc|volume|storage", lowered):
            canonical = "Storage"
        elif re.search(r"dag|airflow|service|datasourcenodata", lowered):
            canonical = "Service"
    if canonical and analysis.get("category") != canonical:
        analysis["category"] = canonical
        overrides.append("category")

    # Keep incident impact severity for routing, but expose event state separately.
    status = str(analysis.get("status", "")).upper()
    analysis["event_state"] = "Resolved" if status == "RESOLVED" else "Firing" if status == "FIRING" else "Info"
    analysis["incident_severity"] = analysis.get("severity", "Unknown")

    confidence = float(analysis.get("confidence") or 0)
    evidence_confidence = confidence
    if warnings:
        evidence_confidence = min(evidence_confidence, 0.70)
    elif source_type != "generic" and analysis.get("target_resource"):
        evidence_confidence = min(1.0, confidence)
    analysis["model_confidence"] = confidence
    analysis["evidence_confidence"] = round(evidence_confidence, 2)
    analysis["confidence"] = round(min(confidence, evidence_confidence), 2)
    analysis["evidence_status"] = "inferred" if warnings else "verified"
    analysis["validation_warnings"] = warnings
    analysis["taxonomy_overrides"] = overrides
    _metric(metrics_client, "validated")
    for item in warnings:
        _metric(metrics_client, f"warning:{item}")
    for item in overrides:
        _metric(metrics_client, f"override:{item}")
    return ai_result


def split_grafana_mixed_payload(payload: Dict[str, Any], body: str) -> List[Dict[str, Any]]:
    """Split Grafana grouped FIRING/RESOLVED mail into ordered state events."""
    subject = str(payload.get("subject", ""))
    if payload.get("grafana_split_state"):
        return []
    match = re.search(r"\[FIRING:(\d+)\s*,\s*RESOLVED:(\d+)\]", subject, re.I)
    if not match:
        return []

    firing_marker = re.search(r"🔥\s*\d+\s+firing instances?", body, re.I)
    resolved_marker = re.search(r"✅\s*\d+\s+resolved instances?", body, re.I)
    if not firing_marker or not resolved_marker or resolved_marker.start() <= firing_marker.start():
        return []

    prefix = body[:firing_marker.start()].strip()
    firing_body = body[firing_marker.start():resolved_marker.start()].strip()
    resolved_body = body[resolved_marker.start():].strip()
    children = []
    for state, count, section in (
        ("FIRING", match.group(1), firing_body),
        ("RESOLVED", match.group(2), resolved_body),
    ):
        child = dict(payload)
        child["subject"] = subject[:match.start()] + f"[{state}:{count}]" + subject[match.end():]
        child["text"] = f"{prefix}\n{section}".strip()
        child["html"] = ""
        child["grafana_split_state"] = state
        child["grafana_parent_subject"] = subject
        children.append(child)
    return children
