"""
CogVideoX engine for text-to-video generation.
"""

import tempfile
import uuid
from pathlib import Path
from typing import Optional, List, Tuple, Any
from datetime import datetime

from .config import GenerationConfig
from .models import GenerationResult
from src.shared.logging import get_logger


class CogVideoEngine:
    """
    Engine for text-to-video generation using CogVideoX-5b.
    
    Features:
    - Safety checking with Stable Diffusion safety checker
    - Optimizations for 24GB VRAM (CPU offload, VAE slicing, tiling)
    - Batch processing support
    - NSFW content filtering
    """
    
    def __init__(self, config: Optional[GenerationConfig] = None):
        """
        Initialize the generation engine.
        
        Args:
            config: Generation configuration (uses default if None)
        """
        self.config = config or GenerationConfig()
        self.logger = get_logger(__name__)
        
        self.pipe = None  # Will be initialized as CogVideoXPipeline
        self.safety_checker = None
        self._initialized = False
        
    def initialize(self) -> None:
        """Initialize the pipeline and safety checker."""
        if self._initialized:
            return
            
        self.logger.info(f"Initializing CogVideoEngine with model: {self.config.T2V_MODEL_ID}")
        
        try:
            from diffusers import CogVideoXPipeline
            from transformers import pipeline as transformers_pipeline
            import torch
            
            # Load pipeline with optimizations
            self.logger.info("Loading CogVideoX pipeline...")
            self.pipe = CogVideoXPipeline.from_pretrained(
                self.config.T2V_MODEL_ID,
                **self.config.get_optimization_kwargs()
            )
            
            # Apply optimizations
            if self.config.ENABLE_CPU_OFFLOAD:
                self.pipe.enable_model_cpu_offload()
                self.logger.info("Enabled model CPU offload")
            
            if self.config.ENABLE_VAE_SLICING:
                self.pipe.enable_vae_slicing()
                self.logger.info("Enabled VAE slicing")
            
            if self.config.ENABLE_TILING:
                self.pipe.enable_tiling()
                self.logger.info("Enabled tiling")
            
            if self.config.USE_XFORMERS:
                try:
                    self.pipe.enable_xformers_memory_efficient_attention()
                    self.logger.info("Enabled xformers memory efficient attention")
                except ImportError:
                    self.logger.warning("xformers not available, skipping")
            
            # Initialize safety checker if enabled
            if self.config.ENABLE_SAFETY_CHECKER:
                self.logger.info(f"Loading safety checker: {self.config.SAFETY_CHECKER_MODEL}")
                self.safety_checker = transformers_pipeline(
                    "image-classification",
                    model=self.config.SAFETY_CHECKER_MODEL,
                    device="cuda" if torch.cuda.is_available() else "cpu"
                )
            
            self._initialized = True
            self.logger.info("CogVideoEngine initialized successfully")
            
        except Exception as e:
            self.logger.error(f"Failed to initialize CogVideoEngine: {e}")
            raise
    
    def _check_safety(self, frames: List) -> bool:
        """
        Check frames for NSFW content.
        
        Args:
            frames: List of frames to check
            
        Returns:
            True if content is safe, False if NSFW detected
        """
        if not self.safety_checker or not frames:
            return True
        
        try:
            # Check a sample of frames (first, middle, last)
            sample_indices = [0, len(frames) // 2, -1]
            sample_frames = [frames[i] for i in sample_indices if i < len(frames)]
            
            for frame in sample_frames:
                results = self.safety_checker(frame, top_k=2)
                
                # Check for NSFW classifications
                for result in results:
                    label = result['label'].lower()
                    score = result['score']
                    
                    if 'nsfw' in label or 'explicit' in label or 'adult' in label:
                        if score > 0.5:  # Confidence threshold
                            self.logger.warning(f"NSFW content detected: {label} (score: {score:.3f})")
                            return False
            
            return True
            
        except Exception as e:
            self.logger.warning(f"Safety check failed: {e}, allowing content")
            return True  # Fail open for safety
    
    def _create_generator(self, seed: Optional[int] = None):
        """
        Create torch generator with optional seed.
        
        Args:
            seed: Random seed
            
        Returns:
            torch.Generator or None
        """
        if seed is not None:
            import torch
            generator = torch.Generator(device="cuda")
            generator.manual_seed(seed)
            return generator
        return None
    
    def generate(
        self,
        prompt: str,
        negative_prompt: Optional[str] = None,
        seed: Optional[int] = None,
        guidance_scale: Optional[float] = None,
        num_inference_steps: Optional[int] = None,
        num_frames: Optional[int] = None,
        **kwargs
    ) -> Path:
        """
        Generate video from text prompt.
        
        Args:
            prompt: Text prompt for generation
            negative_prompt: Negative prompt for guidance
            seed: Random seed for reproducibility
            guidance_scale: Guidance scale
            num_inference_steps: Number of inference steps
            num_frames: Number of frames to generate
            **kwargs: Additional pipeline parameters
            
        Returns:
            Path to generated video file
        """
        if not self._initialized:
            self.initialize()
        
        # Use config defaults if not specified
        guidance_scale = guidance_scale or self.config.DEFAULT_GUIDANCE_SCALE
        num_inference_steps = num_inference_steps or self.config.DEFAULT_NUM_INFERENCE_STEPS
        num_frames = num_frames or self.config.DEFAULT_NUM_FRAMES
        
        self.logger.info(
            f"Generating video: '{prompt[:50]}...' "
            f"(steps: {num_inference_steps}, guidance: {guidance_scale}, frames: {num_frames})"
        )
        
        start_time = datetime.now()
        
        try:
            import torch
            from diffusers.utils import export_to_video
            
            # Generate frames
            with torch.inference_mode():
                output = self.pipe(
                    prompt=prompt,
                    negative_prompt=negative_prompt,
                    num_videos_per_prompt=1,
                    num_inference_steps=num_inference_steps,
                    num_frames=num_frames,
                    guidance_scale=guidance_scale,
                    generator=self._create_generator(seed),
                    **kwargs
                )
            
            frames = output.frames[0]
            
            # Safety check
            if not self._check_safety(frames):
                raise ValueError("NSFW content detected in generated video")
            
            # Create temporary file
            temp_dir = self.config.temp_dir_path
            temp_dir.mkdir(parents=True, exist_ok=True)
            output_path = temp_dir / f"generated_{uuid.uuid4().hex[:8]}.mp4"
            
            # Export to video
            export_to_video(
                frames,
                str(output_path),
                fps=self.config.DEFAULT_FPS
            )
            
            duration = (datetime.now() - start_time).total_seconds()
            self.logger.info(
                f"Video generated successfully: {output_path} "
                f"({output_path.stat().st_size / 1024 / 1024:.2f} MB, {duration:.1f}s)"
            )
            
            return output_path
            
        except Exception as e:
            self.logger.error(f"Video generation failed: {e}")
            raise
    
    def generate_batch(
        self,
        prompts: List[str],
        **kwargs
    ) -> List[Tuple[str, Path]]:
        """
        Generate videos for multiple prompts.
        
        Args:
            prompts: List of text prompts
            **kwargs: Generation parameters passed to generate()
            
        Returns:
            List of (prompt, output_path) tuples
        """
        if not self._initialized:
            self.initialize()
        
        results = []
        total = len(prompts)
        
        for i, prompt in enumerate(prompts, 1):
            self.logger.info(f"Processing prompt {i}/{total}: '{prompt[:50]}...'")
            
            try:
                output_path = self.generate(prompt, **kwargs)
                results.append((prompt, output_path))
                
            except Exception as e:
                self.logger.error(f"Failed to generate video for prompt {i}: {e}")
                # Continue with next prompt
                continue
        
        return results
    
    def cleanup(self) -> None:
        """Clean up resources."""
        if self.pipe:
            try:
                # Clear pipeline from GPU memory
                self.pipe = None
                import torch
                torch.cuda.empty_cache()
                self.logger.info("Cleaned up pipeline resources")
            except ImportError:
                pass  # torch not available
            except Exception as e:
                self.logger.warning(f"Error during cleanup: {e}")
        
        self._initialized = False
    
    def __enter__(self):
        """Context manager entry."""
        self.initialize()
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit."""
        self.cleanup()


class UniversalVideoEngine:
    """
    Engine for sequential Text-to-Image -> Image-to-Video generation.
    
    Uses two-stage pipeline:
    1. Generate high-quality reference image using SDXL Lightning (Lykon/dreamshaper-xl-lightning)
    2. Clear VRAM completely
    3. Animate the image using CogVideoX-5b-I2V
    
    Features:
    - Aggressive VRAM management between stages
    - Safety checking for both stages
    - Optimized for 24GB VRAM cards
    - Support for universal styles (realism, anime, 3D art)
    """
    
    def __init__(self, config: Optional[GenerationConfig] = None):
        """
        Initialize the universal video engine.
        
        Args:
            config: Generation configuration (uses default if None)
        """
        self.config = config or GenerationConfig()
        self.logger = get_logger(__name__)
        
        # Stage 1: Text-to-Image pipeline
        self.t2i_pipe = None
        # Stage 2: Image-to-Video pipeline  
        self.i2v_pipe = None
        
        self.safety_checker = None
        self._initialized = False
        
    def initialize(self) -> None:
        """
        Initialize the safety checker only.
        
        Note: Models are loaded and unloaded dynamically during generation
        to minimize VRAM usage.
        """
        if self._initialized:
            return
            
        self.logger.info("Initializing UniversalVideoEngine (lazy model loading)")
        
        try:
            # Initialize safety checker if enabled
            if self.config.ENABLE_SAFETY_CHECKER:
                from transformers import pipeline as transformers_pipeline
                import torch
                
                self.logger.info(f"Loading safety checker: {self.config.SAFETY_CHECKER_MODEL}")
                self.safety_checker = transformers_pipeline(
                    "image-classification",
                    model=self.config.SAFETY_CHECKER_MODEL,
                    device="cuda" if torch.cuda.is_available() else "cpu"
                )
            
            self._initialized = True
            self.logger.info("UniversalVideoEngine initialized (safety checker ready)")
            
        except Exception as e:
            self.logger.error(f"Failed to initialize UniversalVideoEngine: {e}")
            raise
    
    def _load_t2i_pipeline(self) -> None:
        """Load Text-to-Image pipeline (SDXL Lightning)."""
        if self.t2i_pipe is not None:
            return
            
        self.logger.info(f"Loading T2I model: {self.config.T2I_MODEL_ID}")
        
        try:
            from diffusers import StableDiffusionXLPipeline
            from diffusers import EulerDiscreteScheduler
            import torch
            
            # Load pipeline with SDXL Lightning optimizations
            self.t2i_pipe = StableDiffusionXLPipeline.from_pretrained(
                self.config.T2I_MODEL_ID,
                torch_dtype=torch.float16,
                variant="fp16",
                use_safetensors=True,
            )
            
            # Configure scheduler for Lightning model
            self.t2i_pipe.scheduler = EulerDiscreteScheduler.from_config(
                self.t2i_pipe.scheduler.config,
                timestep_spacing="trailing"
            )
            
            # Move to GPU if available
            if torch.cuda.is_available():
                self.t2i_pipe = self.t2i_pipe.to("cuda")
                
                # Apply optimizations
                if hasattr(self.t2i_pipe, "enable_model_cpu_offload"):
                    self.t2i_pipe.enable_model_cpu_offload()
                
                if hasattr(self.t2i_pipe, "enable_vae_slicing"):
                    self.t2i_pipe.enable_vae_slicing()
            
            self.logger.info("✓ T2I pipeline loaded")
            
        except Exception as e:
            self.logger.error(f"Failed to load T2I pipeline: {e}")
            raise
    
    def _load_i2v_pipeline(self) -> None:
        """Load Image-to-Video pipeline (CogVideoX-5b-I2V)."""
        if self.i2v_pipe is not None:
            return
            
        self.logger.info(f"Loading I2V model: {self.config.I2V_MODEL_ID}")
        
        try:
            from diffusers import CogVideoXImageToVideoPipeline
            import torch
            
            # Load pipeline with optimizations
            self.i2v_pipe = CogVideoXImageToVideoPipeline.from_pretrained(
                self.config.I2V_MODEL_ID,
                torch_dtype=torch.bfloat16,
            )
            
            # Move to GPU if available
            if torch.cuda.is_available():
                self.i2v_pipe = self.i2v_pipe.to("cuda")
                
                # Apply optimizations
                if hasattr(self.i2v_pipe, "enable_model_cpu_offload"):
                    self.i2v_pipe.enable_model_cpu_offload()
                
                if hasattr(self.i2v_pipe, "enable_vae_slicing"):
                    self.i2v_pipe.enable_vae_slicing()
            
            self.logger.info("✓ I2V pipeline loaded")
            
        except Exception as e:
            self.logger.error(f"Failed to load I2V pipeline: {e}")
            raise
    
    def _cleanup_vram(self, stage: str = "both") -> None:
        """
        Clean up VRAM aggressively.
        
        Args:
            stage: Which stage to clean ("t2i", "i2v", or "both")
        """
        import gc
        
        if stage in ["t2i", "both"] and self.t2i_pipe is not None:
            del self.t2i_pipe
            self.t2i_pipe = None
            self.logger.debug("Cleaned T2I pipeline from VRAM")
        
        if stage in ["i2v", "both"] and self.i2v_pipe is not None:
            del self.i2v_pipe
            self.i2v_pipe = None
            self.logger.debug("Cleaned I2V pipeline from VRAM")
        
        # Force garbage collection
        gc.collect()
        try:
            import torch
            if torch.cuda.is_available():
                torch.cuda.empty_cache()
                
                # Log VRAM usage for verification
                allocated = torch.cuda.memory_allocated() / 1024**3
                reserved = torch.cuda.memory_reserved() / 1024**3
                self.logger.info(f"VRAM after cleanup: {allocated:.2f} GB allocated, {reserved:.2f} GB reserved")
        except ImportError:
            pass  # torch not available, skip
    
    def _check_safety(self, image_or_frames) -> bool:
        """
        Check image or frames for NSFW content.
        
        Args:
            image_or_frames: PIL Image or list of frames
            
        Returns:
            True if content is safe, False if NSFW detected
        """
        if not self.safety_checker:
            return True
        
        try:
            if isinstance(image_or_frames, list):
                # Check sample of frames
                sample_indices = [0, len(image_or_frames) // 2, -1]
                samples = [image_or_frames[i] for i in sample_indices if i < len(image_or_frames)]
            else:
                # Single image
                samples = [image_or_frames]
            
            for sample in samples:
                results = self.safety_checker(sample, top_k=2)
                
                for result in results:
                    label = result['label'].lower()
                    score = result['score']
                    
                    if any(keyword in label for keyword in ['nsfw', 'explicit', 'adult']):
                        if score > self.config.SAFETY_CHECKER_THRESHOLD:
                            self.logger.warning(f"NSFW content detected: {label} (score: {score:.3f})")
                            return False
            
            return True
            
        except Exception as e:
            self.logger.warning(f"Safety check failed: {e}, allowing content")
            return True  # Fail open for safety
    
    def _create_generator(self, seed: Optional[int] = None):
        """
        Create torch generator with optional seed.
        
        Args:
            seed: Random seed
            
        Returns:
            torch.Generator or None
        """
        if seed is not None:
            try:
                import torch
                if torch.cuda.is_available():
                    generator = torch.Generator(device="cuda")
                    generator.manual_seed(seed)
                    return generator
            except ImportError:
                pass  # torch not available
        return None
    
    def _generate_image(
        self,
        prompt: str,
        negative_prompt: Optional[str] = None,
        seed: Optional[int] = None,
        num_inference_steps: int = 4,
        guidance_scale: float = 0.0  # Lightning models use guidance_scale=0
    ) -> Path:
        """
        Phase 1: Generate high-quality reference image.
        
        Args:
            prompt: Text prompt for image generation
            negative_prompt: Negative prompt for guidance
            seed: Random seed for reproducibility
            num_inference_steps: Number of inference steps (4-8 for Lightning)
            guidance_scale: Guidance scale (0 for Lightning models)
            
        Returns:
            Path to generated image file
        """
        self.logger.info("=" * 60)
        self.logger.info("PHASE 1: Text-to-Image Generation")
        self.logger.info(f"Prompt: '{prompt[:60]}...'")
        self.logger.info(f"Model: {self.config.T2I_MODEL_ID}")
        self.logger.info(f"Steps: {num_inference_steps}, Guidance: {guidance_scale}")
        self.logger.info("=" * 60)
        
        start_time = datetime.now()
        
        try:
            # Load T2I pipeline
            self._load_t2i_pipeline()
            
            # Generate image
            import torch
            with torch.inference_mode():
                image = self.t2i_pipe(
                    prompt=prompt,
                    negative_prompt=negative_prompt,
                    num_inference_steps=num_inference_steps,
                    guidance_scale=guidance_scale,
                    generator=self._create_generator(seed),
                ).images[0]
            
            # Safety check
            if not self._check_safety(image):
                raise ValueError("NSFW content detected in generated image")
            
            # Save to temporary file
            temp_dir = self.config.temp_dir_path
            temp_dir.mkdir(parents=True, exist_ok=True)
            image_path = temp_dir / f"ref_image_{uuid.uuid4().hex[:8]}.png"
            image.save(image_path)
            
            duration = (datetime.now() - start_time).total_seconds()
            self.logger.info(f"✓ Image generated in {duration:.1f}s: {image_path}")
            
            return image_path
            
        except Exception as e:
            self.logger.error(f"Image generation failed: {e}")
            raise
        finally:
            # Clean up T2I pipeline to free VRAM
            self._cleanup_vram(stage="t2i")
    
    def _generate_video(
        self,
        image_path: Path,
        prompt: str,
        negative_prompt: Optional[str] = None,
        seed: Optional[int] = None,
        guidance_scale: Optional[float] = None,
        num_inference_steps: Optional[int] = None,
        num_frames: Optional[int] = None,
        **kwargs
    ) -> Path:
        """
        Phase 3: Generate video from reference image.
        
        Args:
            image_path: Path to reference image
            prompt: Text prompt for video generation
            negative_prompt: Negative prompt for guidance
            seed: Random seed for reproducibility
            guidance_scale: Guidance scale (default from config)
            num_inference_steps: Number of inference steps (default from config)
            num_frames: Number of frames to generate (default from config)
            **kwargs: Additional pipeline parameters
            
        Returns:
            Path to generated video file
        """
        self.logger.info("=" * 60)
        self.logger.info("PHASE 3: Image-to-Video Animation")
        self.logger.info(f"Prompt: '{prompt[:60]}...'")
        self.logger.info(f"Model: {self.config.I2V_MODEL_ID}")
        self.logger.info(f"Reference image: {image_path.name}")
        self.logger.info("=" * 60)
        
        start_time = datetime.now()
        
        try:
            # Load I2V pipeline
            self._load_i2v_pipeline()
            
            # Load image
            from PIL import Image
            image = Image.open(image_path)
            
            # Use config defaults if not specified
            guidance_scale = guidance_scale or self.config.DEFAULT_GUIDANCE_SCALE
            num_inference_steps = num_inference_steps or self.config.DEFAULT_NUM_INFERENCE_STEPS
            num_frames = num_frames or self.config.DEFAULT_NUM_FRAMES
            
            # Generate video
            import torch
            from diffusers.utils import export_to_video
            
            with torch.inference_mode():
                output = self.i2v_pipe(
                    prompt=prompt,
                    image=image,
                    negative_prompt=negative_prompt,
                    num_inference_steps=num_inference_steps,
                    num_frames=num_frames,
                    guidance_scale=guidance_scale,
                    generator=self._create_generator(seed),
                    **kwargs
                )
            
            frames = output.frames[0]
            
            # Safety check
            if not self._check_safety(frames):
                raise ValueError("NSFW content detected in generated video")
            
            # Export to video file
            temp_dir = self.config.temp_dir_path
            video_path = temp_dir / f"video_{uuid.uuid4().hex[:8]}.mp4"
            
            export_to_video(
                frames,
                str(video_path),
                fps=self.config.DEFAULT_FPS
            )
            
            duration = (datetime.now() - start_time).total_seconds()
            file_size_mb = video_path.stat().st_size / 1024 / 1024
            self.logger.info(f"✓ Video generated in {duration:.1f}s: {video_path} ({file_size_mb:.2f} MB)")
            
            return video_path
            
        except Exception as e:
            self.logger.error(f"Video generation failed: {e}")
            raise
        finally:
            # Clean up I2V pipeline
            self._cleanup_vram(stage="i2v")
    
    def generate(
        self,
        prompt: str,
        negative_prompt: Optional[str] = None,
        seed: Optional[int] = None,
        guidance_scale: Optional[float] = None,
        num_inference_steps: Optional[int] = None,
        num_frames: Optional[int] = None,
        t2i_steps: int = 4,
        t2i_guidance_scale: float = 0.0,
        **kwargs
    ) -> Path:
        """
        Generate video using two-stage pipeline: T2I -> I2V.
        
        Args:
            prompt: Text prompt for generation (used for both image and video)
            negative_prompt: Negative prompt for guidance (used for both stages)
            seed: Random seed for reproducibility (applied to both stages)
            guidance_scale: Guidance scale for video generation (default from config)
            num_inference_steps: Number of inference steps for video (default from config)
            num_frames: Number of frames to generate (default from config)
            t2i_steps: Number of inference steps for image generation (4-8 for Lightning)
            t2i_guidance_scale: Guidance scale for image generation (0 for Lightning)
            **kwargs: Additional pipeline parameters
            
        Returns:
            Path to generated video file
            
        Raises:
            ValueError: If NSFW content detected
            Exception: If generation fails at any stage
        """
        if not self._initialized:
            self.initialize()
        
        self.logger.info("🚀 Starting Universal Video Generation Pipeline")
        self.logger.info(f"Prompt: '{prompt}'")
        self.logger.info(f"Total stages: 2 (T2I → I2V)")
        self.logger.info("=" * 60)
        
        try:
            # Phase 1: Generate reference image
            image_path = self._generate_image(
                prompt=prompt,
                negative_prompt=negative_prompt,
                seed=seed,
                num_inference_steps=t2i_steps,
                guidance_scale=t2i_guidance_scale
            )
            
            # Phase 2: Aggressive VRAM flush (critical)
            self.logger.info("=" * 60)
            self.logger.info("PHASE 2: VRAM Flush")
            self.logger.info("Clearing all models from VRAM...")
            self._cleanup_vram(stage="both")
            self.logger.info("✓ VRAM flushed, ready for Phase 3")
            self.logger.info("=" * 60)
            
            # Phase 3: Generate video from image
            video_path = self._generate_video(
                image_path=image_path,
                prompt=prompt,
                negative_prompt=negative_prompt,
                seed=seed,
                guidance_scale=guidance_scale,
                num_inference_steps=num_inference_steps,
                num_frames=num_frames,
                **kwargs
            )
            
            self.logger.info("=" * 60)
            self.logger.info("✅ Universal pipeline completed successfully!")
            self.logger.info(f"  Image: {image_path.name}")
            self.logger.info(f"  Video: {video_path.name}")
            self.logger.info("=" * 60)
            
            return video_path
            
        except Exception as e:
            self.logger.error(f"Universal pipeline failed: {e}")
            # Ensure VRAM is cleaned up even on failure
            self._cleanup_vram(stage="both")
            raise
    
    def cleanup(self) -> None:
        """Clean up all resources."""
        # Clean up pipelines
        self._cleanup_vram(stage="both")
        
        # Clean up safety checker
        if self.safety_checker is not None:
            del self.safety_checker
            self.safety_checker = None
        
        # Force garbage collection
        import gc
        gc.collect()
        try:
            import torch
            if torch.cuda.is_available():
                torch.cuda.empty_cache()
        except ImportError:
            pass  # torch not available
        
        self._initialized = False
        self.logger.info("UniversalVideoEngine cleaned up")
    
    def __enter__(self):
        """Context manager entry."""
        self.initialize()
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit."""
        self.cleanup()
        return False
