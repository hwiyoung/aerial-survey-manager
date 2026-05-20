"""Processing engine router and implementations."""
import os
import subprocess
import asyncio
import re
import logging
import time
import json
import hashlib
from abc import ABC
from pathlib import Path
from typing import Optional, Callable, Awaitable
from datetime import datetime

import httpx

from datetime import timedelta

from app.config import get_settings
from app.auth.jwt import create_internal_token
from app.utils.storage_paths import orthomosaic_key, processing_log_path

settings = get_settings()
logger = logging.getLogger("app.processing.router")


def _image_merge_key(image_name: str) -> str:
    basename = os.path.basename(str(image_name or "").strip())
    return os.path.splitext(basename)[0].lower()


def _load_processing_excluded_image_keys(input_dir: Path) -> set[str]:
    exclusion_path = input_dir / ".excluded_images.txt"
    if not exclusion_path.exists():
        return set()
    try:
        with open(exclusion_path, "r", encoding="utf-8") as f:
            return {
                line.strip().lower()
                for line in f
                if line.strip() and not line.lstrip().startswith("#")
            }
    except OSError as exc:
        logger.warning("Failed to read EO exclusion file %s: %s", exclusion_path, exc)
        return set()


def _as_bool(value, default: bool = False) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "yes", "y", "on"}


