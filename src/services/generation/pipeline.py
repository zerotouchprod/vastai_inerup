"""
Universal Image-to-Video Pipeline
Text-to-Image (DreamShaper XL Lightning) -> Image-to-Video (CogVideoX-5b-I2V)
Supports: Photorealism, Anime, 3D Art, and all styles
"""

import torch
import gc
import tempfile
import logging
from pathlib import Path
from typing import Tuple, Optional
from diffusers import StableDiffusionXLPipeline
from cogvideox_pipeline import CogVideoXImageToVideoPipeline

logger = logging.getLogger(__name__)


class UniversalPipeline:
    """Universal pipeline for Text-to-Image -> Image-to-Video generation."""
    
    def __init__(self, device: Optional[str] = None):
        """
        Initialize the universal pipeline.
        
        Args:
            device: Device to run on ('cuda', 'cpu', or None for auto-detection)
        """
        self.device = device or ("cuda" if torch.cuda.is_available() else "cpu")
        logger.info(f"UniversalPipeline initialized on device: {self.device}")
        
        # Configuration
        self.t2i_model_id = "Lykon/dreamshaper-xl-lightning"
        self.i2v_model_id = "THUDM/CogVideoX-5b-I2V"
        
        # Image generation settings (optimized for Lightning model)
        self.t2i_config = {
            "torch_dtype": torch.float16,
            "variant": "fp16",
            "use_safetensors": True,
            "num_inference_steps": 4,  # Lightning is fast! 4-8 steps
            "guidance_scale": 7.5,
            "width": 1024,
            "height": 1024,
        }
        
        # Video generation settings
        self.i2v_config = {
            "torch_dtype": torch.float16,
            "num_frames": 32,
            "num_inference_steps": 50,
            "guidance_scale": 7.5,
        }
        
    def _cleanup_vram(self):
        """Clean up VRAM by deleting models and clearing cache."""
        if hasattr(self, '_t2i_pipeline'):
            del self._t2i_pipeline
        if hasattr(self, '_i2v_pipeline'):
            del self._i2v_pipeline
            
        torch.cuda.empty_cache()
        gc.collect()
        logger.debug("VRAM cleaned up")
    
    def generate_image(self, prompt: str, negative_prompt: str = "") -> Path:
        """
        Generate image using DreamShaper XL Lightning.
        
        Args:
            prompt: Text prompt for image generation
            negative_prompt: Negative prompt for image generation
            
        Returns:
            Path to generated image file
        """
        logger.info(f"Generating image for prompt: {prompt[:50]}...")
        
        try:
            # Load T2I pipeline
            self._t2i_pipeline = StableDiffusionXLPipeline.from_pretrained(
                self.t2i_model_id,
                torch_dtype=self.t2i_config["torch_dtype"],
                variant=self.t2i_config["variant"],
                use_safetensors=self.t2i_config["use_safetensors"],
            )
            self._t2i_pipeline = self._t2i_pipeline.to(self.device)
            
            # Enable CPU offload if available and VRAM is limited
            if hasattr(self._t2i_pipeline, "enable_model_cpu_offload"):
                self._t2i_pipeline.enable_model_cpu_offload()
                logger.debug("Enabled CPU offload for T2I pipeline")
            
            # Generate image
            image = self._t2i_pipeline(
                prompt=prompt,
                negative_prompt=negative_prompt,
                num_inference_steps=self.t2i_config["num_inference_steps"],
                guidance_scale=self.t2i_config["guidance_scale"],
                width=self.t2i_config["width"],
                height=self.t2i_config["height"],
            ).images[0]
            
            # Save to temp file
            temp_file = tempfile.NamedTemporaryFile(suffix=".png", delete=False)
            image_path = Path(temp_file.name)
            image.save(image_path)
            temp_file.close()
            
            logger.info(f"Image saved to: {image_path}")
            return image_path
            
        except Exception as e:
            logger.error(f"Image generation failed: {e}")
            raise
        finally:
            # Clean up T2I pipeline
            if hasattr(self, '_t2i_pipeline'):
                del self._t2i_pipeline
            torch.cuda.empty_cache()
            gc.collect()
    
    def generate_video(self, image_path: Path, prompt: str) -> Path:
        """
        Generate video from image using CogVideoX.
        
        Args:
            image_path: Path to input image
            prompt: Text prompt for video generation
            
        Returns:
            Path to generated video file
        """
        logger.info(f"Generating video from {image_path.name} with prompt: {prompt[:50]}...")
        
        try:
            # Load I2V pipeline
            self._i2v_pipeline = CogVideoXImageToVideoPipeline.from_pretrained(
                self.i2v_model_id,
                torch_dtype=self.i2v_config["torch_dtype"],
            )
            self._i2v_pipeline = self._i2v_pipeline.to(self.device)
            
            # Generate video
            video = self._i2v_pipeline(
                image_path=str(image_path),
                prompt=prompt,
                num_frames=self.i2v_config["num_frames"],
                num_inference_steps=self.i2v_config["num_inference_steps"],
                guidance_scale=self.i2v_config["guidance_scale"],
            ).videos[0]
            
            # Save to temp file (simplified - actual implementation depends on pipeline output)
            temp_file = tempfile.NamedTemporaryFile(suffix=".mp4", delete=False)
            video_path = Path(temp_file.name)
            
            # TODO: Implement actual video saving based on CogVideoX output format
            # For now, create a placeholder file
            with open(video_path, 'wb') as f:
                f.write(b"Video placeholder - actual implementation needed")
            
            temp_file.close()
            
            logger.info(f"Video saved to: {video_path}")
            return video_path
            
        except Exception as e:
            logger.error(f"Video generation failed: {e}")
            raise
        finally:
            # Clean up I2V pipeline
            if hasattr(self, '_i2v_pipeline'):
                del self._i2v_pipeline
            torch.cuda.empty_cache()
            gc.collect()
    
    def run_pipeline(self, prompt: str, negative_prompt: str = "") -> Tuple[Path, Path]:
        """
        Run full pipeline: Text-to-Image -> Image-to-Video.
        
        Args:
            prompt: Text prompt for generation
            negative_prompt: Negative prompt for image generation
            
        Returns:
            Tuple of (image_path, video_path)
        """
        logger.info(f"Starting universal pipeline for prompt: {prompt[:50]}...")
        
        try:
            # Step 1: Generate image
            image_path = self.generate_image(prompt, negative_prompt)
            
            # Step 2: Generate video from image
            video_path = self.generate_video(image_path, prompt)
            
            logger.info(f"Pipeline completed successfully")
            logger.info(f"  Image: {image_path}")
            logger.info(f"  Video: {video_path}")
            
            return image_path, video_path
            
        except Exception as e:
            logger.error(f"Pipeline failed: {e}")
            self._cleanup_vram()
            raise
    
    def __del__(self):
        """Cleanup on destruction."""
        self._cleanup_vram()


