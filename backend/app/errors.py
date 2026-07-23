"""User-safe application errors and FastAPI exception handlers."""

from __future__ import annotations

import logging
import secrets
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ErrorSpec:
    """Stable public representation of an error type."""

    status_code: int
    message: str
    action: str
    retryable: bool


ERROR_SPECS: dict[str, ErrorSpec] = {
    "AUTH_INVALID_CREDENTIALS": ErrorSpec(401, "로그인 정보를 확인할 수 없습니다.", "계정과 비밀번호를 확인해주세요.", True),
    "AUTH_SESSION_EXPIRED": ErrorSpec(401, "로그인 시간이 만료되었습니다.", "다시 로그인해주세요.", True),
    "AUTH_ACCESS_DENIED": ErrorSpec(403, "이 작업을 수행할 수 없습니다.", "로그인 상태를 확인한 뒤 다시 시도해주세요.", False),
    "REQUEST_INVALID": ErrorSpec(400, "요청 내용을 처리할 수 없습니다.", "입력값을 확인해주세요.", False),
    "RESOURCE_NOT_FOUND": ErrorSpec(404, "요청한 항목을 찾을 수 없습니다.", "목록을 새로고침하고 대상을 다시 선택해주세요.", False),
    "RESOURCE_STATE_CONFLICT": ErrorSpec(409, "현재 상태에서는 이 작업을 수행할 수 없습니다.", "최신 상태를 확인한 뒤 다시 시도해주세요.", True),
    "INPUT_FILE_REQUIRED": ErrorSpec(400, "필요한 파일이 선택되지 않았습니다.", "이미지 또는 EO 파일을 선택해주세요.", False),
    "FILE_NOT_FOUND": ErrorSpec(404, "선택한 파일을 찾을 수 없습니다.", "파일 위치와 마운트 상태를 확인해주세요.", False),
    "FILE_READ_FAILED": ErrorSpec(422, "파일을 읽을 수 없습니다.", "파일 접근 권한과 손상 여부를 확인해주세요.", False),
    "FILE_FORMAT_UNSUPPORTED": ErrorSpec(415, "지원하지 않는 파일 형식입니다.", "지원 형식으로 변환하거나 다른 파일을 선택해주세요.", False),
    "EO_PARSE_FAILED": ErrorSpec(422, "EO 파일 내용을 읽을 수 없습니다.", "파일 형식과 구분자, 필수 열을 확인해주세요.", False),
    "EO_IMAGE_MISMATCH": ErrorSpec(422, "이미지와 EO 항목이 일치하지 않습니다.", "파일명 매칭과 제외 항목을 확인해주세요.", False),
    "CRS_INVALID": ErrorSpec(422, "좌표계를 확인할 수 없습니다.", "입력 좌표계를 직접 선택하고 좌표 범위를 확인해주세요.", False),
    "CAMERA_MODEL_INVALID": ErrorSpec(422, "카메라 모델 값이 올바르지 않습니다.", "초점거리, 센서 크기, 픽셀 크기를 확인해주세요.", False),
    "CAMERA_IO_PARSE_FAILED": ErrorSpec(422, "카메라 IO 설정을 읽을 수 없습니다.", "변경 내용을 확인하고 원본으로 복원한 뒤 다시 시도해주세요.", False),
    "CAMERA_IO_SAVE_FAILED": ErrorSpec(500, "카메라 IO 설정을 저장하지 못했습니다.", "디스크 상태를 확인한 뒤 다시 시도해주세요.", True),
    "CAMERA_IO_SYNC_FAILED": ErrorSpec(500, "카메라 IO 설정과 DB를 동기화하지 못했습니다.", "자동 복원 결과를 확인하고 다시 시도해주세요.", True),
    "PROCESSING_ALREADY_ACTIVE": ErrorSpec(409, "이미 대기 또는 처리 중인 작업이 있습니다.", "현재 작업을 확인하거나 취소한 뒤 다시 시도해주세요.", False),
    "PROCESSING_ENQUEUE_FAILED": ErrorSpec(503, "처리 작업을 대기열에 등록하지 못했습니다.", "잠시 후 다시 시도해주세요.", True),
    "PROCESSING_STEP_FAILED": ErrorSpec(500, "처리 단계가 완료되지 않았습니다.", "입력 데이터와 오류 참조번호를 확인한 뒤 다시 처리해주세요.", False),
    "PROCESSING_CHECKPOINT_FAILED": ErrorSpec(500, "처리 복구 정보를 저장하거나 불러오지 못했습니다.", "저장 공간을 확인한 뒤 처음부터 다시 처리해주세요.", False),
    "PROCESSING_INTERRUPTED": ErrorSpec(503, "시스템 재시작 또는 연결 중단으로 처리가 멈췄습니다.", "워커 상태를 확인한 뒤 다시 처리해주세요.", True),
    "PROCESSING_CANCEL_FAILED": ErrorSpec(503, "처리 취소 상태를 저장하지 못했습니다.", "상태를 새로고침한 뒤 다시 취소해주세요.", True),
    "GPU_DEVICE_UNAVAILABLE": ErrorSpec(503, "GPU 처리 장치를 사용할 수 없습니다.", "GPU 워커와 장치 연결 상태를 확인해주세요.", True),
    "GPU_DRIVER_UNAVAILABLE": ErrorSpec(503, "GPU 드라이버를 사용할 수 없습니다.", "호스트 드라이버와 컨테이너 연결을 확인해주세요.", True),
    "GPU_RUNTIME_INTERRUPTED": ErrorSpec(503, "처리 중 GPU 연결이 끊겼습니다.", "GPU 워커를 복구한 뒤 다시 처리해주세요.", True),
    "GPU_MEMORY_EXHAUSTED": ErrorSpec(507, "GPU 메모리가 부족해 처리를 계속할 수 없습니다.", "다른 작업을 종료하거나 처리 설정을 조정해주세요.", False),
    "STORAGE_READ_FAILED": ErrorSpec(500, "저장된 데이터를 읽지 못했습니다.", "저장 장치와 마운트 상태를 확인해주세요.", True),
    "STORAGE_WRITE_FAILED": ErrorSpec(500, "결과를 저장하지 못했습니다.", "저장 장치와 쓰기 권한을 확인해주세요.", True),
    "STORAGE_CAPACITY_EXCEEDED": ErrorSpec(507, "저장 공간이 부족합니다.", "불필요한 데이터를 정리하고 다시 시도해주세요.", False),
    "DATABASE_UNAVAILABLE": ErrorSpec(503, "프로젝트 정보를 불러오거나 저장하지 못했습니다.", "잠시 후 다시 시도하고 반복되면 오류 참조번호를 전달해주세요.", True),
    "DATABASE_CONFLICT": ErrorSpec(409, "동시에 변경된 정보와 충돌했습니다.", "화면을 새로고침한 뒤 다시 시도해주세요.", True),
    "QUEUE_UNAVAILABLE": ErrorSpec(503, "작업 대기열에 연결할 수 없습니다.", "워커와 대기열 상태를 확인한 뒤 다시 시도해주세요.", True),
    "EXPORT_SOURCE_NOT_FOUND": ErrorSpec(404, "내보낼 정사영상을 찾을 수 없습니다.", "프로젝트 처리 완료 여부를 확인해주세요.", False),
    "EXPORT_SOURCE_INVALID": ErrorSpec(422, "내보낼 정사영상이 올바른 COG가 아닙니다.", "정사영상을 다시 생성하거나 COG 상태를 확인해주세요.", False),
    "EXPORT_FORMAT_INVALID": ErrorSpec(422, "선택한 내보내기 설정을 사용할 수 없습니다.", "형식, 좌표계, 해상도를 확인해주세요.", False),
    "EXPORT_CONVERSION_FAILED": ErrorSpec(500, "내보내기 파일을 만들지 못했습니다.", "설정을 확인하고 다시 시도해주세요.", True),
    "EXPORT_ARCHIVE_FAILED": ErrorSpec(500, "다운로드 묶음을 만들지 못했습니다.", "잠시 후 다시 시도해주세요.", True),
    "CLIP_SELECTION_REQUIRED": ErrorSpec(400, "클립에 사용할 도엽이 선택되지 않았습니다.", "지도에서 하나 이상의 도엽을 선택해주세요.", False),
    "CLIP_OUTSIDE_COVERAGE": ErrorSpec(422, "선택 영역과 정사영상이 겹치지 않습니다.", "다른 도엽을 선택하거나 정사영상 범위를 확인해주세요.", False),
    "CLIP_PROCESSING_FAILED": ErrorSpec(500, "선택 영역으로 정사영상을 자르지 못했습니다.", "선택과 내보내기 설정을 확인한 뒤 다시 시도해주세요.", True),
    "NETWORK_OFFLINE": ErrorSpec(503, "네트워크에 연결되어 있지 않습니다.", "연결 상태를 확인해주세요.", True),
    "NETWORK_TIMEOUT": ErrorSpec(504, "요청 시간이 초과되었습니다.", "진행 상태를 먼저 확인한 뒤 다시 시도해주세요.", True),
    "SERVER_UNAVAILABLE": ErrorSpec(503, "서버에 연결할 수 없습니다.", "잠시 후 새로고침해주세요.", True),
    "INTERNAL_ERROR": ErrorSpec(500, "시스템 내부 오류가 발생했습니다.", "오류 참조번호를 운영 담당자에게 전달해주세요.", False),
}

