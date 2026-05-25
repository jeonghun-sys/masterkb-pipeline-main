from fastapi.testclient import TestClient

from kb_pipeline.main import app
from kb_pipeline.models import PipelineMode, TriggerType
from kb_pipeline.pipelines.runner import PipelineRunner
from kb_pipeline.settings import get_settings


def test_health_endpoint_reports_service_and_cutoff():
    client = TestClient(app)

    response = client.get("/health")

    assert response.status_code == 200
    payload = response.json()
    assert payload["service"] == "kb-pipeline"
    assert payload["cutoff"].startswith("2026-04-01T00:00:00")


def test_pipeline_runner_dry_run_smoke_does_not_write():
    runner = PipelineRunner()

    result = runner.run(mode=PipelineMode.SMOKE, write_mode="dry-run", target_sources=["slack"])

    assert result.mode == PipelineMode.SMOKE
    assert result.write_mode == "dry-run"
    assert result.summary["writes"] == 0
    assert result.summary["target_sources"] == ["slack"]
    assert result.summary["collected"] == 8
    assert result.summary["dry_run_candidates"] == 8


def test_pipeline_runner_collects_one_sample_for_each_source():
    runner = PipelineRunner()

    result = runner.run(
        mode=PipelineMode.SMOKE,
        write_mode="dry-run",
        target_sources=["slack", "event", "docbuilder"],
    )

    assert result.summary["collected"] == 10
    assert {record.target_table for record in result.records} >= {
        "class101_changelog",
        "class101_promotion",
        "product_issue",
        "slack_cs_data",
        "event_promotion",
        "doc_builder",
    }
    assert all(
        record.normalized["llm_status"] == "fallback_no_api_key"
        for record in result.records
    )


def test_manual_run_endpoint_uses_manual_trigger(monkeypatch):
    calls = []

    class FakeRunner:
        def run(self, **kwargs):
            calls.append(kwargs)

            class Result:
                def model_dump(self):
                    return {"summary": {"ok": True}}

            return Result()

    monkeypatch.setattr("kb_pipeline.main.PipelineRunner", lambda: FakeRunner())
    client = TestClient(app)

    response = client.post(
        "/runs",
        json={
            "mode": "smoke",
            "write_mode": "dry-run",
            "target_sources": ["event"],
            "limit": 1,
            "lookback_hours": 24,
        },
    )

    assert response.status_code == 200
    assert calls[0]["trigger_type"] == TriggerType.MANUAL
    assert calls[0]["target_sources"] == ["event"]
    assert calls[0]["limit"] == 1
    assert calls[0]["lookback_hours"] == 24


def test_scheduled_endpoint_uses_schedule_trigger(monkeypatch):
    calls = []

    class FakeRunner:
        def run(self, **kwargs):
            calls.append(kwargs)

            class Result:
                def model_dump(self):
                    return {"summary": {"ok": True}}

            return Result()

    monkeypatch.setattr("kb_pipeline.main.PipelineRunner", lambda: FakeRunner())
    client = TestClient(app)

    response = client.post(
        "/runs/scheduled",
        json={"target_sources": ["slack"], "lookback_hours": 24},
    )

    assert response.status_code == 200
    assert calls[0]["trigger_type"] == TriggerType.SCHEDULE
    assert calls[0]["mode"] == PipelineMode.INCREMENTAL
    assert calls[0]["write_mode"] == "write"
    assert calls[0]["target_sources"] == ["slack"]
    assert calls[0]["lookback_hours"] == 24


def test_pipeline_token_rejects_missing_or_wrong_header(monkeypatch):
    calls = []

    class FakeRunner:
        def run(self, **kwargs):
            calls.append(kwargs)

            class Result:
                def model_dump(self):
                    return {"summary": {"ok": True}}

            return Result()

    monkeypatch.setenv("PIPELINE_WEBHOOK_TOKEN", "secret-token")
    get_settings.cache_clear()
    monkeypatch.setattr("kb_pipeline.main.PipelineRunner", lambda: FakeRunner())
    client = TestClient(app)

    missing = client.post("/runs/scheduled", json={"target_sources": ["event"]})
    wrong = client.post(
        "/runs/scheduled",
        json={"target_sources": ["event"]},
        headers={"X-Pipeline-Token": "wrong-token"},
    )
    correct = client.post(
        "/runs/scheduled",
        json={"target_sources": ["event"]},
        headers={"X-Pipeline-Token": "secret-token"},
    )

    assert missing.status_code == 401
    assert wrong.status_code == 401
    assert correct.status_code == 200
    assert len(calls) == 1


def test_slack_webhook_url_verification_returns_challenge():
    client = TestClient(app)

    response = client.post(
        "/webhooks/slack",
        json={"type": "url_verification", "challenge": "challenge-token"},
    )

    assert response.status_code == 200
    assert response.json() == {"challenge": "challenge-token"}


def test_slack_webhook_uses_event_trigger_scope(monkeypatch):
    calls = []

    class FakeRunner:
        def run(self, **kwargs):
            calls.append(kwargs)

            class Result:
                def model_dump(self):
                    return {"summary": {"ok": True}}

            return Result()

    monkeypatch.setattr("kb_pipeline.main.PipelineRunner", lambda: FakeRunner())
    client = TestClient(app)

    response = client.post(
        "/webhooks/slack",
        json={
            "type": "event_callback",
            "event_id": "Ev123",
            "event": {
                "type": "message",
                "channel": "C01J93WPXN3",
                "ts": "1778136170.724039",
                "thread_ts": "1778136170.724039",
                "text": "업데이트",
            },
        },
    )

    assert response.status_code == 200
    assert response.json()["ok"] is True
    assert calls[0]["trigger_type"] == TriggerType.SLACK_EVENT
    assert calls[0]["target_sources"] == ["slack"]
    assert calls[0]["scope"].channel_id == "C01J93WPXN3"
    assert calls[0]["scope"].thread_ts == "1778136170.724039"
