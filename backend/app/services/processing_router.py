"""Processing engine router and implementations."""
import os
import subprocess
import asyncio
import re
import logging
import time
from abc import ABC
from pathlib import Path
from typing import Optional, List, Callable, Awaitable
from datetime import datetime

import httpx

from datetime import timedelta

from app.config import get_settings
from app.auth.jwt import create_internal_token

settings = get_settings()
logger = logging.getLogger("app.processing.router")


class ProcessingEngine(ABC):
    """Abstract base class for processing engines."""
    
    async def process(
        self,
        project_id: str,
        input_dir: Path,
        output_dir: Path,
        options: dict,
        progress_callback=None,
    ) -> Path:
        """
        Run the processing pipeline.
        """
        pass
    
    async def get_status(self, job_id: str) -> dict:
        """Get the status of a processing job."""
        pass
    
    async def cancel(self, job_id: str) -> bool:
        """Cancel a processing job."""
        pass


class ODMEngine(ProcessingEngine):
    """OpenDroneMap processing engine."""

    # Deprecated in current policy (4차 스프린트 기준 비활성)
    # Kept for emergency re-enable path with configuration work if needed.
    
    def __init__(self):
        self.docker_image = settings.ODM_DOCKER_IMAGE
    
    async def process(
        self,
        project_id: str,
        input_dir: Path,
        output_dir: Path,
        options: dict,
        progress_callback=None,
    ) -> Path:
        """Run ODM processing via Docker."""
        
        gsd = options.get("gsd", 5.0)  # cm/pixel
        
        # ODM expects images in a specific structure
        # input_dir should contain the images
        # output_dir is where results will be written
        
        # For Docker-in-Docker, we need to use HOST paths, not container paths
        # The HOST_DATA_PATH env var contains the host's data folder path
        import os
        host_data_path = os.environ.get('HOST_DATA_PATH', '/data/processing')
        
        # Convert container paths to host paths
        project_id_str = str(input_dir).split('/')[-2]  # Extract project ID from path
        host_project_dir = f"{host_data_path}/{project_id_str}"
        
        cmd = [
            "docker", "run", "--rm",
            # Mount entire project folder - ODM creates all output subdirectories here
            "-v", f"{host_project_dir}:/datasets/project",
            self.docker_image,
            "--project-path", "/datasets",
            "project",
            "--orthophoto-resolution", str(gsd / 100),  # ODM uses meters
            "--dsm",
            "--dtm",
            "--skip-3dmodel",  # Skip 3D model to speed up
            "--skip-report",  # Skip report generation to avoid GDAL gdal_array error
            "--force-gps",
            "--auto-boundary",
        ]
        
        # Log the command for debugging
        import logging
        logging.info(f"[ODM] Running command: {' '.join(cmd)}")
        
        # Run ODM process
        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,  # Merge stderr into stdout
        )
        
        # Stage-based base progress mapping
        STAGE_PROGRESS = {
            "dataset": 5,
            "opensfm": 20,
            "openmvs": 40,
            "mvs": 40,
            "filterpoints": 50,
            "meshing": 60,
            "dem": 70,
            "orthophoto": 80,
            "postprocess": 95,
        }
        
        # Collect all output and monitor progress
        all_output = []
        current_progress = 0
        last_progress = 0
        
        async for line in process.stdout:
            line_str = line.decode().strip()
            all_output.append(line_str)
            logging.info(f"[ODM] {line_str}")
            
            # 1. Look for explicit percentage in line (e.g., "[Stage] 45%")
            pct_match = re.search(r'(\d+)%', line_str)
            
            # 2. Determine stage base progress
            line_lower = line_str.lower()
            stage_base = 0
            current_stage = ""
            for stage, base in STAGE_PROGRESS.items():
                if stage in line_lower:
                    stage_base = base
                    current_stage = stage
                    break
            
            if pct_match:
                # Calculate progress within the stage or overall
                # ODM percentages are often relative to the current stage
                # But we'll try to map it to our 0-100 scale
                stage_pct = int(pct_match.group(1))
                
                if current_stage == "dataset":
                    current_progress = 0 + (stage_pct * 0.05)
                elif current_stage in ["opensfm", "openmvs", "mvs"]:
                    current_progress = 20 + (stage_pct * 0.20)
                elif current_stage == "filterpoints":
                    current_progress = 40 + (stage_pct * 0.10)
                elif current_stage == "meshing":
                    current_progress = 50 + (stage_pct * 0.10)
                elif current_stage == "dem":
                    current_progress = 60 + (stage_pct * 0.10)
                elif current_stage == "orthophoto":
                    current_progress = 70 + (stage_pct * 0.15)
                elif current_stage == "postprocess":
                    current_progress = 85 + (stage_pct * 0.10)
                else:
                    # If we can't determine current stage accurately, 
                    # use the percentage if it's higher than current
                    if stage_pct > current_progress:
                        current_progress = stage_pct
            elif "running" in line_lower and stage_base > current_progress:
                # Update based on stage keywords if no percentage found
                current_progress = stage_base
            
            # Ensure progress is capped and integer
            final_progress = min(99, int(current_progress))
            if final_progress < last_progress:
                final_progress = last_progress

            if progress_callback and final_progress > 0 and final_progress != last_progress:
                await progress_callback(final_progress, line_str)
            last_progress = final_progress
        
        await process.wait()
        
        if process.returncode != 0:
            # Get last 50 lines of output for error message
            error_output = "\n".join(all_output[-50:]) if all_output else f"Exit code: {process.returncode}"
            raise RuntimeError(f"ODM processing failed: {error_output}")
        
        # Find the output orthophoto - ODM saves it in project root, not output folder
        # input_dir is /data/processing/{project_id}/images, so parent is project folder
        project_folder = input_dir.parent
        ortho_path = project_folder / "odm_orthophoto" / "odm_orthophoto.tif"
        if not ortho_path.exists():
            raise FileNotFoundError("ODM did not produce an orthophoto")
        
        return ortho_path
    
    async def get_status(self, job_id: str) -> dict:
        """Check Docker container status."""
        # For ODM, we track the process directly
        return {"status": "running"}
    
    async def cancel(self, job_id: str) -> bool:
        """Stop Docker container."""
        try:
            subprocess.run(
                ["docker", "stop", f"odm_{job_id}"],
                check=True,
                capture_output=True,
            )
            return True
        except subprocess.CalledProcessError:
            return False


