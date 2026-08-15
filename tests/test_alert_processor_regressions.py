import json
import importlib.util
import os
import sys
import tempfile
import types
import unittest
from unittest.mock import Mock, patch


PROCESSOR_DIR = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "services", "alert-processor")
)
sys.path.insert(0, PROCESSOR_DIR)

# Keep regression tests runnable from a clean checkout without installing service
# dependencies. Production containers still use the pinned requirements files.
try:
    import requests  # noqa: F401
except ModuleNotFoundError:
    requests_stub = types.ModuleType("requests")
    requests_stub.post = lambda *args, **kwargs: None
    requests_stub.exceptions = types.SimpleNamespace(RequestException=Exception)
    sys.modules["requests"] = requests_stub

try:
    import redis  # noqa: F401
except ModuleNotFoundError:
    redis_stub = types.ModuleType("redis")
    redis_stub.Redis = object
    sys.modules["redis"] = redis_stub

try:
    import bs4  # noqa: F401
except ModuleNotFoundError:
    bs4_stub = types.ModuleType("bs4")
    bs4_stub.BeautifulSoup = object
    sys.modules["bs4"] = bs4_stub

try:
    import pytz  # noqa: F401
except ModuleNotFoundError:
    pytz_stub = types.ModuleType("pytz")
    pytz_stub.timezone = lambda name: None
    sys.modules["pytz"] = pytz_stub

import ai_service
import utils
from correlation import IncidentTracker
from routing import find_matching_rule, get_routing_targets
from resolution import build_resolution_cards
from source_adapters import build_correlation_identity, normalize_alert, normalize_resource_identifiers, preserve_resources, split_grafana_mixed_payload, validate_analysis

processor_spec = importlib.util.spec_from_file_location(
    "processor_main_test", os.path.join(PROCESSOR_DIR, "main.py")
)
processor_main = importlib.util.module_from_spec(processor_spec)
processor_spec.loader.exec_module(processor_main)


class FakeRedis:
    def __init__(self):
        self.values = {}
        self.sets = {}

    def set(self, key, value, ex=None):
        self.values[key] = value

    def get(self, key):
        return self.values.get(key)

    def sadd(self, key, value):
        self.sets.setdefault(key, set()).add(value)

    def srem(self, key, value):
        self.sets.setdefault(key, set()).discard(value)

    def smembers(self, key):
        return self.sets.get(key, set())

    def scan_iter(self, match=None):
        prefix = (match or "").rstrip("*")
        for key in list(self.sets) + list(self.values):
            if key.startswith(prefix):
                yield key

    def xadd(self, key, fields, maxlen=None, approximate=None):
        self.values.setdefault(key, []).append(fields)

    def expire(self, key, seconds):
        return True

    def delete(self, key):
        self.values.pop(key, None)


class DestinationOnlyRoutingTests(unittest.TestCase):
    def test_rule_returns_destination_and_severity_destination_ids(self):
        result = get_routing_targets(
            "alert@example.com",
            [{
                "id": "r1", "name": "Example", "enabled": "true", "priority": "0",
                "email_pattern": "*@example.com", "alert_destination_ids": '["default"]',
                "resolved_destination_ids": '["resolved"]',
                "severity_destination_ids": '{"critical":["noc"]}',
            }],
            "", "0", "", "telegram",
        )
        self.assertEqual("destinations", result["channel"])
        self.assertEqual(["default"], result["alert_destination_ids"])
        self.assertEqual(["resolved"], result["resolved_destination_ids"])
        self.assertEqual({"critical": ["noc"]}, result["severity_destination_ids"])
        self.assertNotIn("notification_channel_ids", result)


