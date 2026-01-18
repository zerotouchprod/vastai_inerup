"""
Orchestrator for text-to-video generation workflow.
"""

import tempfile
from pathlib import Path
from typing import List, Optional
from datetime import datetime

from .config import GenerationConfig
from .models import GenJob, GenerationResult, BatchGenerationResult
from .engine import CogVideoEngine
from src.infrastructure.storage.b2_client import B2Client
from src.shared.logging import get_logger


class GenerationOrchestrator:
    """
    Orchestrator for the text-to-video generation workflow.
    
    Coordinates:
    1. Video generation using CogVideoEngine
    2. Upload to B2 storage
    3. Result tracking and logging
    4. Cleanup of temporary files
    """
    
    def __init__(
        self,
        engine: Optional[CogVideoEngine] = None,
        b2_client: Optional[B2Client] = None,
        config: Optional[GenerationConfig] = None
    ):
        """
        Initialize the orchestrator.
        
        Args:
            engine: CogVideoEngine instance (creates new if None)
            b2_client: B2Client instance (creates new if None)
            config: Generation configuration
        """
        self.config = config or GenerationConfig()
        self.logger = get_logger(__name__)
        
        # Initialize engine
        self.engine = engine or CogVideoEngine(self.config)
        
        # Initialize B2 client
        self.b2_client = b2_client
        if not self.b2_client:
            try:
                self.b2_client = B2Client()
                self.logger.info("B2 client initialized successfully")
            except Exception as e:
                self.logger.warning(f"Failed to initialize B2 client: {e}")
                self.b2_client = None
        
        # Track results
        self._current_job: Optional[GenJob] = None
        self._results: List[GenerationResult] = []
    
    def process_job(self, job: GenJob) -> BatchGenerationResult:
        """
        Process a generation job.
        
        Args:
            job: Generation job specification
            
        Returns:
            Batch generation result
        """
        self._current_job = job
        self._results = []
        
        batch_result = BatchGenerationResult(
            job_id=job.id,
            total_prompts=len(job.prompts)
        )
        
        self.logger.info(
            f"Processing generation job {job.id} with {len(job.prompts)} prompts"
        )
        
        try:
            # Initialize engine
            self.engine.initialize()
            
            # Process each prompt
            for i, prompt in enumerate(job.prompts):
                result = self._process_single_prompt(job, prompt, i)
                self._results.append(result)
                
                if result.success:
                    batch_result.successful += 1
                else:
                    batch_result.failed += 1
                
                batch_result.results.append(result)
            
            # Finalize
            batch_result.completed_at = datetime.utcnow()
            
            success_rate = (batch_result.successful / batch_result.total_prompts * 100)
            self.logger.info(
                f"Job {job.id} completed: {batch_result.successful}/{batch_result.total_prompts} "
                f"successful ({success_rate:.1f}%) in {batch_result.duration_seconds:.1f}s"
            )
            
            return batch_result
            
        except Exception as e:
            self.logger.error(f"Job {job.id} failed: {e}")
            batch_result.completed_at = datetime.utcnow()
            return batch_result
            
        finally:
            # Cleanup
            self._cleanup_temporary_files()
            self._current_job = None
    
    def _process_single_prompt(
        self,
        job: GenJob,
        prompt: str,
        index: int
    ) -> GenerationResult:
        """
        Process a single prompt.
        
        Args:
            job: Parent job
            prompt: Text prompt
            index: Prompt index in the batch
            
        Returns:
            Generation result
        """
        result = GenerationResult(
            job_id=job.id,
            prompt_index=index,
            prompt=prompt,
            output_key=job.get_output_key(index)
        )
        
        try:
            # Generate video
            self.logger.info(f"Generating video for prompt {index + 1}: '{prompt[:50]}...'")
            
            video_path = self.engine.generate(
                prompt=prompt,
                negative_prompt=job.negative_prompt,
                seed=job.seed,
                guidance_scale=job.guidance_scale,
                num_inference_steps=job.num_inference_steps
            )
            
            # Get video metadata
            result.size_bytes = video_path.stat().st_size
            
            # Upload to B2 if client is available
            if self.b2_client:
                self.logger.info(f"Uploading to B2: {result.output_key}")
                
                b2_object = self.b2_client.upload_file(
                    video_path,
                    result.output_key
                )
                
                # Get presigned URL
                result.url = self.b2_client.get_presigned_url(result.output_key)
                self.logger.info(f"Upload successful: {result.url}")
            
            else:
                self.logger.warning("B2 client not available, skipping upload")
                result.url = f"file://{video_path}"
            
            # Clean up local file
            video_path.unlink(missing_ok=True)
            
            self.logger.info(f"Prompt {index + 1} processed successfully")
            
        except Exception as e:
            self.logger.error(f"Failed to process prompt {index + 1}: {e}")
            result.success = False
            result.error = str(e)
        
        return result
    
    def _cleanup_temporary_files(self) -> None:
        """Clean up temporary files."""
        try:
            temp_dir = self.config.temp_dir_path
            if temp_dir.exists():
                # Remove files older than 1 hour
                import time
                current_time = time.time()
                
                for file_path in temp_dir.glob("*"):
                    if file_path.is_file():
                        file_age = current_time - file_path.stat().st_mtime
                        if file_age > 3600:  # 1 hour
                            file_path.unlink(missing_ok=True)
                
                self.logger.debug("Cleaned up temporary files")
                
        except Exception as e:
            self.logger.warning(f"Failed to clean up temporary files: {e}")
    
    def get_job_status(self, job_id: str) -> Optional[BatchGenerationResult]:
        """
        Get status of a job.
        
        Args:
            job_id: Job identifier
            
        Returns:
            Batch generation result if job is current, None otherwise
        """
        if self._current_job and self._current_job.id == job_id:
            return BatchGenerationResult(
                job_id=job_id,
                total_prompts=len(self._current_job.prompts),
                successful=sum(1 for r in self._results if r.success),
                failed=sum(1 for r in self._results if not r.success),
                results=self._results.copy(),
                started_at=datetime.utcnow(),  # TODO: Track actual start time
                completed_at=None
            )
        return None
    
    def shutdown(self) -> None:
        """Shutdown the orchestrator and clean up resources."""
        self.logger.info("Shutting down generation orchestrator")
        
        try:
            self.engine.cleanup()
            self.logger.info("Engine cleaned up")
        except Exception as e:
            self.logger.warning(f"Error cleaning up engine: {e}")
        
        self._cleanup_temporary_files()
        self._current_job = None
        self._results = []
    
    def __enter__(self):
        """Context manager entry."""
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit."""
        self.shutdown()