def _normalize_epsg_crs(value: object, default: str = "EPSG:5186") -> str:
    raw = str(value or default).strip().upper()
    if re.fullmatch(r"\d{4,5}", raw):
        raw = f"EPSG:{raw}"
    if not re.fullmatch(r"EPSG:\d{4,5}", raw):
        raise ValueError(f"Invalid export CRS: {value}")
    return raw


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
    Local GPU processing engine.
    Runs locally on worker-engine (aerial-worker-engine container).
    """
    PROJECT_STATE_STEPS = {
        "align_photos.py",
        "build_depth_maps.py",
        "build_point_cloud.py",
        "build_dem.py",
        "build_orthomosaic.py",
    }
    PROJECT_STATE_STEP_RANK = {
        "align_photos.py": 1,
        "build_depth_maps.py": 2,
        "build_point_cloud.py": 3,
        "build_dem.py": 4,
        "build_orthomosaic.py": 5,
    }

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

    @staticmethod
    def _hash_file(path: Path) -> str | None:
        if not path.exists():
            return None
        digest = hashlib.sha256()
        with open(path, "rb") as f:
            for chunk in iter(lambda: f.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()

    @staticmethod
    def _step_task_name(script_name: str) -> str:
        return {
            "align_photos.py": "Align Photos",
            "build_depth_maps.py": "Build Depth Maps",
            "build_point_cloud.py": "Build Point Cloud",
            "build_dem.py": "Build DEM",
            "build_orthomosaic.py": "Build Orthomosaic",
            "export_orthomosaic.py": "Export Raster",
            "convert_cog.py": "Convert COG",
        }.get(script_name, script_name)

    def _build_processing_fingerprint(
        self,
        image_files: list[str],
        input_dir: Path,
        steps: list[tuple[str, str]],
        process_mode: str,
        output_epsg: object,
        eo_only_align: bool,
        options: dict,
    ) -> str:
        image_entries = []
        for image_path in image_files:
            path = Path(image_path)
            try:
                stat = path.stat()
                image_entries.append({
                    "name": path.name,
                    "size": stat.st_size,
                })
            except OSError:
                image_entries.append({"name": path.name, "missing": True})

        payload = {
            "version": 1,
            "images": image_entries,
            "metadata_hash": self._hash_file(input_dir / "metadata.txt"),
            "excluded_hash": self._hash_file(input_dir / ".excluded_images.txt"),
            "steps": [script_name for script_name, _ in steps],
            "process_mode": process_mode,
            "output_epsg": str(output_epsg),
            "eo_only_align": bool(eo_only_align),
            "build_point_cloud": _as_bool(options.get("build_point_cloud"), False),
            "auto_export": _as_bool(options.get("auto_export"), settings.AUTO_EXPORT_ENABLED),
            "export_target_crs": str(options.get("export_target_crs") or settings.AUTO_EXPORT_TARGET_CRS),
        }
        raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()

    @staticmethod
    def _load_manifest(manifest_path: Path) -> dict:
        if not manifest_path.exists():
            return {}
        try:
            with open(manifest_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            return data if isinstance(data, dict) else {}
        except Exception as exc:
            logger.warning("[ProcessingEngine] Failed to read checkpoint manifest %s: %s", manifest_path, exc)
            return {}

    @staticmethod
    def _save_manifest(manifest_path: Path, manifest: dict) -> None:
        manifest["updated_at"] = datetime.now().isoformat(timespec="seconds")
        tmp_path = manifest_path.with_suffix(".json.tmp")
        with open(tmp_path, "w", encoding="utf-8") as f:
            json.dump(manifest, f, ensure_ascii=False, indent=2, sort_keys=True)
        tmp_path.replace(manifest_path)

    @staticmethod
    def _reset_checkpoint_outputs(output_dir: Path) -> None:
        import shutil

        for name in (
            "project.psx",
            "result.tif",
            "result_cog.tif",
            "reference_normalized.txt",
            "images_list.txt",
            "processing_manifest.json",
        ):
            path = output_dir / name
            if path.exists() or path.is_symlink():
                path.unlink()
        project_files = output_dir / "project.files"
        if project_files.exists():
            shutil.rmtree(project_files, ignore_errors=True)
        for checkpoint_dir in (
            output_dir / ".processing_checkpoint",
            output_dir / ".processing_checkpoint.tmp",
        ):
            if checkpoint_dir.exists():
                shutil.rmtree(checkpoint_dir, ignore_errors=True)

    @staticmethod
    def _cleanup_project_file_locks(output_dir: Path, reason: str) -> None:
        import shutil

        project_files = output_dir / "project.files"
        for lock_path in (
            project_files / "lock",
            project_files / "project.lock",
            project_files / ".lock",
        ):
            try:
                if lock_path.is_symlink() or lock_path.is_file():
                    lock_path.unlink()
                    logger.info("[ProcessingEngine] Removed stale Metashape lock before %s: %s", reason, lock_path)
                elif lock_path.is_dir():
                    shutil.rmtree(lock_path, ignore_errors=True)
                    logger.info("[ProcessingEngine] Removed stale Metashape lock directory before %s: %s", reason, lock_path)
            except OSError as exc:
                logger.warning("[ProcessingEngine] Failed to remove stale Metashape lock %s: %s", lock_path, exc)

    @staticmethod
    def _clear_downstream_artifacts(output_dir: Path, script_name: str) -> None:
        artifact_map = {
            "build_orthomosaic.py": (
                "result.tif",
                "result_cog.tif",
                "auto_export_status.json",
                ".auto_export.log",
            ),
            "export_orthomosaic.py": (
                "result.tif",
                "result_cog.tif",
                "auto_export_status.json",
                ".auto_export.log",
            ),
            "convert_cog.py": (
                "result_cog.tif",
            ),
        }
        for name in artifact_map.get(script_name, ()):
            path = output_dir / name
            try:
                if path.exists() or path.is_symlink():
                    path.unlink()
                    logger.info("[ProcessingEngine] Cleared downstream artifact before %s: %s", script_name, path)
            except OSError as exc:
                logger.warning("[ProcessingEngine] Failed to clear downstream artifact %s: %s", path, exc)

    @staticmethod
    def _project_checkpoint_valid(output_dir: Path) -> bool:
        checkpoint_dir = output_dir / ".processing_checkpoint"
        return (
            (checkpoint_dir / "project.psx").exists()
            and (checkpoint_dir / "project.files").exists()
        )

    @staticmethod
    def _project_checkpoint_step(output_dir: Path) -> str | None:
        step_path = output_dir / ".processing_checkpoint" / "step.txt"
        try:
            if step_path.exists():
                return step_path.read_text(encoding="utf-8").strip() or None
        except OSError:
            return None
        return None

    def _project_checkpoint_covers(self, output_dir: Path, script_name: str) -> bool:
        if not self._project_checkpoint_valid(output_dir):
            return False
        checkpoint_step = self._project_checkpoint_step(output_dir)
        checkpoint_rank = self.PROJECT_STATE_STEP_RANK.get(checkpoint_step or "")
        requested_rank = self.PROJECT_STATE_STEP_RANK.get(script_name)
        return bool(checkpoint_rank and requested_rank and checkpoint_rank >= requested_rank)

    @staticmethod
    def _save_project_checkpoint(output_dir: Path, script_name: str) -> None:
        import shutil

        project_psx = output_dir / "project.psx"
        project_files = output_dir / "project.files"
        if not project_psx.exists() or not project_files.exists():
            raise RuntimeError(f"단계 완료 산출물을 찾을 수 없습니다 ({script_name})")

        MetashapeEngine._cleanup_project_file_locks(output_dir, f"checkpoint save {script_name}")
        checkpoint_dir = output_dir / ".processing_checkpoint"
        tmp_dir = output_dir / ".processing_checkpoint.tmp"
        if tmp_dir.exists():
            shutil.rmtree(tmp_dir, ignore_errors=True)
        tmp_dir.mkdir(parents=True, exist_ok=True)
        shutil.copy2(project_psx, tmp_dir / "project.psx")
        shutil.copytree(project_files, tmp_dir / "project.files", symlinks=True)
        with open(tmp_dir / "step.txt", "w", encoding="utf-8") as f:
            f.write(script_name)
        if checkpoint_dir.exists():
            shutil.rmtree(checkpoint_dir, ignore_errors=True)
        tmp_dir.rename(checkpoint_dir)

    @staticmethod
    def _restore_project_checkpoint(output_dir: Path) -> None:
        import shutil

        checkpoint_dir = output_dir / ".processing_checkpoint"
        if not (
            (checkpoint_dir / "project.psx").exists()
            and (checkpoint_dir / "project.files").exists()
        ):
            raise RuntimeError("복구할 처리 엔진 checkpoint가 없습니다.")

        project_psx = output_dir / "project.psx"
        project_files = output_dir / "project.files"
        if project_psx.exists() or project_psx.is_symlink():
            project_psx.unlink()
        if project_files.exists():
            shutil.rmtree(project_files, ignore_errors=True)
        shutil.copy2(checkpoint_dir / "project.psx", project_psx)
        shutil.copytree(checkpoint_dir / "project.files", project_files, symlinks=True)
        MetashapeEngine._cleanup_project_file_locks(output_dir, "checkpoint restore")

    @staticmethod
    def _step_checkpoint_valid(output_dir: Path, script_name: str) -> bool:
        project_psx = output_dir / "project.psx"
        project_files = output_dir / "project.files"
        if script_name in MetashapeEngine.PROJECT_STATE_STEPS:
            return project_psx.exists() and project_files.exists()
        if script_name == "export_orthomosaic.py":
            return project_psx.exists() and (output_dir / "result.tif").exists()
        if script_name == "convert_cog.py":
            return (output_dir / "result_cog.tif").exists()
        return False

    def _step_checkpoint_usable(self, output_dir: Path, script_name: str, manifest_steps: dict) -> bool:
        if script_name in self.PROJECT_STATE_STEPS and self._project_checkpoint_covers(output_dir, script_name):
            return True

        if self._step_checkpoint_valid(output_dir, script_name):
            return True

        convert_done = (
            manifest_steps.get("convert_cog.py", {}).get("status") == "completed"
            and (output_dir / "result_cog.tif").exists()
        )
        if convert_done:
            return True

        export_done = (
            manifest_steps.get("export_orthomosaic.py", {}).get("status") == "completed"
            and (output_dir / "result.tif").exists()
        )
        return export_done and script_name != "convert_cog.py"

    @staticmethod
    def _container_gpu_available() -> bool:
        return subprocess.run(
            ["nvidia-smi", "-L"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            text=True,
        ).returncode == 0

    @staticmethod
    def _step_subprocess_preexec() -> None:
        try:
            import ctypes
            import signal

            libc = ctypes.CDLL("libc.so.6")
            libc.prctl(1, signal.SIGTERM)
            if os.getppid() == 1:
                os._exit(1)
        except Exception:
            pass

        try:
            os.setsid()
        except Exception:
            pass

    @staticmethod
    def _terminate_step_process(process: subprocess.Popen, log_f=None, timeout: int = 30):
        if process.poll() is not None:
            return process.returncode

        def write_log(message: str) -> None:
            if log_f is None:
                return
            try:
                log_f.write(message)
                log_f.flush()
            except Exception:
                pass

        try:
            import signal

            os.killpg(process.pid, signal.SIGTERM)
        except Exception:
            try:
                process.terminate()
            except Exception:
                pass

        try:
            return process.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            write_log("[Process Watch] step did not exit after SIGTERM; sending SIGKILL\n")
            try:
                import signal

                os.killpg(process.pid, signal.SIGKILL)
            except Exception:
                try:
                    process.kill()
                except Exception:
                    pass
            return process.wait()

    def _initial_step_status(self, steps: list[tuple[str, str]], manifest: dict, resume_enabled: bool) -> dict:
        initial_status = {}
        manifest_steps = manifest.get("steps", {}) if isinstance(manifest.get("steps"), dict) else {}
        for script_name, _ in steps:
            task_name = self._step_task_name(script_name)
            completed = (
                resume_enabled
                and manifest_steps.get(script_name, {}).get("status") == "completed"
            )
            initial_status[task_name] = 100 if completed else 0
        return initial_status

    def _auto_export_enabled(self, options: dict) -> bool:
        return _as_bool(options.get("auto_export"), settings.AUTO_EXPORT_ENABLED)

    def _run_auto_export(
        self,
        project_id: str,
        output_dir: Path,
        options: dict,
        log_file_path: Path,
    ) -> Optional[Path]:
        if not self._auto_export_enabled(options):
            logger.info("[ProcessingEngine] Auto export disabled")
            return None

        target_crs = _normalize_epsg_crs(
            options.get("export_target_crs") or settings.AUTO_EXPORT_TARGET_CRS
        )
        export_root = Path(settings.EXPORT_ROOT_PATH).expanduser()
        source_path = output_dir / "result_cog.tif"
        if not source_path.exists():
            source_path = output_dir / "result.tif"
        if not source_path.exists():
            raise RuntimeError("자동 내보내기 원본 정사영상 파일을 찾을 수 없습니다.")

        export_time = datetime.now()

        export_root.mkdir(parents=True, exist_ok=True)
        export_root_resolved = export_root.resolve()

        target_dir = export_root_resolved
        subdir_raw = options.get("export_subdir") or options.get("auto_export_subdir")
        if subdir_raw:
            safe_subdir = re.sub(r"[^A-Za-z0-9._-]+", "_", str(subdir_raw)).strip("._-")
            if safe_subdir:
                target_dir = (export_root_resolved / safe_subdir).resolve()
        if export_root_resolved != target_dir and export_root_resolved not in target_dir.parents:
            raise RuntimeError("자동 내보내기 대상 경로가 허용된 export root 밖에 있습니다.")
        target_dir.mkdir(parents=True, exist_ok=True)

        target_path = target_dir / Path(orthomosaic_key(project_id, target_crs, when=export_time)).name
        export_log_path = output_dir / ".auto_export.log"
        export_status_path = output_dir / "auto_export_status.json"
        cmd = [
            "gdalwarp",
            "-of", "COG",
            "-t_srs", target_crs,
            "-r", "bilinear",
            "-overwrite",
            "-multi",
            "-wo", "NUM_THREADS=ALL_CPUS",
            "-co", "COMPRESS=LZW",
            "-co", "BLOCKSIZE=1024",
            "-co", "OVERVIEW_RESAMPLING=AVERAGE",
            "-co", "BIGTIFF=YES",
            str(source_path),
            str(target_path),
        ]
        timeout_seconds = int(os.getenv("AUTO_EXPORT_TIMEOUT_SECONDS", "1800"))

        logger.info(
            "[ProcessingEngine] Auto export started: source=%s target=%s crs=%s",
            source_path,
            target_path,
            target_crs,
        )

        with open(export_log_path, "a") as export_log, open(log_file_path, "a") as processing_log:
            started_at = datetime.now().isoformat(timespec="seconds")
            header = (
                f"\n{'='*60}\n"
                f"[Auto Export] started={started_at}\n"
                f"source={source_path}\n"
                f"target={target_path}\n"
                f"target_crs={target_crs}\n"
                f"command={' '.join(cmd)}\n"
                f"{'='*60}\n"
            )
            export_log.write(header)
            processing_log.write(header)
            export_log.flush()
            processing_log.flush()

            result = subprocess.run(
                cmd,
                stdout=export_log,
                stderr=subprocess.STDOUT,
                text=True,
                timeout=timeout_seconds,
            )

        status_payload = {
            "enabled": True,
            "status": "success" if result.returncode == 0 and target_path.exists() else "failed",
            "source": str(source_path),
            "target": str(target_path),
            "target_crs": target_crs,
            "returncode": result.returncode,
            "completed_at": datetime.now().isoformat(timespec="seconds"),
        }

        if status_payload["status"] != "success":
            if target_path.exists():
                try:
                    target_path.unlink()
                except OSError:
                    logger.warning("[ProcessingEngine] Failed to remove partial auto export: %s", target_path)
            with open(export_status_path, "w") as f:
                json.dump(status_payload, f, ensure_ascii=False, indent=2)
            logger.error("[ProcessingEngine] Auto export failed: %s", target_path)
            return None

        status_payload["size_bytes"] = target_path.stat().st_size
        with open(export_status_path, "w") as f:
            json.dump(status_payload, f, ensure_ascii=False, indent=2)
        logger.info("[ProcessingEngine] Auto export completed: %s", target_path)
        return target_path

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

        if progress_callback:
            await progress_callback(0, "엔진 초기화 중...")

        # 1. 사이클 시작: 라이선스 활성화
        script_base = Path("/app/engines/metashape/dags/metashape")
        activate_script = self._get_script_path(script_base, "activate.py")
        deactivate_script = self._get_script_path(script_base, "deactivate.py")
        
        try:
            if activate_script.exists():
                logger.info("🔑 사이클 시작: 처리 엔진 라이선스 활성화를 시도합니다.")
                act_result = subprocess.run([sys.executable, str(activate_script)], capture_output=True, text=True)
                if act_result.stdout:
                    logger.info(f"Activation stdout: {act_result.stdout.strip()}")
                if act_result.stderr:
                    logger.warning(f"Activation stderr: {act_result.stderr.strip()}")

            # 2. 본 작업 수행
            image_files = sorted(
                str(f) for f in input_dir.glob("*")
                if f.suffix.lower() in [".jpg", ".jpeg", ".tif", ".tiff"]
            )
            excluded_image_keys = _load_processing_excluded_image_keys(input_dir)
            if excluded_image_keys:
                before_count = len(image_files)
                image_files = [
                    image_path for image_path in image_files
                    if _image_merge_key(image_path) not in excluded_image_keys
                ]
                logger.info(
                    "[ProcessingEngine] EO preview exclusions applied to image list: "
                    "skipped=%s total_before=%s",
                    before_count - len(image_files),
                    before_count,
                )
            if not image_files:
                raise RuntimeError("처리할 이미지가 없습니다. EO 위치 preview의 제외 상태를 확인해주세요.")
                
            # Point cloud 생성 여부 (기본값: False, advanced 옵션)
            build_point_cloud = _as_bool(options.get("build_point_cloud"), False)
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
                f"[ProcessingEngine] build_point_cloud={build_point_cloud}, "
                f"eo_only_align={eo_only_align}, total steps={len(steps)}"
            )

            process_mode = options.get("process_mode") or options.get("gsd", "Normal")
            if process_mode not in ["Preview", "Normal", "High"]:
                process_mode = "Normal"
            logger.info(f"[ProcessingEngine] process_mode={process_mode} gsd={options.get('gsd')} output_crs={options.get('output_crs')}")
            output_epsg = options.get("output_crs", "4326")

            resume_enabled = _as_bool(options.get("resume_checkpoint"), True)
            manifest_path = output_dir / "processing_manifest.json"
            fingerprint = self._build_processing_fingerprint(
                image_files=image_files,
                input_dir=input_dir,
                steps=steps,
                process_mode=process_mode,
                output_epsg=output_epsg,
                eo_only_align=eo_only_align,
                options=options,
            )

            def new_manifest(reset_reason: str) -> dict:
                return {
                    "version": 1,
                    "project_id": project_id,
                    "fingerprint": fingerprint,
                    "reset_reason": reset_reason,
                    "created_at": datetime.now().isoformat(timespec="seconds"),
                    "steps": {},
                }

            manifest = self._load_manifest(manifest_path)
            reset_reason = None
            if not resume_enabled:
                reset_reason = "resume_disabled"
            elif manifest.get("version") != 1:
                reset_reason = "manifest_version_changed"
            elif manifest.get("fingerprint") != fingerprint:
                reset_reason = "input_or_options_changed"

            if reset_reason:
                logger.info("[ProcessingEngine] Resetting processing checkpoints: %s", reset_reason)
                self._reset_checkpoint_outputs(output_dir)
                manifest = new_manifest(reset_reason)
            else:
                if not isinstance(manifest.get("steps"), dict):
                    manifest["steps"] = {}
                manifest_steps = manifest["steps"]
                invalid_completed_steps = [
                    script_name
                    for script_name, _ in steps
                    if manifest_steps.get(script_name, {}).get("status") == "completed"
                    and not self._step_checkpoint_usable(output_dir, script_name, manifest_steps)
                ]
                if invalid_completed_steps:
                    logger.warning(
                        "[ProcessingEngine] Resetting processing checkpoints because completed outputs are missing: %s",
                        ", ".join(invalid_completed_steps),
                    )
                    self._reset_checkpoint_outputs(output_dir)
                    manifest = new_manifest("completed_outputs_missing")
                else:
                    logger.info("[ProcessingEngine] Reusing compatible processing checkpoints")

            manifest.setdefault("steps", {})
            self._save_manifest(manifest_path, manifest)
            initial_completed_steps = {
                script_name
                for script_name, _ in steps
                if manifest["steps"].get(script_name, {}).get("status") == "completed"
                and self._step_checkpoint_usable(output_dir, script_name, manifest["steps"])
            }

            # status.json 초기화 - 실행할 단계만 포함하고 checkpoint 완료 단계는 100으로 표시
            initial_status = self._initial_step_status(steps, manifest, resume_enabled)
            status_file = output_dir / "status.json"
            with open(status_file, "w") as f:
                json.dump(initial_status, f)
            logger.info(f"[ProcessingEngine] Initialized status.json with tasks: {list(initial_status.keys())}")

            # 이미지 목록을 파일로 저장 (ARG_MAX 제한 우회)
            images_list_file = output_dir / "images_list.txt"
            with open(images_list_file, "w") as f:
                f.write("\n".join(image_files))
            logger.info(f"[ProcessingEngine] Saved {len(image_files)} image paths to {images_list_file}")

            # .processing.log 및 타이밍 추적
            log_file_path = processing_log_path(project_id)
            log_file_path.parent.mkdir(parents=True, exist_ok=True)
            step_timings = []
            total_start = time.time()
            total_steps = len(steps)
            try:
                gpu_watch_interval = max(5, int(os.getenv("PROCESSING_GPU_WATCH_INTERVAL_SECONDS", "30")))
            except ValueError:
                gpu_watch_interval = 30
            try:
                gpu_watch_strikes = max(1, int(os.getenv("PROCESSING_GPU_WATCH_STRIKES", "2")))
            except ValueError:
                gpu_watch_strikes = 2

            for i, (script_name, message) in enumerate(steps):
                step_num = i + 1
                task_name = self._step_task_name(script_name)
                manifest_steps = manifest.setdefault("steps", {})
                step_record = manifest_steps.setdefault(script_name, {})
                step_record.setdefault("task_name", task_name)
                step_record["message"] = message

                if (
                    resume_enabled
                    and step_record.get("status") == "completed"
                    and self._step_checkpoint_usable(output_dir, script_name, manifest_steps)
                ):
                    logger.info(
                        "[ProcessingEngine] Step %s/%s checkpoint hit; skipping %s",
                        step_num,
                        total_steps,
                        script_name,
                    )
                    step_timings.append((script_name, f"{message} (checkpoint)", 0.0))
                    with open(log_file_path, 'a') as log_f:
                        log_f.write(f"\n{'='*60}\n")
                        log_f.write(f"[Step {step_num}/{total_steps}] {script_name} - checkpoint 재사용\n")
                        log_f.write(f"[Skipped: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}]\n")
                        log_f.write(f"{'='*60}\n")
                    if progress_callback:
                        await progress_callback(min(99, ((i + 1) / total_steps) * 100), f"{message} 완료(checkpoint)")
                    continue

                if progress_callback:
                    step_progress = (i / total_steps) * 100
                    await progress_callback(step_progress, message)

                try:
                    script_path = self._get_script_path(script_base, script_name)
                except FileNotFoundError as e:
                    logger.error(f"Processing engine script not found: {e}")
                    raise RuntimeError(f"처리 엔진 필수 스크립트를 찾을 수 없습니다: {script_name}")

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
                    logger.info(f"[ProcessingEngine] EO metadata path: {metadata_path} (exists={metadata_path.exists()})")
                    logger.info(f"[ProcessingEngine] EO-only align mode: {eo_only_align}")
                    if reference_path:
                        logger.info(f"[ProcessingEngine] EO reference_path option: {reference_path}")

                previous_project_step = None
                for previous_script, _ in steps[:i]:
                    if (
                        previous_script in self.PROJECT_STATE_STEPS
                        and previous_script in initial_completed_steps
                        and manifest_steps.get(previous_script, {}).get("status") == "completed"
                    ):
                        previous_project_step = previous_script
                if previous_project_step:
                    if not self._project_checkpoint_covers(output_dir, previous_project_step):
                        error_message = f"복구할 단계 checkpoint가 유효하지 않습니다 ({previous_project_step})"
                        step_record.update({
                            "status": "failed",
                            "completed_at": datetime.now().isoformat(timespec="seconds"),
                            "error_code": "CHECKPOINT_RESTORE_FAILED",
                            "error_message": error_message,
                        })
                        self._save_manifest(manifest_path, manifest)
                        logger.error("[ProcessingEngine] %s", error_message)
                        raise RuntimeError(error_message)
                    logger.info(
                        "[ProcessingEngine] Restoring project checkpoint from %s before %s",
                        previous_project_step,
                        script_name,
                    )
                    try:
                        self._restore_project_checkpoint(output_dir)
                    except Exception as restore_error:
                        error_message = f"단계 checkpoint 복원 실패 ({previous_project_step}): {restore_error}"
                        step_record.update({
                            "status": "failed",
                            "completed_at": datetime.now().isoformat(timespec="seconds"),
                            "error_code": "CHECKPOINT_RESTORE_FAILED",
                            "error_message": error_message,
                        })
                        self._save_manifest(manifest_path, manifest)
                        logger.error("[ProcessingEngine] %s", error_message)
                        raise RuntimeError(error_message)

                self._cleanup_project_file_locks(output_dir, script_name)
                self._clear_downstream_artifacts(output_dir, script_name)

                if not self._container_gpu_available():
                    error_message = f"GPU_RUNTIME_LOST: worker-engine GPU access is unavailable before {script_name}"
                    step_record.update({
                        "status": "failed",
                        "task_name": task_name,
                        "message": message,
                        "started_at": datetime.now().isoformat(timespec="seconds"),
                        "completed_at": datetime.now().isoformat(timespec="seconds"),
                        "error_code": "GPU_RUNTIME_LOST",
                        "error_message": error_message,
                    })
                    self._save_manifest(manifest_path, manifest)
                    logger.error("[ProcessingEngine] %s", error_message)
                    raise RuntimeError(error_message)

                logger.info(f"[ProcessingEngine] Step {step_num}/{total_steps}: {message} ({script_name})")
                step_start = time.time()
                step_record.update({
                    "status": "running",
                    "task_name": task_name,
                    "message": message,
                    "started_at": datetime.now().isoformat(timespec="seconds"),
                })
                for key in ("completed_at", "elapsed_seconds", "returncode", "error_code", "error_message"):
                    step_record.pop(key, None)
                self._save_manifest(manifest_path, manifest)

                # stdout+stderr를 .processing.log에 직접 기록 (실시간)
                returncode = None
                gpu_lost_during_step = False
                with open(log_file_path, 'a') as log_f:
                    log_f.write(f"\n{'='*60}\n")
                    log_f.write(f"[Step {step_num}/{total_steps}] {script_name} - {message}\n")
                    log_f.write(f"[Started: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}]\n")
                    log_f.write(f"{'='*60}\n")
                    log_f.flush()
                    process = subprocess.Popen(
                        cmd,
                        stdout=log_f,
                        stderr=subprocess.STDOUT,
                        text=True,
                        preexec_fn=self._step_subprocess_preexec,
                    )
                    try:
                        next_gpu_check = time.monotonic() + gpu_watch_interval
                        gpu_failure_count = 0
                        while True:
                            returncode = process.poll()
                            if returncode is not None:
                                break

                            now = time.monotonic()
                            if now >= next_gpu_check:
                                if self._container_gpu_available():
                                    gpu_failure_count = 0
                                else:
                                    gpu_failure_count += 1
                                    log_f.write(
                                        f"\n[GPU Watch] nvidia-smi unavailable "
                                        f"({gpu_failure_count}/{gpu_watch_strikes})\n"
                                    )
                                    log_f.flush()
                                    if gpu_failure_count >= gpu_watch_strikes:
                                        gpu_lost_during_step = True
                                        log_f.write("[GPU Watch] terminating step because GPU runtime was lost\n")
                                        log_f.flush()
                                        returncode = self._terminate_step_process(process, log_f)
                                        break
                                next_gpu_check = now + gpu_watch_interval
                            time.sleep(1)
                    except BaseException:
                        if process.poll() is None:
                            log_f.write("[Process Watch] parent task interrupted; terminating step process\n")
                            log_f.flush()
                            self._terminate_step_process(process, log_f)
                        raise

                elapsed = time.time() - step_start
                step_timings.append((script_name, message, elapsed))

                # 타이밍을 로그 파일에도 기록
                with open(log_file_path, 'a') as log_f:
                    log_f.write(
                        f"\n[Step {step_num}/{total_steps}] 종료(returncode={returncode}): "
                        f"{self._format_elapsed(elapsed)}\n"
                    )

                if returncode != 0:
                    error_tail = self._read_log_tail(log_file_path)
                    logger.error(f"[ProcessingEngine] Step {step_num}/{total_steps} 실패 ({script_name}):\n{error_tail}")
                    gpu_lost = gpu_lost_during_step or not self._container_gpu_available()
                    error_code = "GPU_RUNTIME_LOST" if gpu_lost else "STEP_FAILED"
                    error_message = (
                        f"GPU_RUNTIME_LOST: worker-engine GPU access was lost during {script_name}"
                        if gpu_lost
                        else f"처리 엔진 처리 실패 ({script_name})"
                    )
                    step_record.update({
                        "status": "failed",
                        "completed_at": datetime.now().isoformat(timespec="seconds"),
                        "elapsed_seconds": round(elapsed, 3),
                        "returncode": returncode,
                        "error_code": error_code,
                        "error_message": error_message,
                    })
                    self._save_manifest(manifest_path, manifest)
                    raise RuntimeError(error_message)

                if not self._step_checkpoint_valid(output_dir, script_name):
                    error_message = f"단계 완료 검증 실패 ({script_name})"
                    step_record.update({
                        "status": "failed",
                        "completed_at": datetime.now().isoformat(timespec="seconds"),
                        "elapsed_seconds": round(elapsed, 3),
                        "returncode": 0,
                        "error_code": "CHECKPOINT_INVALID",
                        "error_message": error_message,
                    })
                    self._save_manifest(manifest_path, manifest)
                    logger.error("[ProcessingEngine] %s", error_message)
                    raise RuntimeError(error_message)

                if script_name in self.PROJECT_STATE_STEPS:
                    try:
                        self._save_project_checkpoint(output_dir, script_name)
                    except Exception as checkpoint_error:
                        error_message = f"단계 checkpoint 저장 실패 ({script_name}): {checkpoint_error}"
                        step_record.update({
                            "status": "failed",
                            "completed_at": datetime.now().isoformat(timespec="seconds"),
                            "elapsed_seconds": round(elapsed, 3),
                            "returncode": 0,
                            "error_code": "CHECKPOINT_SAVE_FAILED",
                            "error_message": error_message,
                        })
                        self._save_manifest(manifest_path, manifest)
                        logger.error("[ProcessingEngine] %s", error_message)
                        raise RuntimeError(error_message)

                step_record.update({
                    "status": "completed",
                    "completed_at": datetime.now().isoformat(timespec="seconds"),
                    "elapsed_seconds": round(elapsed, 3),
                    "returncode": 0,
                })
                step_record.pop("error_code", None)
                step_record.pop("error_message", None)
                self._save_manifest(manifest_path, manifest)

                logger.info(f"[ProcessingEngine] Step {step_num}/{total_steps}: 완료 - {self._format_elapsed(elapsed)}")

                if script_name == "align_photos.py":
                    normalized_reference = output_dir / "reference_normalized.txt"
                    logger.info(f"[ProcessingEngine] reference_normalized.txt exists={normalized_reference.exists()} path={normalized_reference}")

            # 전체 처리 요약
            total_elapsed = time.time() - total_start
            logger.info(f"[ProcessingEngine] {'='*40}")
            logger.info(f"[ProcessingEngine] 전체 처리 완료 - 총 {self._format_elapsed(total_elapsed)}")
            for idx, (name, msg, elapsed) in enumerate(step_timings, 1):
                logger.info(f"[ProcessingEngine]   {idx}. {name:<25s}: {self._format_elapsed(elapsed)}")
            logger.info(f"[ProcessingEngine] {'='*40}")
                    
            # Result check
            result_tif = output_dir / "result.tif"
            if not result_tif.exists():
                logger.warning(f"Result TIF not found at {result_tif}, searching in {output_dir}")
                tifs = list(output_dir.glob("*.tif"))
                if tifs:
                    result_tif = tifs[0]
                else:
                    raise RuntimeError("최종 정사영상 결과물을 찾을 수 없습니다.")

            if self._auto_export_enabled(options):
                if progress_callback:
                    await progress_callback(98, "정사영상 자동 내보내기 중...")
                try:
                    auto_export_path = self._run_auto_export(project_id, output_dir, options, log_file_path)
                    if auto_export_path:
                        logger.info("[ProcessingEngine] Auto export result: %s", auto_export_path)
                    else:
                        logger.warning("[ProcessingEngine] Auto export did not produce a file; processing result remains completed.")
                except Exception as export_error:
                    logger.error("[ProcessingEngine] Auto export failed without failing processing: %s", export_error)
                    with open(log_file_path, "a") as log_f:
                        log_f.write(f"\n[Auto Export] failed without failing processing: {export_error}\n")

            if progress_callback:
                await progress_callback(100, "처리 완료")
                
            return result_tif

        except Exception as e:
            logger.error(f"Processing engine error: {e}")
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