class IncidentCorrelationTests(unittest.TestCase):
    def setUp(self):
        self.redis = FakeRedis()
        self.tracker = IncidentTracker(self.redis)

    def test_update_enriches_generic_incident_with_named_pvcs(self):
        created = self.tracker.process_incident_state_ai(
            "Grafana-Example@example.com",
            "[FIRING:1] Longhorn Detached Volumes",
            "NEW",
            target_resource="unknown",
        )
        updated = self.tracker.process_incident_state_ai(
            "Grafana-Example@example.com",
            "[FIRING:2] Longhorn Detached Volumes",
            "UPDATE",
            target_incident_id=created["incident_key"],
            target_resources=["data-kutt-postgresql-0", "redis-data-kutt-redis-master-0"],
            main_message="Two named PVCs are detached.",
            details=["Firing instances: 2"],
        )

        self.assertEqual("MERGE", updated["action"])
        state = json.loads(self.redis.get(f"incident:{created['incident_key']}"))
        self.assertEqual(
            ["data-kutt-postgresql-0", "redis-data-kutt-redis-master-0"],
            state["target_resources"],
        )
        self.assertEqual("Two named PVCs are detached.", state["latest_main_message"])
        self.assertEqual(2, state["revision"])

    def test_incident_resource_state_is_bounded(self):
        resources = [f"resource-{index}.example" for index in range(30)]
        created = self.tracker.process_incident_state_ai(
            "syncovery@example.com", "Large resource list", "NEW", target_resources=resources,
        )
        state = json.loads(self.redis.get(f"incident:{created['incident_key']}"))
        self.assertEqual(12, len(state["target_resources"]))
        self.assertEqual(18, state["omitted_resource_count"])

    def test_disjoint_resources_create_a_new_incident(self):
        created = self.tracker.process_incident_state_ai(
            "grafana@example.com", "Detached", "NEW",
            target_resources=["database-pvc"],
        )
        updated = self.tracker.process_incident_state_ai(
            "grafana@example.com", "Detached", "UPDATE",
            target_incident_id=created["incident_key"],
            target_resources=["redis-pvc"],
        )

        self.assertEqual("NEW", updated["action"])
        self.assertNotEqual(created["incident_key"], updated["incident_key"])

    def test_failed_analysis_is_not_an_open_incident(self):
        created = self.tracker.process_incident_state_ai(
            "grafana@example.com", "Detached", "NEW",
            target_resource="analysis_failed", track_open=False,
        )
        state = json.loads(self.redis.get(f"incident:{created['incident_key']}"))
        self.assertEqual("ANALYSIS_FAILED", state["status"])
        self.assertEqual(set(), self.redis.smembers("open_incidents:example.com"))

    def test_resolve_without_target_is_stored_closed_and_not_open(self):
        result = self.tracker.process_incident_state_ai(
            "veeam@example.com", "Reset/resolved for VM app-01", "RESOLVE",
            target_resources=["app-01"], main_message="VM recovered.",
        )
        self.assertEqual("ORPHAN_RESOLVE", result["action"])
        state = json.loads(self.redis.get(f"incident:{result['incident_key']}"))
        self.assertEqual("ORPHAN_RESOLVED", state["status"])
        self.assertEqual(set(), self.redis.smembers("open_incidents:example.com"))

    def test_exact_duplicate_updates_occurrence_without_new_alert(self):
        created = self.tracker.process_incident_state_ai(
            "grafana@example.com", "PVC detached", "NEW", target_resources=["data-pvc"]
        )
        self.assertTrue(self.tracker.record_suppressed_occurrence(created["incident_key"]))
        state = json.loads(self.redis.get(f"incident:{created['incident_key']}"))
        self.assertEqual(2, state["occurrences"])
        self.assertEqual("exact_duplicate", state["last_suppressed_reason"])
        self.assertEqual(1, state["suppressed_occurrences"])

    def test_deterministic_identity_merges_even_when_volatile_resources_differ(self):
        key = "stable-key"
        created = self.tracker.process_incident_state_ai(
            "syncovery@example.com", "Cinnagen Box", "NEW",
            target_resources=["Cinnagen Box", "/1/2026"], correlation_key=key,
            correlation_identity="syncovery|cinnagen-box|disk-full",
        )
        self.assertEqual(created["incident_key"], self.tracker.find_open_by_correlation_key("syncovery@example.com", key))
        updated = self.tracker.process_incident_state_ai(
            "syncovery@example.com", "Cinnagen Box", "UPDATE",
            target_incident_id=created["incident_key"], target_resources=["Cinnagen Box", "/4/2026"],
            correlation_key=key, correlation_identity="syncovery|cinnagen-box|disk-full",
        )
        self.assertEqual("MERGE", updated["action"])


    def test_disjoint_source_fingerprint_cannot_merge(self):
        created = self.tracker.process_incident_state_ai(
            "grafana@example.com", "Deployment", "NEW",
            target_resources=["same-namespace"], source_fingerprint="pod-a",
        )
        updated = self.tracker.process_incident_state_ai(
            "grafana@example.com", "Deployment", "UPDATE",
            target_incident_id=created["incident_key"],
            target_resources=["same-namespace"], source_fingerprint="pod-b",
        )

        self.assertEqual("NEW", updated["action"])
        self.assertNotEqual(created["incident_key"], updated["incident_key"])

    @patch("correlation.time.time", return_value=400000)
    def test_inactive_incident_becomes_stale_not_resolved(self, _now):
        created = self.tracker.process_incident_state_ai(
            "grafana@example.com", "Old alert", "NEW", target_resource="old-pvc"
        )
        state_key = f"incident:{created['incident_key']}"
        state = json.loads(self.redis.get(state_key))
        state["last_updated"] = 1
        self.redis.set(state_key, json.dumps(state))

        marked = self.tracker.mark_stale_open_incidents(max_age_seconds=3600)

        state = json.loads(self.redis.get(state_key))
        self.assertEqual(1, marked)
        self.assertEqual("STALE", state["status"])
        self.assertNotIn(created["incident_key"], self.redis.smembers("open_incidents:example.com"))


class ResourceNormalizationTests(unittest.TestCase):
    def test_removes_date_and_status_noise_but_preserves_vm_parentheses(self):
        resources = normalize_resource_identifiers([
            "HL-BKP-02(HL-DB)", "/resolved", "/4/2026", "E:\\\"", "data-pvc",
        ])
        self.assertIn("HL-BKP-02(HL-DB)", resources)
        self.assertIn("E:", resources)
        self.assertIn("data-pvc", resources)
        self.assertNotIn("/resolved", resources)
        self.assertNotIn("/4/2026", resources)

    def test_removes_speed_and_label_fragments(self):
        resources = normalize_resource_identifiers([
            "EXAMPLE-SG01-SRV", "/sec", "/slowest", "/Datastore:", "/16/2026)",
        ])
        self.assertEqual(["EXAMPLE-SG01-SRV"], resources)

    def test_syncovery_identity_ignores_counts_dates_and_duration(self):
        first = build_correlation_identity(
            "Syncovery@example.com",
            "Cinnagen Box: INCOMPLETE: 0 copied of 50, Duration: 00:02:01, Writing problems (full?)",
            "Error 112 on 8/1/2026", {},
        )
        second = build_correlation_identity(
            "Syncovery@example.com",
            "Cinnagen Box: INCOMPLETE: 0 copied of 62, Duration: 00:05:44, Writing problems (full?)",
            "Insufficient disk space on 8/4/2026", {},
        )
        self.assertTrue(first["correlation_key"])
        self.assertEqual(first["correlation_key"], second["correlation_key"])

    def test_syncovery_identity_uses_grounded_analysis_when_subject_is_generic(self):
        identity = build_correlation_identity(
            "Syncovery@example.com",
            "Cinnagen Box: INCOMPLETE: 0 copied of 92, Errors with 92 File(s)",
            "",
            {"main_message": "All files failed with error 29: cannot write to the specified device", "details": []},
        )
        self.assertEqual("syncovery|cinnagen-box|write-failure", identity["correlation_identity"])