class ExternalAPIEngine(ProcessingEngine):
    """External processing engine via REST API."""

    # Deprecated in current policy (4차 스프린트 기준 비활성)
    # Kept for emergency re-enable path with external engine integration.
    
    def __init__(self):
        self.base_url = settings.EXTERNAL_ENGINE_URL
        self.api_key = settings.EXTERNAL_ENGINE_API_KEY
        self._job_ids: dict[str, str] = {}  # Map project_id to external job_id
        import logging
        self.logger = logging.getLogger("app.processing.external")
    
    async def process(
        self,
        project_id: str,
        input_dir: Path,
        output_dir: Path,
        options: dict,
        progress_callback=None,
    ) -> Path:
        """Submit job to external API and poll for completion."""
        
        if not self.base_url:
            self.logger.error("External engine URL not configured")
            raise ValueError("External engine URL not configured. Please check EXTERNAL_ENGINE_URL in .env")
        
        # Determine internal callback URL for Webhook
        # Default to internal docker host if not specified
        callback_base = os.environ.get("WEBHOOK_URL_BASE", "http://api:8000")
        webhook_token = create_internal_token(
            "processing_webhook",
            subject="external-engine",
            expires_delta=timedelta(hours=1),
        )
        callback_url = f"{callback_base}/api/v1/processing/webhook?internal_token={webhook_token}"
        
        self.logger.info(f"Submitting job for project {project_id} to {self.base_url}")
        
        async with httpx.AsyncClient(timeout=300.0) as client:
            try:
                # 1. Submit the job
                payload = {
                    "project_id": project_id,
                    "input_path": str(input_dir),
                    "options": options,
                    "callback_url": callback_url
                }
                
                response = await client.post(
                    f"{self.base_url}/jobs",
                    json=payload,
                    headers={"Authorization": f"Bearer {self.api_key}"},
                )
                response.raise_for_status()
                job_data = response.json()
                external_job_id = job_data.get("job_id")
                
                if not external_job_id:
                    raise RuntimeError("External engine did not return a job_id")
                
                self._job_ids[project_id] = external_job_id
                self.logger.info(f"Job submitted successfully. External Job ID: {external_job_id}")
                
            except Exception as e:
                self.logger.error(f"Failed to submit job to external engine: {e}")
                raise RuntimeError(f"External API submission error: {str(e)}")

            # 2. Polling for completion (as fallback to Webhook)
            # Webhook will update the DB independently, but we keep this loop
            # to fulfill the awaitable interface of the processing task.
            retry_count = 0
            max_retries = 3
            
            while True:
                try:
                    status_response = await client.get(
                        f"{self.base_url}/jobs/{external_job_id}",
                        headers={"Authorization": f"Bearer {self.api_key}"},
                    )
                    status_response.raise_for_status()
                    status_data = status_response.json()
                    
                    status = status_data.get("status")
                    progress = status_data.get("progress", 0)
                    
                    if progress_callback:
                        await progress_callback(progress, f"External: {status}")
                    
                    self.logger.debug(f"Job {external_job_id} status: {status}, progress: {progress}%")
                    
                    if status == "completed":
                        result_url = status_data.get("result_url")
                        if not result_url:
                            raise RuntimeError("External job completed but no result_url provided")
                            
                        # 3. Download result
                        self.logger.info(f"Job {external_job_id} completed. Downloading result from {result_url}")
                        output_path = output_dir / f"{project_id}_ortho.tif"
                        
                        async with client.stream("GET", result_url) as download:
                            download.raise_for_status()
                            with open(output_path, "wb") as f:
                                async for chunk in download.aiter_bytes():
                                    f.write(chunk)
                        
                        self.logger.info(f"Result downloaded to {output_path}")
                        return output_path
                    
                    elif status == "failed":
                        error = status_data.get("error", "Unknown error")
                        self.logger.error(f"External job {external_job_id} failed: {error}")
                        raise RuntimeError(f"External processing failed: {error}")
                    
                    retry_count = 0 # Reset retries on success
                    
                except httpx.HTTPError as e:
                    retry_count += 1
                    self.logger.warning(f"Error polling external status (attempt {retry_count}): {e}")
                    if retry_count >= max_retries:
                        raise RuntimeError(f"Lost connection to external engine after {max_retries} attempts")
                
                # Wait before polling again
                await asyncio.sleep(10) # 10s is safer for external APIs
    
    async def get_status(self, job_id: str) -> dict:
        """Get status from external API."""
        external_id = self._job_ids.get(job_id)
        if not external_id:
            return {"status": "unknown"}
        
        async with httpx.AsyncClient() as client:
            try:
                response = await client.get(
                    f"{self.base_url}/jobs/{external_id}",
                    headers={"Authorization": f"Bearer {self.api_key}"},
                )
                return response.json()
            except Exception as e:
                self.logger.error(f"Failed to get status for {external_id}: {e}")
                return {"status": "error", "message": str(e)}
    
    async def cancel(self, job_id: str) -> bool:
        """Cancel job via external API."""
        external_id = self._job_ids.get(job_id)
        if not external_id:
            return False
        
        async with httpx.AsyncClient() as client:
            try:
                response = await client.post(
                    f"{self.base_url}/jobs/{external_id}/cancel",
                    headers={"Authorization": f"Bearer {self.api_key}"},
                )
                return response.status_code == 200
            except Exception as e:
                self.logger.error(f"Failed to cancel job {external_id}: {e}")
                return False


