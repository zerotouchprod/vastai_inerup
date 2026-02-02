"""
Orchestrator for video generation workflow (Text-to-Video & Image-to-Video).
"""

import time
from typing import List, Optional
from datetime import datetime, timezone

from .config import GenerationConfig
from .models import GenJob, GenerationResult, BatchGenerationResult, GenerationMode
from .engines.base import BaseVideoEngine
from .engines.text2video import CogVideoText2VideoEngine
from src.infrastructure.storage.b2_client import B2Client
from src.shared.logging import get_logger


class GenerationOrchestrator:
    """
    Orchestrator for video generation workflow.

    Coordinates:
    1. Video generation using appropriate engine (T2V/I2V)
    2. Upload to B2/S3 storage
    3. Result tracking and logging
    4. Cleanup of temporary files

    Supports:
    - Text-to-Video (CogVideoX-5b)
    - Image-to-Video (CogVideoX-5b-I2V) - Coming in Phase 2
    """
    
    def __init__(
        self,
        config: Optional[GenerationConfig] = None,
        b2_client: Optional[B2Client] = None
    ):
        """
        Initialize the orchestrator.
        
        Args:
            config: Generation configuration (creates default if None)
            b2_client: B2Client instance (creates new if None)
        """
        self.config = config or GenerationConfig()
        self.logger = get_logger(__name__)
        
        # Engines (lazy loading)
        self._t2v_engine: Optional[CogVideoText2VideoEngine] = None
        self._i2v_engine: Optional[BaseVideoEngine] = None  # TODO: Phase 2

        # Initialize B2 client
        self.b2_client = b2_client
        if not self.b2_client:
            try:
                self.b2_client = B2Client()
                self.logger.info("✓ B2 client initialized")
            except Exception as e:
                self.logger.warning(f"B2 client unavailable: {e}")
                self.b2_client = None
        
        # State tracking
        self._current_job: Optional[GenJob] = None
        self._results: List[GenerationResult] = []
    
    def _get_engine(self, mode: GenerationMode) -> BaseVideoEngine:
        """
        Get or create engine for specified mode.

        Args:
            mode: Generation mode

        Returns:
            Initialized engine instance

        Raises:
            ValueError: If mode is not supported
        """
        if mode == GenerationMode.TEXT2VIDEO:
            if not self._t2v_engine:
                self.logger.info("Creating Text-to-Video engine...")
                self._t2v_engine = CogVideoText2VideoEngine(self.config)
            return self._t2v_engine

        elif mode == GenerationMode.IMAGE2VIDEO:
            if not self._i2v_engine:
                self.logger.info("Creating Image-to-Video engine...")
                from .engines.image2video import CogVideoImage2VideoEngine
                self._i2v_engine = CogVideoImage2VideoEngine(self.config)
            return self._i2v_engine

        else:
            raise ValueError(f"Unknown generation mode: {mode}")

    def process_job(self, job: GenJob) -> BatchGenerationResult:
        """
        Process a generation job.
        
        Args:
            job: Generation job specification
            
        Returns:
            Batch generation result with all results
        """
        self._current_job = job
        self._results = []
        
        batch_result = BatchGenerationResult(
            job_id=job.id,
            mode=job.mode,
            total_prompts=len(job.prompts)
        )
        
        self.logger.info("=" * 60)
        self.logger.info(f"Processing Job: {job.id}")
        self.logger.info(f"  Mode: {job.mode.value}")
        self.logger.info(f"  Prompts: {len(job.prompts)}")
        self.logger.info(f"  Output: {job.output_prefix}")
        self.logger.info("=" * 60)

        try:
            # Get appropriate engine for mode
            engine = self._get_engine(job.mode)

            # Initialize engine
            engine.initialize()

            # Process each prompt
            for i, prompt in enumerate(job.prompts):
                result = self._process_single_prompt(job, engine, prompt, i)
                self._results.append(result)
                
                if result.success:
                    batch_result.successful += 1
                else:
                    batch_result.failed += 1
                
                batch_result.results.append(result)
            
            # Finalize
            batch_result.completed_at = datetime.now(timezone.utc)

            success_rate = (batch_result.successful / batch_result.total_prompts * 100)
            self.logger.info("=" * 60)
            self.logger.info(f"✅ Job {job.id} completed")
            self.logger.info(f"  Success: {batch_result.successful}/{batch_result.total_prompts} ({success_rate:.1f}%)")
            self.logger.info(f"  Duration: {batch_result.duration_seconds:.1f}s")
            self.logger.info("=" * 60)

            return batch_result
            
        except Exception as e:
            self.logger.error(f"❌ Job {job.id} failed: {e}", exc_info=True)
            batch_result.completed_at = datetime.now(timezone.utc)
            return batch_result
            
        finally:
            # Cleanup
            self._cleanup_temporary_files()
            self._current_job = None
    
    def _process_single_prompt(
        self,
        job: GenJob,
        engine: BaseVideoEngine,
        prompt: str,
        index: int
    ) -> GenerationResult:
        """
        Process a single prompt with specified engine.

        Args:
            job: Parent job
            engine: Engine to use for generation
            prompt: Text prompt
            index: Prompt index in the batch
            
        Returns:
            Generation result
        """
        result = GenerationResult(
            job_id=job.id,
            prompt_index=index,
            prompt=prompt,
            mode=job.mode,
            output_key=job.get_output_key(index)
        )
        
        try:
            # Generate video
            self.logger.info(f"[{index + 1}/{len(job.prompts)}] Generating: '{prompt[:50]}...'")

            # Prepare generation kwargs
            gen_kwargs = {
                'prompt': prompt,
                'negative_prompt': job.negative_prompt,
                'seed': job.seed,
                'guidance_scale': job.guidance_scale,
                'num_inference_steps': job.num_inference_steps,
                'num_frames': job.num_frames,
                'fps': job.fps
            }

            # Add input_image for I2V mode
            if job.mode == GenerationMode.IMAGE2VIDEO:
                if not job.input_images or index >= len(job.input_images):
                    raise ValueError(f"Missing input_image for prompt {index}")
                gen_kwargs['input_image'] = job.input_images[index]
                self.logger.info(f"  Using input image: {job.input_images[index][:50]}...")

            video_path = engine.generate(**gen_kwargs)

            # Get video metadata
            result.local_path = video_path
            result.size_bytes = video_path.stat().st_size
            result.num_frames = job.num_frames

            # Upload to B2 if client is available
            if self.b2_client:
                self.logger.info(f"  ↑ Uploading to B2: {result.output_key}")

                self.b2_client.upload_file(
                    video_path,
                    result.output_key
                )
                
                # Get presigned URL
                result.url = self.b2_client.get_presigned_url(result.output_key)
                self.logger.info(f"  ✓ Upload complete")

            else:
                self.logger.warning("  ! B2 client not available, keeping local file")
                result.url = f"file://{video_path}"
            
            # Clean up local file only if uploaded
            if self.b2_client:
                video_path.unlink(missing_ok=True)

            self.logger.info(f"  ✅ [{index + 1}] Success")

        except Exception as e:
            self.logger.error(f"  ❌ [{index + 1}] Failed: {e}")
            result.success = False
            result.error = str(e)
        
        return result
    
    def _cleanup_temporary_files(self) -> None:
        """Clean up old temporary files."""
        try:
            temp_dir = self.config.temp_dir_path
            if not temp_dir.exists():
                return

            # Remove files older than 1 hour
            current_time = time.time()
            cleaned_count = 0

            for file_path in temp_dir.glob("*"):
                if file_path.is_file():
                    file_age = current_time - file_path.stat().st_mtime
                    if file_age > 3600:  # 1 hour
                        file_path.unlink(missing_ok=True)
                        cleaned_count += 1

            if cleaned_count > 0:
                self.logger.debug(f"Cleaned up {cleaned_count} temporary file(s)")

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