class EvidenceValidationTests(unittest.TestCase):
    def test_datasource_uid_is_not_invented_as_a_pvc(self):
        subject = "[FIRING:1] DatasourceNoData Kubernetes (cf98d7ch9jrpcf A Longhorn Detached Volumes)"
        normalized = normalize_alert("grafana@example.com", subject, "")
        result = {"analysis": {
            "severity": "Critical", "category": "Storage", "status": "FIRING",
            "confidence": 0.99, "target_resource": "PVC cf98d7ch9jrpcf",
            "target_resources": ["datasource_uid:cf98d7ch9jrpcf", "PVC cf98d7ch9jrpcf"],
            "main_message": "PVC cf98d7ch9jrpcf is detached.", "details": [],
            "recommended_actions": ["Reattach PVC cf98d7ch9jrpcf"],
        }}
        analysis = validate_analysis(result, "grafana@example.com", subject, "", normalized)["analysis"]
        self.assertEqual("Grafana datasource cf98d7ch9jrpcf", analysis["target_resource"])
        self.assertNotIn("PVC cf98d7ch9jrpcf", analysis["target_resources"])
        self.assertIn("not identified", analysis["main_message"])
        self.assertEqual("inferred", analysis["evidence_status"])
        self.assertEqual(0.70, analysis["confidence"])

    def test_datasource_rule_name_cannot_prove_an_unnamed_detached_pvc(self):
        subject = "[FIRING:1] DatasourceNoData Kubernetes (cf98d7ch9jrpcf A Longhorn Detached Volumes)"
        normalized = normalize_alert("grafana@example.com", subject, "")
        result = {"analysis": {
            "severity": "Critical", "category": "Storage", "status": "FIRING",
            "confidence": 0.90, "target_resource": "Longhorn Detached Volumes",
            "target_resources": ["Longhorn Detached Volumes"],
            "main_message": "A PersistentVolumeClaim is detached and unavailable.",
            "details": [], "recommended_actions": [{"text": "Inspect and reattach the detached PVC"}],
        }}
        analysis = validate_analysis(result, "grafana@example.com", subject, "", normalized)["analysis"]
        self.assertEqual("Grafana datasource cf98d7ch9jrpcf", analysis["target_resource"])
        self.assertIn("not identified", analysis["main_message"])
        self.assertEqual("inferred", analysis["evidence_status"])
        self.assertEqual("diagnostic", analysis["recommended_actions"][0]["type"])

    def test_named_pvc_from_payload_is_preserved(self):
        subject = "[FIRING:2] Longhorn Detached Volumes"
        body = "PVCs: data-kutt-postgresql-0, redis-data-kutt-redis-master-0"
        normalized = normalize_alert("grafana@example.com", subject, body)
        result = {"analysis": {
            "severity": "Critical", "category": "Storage", "status": "FIRING",
            "confidence": 0.97, "target_resource": "data-kutt-postgresql-0",
            "target_resources": ["data-kutt-postgresql-0", "redis-data-kutt-redis-master-0"],
            "main_message": "Two PVCs are detached.", "details": [], "recommended_actions": [],
        }}
        analysis = validate_analysis(result, "grafana@example.com", subject, body, normalized)["analysis"]
        self.assertEqual("verified", analysis["evidence_status"])
        self.assertEqual(2, len(analysis["target_resources"]))

    def test_known_source_category_is_canonical(self):
        subject = 'Guest disk space Error for Virtual Machine "APP-01"'
        body = 'Current state: Error\nObject: APP-01'
        normalized = normalize_alert("veeam@example.com", subject, body)
        result = {"analysis": {
            "severity": "High", "category": "Virtualization", "status": "FIRING",
            "confidence": 0.98, "target_resource": "APP-01", "target_resources": ["APP-01"],
            "main_message": "Disk is full", "details": [], "recommended_actions": [],
        }}
        analysis = validate_analysis(result, "veeam@example.com", subject, body, normalized)["analysis"]
        self.assertEqual("Storage", analysis["category"])
        self.assertIn("category", analysis["taxonomy_overrides"])

    def test_resolved_message_separates_state_from_incident_severity(self):
        result = {"analysis": {
            "severity": "Critical", "category": "Security", "status": "RESOLVED",
            "event_state": "Resolved", "system_name": "VeeamOne", "source_host": "host",
            "main_message": "Alert resolved.", "details": [], "recommended_actions": [],
        }}
        rendered = ai_service.format_for_matrix(result, "sender", "subject")
        self.assertIn("Resolved | Previously Critical | Security", rendered)

    def test_veeam_warning_and_resolve_have_same_identity(self):
        firing = build_correlation_identity(
            "VeeamOne@example.com", "VM CPU usage8/4/2026 Warning for Virtual Machine \"APP-01\"", "", {},
        )
        resolved = build_correlation_identity(
            "VeeamOne@example.com", "VM CPU usage8/4/2026 Reset/resolved for Virtual Machine \"APP-01\"", "", {},
        )
        self.assertEqual(firing["correlation_key"], resolved["correlation_key"])

    def test_veeam_infrastructure_tree_warning_and_error_share_identity(self):
        warning = build_correlation_identity(
            "VeeamOne@example.com", "Object properties data collection failure Warning for Infrastructure Tree \"Virtual Infrastructure\"6/29/2026", "", {},
        )
        error = build_correlation_identity(
            "VeeamOne@example.com", "Object properties data collection failure6/8/2026 Error for Infrastructure Tree \"Virtual Infrastructure\"", "", {},
        )
        self.assertTrue(warning["correlation_key"])
        self.assertEqual(warning["correlation_key"], error["correlation_key"])

    def test_same_feed_subject_keeps_inventory_and_sales_separate(self):
        subject = "High - Dev - Shafaarad/Cinnagen feed failing"
        inventory = build_correlation_identity(
            "alerts@example.com", subject, "", {"category": "Service", "target_resources": ["inventory_shafa_arad_pipeline"]},
        )
        sales = build_correlation_identity(
            "alerts@example.com", subject, "", {"category": "Service", "target_resources": ["sale_shafaarad_daily_dag"]},
        )
        self.assertNotEqual(inventory["correlation_key"], sales["correlation_key"])

    def test_shared_pipeline_keeps_different_feed_partners_separate(self):
        analysis = {"category": "Service", "target_resources": ["inventory_hejrat_pipeline"]}
        aryogen = build_correlation_identity(
            "alerts@example.com", "High - Dev - Hejrat/Aryogen feed failing", "", analysis,
        )
        nanoalvand = build_correlation_identity(
            "alerts@example.com", "High - Dev - Hejrat/Nanoalvand feed failing", "", analysis,
        )
        self.assertNotEqual(aryogen["correlation_key"], nanoalvand["correlation_key"])

    def test_unknown_opaque_sender_remains_ai_fallback(self):
        identity = build_correlation_identity("new@example.com", "Opaque alarm", "no identifiers", {})
        self.assertEqual("", identity["correlation_key"])