LEGACY_PUBLIC_CONTEXT_FIELDS = {
    "type",
    "confirm_message",
    "engine",
    "supported_engines",
    "can_force_restart",
    "job_id",
    "job_status",
    "project_status",
    "progress",
    "can_resume",
    "completed_steps",
    "failed_step",
    "next_step",
    "status",
    "eo_count",
    "metadata_count",
    "filenames",
}

LEGACY_TYPE_CODES = {
    "eo_required": "INPUT_FILE_REQUIRED",
    "eo_metadata_missing": "FILE_NOT_FOUND",
    "eo_metadata_empty": "EO_PARSE_FAILED",
    "eo_metadata_stale": "EO_IMAGE_MISMATCH",
    "eo_reference_missing": "FILE_NOT_FOUND",
    "eo_reference_unmatched": "EO_IMAGE_MISMATCH",
    "eo_reference_crs_missing": "CRS_INVALID",
    "eo_crs_transform_failed": "CRS_INVALID",
    "eo_crs_transform_invalid": "CRS_INVALID",
    "unsupported_crs_correction": "CRS_INVALID",
    "unsupported_engine": "REQUEST_INVALID",
    "incomplete_uploads": "INPUT_FILE_REQUIRED",
    "job_already_running": "PROCESSING_ALREADY_ACTIVE",
    "restart_choice_required": "RESOURCE_STATE_CONFLICT",
    "completed_job_restart_requires_explicit_action": "RESOURCE_STATE_CONFLICT",
    "crs_correction_unavailable": "RESOURCE_STATE_CONFLICT",
    "crs_correction_locked": "RESOURCE_STATE_CONFLICT",
    "deprecated_endpoint": "REQUEST_INVALID",
}


