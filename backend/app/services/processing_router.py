"""Processing engine router and implementations."""
import os
import subprocess
import asyncio
import re
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Optional
from datetime import datetime

import httpx

from app.config import get_settings

settings = get_settings()


class ProcessingEngine(ABC):
    """Abstract base class for processing engines."""
    
    @abstractmethod
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
        
        Args:
            project_id: Project identifier
            input_dir: Directory containing input images
            output_dir: Directory for output files
            options: Processing options (gsd, crs, format, etc.)
            progress_callback: Callback function for progress updates
        
        Returns:
            Path to the generated orthophoto
        """
        pass
    
    @abstractmethod
    async def get_status(self, job_id: str) -> dict:
        """Get the status of a processing job."""
        pass
    
    @abstractmethod
    async def cancel(self, job_id: str) -> bool:
        """Cancel a processing job."""
        pass


class ODMEngine(ProcessingEngine):
    """OpenDroneMap processing engine."""
    
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
            
            if progress_callback and final_progress > 0:
                await progress_callback(final_progress, line_str)
        
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
    
    def __init__(self):
        self.base_url = settings.EXTERNAL_ENGINE_URL
        self.api_key = settings.EXTERNAL_ENGINE_API_KEY
        self._job_ids: dict[str, str] = {}  # Map project_id to external job_id
    
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
            raise ValueError("External engine URL not configured")
        
        async with httpx.AsyncClient(timeout=300.0) as client:
            # 1. Submit the job
            # This would typically involve uploading files or providing presigned URLs
            response = await client.post(
                f"{self.base_url}/jobs",
                json={
                    "project_id": project_id,
                    "input_path": str(input_dir),
                    "options": options,
                },
                headers={"Authorization": f"Bearer {self.api_key}"},
            )
            response.raise_for_status()
            job_data = response.json()
            external_job_id = job_data["job_id"]
            
            self._job_ids[project_id] = external_job_id
            
            # 2. Poll for completion
            while True:
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
                
                if status == "completed":
                    result_url = status_data.get("result_url")
                    
                    # 3. Download result
                    output_path = output_dir / f"{project_id}_ortho.tif"
                    
                    async with client.stream("GET", result_url) as download:
                        download.raise_for_status()
                        with open(output_path, "wb") as f:
                            async for chunk in download.aiter_bytes():
                                f.write(chunk)
                    
                    return output_path
                
                elif status == "failed":
                    error = status_data.get("error", "Unknown error")
                    raise RuntimeError(f"External processing failed: {error}")
                
                # Wait before polling again
                await asyncio.sleep(5)
    
    async def get_status(self, job_id: str) -> dict:
        """Get status from external API."""
        external_id = self._job_ids.get(job_id)
        if not external_id:
            return {"status": "unknown"}
        
        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"{self.base_url}/jobs/{external_id}",
                headers={"Authorization": f"Bearer {self.api_key}"},
            )
            return response.json()
    
    async def cancel(self, job_id: str) -> bool:
        """Cancel job via external API."""
        external_id = self._job_ids.get(job_id)
        if not external_id:
            return False
        
        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"{self.base_url}/jobs/{external_id}/cancel",
                headers={"Authorization": f"Bearer {self.api_key}"},
            )
            return response.status_code == 200


class ProcessingRouter:
    """Router to select and use appropriate processing engine."""
    
    def __init__(self):
        self.engines = {
            "odm": ODMEngine(),
            "external": ExternalAPIEngine(),
        }
    
    def get_engine(self, engine_name: str) -> ProcessingEngine:
        """Get processing engine by name."""
        if engine_name not in self.engines:
            raise ValueError(f"Unknown engine: {engine_name}")
        return self.engines[engine_name]
    
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
