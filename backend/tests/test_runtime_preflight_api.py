from __future__ import annotations

from datetime import UTC, datetime

from fastapi.testclient import TestClient

from app.api.routes.runtime import get_runtime_diagnostics_service
from app.schemas.runtime import RuntimePreflightError, RuntimePreflightResponse
from app.main import create_app

UNSAFE_TOKENS = (
    "/Users/",
    "/tmp/",
    "/private/tmp/",
    "/var/folders/",
    "Traceback",
    "stdout",
    "stderr",
    "raw command",
    "command_template",
)


class FakeRuntimeDiagnosticsService:
    def __init__(self, response: RuntimePreflightResponse) -> None:
        self.response = response

    def get_preflight(self) -> RuntimePreflightResponse:
        return self.response


def test_runtime_preflight_api_returns_200_and_contract() -> None:
    app = create_app()
    response_model = RuntimePreflightResponse(
        status="degraded",
        generic_baseline_ready=False,
        demo_mock_ready=True,
        mock_ai_ready=True,
        true_ai_ready=False,
        missing_requirements=["Demucs package/command probe is not ready"],
        checks={
            "ai_python": {"available": True, "executable": "python"},
            "ffmpeg": {"ready": True},
        },
        offline_evaluation={"adtof": {"enabled": False, "reason": "offline_evaluation_only"}},
        smoke_commands={"runtime_check": "PYTHONPATH=. <ai_python> scripts/check_ai_runtime.py"},
        checked_at=datetime(2026, 7, 2, tzinfo=UTC),
    )
    app.dependency_overrides[get_runtime_diagnostics_service] = lambda: FakeRuntimeDiagnosticsService(response_model)

    response = TestClient(app).get("/api/v1/runtime/preflight")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "degraded"
    assert body["generic_baseline_ready"] is False
    assert body["demo_mock_ready"] is True
    assert body["missing_requirements"] == ["Demucs package/command probe is not ready"]
    assert body["offline_evaluation"]["adtof"] == {"enabled": False, "reason": "offline_evaluation_only"}
    assert body["mock_ai_ready"] is True
    assert body["true_ai_ready"] is False
    assert "checks" in body
    assert "smoke_commands" in body
    assert body["error"] is None


def test_runtime_preflight_api_error_response_does_not_expose_sensitive_details() -> None:
    app = create_app()
    response_model = RuntimePreflightResponse(
        status="error",
        generic_baseline_ready=False,
        demo_mock_ready=False,
        missing_requirements=[],
        checks={"ai_python": {"available": False, "executable": "python"}},
        smoke_commands={},
        checked_at=datetime(2026, 7, 2, tzinfo=UTC),
        error=RuntimePreflightError(
            code="RUNTIME_PREFLIGHT_FAILED",
            message="Runtime preflight command failed.",
        ),
    )
    app.dependency_overrides[get_runtime_diagnostics_service] = lambda: FakeRuntimeDiagnosticsService(response_model)

    response = TestClient(app).get("/api/v1/runtime/preflight")
    encoded = response.text

    assert response.status_code == 200
    assert response.json()["status"] == "error"
    for unsafe in UNSAFE_TOKENS:
        assert unsafe.lower() not in encoded.lower()