class MetashapeEngine(ProcessingEngine):
    """
    Engine using Agisoft Metashape Python SDK.
    Runs locally on worker-engine (aerial-worker-engine container).
    """

    @staticmethod
    def _format_elapsed(seconds):
        """초 단위 시간을 읽기 쉬운 형식으로 변환"""
        from app.utils.formatting import format_elapsed
        return format_elapsed(seconds)

    @staticmethod
    def _read_log_tail(log_path, lines=20):
        """로그 파일의 마지막 N줄을 읽어 반환"""
        try:
            with open(log_path, 'r') as f:
                all_lines = f.readlines()
                tail = all_lines[-lines:] if len(all_lines) > lines else all_lines
                return ''.join(tail)
        except Exception:
            return "(로그 파일 읽기 실패)"

    @staticmethod
    def _get_script_path(script_base: Path, script_name: str) -> Path:
        """
        스크립트 경로를 반환합니다. .pyc (바이트코드) 우선, .py 폴백.
        프로덕션 환경에서는 소스 코드 보호를 위해 .pyc만 존재합니다.
        """
        pyc_path = script_base / script_name.replace(".py", ".pyc")
        py_path = script_base / script_name

        if pyc_path.exists():
            return pyc_path
        elif py_path.exists():
            return py_path
        else:
            raise FileNotFoundError(f"Script not found: {script_name} (checked .pyc and .py)")

    async def process(
        self,
        project_id: str,
        input_dir: Path,
        output_dir: Path,
        options: dict,
        progress_callback: Optional[Callable[[float, str], Awaitable[None]]] = None,
    ) -> Path:
        import subprocess
        import sys
        import os
        import json
        import shutil

        if progress_callback:
            await progress_callback(0, "엔진 초기화 중...")

        # 1. 사이클 시작: 라이선스 활성화
        script_base = Path("/app/engines/metashape/dags/metashape")
        activate_script = self._get_script_path(script_base, "activate.py")
        deactivate_script = self._get_script_path(script_base, "deactivate.py")
        
        try:
            if activate_script.exists():
                logger.info("🔑 사이클 시작: Metashape 라이선스 활성화를 시도합니다.")
                act_result = subprocess.run([sys.executable, str(activate_script)], capture_output=True, text=True)
                if act_result.stdout:
                    logger.info(f"Activation stdout: {act_result.stdout.strip()}")
                if act_result.stderr:
                    logger.warning(f"Activation stderr: {act_result.stderr.strip()}")

            # 2. 본 작업 수행 (기존 로직)
            # 이전 실행에서 남은 Metashape 프로젝트가 있으면 읽기 전용 상태로 열릴 수 있으므로 정리
            project_psx = output_dir / "project.psx"
            project_files = output_dir / "project.files"
            if project_psx.exists():
                logger.info(f"Cleaning existing Metashape project: {project_psx}")
                project_psx.unlink()
            if project_files.exists():
                logger.info(f"Cleaning existing Metashape project folder: {project_files}")
                shutil.rmtree(project_files, ignore_errors=True)

            image_files = [str(f) for f in input_dir.glob("*") if f.suffix.lower() in [".jpg", ".jpeg", ".tif", ".tiff"]]
            if not image_files:
                raise RuntimeError("처리할 이미지가 없습니다.")
                
            # Point cloud 생성 여부 (기본값: False, advanced 옵션)
            build_point_cloud = options.get("build_point_cloud", False)
            eo_only_align = options.get("eo_only_align", True)
            if eo_only_align is None:
                eo_only_align = True
            elif isinstance(eo_only_align, str):
                eo_only_align = eo_only_align.strip().lower() not in {"0", "false", "no", "n", "off"}
            else:
                eo_only_align = bool(eo_only_align)

            steps = [
                ("align_photos.py", "이미지 정렬 중..."),
                ("build_depth_maps.py", "깊이 맵 생성 중..."),
            ]
            if build_point_cloud:
                steps.append(("build_point_cloud.py", "포인트 클라우드 생성 중..."))
            steps.extend([
                ("build_dem.py", "수치표고모델 생성 중..."),
                ("build_orthomosaic.py", "정사모자이크 생성 중..."),
                ("export_orthomosaic.py", "정사영상 내보내기 중..."),
                ("convert_cog.py", "COG 변환 중..."),
            ])

            logger.info(
                f"[Metashape] build_point_cloud={build_point_cloud}, "
                f"eo_only_align={eo_only_align}, total steps={len(steps)}"
            )

            # status.json 초기화 - 실행할 단계만 포함
            script_to_task_name = {
                "align_photos.py": "Align Photos",
                "build_depth_maps.py": "Build Depth Maps",
                "build_point_cloud.py": "Build Point Cloud",
                "build_dem.py": "Build DEM",
                "build_orthomosaic.py": "Build Orthomosaic",
                "export_orthomosaic.py": "Export Raster",
                "convert_cog.py": "Convert COG",
            }
            initial_status = {}
            for script_name, _ in steps:
                task_name = script_to_task_name.get(script_name)
                if task_name and task_name not in initial_status:
                    initial_status[task_name] = 0

            status_file = output_dir / "status.json"
            import json
            with open(status_file, "w") as f:
                json.dump(initial_status, f)
            logger.info(f"[Metashape] Initialized status.json with tasks: {list(initial_status.keys())}")

            process_mode = options.get("process_mode") or options.get("gsd", "Normal")
            if process_mode not in ["Preview", "Normal", "High"]:
                process_mode = "Normal"
            logger.info(f"[Metashape] process_mode={process_mode} gsd={options.get('gsd')} output_crs={options.get('output_crs')}")
            output_epsg = options.get("output_crs", "4326")

            # 이미지 목록을 파일로 저장 (ARG_MAX 제한 우회)
            images_list_file = output_dir / "images_list.txt"
            with open(images_list_file, "w") as f:
                f.write("\n".join(image_files))
            logger.info(f"[Metashape] Saved {len(image_files)} image paths to {images_list_file}")

            # .processing.log 및 타이밍 추적
            log_file_path = output_dir / ".processing.log"
            step_timings = []
            total_start = time.time()
            total_steps = len(steps)

            for i, (script_name, message) in enumerate(steps):
                step_num = i + 1
                if progress_callback:
                    step_progress = (i / total_steps) * 100
                    await progress_callback(step_progress, message)

                try:
                    script_path = self._get_script_path(script_base, script_name)
                except FileNotFoundError as e:
                    logger.error(f"Metashape script not found: {e}")
                    raise RuntimeError(f"Metashape 필수 스크립트를 찾을 수 없습니다: {script_name}")

                cmd = [
                    sys.executable, str(script_path),
                    "--input_images_file", str(images_list_file),
                    "--image_folder", str(input_dir),
                    "--output_path", str(output_dir),
                    "--run_id", project_id,
                    "--process_mode", process_mode,
                    "--output_tiff_name", "result.tif",
                    "--output_epsg", output_epsg,
                    "--reai_task_id", project_id
                ]
                reference_path = options.get("reference_path")
                if reference_path:
                    cmd.extend(["--reference_path", str(reference_path)])

                if script_name == "align_photos.py":
                    if eo_only_align:
                        cmd.extend(["--eo_only_align", "true"])
                    else:
                        cmd.append("--allow_non_eo_incremental")
                    metadata_path = input_dir / "metadata.txt"
                    logger.info(f"[Metashape] EO metadata path: {metadata_path} (exists={metadata_path.exists()})")
                    logger.info(f"[Metashape] EO-only align mode: {eo_only_align}")
                    if reference_path:
                        logger.info(f"[Metashape] EO reference_path option: {reference_path}")

                logger.info(f"[Metashape] Step {step_num}/{total_steps}: {message} ({script_name})")
                step_start = time.time()

                # stdout+stderr를 .processing.log에 직접 기록 (실시간)
                with open(log_file_path, 'a') as log_f:
                    log_f.write(f"\n{'='*60}\n")
                    log_f.write(f"[Step {step_num}/{total_steps}] {script_name} - {message}\n")
                    log_f.write(f"[Started: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}]\n")
                    log_f.write(f"{'='*60}\n")
                    log_f.flush()
                    result = subprocess.run(cmd, stdout=log_f, stderr=subprocess.STDOUT, text=True)

                elapsed = time.time() - step_start
                step_timings.append((script_name, message, elapsed))

                # 타이밍을 로그 파일에도 기록
                with open(log_file_path, 'a') as log_f:
                    log_f.write(f"\n[Step {step_num}/{total_steps}] 완료: {self._format_elapsed(elapsed)}\n")

                if result.returncode != 0:
                    error_tail = self._read_log_tail(log_file_path)
                    logger.error(f"[Metashape] Step {step_num}/{total_steps} 실패 ({script_name}):\n{error_tail}")
                    raise RuntimeError(f"Metashape 처리 실패 ({script_name})")

                logger.info(f"[Metashape] Step {step_num}/{total_steps}: 완료 - {self._format_elapsed(elapsed)}")

                if script_name == "align_photos.py":
                    normalized_reference = output_dir / "reference_normalized.txt"
                    logger.info(f"[Metashape] reference_normalized.txt exists={normalized_reference.exists()} path={normalized_reference}")

            # 전체 처리 요약
            total_elapsed = time.time() - total_start
            logger.info(f"[Metashape] {'='*40}")
            logger.info(f"[Metashape] 전체 처리 완료 - 총 {self._format_elapsed(total_elapsed)}")
            for idx, (name, msg, elapsed) in enumerate(step_timings, 1):
                logger.info(f"[Metashape]   {idx}. {name:<25s}: {self._format_elapsed(elapsed)}")
            logger.info(f"[Metashape] {'='*40}")
                    
            # Result check
            result_tif = output_dir / "result.tif"
            if not result_tif.exists():
                logger.warning(f"Result TIF not found at {result_tif}, searching in {output_dir}")
                tifs = list(output_dir.glob("*.tif"))
                if tifs:
                    result_tif = tifs[0]
                else:
                    raise RuntimeError("최종 정사영상 결과물을 찾을 수 없습니다.")
                    
            if progress_callback:
                await progress_callback(100, "Metashape 처리 완료")
                
            return result_tif

        except Exception as e:
            logger.error(f"Metashape processing error: {e}")
            raise e

    async def get_status(self, job_id: str) -> dict:
        """Get the status of a processing job."""
        return {"status": "running"}
        
    async def cancel(self, job_id: str) -> bool:
        """Cancel a processing job."""
        return False