class AIFailoverTests(unittest.TestCase):
    @patch.object(ai_service, "get_failover_providers")
    @patch.object(ai_service, "get_default_provider")
    @patch.object(ai_service.requests, "post")
    def test_uses_second_provider_after_503(self, post, get_default, get_failovers):
        get_default.return_value = {
            "id": "primary", "name": "Primary", "type": "custom",
            "base_url": "https://primary.invalid/v1/chat/completions",
            "model": "primary-model", "api_key": "", "timeout": 1,
        }
        get_failovers.return_value = [{
            "id": "secondary", "name": "Secondary", "type": "vllm",
            "base_url": "https://secondary.invalid/v1",
            "model": "secondary-model", "api_key": "", "timeout": 1,
        }]
        failed = Mock(status_code=503, text="no available server")
        succeeded = Mock(status_code=200)
        succeeded.json.return_value = {
            "choices": [{"message": {"content": json.dumps({
                "analysis": {
                    "severity": "Critical",
                    "target_resource": "data-kutt-postgresql-0",
                    "main_message": "PVC detached",
                }
            })}}]
        }
        post.side_effect = [failed, succeeded]

        result, provider, _ = ai_service.analyze_email(
            "grafana@example.com", "Detached",
            "PVC data-kutt-postgresql-0 " + ("x" * 5000),
        )

        self.assertEqual(2, post.call_count)
        self.assertIn("Secondary", provider)
        self.assertEqual(
            "https://secondary.invalid/v1/chat/completions",
            post.call_args_list[1].args[0],
        )
        self.assertEqual(
            ["data-kutt-postgresql-0"],
            result["analysis"]["target_resources"],
        )
        sent_user_prompt = post.call_args_list[0].kwargs["json"]["messages"][1]["content"]
        self.assertLess(len(sent_user_prompt), 2800)

    def test_prompt_requires_resources_and_safe_actions(self):
        prompt = ai_service.build_system_prompt()
        self.assertIn("target_resources", prompt)
        self.assertIn("Never recommend deleting", prompt)
        self.assertIn("Never replace named resources with generic wording", prompt)
        bounded = ai_service.build_system_prompt("start" + ("x" * 3000) + "tail-marker")
        self.assertNotIn("tail-marker", bounded)

    def test_recommended_actions_receive_deterministic_safety_labels(self):
        analysis = {"recommended_actions": [
            "Inspect PVC events with kubectl describe pvc",
            "Delete and recreate the PVC",
        ]}

        ai_service.normalize_recommended_actions(analysis)

        self.assertEqual("diagnostic", analysis["recommended_actions"][0]["type"])
        self.assertFalse(analysis["recommended_actions"][0]["requires_approval"])
        self.assertEqual("destructive", analysis["recommended_actions"][1]["type"])
        self.assertTrue(analysis["recommended_actions"][1]["requires_approval"])

    def test_analysis_taxonomy_is_stable(self):
        analysis = {"severity": "CRITICAL", "category": "Other"}

        ai_service.normalize_analysis_taxonomy(analysis)

        self.assertEqual("Critical", analysis["severity"])
        self.assertEqual("Unclassified", analysis["category"])

        invalid = {"severity": "urgent", "category": "made-up"}
        ai_service.normalize_analysis_taxonomy(invalid)
        self.assertEqual("Unknown", invalid["severity"])
        self.assertEqual("Unclassified", invalid["category"])

    @patch.object(ai_service, "get_provider_by_id")
    @patch.object(ai_service, "get_redis_client")
    def test_selected_fallback_is_first(self, get_redis, get_provider):
        get_redis.return_value.smembers.return_value = {"ordinary", "selected"}
        providers = {
            "ordinary": {"id": "ordinary", "name": "A Provider", "base_url": "x", "model": "x", "is_fallback": False},
            "selected": {"id": "selected", "name": "Z Provider", "base_url": "x", "model": "x", "is_fallback": True},
        }
        get_provider.side_effect = lambda provider_id: providers[provider_id]

        ordered = ai_service.get_failover_providers("primary")

        self.assertEqual("selected", ordered[0]["id"])


class RoutingDeterminismTests(unittest.TestCase):
    def test_more_specific_rule_wins_when_priorities_are_equal(self):
        rules = [
            {"id": "generic", "enabled": "true", "priority": "0", "email_pattern": "*@example.com"},
            {"id": "grafana", "enabled": "true", "priority": "0", "email_pattern": "grafana-*@example.com"},
        ]

        matched = find_matching_rule("grafana-prod@example.com", rules)

        self.assertEqual("grafana", matched["id"])


