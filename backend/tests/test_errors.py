import asyncio
import json
import re
from datetime import datetime, timezone

from app.errors import (
    AppError,
    classify_legacy_error_detail,
    classify_legacy_http_error,
    new_error_reference_id,
    public_error_payload,
    safe_legacy_error_context,
    http_error_handler,
)
from starlette.exceptions import HTTPException
from starlette.requests import Request


def test_reference_id_has_stable_searchable_format():
    reference_id = new_error_reference_id(datetime(2026, 7, 22, tzinfo=timezone.utc))

    assert re.fullmatch(r"ERR-20260722-[0-9A-F]{12}", reference_id)


def test_public_payload_contains_only_approved_fields():
    payload = public_error_payload("EO_PARSE_FAILED", "ERR-20260722-A1B2C3D4E5F6")

    assert payload == {
        "error": {
            "code": "EO_PARSE_FAILED",
            "message": "EO 파일 내용을 읽을 수 없습니다.",
            "action": "파일 형식과 구분자, 필수 열을 확인해주세요.",
            "reference_id": "ERR-20260722-A1B2C3D4E5F6",
            "retryable": False,
        }
    }
    assert "detail" not in payload["error"]


def test_unknown_code_falls_back_to_internal_error():
    exc = AppError("UNKNOWN_CODE", internal_detail="/private/path")
    payload = public_error_payload(exc.code, "ERR-20260722-000000000000")

    assert exc.code == "INTERNAL_ERROR"
    assert payload["error"]["code"] == "INTERNAL_ERROR"
    assert "/private/path" not in str(payload)


def test_legacy_http_errors_are_classified_without_using_detail_text():
    assert classify_legacy_http_error(401, "/api/v1/auth/login") == "AUTH_INVALID_CREDENTIALS"
    assert classify_legacy_http_error(401, "/api/v1/projects") == "AUTH_SESSION_EXPIRED"
    assert classify_legacy_http_error(403) == "AUTH_ACCESS_DENIED"
    assert classify_legacy_http_error(404) == "RESOURCE_NOT_FOUND"
    assert classify_legacy_http_error(409) == "RESOURCE_STATE_CONFLICT"
    assert classify_legacy_http_error(500) == "INTERNAL_ERROR"


def test_legacy_control_flow_keeps_safe_context_but_removes_paths():
    detail = {
        "type": "restart_choice_required",
        "message": "legacy message",
        "job_id": "job-1",
        "can_resume": True,
        "metadata_path": "/private/project/metadata.txt",
        "result_path": "/private/project/result.tif",
    }

    assert classify_legacy_error_detail(detail, 409) == "RESOURCE_STATE_CONFLICT"
    assert safe_legacy_error_context(detail) == {
        "type": "restart_choice_required",
        "job_id": "job-1",
        "can_resume": True,
    }


def test_http_handler_hides_raw_detail_and_returns_reference_header():
    request = Request(
        {
            "type": "http",
            "method": "POST",
            "path": "/api/v1/processing/projects/project-1/start",
            "headers": [],
            "query_string": b"",
            "server": ("testserver", 80),
            "client": ("testclient", 123),
            "scheme": "http",
        }
    )
    exception = HTTPException(
        409,
        detail={
            "type": "restart_choice_required",
            "job_id": "job-1",
            "can_resume": True,
            "metadata_path": "/private/project/metadata.txt",
        },
    )

    response = asyncio.run(http_error_handler(request, exception))
    payload = json.loads(response.body)

    assert response.status_code == 409
    assert re.fullmatch(r"ERR-\d{8}-[0-9A-F]{12}", response.headers["X-Error-Reference"])
    assert payload["error"]["code"] == "RESOURCE_STATE_CONFLICT"
    assert payload["context"] == {
        "type": "restart_choice_required",
        "job_id": "job-1",
        "can_resume": True,
    }
    assert "/private/project/metadata.txt" not in response.body.decode()