class AppError(Exception):
    """An explicitly classified error with an internal-only cause."""

    def __init__(
        self,
        code: str,
        *,
        internal_detail: Any | None = None,
        context: dict[str, Any] | None = None,
    ) -> None:
        self.code = code if code in ERROR_SPECS else "INTERNAL_ERROR"
        self.internal_detail = internal_detail
        self.context = context or {}
        super().__init__(self.code)


def new_error_reference_id(now: datetime | None = None) -> str:
    """Create a log-searchable reference without exposing sequential IDs."""

    timestamp = now or datetime.now(timezone.utc)
    return f"ERR-{timestamp:%Y%m%d}-{secrets.token_hex(6).upper()}"


def public_error_payload(code: str, reference_id: str | None = None) -> dict[str, Any]:
    """Return the only error fields allowed on user-facing surfaces."""

    safe_code = code if code in ERROR_SPECS else "INTERNAL_ERROR"
    spec = ERROR_SPECS[safe_code]
    return {
        "error": {
            "code": safe_code,
            "message": spec.message,
            "action": spec.action,
            "reference_id": reference_id or new_error_reference_id(),
            "retryable": spec.retryable,
        }
    }


def classify_legacy_http_error(status_code: int, path: str = "") -> str:
    """Safely classify old string-based HTTPException responses during migration."""

    if status_code == 401:
        return "AUTH_INVALID_CREDENTIALS" if path.rstrip("/").endswith("/auth/login") else "AUTH_SESSION_EXPIRED"
    if status_code == 403:
        return "AUTH_ACCESS_DENIED"
    if status_code == 404:
        return "RESOURCE_NOT_FOUND"
    if status_code == 409:
        return "RESOURCE_STATE_CONFLICT"
    if status_code == 503:
        return "SERVER_UNAVAILABLE"
    if status_code == 504:
        return "NETWORK_TIMEOUT"
    if status_code >= 500:
        return "INTERNAL_ERROR"
    return "REQUEST_INVALID"


def safe_legacy_error_context(detail: Any) -> dict[str, Any]:
    """Keep only transition metadata required by existing UI control flows."""

    if not isinstance(detail, dict):
        return {}
    return {
        key: value
        for key, value in detail.items()
        if key in LEGACY_PUBLIC_CONTEXT_FIELDS
    }


