"""
Data models for text-to-video generation.
"""

import json
import uuid
from typing import List, Optional, Dict, Any
from datetime import datetime
from pydantic import BaseModel, Field, validator


class GenJob(BaseModel):
    """
    Generation job specification.
    
    Supports batch processing of multiple prompts.
    """
    
    id: str = Field(
        default_factory=lambda: str(uuid.uuid4()),
        description="Unique job identifier"
    )
    prompts: List[str] = Field(
        ...,
        description="List of text prompts to generate videos from",
        min_items=1,
        max_items=100
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
    output_prefix: str = Field(
        "generated/",
        description="Prefix for output files in storage"
    )
    metadata: Dict[str, Any] = Field(
        default_factory=dict,
        description="Additional metadata for the job"
    )
    created_at: datetime = Field(
        default_factory=datetime.utcnow,
        description="Job creation timestamp"
    )
    
    @validator('prompts')
    def validate_prompts(cls, v):
        """Validate prompts are not empty."""
        for i, prompt in enumerate(v):
            if not prompt or not prompt.strip():
                raise ValueError(f"Prompt {i} is empty")
            if len(prompt.strip()) > 1000:
                raise ValueError(f"Prompt {i} is too long (max 1000 chars)")
        return v
    
    @validator('output_prefix')
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
        return self.json()
    
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
        return f"{self.output_prefix}{self.id}_{index}_{prompt_hash}.{extension}"


class GenerationResult(BaseModel):
    """
    Result of a single video generation.
    """
    
    job_id: str = Field(..., description="Job identifier")
    prompt_index: int = Field(..., description="Index of the prompt in the batch")
    prompt: str = Field(..., description="Text prompt used")
    output_key: str = Field(..., description="Storage key for the generated video")
    url: Optional[str] = Field(None, description="Presigned URL for download")
    size_bytes: Optional[int] = Field(None, description="File size in bytes")
    duration_seconds: Optional[float] = Field(None, description="Video duration")
    generated_at: datetime = Field(default_factory=datetime.utcnow)
    success: bool = Field(True, description="Whether generation was successful")
    error: Optional[str] = Field(None, description="Error message if failed")


class BatchGenerationResult(BaseModel):
    """
    Result of a batch generation job.
    """
    
    job_id: str = Field(..., description="Job identifier")
    total_prompts: int = Field(..., description="Total number of prompts")
    successful: int = Field(..., description="Number of successful generations")
    failed: int = Field(..., description="Number of failed generations")
    results: List[GenerationResult] = Field(default_factory=list)
    started_at: datetime = Field(default_factory=datetime.utcnow)
    completed_at: Optional[datetime] = Field(None)
    
    @property
    def duration_seconds(self) -> Optional[float]:
        """Get total duration in seconds."""
        if self.completed_at:
            return (self.completed_at - self.started_at).total_seconds()
        return None