class ProcessingRouter:
    """Router to select and use appropriate processing engine."""
    
    def __init__(self):
        self._engines: dict[str, ProcessingEngine] = {}

        if settings.ENABLE_METASHAPE_ENGINE:
            self._engines["metashape"] = MetashapeEngine()

        if settings.ENABLE_ODM_ENGINE:
            self._engines["odm"] = ODMEngine()

        if settings.ENABLE_EXTERNAL_ENGINE:
            self._engines["external"] = ExternalAPIEngine()

        if not self._engines:
            logger.warning(
                "No processing engines enabled. Check ENABLE_*_ENGINE env vars."
            )

    def get_engine(self, engine_name: str) -> ProcessingEngine:
        """Get processing engine by name."""
        if engine_name not in self._engines:
            enabled_engines = ", ".join(sorted(self._engines.keys()))
            raise ValueError(
                f"지원되지 않는 처리 엔진입니다: {engine_name}. "
                f"현재 사용 가능한 엔진: {enabled_engines or '없음'}"
            )
        return self._engines[engine_name]
    
    async def process(
        self,
        engine_name: str,
        project_id: str,
        input_dir: Path,
        output_dir: Path,
        options: dict,
        progress_callback=None,
    ) -> Path:
        """Route processing to the appropriate engine."""
        engine = self.get_engine(engine_name)
        return await engine.process(
            project_id, input_dir, output_dir, options, progress_callback
        )


# Global router instance
processing_router = ProcessingRouter()