def classify_legacy_error_detail(detail: Any, status_code: int, path: str = "") -> str:
    """Map known structured legacy responses without trusting their messages."""

    if isinstance(detail, dict):
        detail_code = detail.get("code")
        if detail_code in ERROR_SPECS:
            return detail_code
        detail_type = detail.get("type")
        if detail_type in LEGACY_TYPE_CODES:
            return LEGACY_TYPE_CODES[detail_type]
        if detail_code == "MIXED_EO_CRS":
            return "CRS_INVALID"
    return classify_legacy_http_error(status_code, path)


def classify_processing_error(error: BaseException | str) -> str:
    """Classify worker failures without exposing their original text."""

    text = str(error).lower()
    if "gpu_runtime_lost" in text or "gpu runtime" in text and "lost" in text:
        return "GPU_RUNTIME_INTERRUPTED"
    if ("cuda" in text or "gpu" in text) and "out of memory" in text:
        return "GPU_MEMORY_EXHAUSTED"
    if ("nvidia" in text or "gpu" in text) and "driver" in text:
        return "GPU_DRIVER_UNAVAILABLE"
    if "no cuda-capable device" in text or "gpu device" in text and "unavailable" in text:
        return "GPU_DEVICE_UNAVAILABLE"
    if "checkpoint" in text:
        return "PROCESSING_CHECKPOINT_FAILED"
    if "no space left" in text or "disk full" in text:
        return "STORAGE_CAPACITY_EXCEEDED"
    if "permission denied" in text:
        return "STORAGE_WRITE_FAILED"
    if "no such file" in text or "file not found" in text:
        return "FILE_NOT_FOUND"
    return "PROCESSING_STEP_FAILED"


def _response(
    code: str,
    reference_id: str,
    *,
    status_code: int | None = None,
    headers: dict[str, str] | None = None,
    context: dict[str, Any] | None = None,
) -> JSONResponse:
    spec = ERROR_SPECS[code]
    response_headers = dict(headers or {})
    response_headers["X-Error-Reference"] = reference_id
    content = public_error_payload(code, reference_id)
    if context:
        content["context"] = context
    return JSONResponse(
        status_code=status_code or spec.status_code,
        content=content,
        headers=response_headers,
    )


async def app_error_handler(request: Request, exc: AppError) -> JSONResponse:
    reference_id = new_error_reference_id()
    spec = ERROR_SPECS[exc.code]
    logger.log(
        logging.ERROR if spec.status_code >= 500 else logging.WARNING,
        "application_error reference_id=%s code=%s method=%s path=%s context=%r detail=%r",
        reference_id,
        exc.code,
        request.method,
        request.url.path,
        exc.context,
        exc.internal_detail,
        exc_info=exc.__cause__ is not None,
    )
    return _response(exc.code, reference_id)


async def validation_error_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
    reference_id = new_error_reference_id()
    logger.warning(
        "request_validation_error reference_id=%s method=%s path=%s errors=%r",
        reference_id,
        request.method,
        request.url.path,
        exc.errors(),
    )
    return _response("REQUEST_INVALID", reference_id, status_code=422)


async def http_error_handler(request: Request, exc: StarletteHTTPException) -> JSONResponse:
    code = classify_legacy_error_detail(exc.detail, exc.status_code, request.url.path)
    context = safe_legacy_error_context(exc.detail)
    reference_id = new_error_reference_id()
    logger.log(
        logging.ERROR if exc.status_code >= 500 else logging.WARNING,
        "legacy_http_error reference_id=%s code=%s original_status=%s method=%s path=%s detail=%r",
        reference_id,
        code,
        exc.status_code,
        request.method,
        request.url.path,
        exc.detail,
    )
    return _response(
        code,
        reference_id,
        status_code=exc.status_code,
        headers=exc.headers,
        context=context,
    )


async def unhandled_error_handler(request: Request, exc: Exception) -> JSONResponse:
    reference_id = new_error_reference_id()
    logger.exception(
        "unhandled_error reference_id=%s code=INTERNAL_ERROR method=%s path=%s",
        reference_id,
        request.method,
        request.url.path,
    )
    return _response("INTERNAL_ERROR", reference_id)


def install_error_handlers(app: FastAPI) -> None:
    """Install the standard exception-to-public-error boundary."""

    app.add_exception_handler(AppError, app_error_handler)
    app.add_exception_handler(RequestValidationError, validation_error_handler)
    app.add_exception_handler(StarletteHTTPException, http_error_handler)
    app.add_exception_handler(Exception, unhandled_error_handler)