class NotificationIdempotencyTests(unittest.TestCase):
    @patch.object(utils.requests, "post")
    def test_telegram_not_modified_is_success(self, post):
        response = Mock(status_code=400, text='{"description":"Bad Request: message is not modified"}')
        post.return_value = response

        success = utils.edit_telegram_message(
            "-100123", 42, "same text", bot_token="test-token"
        )

        self.assertTrue(success)


class QueueAndDeliveryTests(unittest.TestCase):
    @patch.object(processor_main, "record_delivery")
    @patch.object(processor_main, "send_telegram_auto", side_effect=[(True, 101), (True, 202)])
    @patch.object(processor_main, "get_channel_config", return_value={
        "type": "telegram", "name": "Bot", "config": json.dumps({"bot_token": "secret"}),
    })
    @patch.object(processor_main, "get_destination")
    def test_same_telegram_connector_supports_multiple_threads(self, get_destination, _config, send, _record):
        get_destination.side_effect = lambda destination_id: {
            "id": destination_id, "name": destination_id, "channel_id": "telegram-bot", "type": "telegram",
            "target": {"chat_id": "-1001", "thread_id": "11" if destination_id == "d1" else "22"},
        }
        success, _, saved, failed = processor_main.dispatch_destinations(
            "alert", "alert", ["d1", "d2"], delivery_alert_id="a1"
        )
        self.assertTrue(success)
        self.assertEqual([], failed)
        self.assertEqual({"destination:d1": 101, "destination:d2": 202}, saved)
        self.assertEqual([11, 22], [call.args[1] for call in send.call_args_list])

    @patch.object(processor_main, "record_delivery")
    @patch.object(processor_main, "dispatch_dynamic_alert", side_effect=[(True, "tg ok", {"telegram_-1001": 1}, []), (False, "mx failed", {}, ["matrix"] )])
    @patch.object(processor_main, "get_destination")
    def test_telegram_matrix_partial_destination_delivery_is_explicit(self, get_destination, _dispatch, _record):
        get_destination.side_effect = [
            {"id":"tg","name":"TG","channel_id":"telegram","type":"telegram","target":{"chat_id":"-1001","thread_id":"7"}},
            {"id":"mx","name":"MX","channel_id":"matrix","type":"matrix","target":{"room_id":"!room"}},
        ]
        success, _, saved, failed = processor_main.dispatch_destinations("t", "m", ["tg", "mx"])
        self.assertFalse(success)
        self.assertEqual(["mx"], failed)
        self.assertEqual({"destination:tg": 1}, saved)

    @patch.object(processor_main, "record_delivery")
    @patch.object(processor_main, "dispatch_dynamic_alert", return_value=(True, "edit ok", {}, []))
    @patch.object(processor_main, "get_destination", return_value={
        "id":"tg","name":"TG","channel_id":"telegram","type":"telegram","target":{"chat_id":"-1001","thread_id":"7"},
    })
    def test_migrated_open_incident_reuses_legacy_message_id(self, _destination, dispatch, _record):
        processor_main.dispatch_destinations(
            "updated", "updated", ["tg"], action="MERGE",
            known_message_ids={"telegram_-1001": "legacy-message"},
        )
        self.assertEqual({"telegram_-1001": "legacy-message"}, dispatch.call_args.kwargs["known_message_ids"])

    def test_resolution_archive_retry_is_never_discarded_as_superseded(self):
        processor_main.redis_client = Mock()
        self.assertFalse(processor_main.retry_is_superseded({
            "resolution_archive": True, "incident_key": "closed-incident", "incident_revision": 99,
        }))
        processor_main.redis_client.get.assert_not_called()

    @patch.object(processor_main, "cleanup_active_incident_messages")
    @patch.object(processor_main, "_save_resolution_archive")
    @patch.object(processor_main, "dispatch_dynamic_alert", return_value=(False, "failed", {}, ["matrix"] ))
    def test_resolution_retry_does_not_cleanup_until_archive_delivery(self, _dispatch, _save, cleanup):
        processor_main.redis_client = Mock()
        success = processor_main.retry_dispatch({
            "telegram_msg": "resolved", "matrix_msg": "resolved", "channel": "dynamic",
            "notification_channel_ids": ["matrix"], "channel_overrides": {}, "retry_count": 1,
            "subject": "resolved", "alert_id": "a1", "action": "NEW", "incident_key": "i1",
            "resolution_archive": True, "cleanup_after_archive": True,
        })
        self.assertFalse(success)
        cleanup.assert_not_called()

    def test_legacy_target_resolves_to_current_channel_credentials(self):
        client = Mock()
        client.smembers.return_value = ["telegram-current"]
        client.pipeline.return_value.execute.return_value = [{
            "type": "telegram", "name": "Current Telegram",
            "config": json.dumps({"bot_token": "secret", "default_chat_id": "-1001"}),
        }]
        processor_main.redis_client = client

        channel_id, config = processor_main.find_channel_for_legacy_target("telegram", "-1001")

        self.assertEqual("telegram-current", channel_id)
        self.assertEqual("Current Telegram", config["name"])

    @patch.object(processor_main, "record_delivery")
    @patch.object(processor_main, "increment_metric")
    @patch.object(processor_main, "add_log")
    @patch.object(processor_main, "push_to_dlq")
    def test_duplicate_dlq_group_is_suppressed(self, push_dlq, _add_log, _metric, _record):
        client = Mock()
        client.set.side_effect = [True, False]
        processor_main.redis_client = client
        payload = {
            "retry_count": 4, "subject": "same update", "incident_key": "incident-1",
            "action": "MERGE", "notification_channel_ids": ["telegram"], "alert_id": "a1",
        }

        processor_main.schedule_retry(dict(payload))
        processor_main.schedule_retry(dict(payload, alert_id="a2"))

        push_dlq.assert_called_once()
        client.hincrby.assert_called_with("metrics:processor", "dlq_duplicates_suppressed", 1)

    def test_reclaims_abandoned_stream_message_before_new_delivery(self):
        client = Mock()
        client.xautoclaim.return_value = ["0-0", [("1-0", {"payload": "old"})], []]

        stream_id, payload = processor_main.read_stream_message(client, True)

        self.assertEqual(("1-0", "old"), (stream_id, payload))
        client.xreadgroup.assert_not_called()

    @patch.object(processor_main, "record_delivery")
    @patch.object(processor_main, "send_webhook", side_effect=[True, False])
    @patch.object(processor_main, "get_channel_config")
    def test_partial_delivery_retries_only_failed_channel(self, get_config, send_webhook, record):
        get_config.side_effect = lambda channel_id: {
            "type": "webhook", "name": channel_id,
            "config": json.dumps({"url": f"https://{channel_id}.invalid"}),
        }

        success, _, _, failed = processor_main.dispatch_dynamic_alert(
            "telegram", "matrix", ["primary", "secondary"], delivery_alert_id="alert-1"
        )

        self.assertFalse(success)
        self.assertEqual(["secondary"], failed)
        self.assertEqual("delivered", record.call_args_list[0].args[2])
        self.assertEqual("failed", record.call_args_list[1].args[2])

    @patch.object(processor_main, "record_delivery")
    @patch.object(utils, "send_telegram_auto", return_value=(True, "new-message-id"))
    def test_legacy_retry_persists_successful_delivery(self, send_telegram, record):
        processor_main.redis_client = Mock()
        success = processor_main.retry_dispatch({
            "telegram_msg": "message", "matrix_msg": "message", "channel": "telegram",
            "chat_id": "-1001", "thread_id": "0", "retry_count": 1,
            "subject": "legacy retry", "alert_id": "alert-1", "action": "NEW",
        })
        self.assertTrue(success)
        send_telegram.assert_called_once()
        self.assertEqual("delivered", record.call_args.args[2])

    @patch.object(processor_main, "record_delivery")
    @patch.object(processor_main, "find_channel_for_legacy_target")
    @patch.object(utils, "send_matrix_message")
    @patch.object(utils, "edit_telegram_message", return_value=True)
    def test_legacy_merge_does_not_create_missing_channel_message(self, _edit, send_matrix, find_channel, _record):
        processor_main.redis_client = Mock()
        find_channel.side_effect = [
            ("telegram", {"config": json.dumps({"bot_token": "secret", "default_chat_id": "-1001"})}),
            ("matrix", {"config": json.dumps({"homeserver_url": "https://matrix", "access_token": "secret", "default_room_id": "!room"})}),
        ]

        success = processor_main.retry_dispatch({
            "telegram_msg": "message", "matrix_msg": "message", "channel": "both",
            "chat_id": "-1001", "room_id": "!room", "retry_count": 3,
            "subject": "legacy merge", "alert_id": "alert-1", "action": "MERGE",
            "known_message_ids": {"telegram_-1001": "42"},
        })

        self.assertTrue(success)
        send_matrix.assert_not_called()


