"""Processing engine router and implementations."""
import os
import subprocess
import asyncio
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
        
        cmd = [
            "docker", "run", "--rm",
            "-v", f"{input_dir}:/datasets/project/images",
            "-v", f"{output_dir}:/datasets/project/output",
            self.docker_image,
            "--project-path", "/datasets",
            "project",
            "--orthophoto-resolution", str(gsd / 100),  # ODM uses meters
            "--dsm",
            "--dtm",
            "--skip-3dmodel",  # Skip 3D model to speed up
            "--force-gps",
            "--auto-boundary",
        ]
        
        # Run ODM process
        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        
        # Monitor progress (parse ODM output)
        current_progress = 0
        async for line in process.stdout:
            line_str = line.decode().strip()
            
            # Parse ODM progress from output
            if "running" in line_str.lower():
                if progress_callback:
                    # Estimate progress based on ODM stages
                    if "opensfm" in line_str.lower():
                        current_progress = 20
                    elif "mvs" in line_str.lower():
                        current_progress = 40
                    elif "odm_filterpoints" in line_str.lower():
                        current_progress = 50
                    elif "odm_meshing" in line_str.lower():
                        current_progress = 60
                    elif "odm_dem" in line_str.lower():
                        current_progress = 70
                    elif "odm_orthophoto" in line_str.lower():
                        current_progress = 80
                    
                    await progress_callback(current_progress, line_str)
        
        await process.wait()
        
        if process.returncode != 0:
            stderr = await process.stderr.read()
            raise RuntimeError(f"ODM processing failed: {stderr.decode()}")
        
        # Find the output orthophoto
        ortho_path = output_dir / "odm_orthophoto" / "odm_orthophoto.tif"
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
