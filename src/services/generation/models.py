"""
Data models for video generation (Text-to-Video & Image-to-Video).
"""

import json
import uuid
from enum import Enum
from typing import List, Optional, Dict, Any
from datetime import datetime, timezone
from pathlib import Path
from pydantic import BaseModel, Field, field_validator, model_validator


class GenerationMode(str, Enum):
    """Video generation modes."""
    UNIVERSAL = "universal"      # Two-stage: T2I → I2V
    IMAGE2VIDEO = "image2video"  # Single-stage: Image → Video


class GenJob(BaseModel):
    """
    Generation job specification.
    
    Supports batch processing of multiple prompts in both T2V and I2V modes.
    """
    
    id: str = Field(
        default_factory=lambda: str(uuid.uuid4()),
        description="Unique job identifier"
    )
    mode: GenerationMode = Field(
        default=GenerationMode.UNIVERSAL,
        description="Generation mode: universal (T2I→I2V) or image2video (Image→Video)"
    )
    prompts: List[str] = Field(
        ...,
        description="List of text prompts to generate videos from",
        min_length=1,
        max_length=100
    )
    input_images: Optional[List[str]] = Field(
        None,
        description="Input images for I2V mode (URLs, paths, or base64)"
    )
    negative_prompt: Optional[str] = Field(
        None,
        description="Negative prompt for guidance"
    )
    seed: Optional[int] = Field(
        None,
        description="Random seed for reproducibility"
    )
    guidance_scale: float = Field(
        6.0,
        description="Guidance scale for generation",
        ge=1.0,
        le=20.0
    )
    num_inference_steps: int = Field(
        50,
        description="Number of inference steps",
        ge=10,
        le=200
    )
    num_frames: int = Field(
        49,
        description="Number of frames to generate",
        ge=1,
        le=96
    )
    fps: int = Field(
        8,
        description="Output video FPS",
        ge=1,
        le=30
    )
    output_prefix: str = Field(
        "generated/",
        description="Prefix for output files in storage"
    )
    metadata: Dict[str, Any] = Field(
        default_factory=dict,
        description="Additional metadata for the job"
    )
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        description="Job creation timestamp"
    )
    
    @field_validator('prompts')
    @classmethod
    def validate_prompts(cls, v):
        """Validate prompts are not empty."""
        for i, prompt in enumerate(v):
            if not prompt or not prompt.strip():
                raise ValueError(f"Prompt {i} is empty")
            if len(prompt.strip()) > 1000:
                raise ValueError(f"Prompt {i} is too long (max 1000 chars)")
        return v
    
    @field_validator('input_images')
    @classmethod
    def validate_input_images(cls, v, info):
        """Validate input_images for I2V mode."""
        data = info.data
        mode = data.get('mode')
        prompts = data.get('prompts', [])

        if mode == GenerationMode.IMAGE2VIDEO:
            if not v:
                raise ValueError("input_images required for image2video mode")
            if len(v) != len(prompts):
                raise ValueError(
                    f"input_images count ({len(v)}) must match prompts count ({len(prompts)})"
                )
        elif mode == GenerationMode.UNIVERSAL and v:
            raise ValueError("input_images not allowed for universal mode (uses text prompts only)")

        return v

    @model_validator(mode='after')
    def check_i2v_requires_images(self) -> "GenJob":
        """Ensure IMAGE2VIDEO mode always has input_images (catches missing field case)."""
        if self.mode == GenerationMode.IMAGE2VIDEO and not self.input_images:
            raise ValueError("input_images required for image2video mode")
        return self

    @field_validator('output_prefix')
    @classmethod
    def validate_output_prefix(cls, v):
        """Ensure output prefix ends with slash if not empty."""
        if v and not v.endswith('/'):
            return v + '/'
        return v
    
    @classmethod
    def from_json(cls, json_str: str) -> "GenJob":
        """
        Create GenJob from JSON string.
        
        Args:
            json_str: JSON string representation
            
        Returns:
            GenJob instance
        """
        try:
            data = json.loads(json_str)
            return cls(**data)
        except json.JSONDecodeError as e:
            raise ValueError(f"Invalid JSON: {e}")
        except Exception as e:
            raise ValueError(f"Failed to parse GenJob: {e}")
    
    def to_json(self) -> str:
        """
        Convert GenJob to JSON string.
        
        Returns:
            JSON string representation
        """
        return self.model_dump_json()

    def get_output_key(self, index: int, extension: str = "mp4") -> str:
        """
        Get output key for a specific prompt in the batch.
        
        Args:
            index: Prompt index in the batch
            extension: File extension
            
        Returns:
            Storage key for the output file
        """
        if index < 0 or index >= len(self.prompts):
            raise ValueError(f"Invalid prompt index: {index}")
        
        prompt_hash = str(uuid.uuid5(uuid.NAMESPACE_DNS, self.prompts[index]))[:8]
        mode_prefix = "universal" if self.mode == GenerationMode.UNIVERSAL else "i2v"
        return f"{self.output_prefix}{mode_prefix}_{self.id}_{index}_{prompt_hash}.{extension}"


class GenerationResult(BaseModel):
    """
    Result of a single video generation.
    """
    
    job_id: str = Field(..., description="Job identifier")
    prompt_index: int = Field(..., description="Index of the prompt in the batch")
    prompt: str = Field(..., description="Text prompt used")
    mode: GenerationMode = Field(..., description="Generation mode used")
    output_key: str = Field(..., description="Storage key for the generated video")
    url: Optional[str] = Field(None, description="Presigned URL for download")
    local_path: Optional[Path] = Field(None, description="Local path (if not uploaded)")
    size_bytes: Optional[int] = Field(None, description="File size in bytes")
    duration_seconds: Optional[float] = Field(None, description="Video duration")
    num_frames: Optional[int] = Field(None, description="Number of frames")
    generated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    success: bool = Field(True, description="Whether generation was successful")
    error: Optional[str] = Field(None, description="Error message if failed")


class BatchGenerationResult(BaseModel):
    """
    Result of a batch generation job.
    """
    
    job_id: str = Field(..., description="Job identifier")
    mode: GenerationMode = Field(..., description="Generation mode")
    total_prompts: int = Field(..., description="Total number of prompts")
    successful: int = Field(0, description="Number of successful generations")
    failed: int = Field(0, description="Number of failed generations")
    results: List[GenerationResult] = Field(default_factory=list)
    started_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    completed_at: Optional[datetime] = Field(None)
    
    @property
    def duration_seconds(self) -> Optional[float]:
        """Get total duration in seconds."""
        if self.completed_at:
            return (self.completed_at - self.started_at).total_seconds()
        return None