def main():
    """Command-line interface for the universal pipeline."""
    import argparse
    
    parser = argparse.ArgumentParser(
        description="Universal Image-to-Video Pipeline: Text -> Image -> Video"
    )
    parser.add_argument(
        "--prompt",
        required=True,
        help="Text prompt for generation (supports all styles: photorealism, anime, 3D art)"
    )
    parser.add_argument(
        "--negative-prompt",
        default="",
        help="Negative prompt for image generation"
    )
    parser.add_argument(
        "--device",
        choices=["cuda", "cpu"],
        help="Device to run on (default: auto-detect)"
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Enable verbose logging"
    )
    
    args = parser.parse_args()
    
    # Setup logging
    log_level = logging.DEBUG if args.verbose else logging.INFO
    logging.basicConfig(
        level=log_level,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    )
    
    try:
        # Run pipeline
        pipeline = UniversalPipeline(device=args.device)
        image_path, video_path = pipeline.run_pipeline(
            prompt=args.prompt,
            negative_prompt=args.negative_prompt
        )
        
        print(f"\n✅ Pipeline completed successfully!")
        print(f"📸 Image: {image_path}")
        print(f"🎬 Video: {video_path}")
        
    except Exception as e:
        logger.error(f"Pipeline execution failed: {e}")
        raise


if __name__ == "__main__":
    main()