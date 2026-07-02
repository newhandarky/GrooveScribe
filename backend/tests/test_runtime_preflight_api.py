from __future__ import annotations

from datetime import UTC, datetime

from fastapi.testclient import TestClient

from app.api.routes.runtime import get_runtime_diagnostics_service
from app.schemas.runtime import RuntimePreflightError, RuntimePreflightResponse
from app.main import create_app


class FakeRuntimeDiagnosticsService:
    def __init__(self, response: RuntimePreflightResponse) -> None:
        self.response = response

    def get_preflight(self) -> RuntimePreflightResponse:
        return self.response


def test_runtime_preflight_api_returns_200_and_contract() -> None:
    app = create_app()
    response_model = RuntimePreflightResponse(
        status="degraded",
        mock_ai_ready=True,
        true_ai_ready=False,
        missing_requirements=["ADTOF runtime is not verified"],
        checks={
            "ai_python": {"available": True, "executable": "python"},
            "ffmpeg": {"ready": True},
        },
        smoke_commands={"runtime_check": "PYTHONPATH=. <ai_python> scripts/check_ai_runtime.py"},
        checked_at=datetime(2026, 7, 2, tzinfo=UTC),
    )
    app.dependency_overrides[get_runtime_diagnostics_service] = lambda: FakeRuntimeDiagnosticsService(response_model)

    response = TestClient(app).get("/api/v1/runtime/preflight")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "degraded"
    assert body["mock_ai_ready"] is True
    assert body["true_ai_ready"] is False
    assert body["missing_requirements"] == ["ADTOF runtime is not verified"]
    assert "checks" in body
    assert "smoke_commands" in body
    assert body["error"] is None


def test_runtime_preflight_api_error_response_does_not_expose_sensitive_details() -> None:
    app = create_app()
    response_model = RuntimePreflightResponse(
        status="error",
        mock_ai_ready=False,
        true_ai_ready=False,
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
    assert "Traceback" not in encoded
    assert "/Users/" not in encoded