class HybridSourceAdapterTests(unittest.TestCase):
    def test_veeam_vm_name_is_extracted(self):
        normalized = normalize_alert(
            "veeam@example.com",
            "Veeam Backup job failed",
            "Job name: Daily-VM-Backup\nVM name: EXAMPLE-APP-01\nError: connection reset",
        )

        self.assertEqual("veeam", normalized["source_type"])
        self.assertIn("Daily-VM-Backup", normalized["target_resources"])
        self.assertIn("EXAMPLE-APP-01", normalized["target_resources"])

    def test_syncovery_profile_is_extracted(self):
        normalized = normalize_alert(
            "syncovery@example.com",
            "Syncovery Report - INCOMPLETE",
            "Profile: EXAMPLE-DB-SRV\nSource: /var/backups/postgres/jira/",
        )

        self.assertEqual("syncovery", normalized["source_type"])
        self.assertIn("EXAMPLE-DB-SRV", normalized["target_resources"])

    def test_uptime_kuma_monitor_url_is_extracted(self):
        normalized = normalize_alert(
            "uptime-kuma@example.com",
            "API is DOWN",
            "Monitor: Example API\nURL: https://api.example.com/health\nReason: timeout",
        )

        self.assertEqual("uptime-kuma", normalized["source_type"])
        self.assertIn("Example API", normalized["target_resources"])
        self.assertIn("https://api.example.com/health", normalized["target_resources"])

    def test_uptime_kuma_drops_bare_scheme_and_timestamp_resources(self):
        normalized = normalize_alert(
            "kuma-inside@webhook.local", "Alert from kuma-inside",
            "Monitor: CRM\nURL: https://\nTime: 2026-08-05 19:52:06.616\nmonitorID 78",
        )

        self.assertNotIn("https://", normalized["target_resources"])
        resources = normalize_resource_identifiers(["monitorID 78", "2026-08-05 19:52:06.616"])
        self.assertNotIn("2026-08-05 19:52:06.616", resources)

    def test_grafana_pvcs_are_preserved_in_ai_output(self):
        normalized = normalize_alert(
            "grafana@example.com",
            "[FIRING:2] Longhorn Detached",
            "PVCs: data-kutt-postgresql-0, redis-data-kutt-redis-master-0\nDetached for 8h",
        )
        result = preserve_resources(
            {"analysis": {"target_resources": [], "main_message": "PVCs detached"}},
            normalized,
        )

        self.assertEqual("grafana", normalized["source_type"])
        self.assertEqual(
            ["data-kutt-postgresql-0", "redis-data-kutt-redis-master-0"],
            result["analysis"]["target_resources"],
        )

    def test_unknown_sender_keeps_generic_ai_path(self):
        normalized = normalize_alert("new-monitor@example.com", "New alert", "opaque payload")

        self.assertEqual("generic", normalized["source_type"])
        self.assertEqual([], normalized["target_resources"])

    def test_grafana_mixed_message_splits_into_ordered_events(self):
        payload = {
            "from": "grafana@example.com",
            "subject": "[FIRING:1, RESOLVED:1] Deployment Kubernetes",
        }
        body = "Header\n🔥 1 firing instances\nFiring\npod\npod-new\n✅ 1 resolved instances\nResolved\npod\npod-old"

        children = split_grafana_mixed_payload(payload, body)

        self.assertEqual(["FIRING", "RESOLVED"], [c["grafana_split_state"] for c in children])
        self.assertIn("[FIRING:1]", children[0]["subject"])
        self.assertIn("pod-new", children[0]["text"])
        self.assertNotIn("pod-old", children[0]["text"])
        self.assertIn("[RESOLVED:1]", children[1]["subject"])


