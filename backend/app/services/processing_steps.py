"""Canonical processing-step metadata shared across API and worker code."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class ProcessingStep:
    script_name: str
    task_name: str
    label: str
    progress_message: str
    project_state_rank: int | None = None
    optional: bool = False


PROCESSING_STEPS = (
    ProcessingStep(
        script_name="align_photos.py",
        task_name="Align Photos",
        label="이미지 정렬",
        progress_message="이미지 정렬 중...",
        project_state_rank=1,
    ),
    ProcessingStep(
        script_name="build_depth_maps.py",
        task_name="Build Depth Maps",
        label="깊이 맵 생성",
        progress_message="깊이 맵 생성 중...",
        project_state_rank=2,
    ),
    ProcessingStep(
        script_name="build_point_cloud.py",
        task_name="Build Point Cloud",
        label="포인트 클라우드 생성",
        progress_message="포인트 클라우드 생성 중...",
        project_state_rank=3,
        optional=True,
    ),
    ProcessingStep(
        script_name="build_dem.py",
        task_name="Build DEM",
        label="수치표고모델 생성",
        progress_message="수치표고모델 생성 중...",
        project_state_rank=4,
    ),
    ProcessingStep(
        script_name="build_orthomosaic.py",
        task_name="Build Orthomosaic",
        label="정사모자이크 생성",
        progress_message="정사모자이크 생성 중...",
        project_state_rank=5,
    ),
    ProcessingStep(
        script_name="export_orthomosaic.py",
        task_name="Export Raster",
        label="정사영상 내보내기",
        progress_message="정사영상 내보내기 중...",
    ),
    ProcessingStep(
        script_name="convert_cog.py",
        task_name="Convert COG",
        label="COG 변환",
        progress_message="COG 변환 중...",
    ),
)

PROCESSING_STEP_BY_SCRIPT = {step.script_name: step for step in PROCESSING_STEPS}
CHECKPOINT_STEP_LABELS = {step.script_name: step.label for step in PROCESSING_STEPS}
PROJECT_STATE_STEP_RANK = {
    step.script_name: step.project_state_rank
    for step in PROCESSING_STEPS
    if step.project_state_rank is not None
}
PROJECT_STATE_STEPS = frozenset(PROJECT_STATE_STEP_RANK)
STEP_MESSAGE_MAP = {step.task_name: step.progress_message for step in PROCESSING_STEPS}
STEP_ORDER = tuple(step.task_name for step in PROCESSING_STEPS)


def task_name_for_script(script_name: str) -> str:
    step = PROCESSING_STEP_BY_SCRIPT.get(script_name)
    return step.task_name if step else script_name


def processing_step_pairs(*, build_point_cloud: bool) -> list[tuple[str, str]]:
    return [
        (step.script_name, step.progress_message)
        for step in PROCESSING_STEPS
        if not step.optional or build_point_cloud
    ]