class SelfMonitorTests(unittest.TestCase):
    def test_retry_is_superseded_after_newer_channel_delivery(self):
        redis_mock = Mock()
        processor_main.redis_client = redis_mock
        redis_mock.get.return_value = json.dumps({"revision": 3, "status": "OPEN"})
        redis_mock.xrevrange.return_value = [
            ("1-0", {"action": "DELIVERY", "channel_id": "telegram", "status": "delivered"}),
        ]
        self.assertTrue(processor_main.retry_is_superseded({
            "incident_key": "incident-1", "incident_revision": 2,
            "notification_channel_ids": ["telegram"],
        }))

    def test_retry_is_not_superseded_when_failed_channel_has_not_recovered(self):
        redis_mock = Mock()
        processor_main.redis_client = redis_mock
        redis_mock.get.return_value = json.dumps({"revision": 3, "status": "OPEN"})
        redis_mock.xrevrange.return_value = [
            ("1-0", {"action": "DELIVERY", "channel_id": "telegram", "status": "failed"}),
        ]
        self.assertFalse(processor_main.retry_is_superseded({
            "incident_key": "incident-1", "incident_revision": 2,
            "notification_channel_ids": ["telegram"],
        }))
    def test_storm_cooldown_suppresses_repeated_notification(self):
        redis_mock = Mock()
        processor_main.redis_client = redis_mock
        redis_mock.pipeline.return_value.execute.return_value = [1, 0, 8, True]
        redis_mock.set.return_value = False

        suppressed, count = processor_main.should_suppress_incident_notification("incident-1", "MERGE")

        self.assertTrue(suppressed)
        self.assertEqual(8, count)
        redis_mock.hincrby.assert_called_with("metrics:processor", "storm_suppressed", 1)

    def test_global_storm_suppresses_noncritical_but_keeps_incident_data(self):
        redis_mock = Mock()
        processor_main.redis_client = redis_mock
        redis_mock.hgetall.side_effect = [{}, {}]
        redis_mock.pipeline.return_value.execute.return_value = [1, 0, 25, True]
        redis_mock.hget.return_value = None

        suppressed, count = processor_main.should_suppress_global_storm(
            "alert-1", "incident-1", "MERGE", "High",
            {"subject": "Database latency"},
            {"system_name": "PostgreSQL", "target_resources": ["db-01"]},
        )

        self.assertTrue(suppressed)
        self.assertEqual(25, count)
        redis_mock.xadd.assert_called_once()
        redis_mock.hset.assert_any_call(
            "alert:alert-1",
            mapping={"notification_suppressed": "global_storm", "storm_window_count": "25"},
        )

    @patch.object(processor_main, "get_channel_config", return_value={"type": "telegram"})
    @patch.object(processor_main, "get_routing_rules", return_value=[])
    @patch.object(processor_main, "get_routing_targets")
    def test_summary_uses_configured_chat_and_thread(self, get_targets, _rules, _config):
        get_targets.return_value = {
            "notification_channel_ids": ["telegram"], "channel_overrides": {},
        }
        processor_main.redis_client = Mock()
        processor_main.redis_client.hgetall.return_value = {
            "summary_telegram_chat_id": "-100123", "summary_telegram_thread_id": "77",
        }

        channels, overrides = processor_main.get_summary_delivery_targets()

        self.assertEqual(["telegram"], channels)
        self.assertEqual({"chat_id": "-100123", "thread_id": "77"}, overrides["telegram"])

    @patch.object(processor_main, "dispatch_dynamic_alert", return_value=(True, "ok", {}, []))
    @patch.object(processor_main, "get_summary_delivery_targets", return_value=(["telegram"], {}))
    @patch.object(processor_main, "_open_incident_snapshot", return_value=[])
    def test_daily_summary_counts_unique_incident_transitions(self, _snapshot, _targets, dispatch):
        redis_mock = Mock()
        processor_main.redis_client = redis_mock
        redis_mock.zrangebyscore.return_value = ["a1", "a2", "a3", "a4"]
        redis_mock.hmget.side_effect = [
            ["NEW", "incident-1"], ["NEW", "incident-1"],
            ["RESOLVE", "incident-1"], ["ORPHAN_RESOLVE", "incident-2"],
        ]
        redis_mock.hgetall.return_value = {}
        redis_mock.lrange.return_value = []
        processor_main.generate_daily_summary()
        message = dispatch.call_args.args[0]
        self.assertIn("New \\(24h\\):* 1", message)
        self.assertIn("Resolved \\(24h\\):* 2", message)


class TelegramSafetyTests(unittest.TestCase):
    def setUp(self):
        utils._telegram_network_failures = []
        utils._telegram_circuit_open_until = 0

    def test_redacts_bot_token_and_bearer_credentials(self):
        value = "POST https://api.telegram.org/bot123456:secret/send Authorization: Bearer abc.def"
        redacted = utils.redact_secrets(value)
        self.assertNotIn("123456:secret", redacted)
        self.assertNotIn("abc.def", redacted)
        self.assertIn("[REDACTED]", redacted)

    @patch.object(utils.requests, "post")
    def test_markdown_parse_error_falls_back_to_plain_text(self, post):
        rejected = Mock(status_code=400, text="Bad Request: can't parse entities")
        accepted = Mock(status_code=200, text="ok")
        post.side_effect = [rejected, accepted]
        response = utils._telegram_post(
            "https://api.telegram.org/botsecret/sendMessage",
            {"text": "file.name", "parse_mode": "MarkdownV2"}, 10,
        )
        self.assertEqual(200, response.status_code)
        fallback_payload = post.call_args_list[1].kwargs["json"]
        self.assertNotIn("parse_mode", fallback_payload)

    def test_ai_chain_reports_fallback_activation(self):
        redis_mock = Mock()
        processor_main.redis_client = redis_mock
        redis_mock.smembers.return_value = ["primary", "fallback"]
        redis_mock.pipeline.return_value.execute.return_value = [
            {"name": "Primary", "is_default": "true"},
            {"last_success_at": "1", "last_failure_at": "2", "last_error": "503"},
            {"name": "Fallback", "is_fallback": "true"},
            {"last_success_at": "3", "last_failure_at": "0"},
        ]

        state, detail = processor_main.get_ai_chain_monitor_state()

        self.assertEqual("warning", state)
        self.assertIn("Fallback", detail)

    def test_directory_size_counts_nested_files(self):
        with tempfile.TemporaryDirectory() as root:
            with open(os.path.join(root, "one"), "wb") as handle:
                handle.write(b"123")
            os.mkdir(os.path.join(root, "nested"))
            with open(os.path.join(root, "nested", "two"), "wb") as handle:
                handle.write(b"4567")

            self.assertEqual(7, processor_main._directory_size(root))

    @patch.object(processor_main, "add_log")
    def test_self_monitor_only_publishes_meaningful_transitions(self, add_log):
        redis_mock = Mock()
        processor_main.redis_client = redis_mock

        redis_mock.hget.return_value = None
        processor_main._publish_self_monitor_transition("loki", "healthy", "ready")
        redis_mock.xadd.assert_not_called()

        redis_mock.hget.return_value = "healthy"
        processor_main._publish_self_monitor_transition("loki", "critical", "down")
        redis_mock.xadd.assert_called_once()
        payload = json.loads(redis_mock.xadd.call_args.args[1]["payload"])
        self.assertIn("[FIRING:1]", payload["subject"])
        add_log.assert_called_once()

    def test_default_notification_channels_are_selected_for_self_monitor(self):
        redis_mock = Mock()
        processor_main.redis_client = redis_mock
        redis_mock.smembers.return_value = ["telegram", "matrix"]
        pipeline = redis_mock.pipeline.return_value
        pipeline.execute.return_value = [
            {"is_default": "true"},
            {"is_default": "false"},
        ]

        self.assertEqual(["telegram"], processor_main.get_default_notification_channel_ids())

    @patch.object(processor_main, "send_telegram_auto", return_value=(True, "42"))
    def test_dynamic_telegram_uses_saved_default_destination(self, send_telegram):
        processor_main.redis_client = Mock()
        processor_main.redis_client.hgetall.return_value = {
            "type": "telegram",
            "name": "Default Telegram",
            "config": json.dumps({
                "bot_token": "secret",
                "default_chat_id": "-100123",
                "default_thread_id": "7",
            }),
        }

        success, _, message_ids, failed = processor_main.dispatch_dynamic_alert(
            "telegram text", "matrix text", ["telegram"],
        )

        self.assertTrue(success)
        self.assertEqual([], failed)
        self.assertEqual({"telegram_-100123": "42"}, message_ids)
        send_telegram.assert_called_once_with(
            "-100123", 7, "telegram text", bot_token="secret", proxy_base_url=None,
        )


class ResolutionCardTests(unittest.TestCase):
    def test_card_preserves_problem_resources_and_complete_timeline(self):
        state = {
            "initial_main_message": "PVC data-db-0 detached (critical).",
            "target_resources": ["data-db-0", "redis-data-0"],
            "first_seen": 1000, "last_updated": 1300, "resolved_at": 1600,
            "occurrences": 4, "merge_occurrences": 2, "suppressed_occurrences": 1,
            "system_name": "Grafana", "category": "Storage",
            "source_first_observed": "2026-08-15 10:00:00 +0330",
        }
        analysis = {"main_message": "Both PVCs reattached at 2026-08-15 10:10:00 +0330."}
        events = [{"action": "DELIVERY", "status": "delivered", "occurred_at": "2026-08-15T06:31:00"}]

        telegram, matrix, _ = build_resolution_cards("incident-123", state, analysis, {}, events, now=1600)

        for expected in ("data\\-db\\-0", "redis\\-data\\-0", "Incident ID: incident\\-123", "Merged updates: 2", "Suppressed duplicates: 1"):
            self.assertIn(expected, telegram)
        self.assertIn("PVC data-db-0 detached (critical).", matrix)
        self.assertIn("Source first observed: 2026-08-15 10:00:00 +0330", matrix)

    def test_card_stays_inside_provider_limits(self):
        state = {
            "initial_main_message": "x" * 20000,
            "target_resources": [f"resource-{i}-" + "y" * 500 for i in range(20)],
            "first_seen": 1000, "last_updated": 1300, "resolved_at": 1600,
        }
        telegram, matrix, _ = build_resolution_cards("incident-long", state, {"main_message": "fixed"}, {}, now=1600)
        self.assertLessEqual(len(telegram), 3500)
        self.assertLessEqual(len(matrix), 12000)
        self.assertIn("Incident ID:", telegram)
        self.assertIn("Incident ID:", matrix)


if __name__ == "__main__":
    unittest.main()
