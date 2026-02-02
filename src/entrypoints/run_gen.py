#!/usr/bin/env python3
"""
Entry point for video generation worker (Text-to-Video & Image-to-Video).

This script implements a "run & die" worker that:
1. Parses a JSON job specification from CLI arguments
2. Initializes the generation engine (T2V or I2V based on mode)
3. Processes all prompts in the job
4. Uploads results to B2/S3 storage
5. Outputs results as JSON to stdout
6. Exits with appropriate status code

Usage:
    # Text-to-Video
    python -m src.entrypoints.run_gen --job '{"prompts": ["A cat dancing"]}'

    # Image-to-Video (Phase 2)
    python -m src.entrypoints.run_gen --job '{
      "mode": "image2video",
      "prompts": ["Make it dance"],
      "input_images": ["https://example.com/cat.jpg"]
    }'
"""

import argparse
import json
import sys
import os
from pathlib import Path

# Add src to Python path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from src.services.generation.models import GenJob
from src.services.generation.orchestrator import GenerationOrchestrator
from src.services.generation.config import GenerationConfig
from src.shared.logging import setup_logger, get_logger


def parse_arguments():
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(
        description="Video Generation Worker (Text-to-Video & Image-to-Video)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Text-to-Video (single prompt)
  python -m src.entrypoints.run_gen --job '{"prompts": ["A cat dancing"]}'
  
  # Batch generation with custom parameters
  python -m src.entrypoints.run_gen --job '{
    "prompts": ["Sunset over ocean", "City at night"],
    "guidance_scale": 7.0,
    "num_inference_steps": 30,
    "output_prefix": "videos/batch1/"
  }'
  
  # Dry run (validation only)
  python -m src.entrypoints.run_gen --job '{"prompts": ["test"]}' --dry-run
        """
    )
    
    parser.add_argument(
        "--job",
        type=str,
        required=True,
        help="JSON string containing job specification"
    )
    
    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="Enable verbose logging"
    )
    
    parser.add_argument(
        "--config",
        type=Path,
        help="Path to configuration file (YAML/JSON)"
    )
    
    parser.add_argument(
        "--no-upload",
        action="store_true",
        help="Skip B2 upload (for testing)"
    )
    
    parser.add_argument(
        "--output-format",
        choices=["json", "minimal"],
        default="json",
        help="Output format (default: json)"
    )
    
    return parser.parse_args()


def setup_environment():
    """Setup environment variables and paths."""
    # Ensure temp directory exists
    temp_dir = Path("/tmp/generation")
    temp_dir.mkdir(parents=True, exist_ok=True)
    
    # Set HuggingFace cache if not set
    if "HF_HOME" not in os.environ:
        os.environ["HF_HOME"] = "/root/.cache/huggingface"
    
    # Enable torch inference mode optimization
    os.environ["TORCH_INFERENCE_MODE"] = "1"


def main():
    """Main entry point."""
    args = parse_arguments()
    
    # Setup logging
    log_level = "DEBUG" if args.verbose else "INFO"
    setup_logger("generation", level=log_level)
    logger = get_logger(__name__)
    
    # Setup environment
    setup_environment()
    
    logger.info("=" * 60)
    logger.info("Text-to-Video Generation Worker")
    logger.info("=" * 60)
    
    try:
        # Parse job
        logger.info(f"Parsing job specification")
        job = GenJob.from_json(args.job)
        logger.info(f"Job ID: {job.id}")
        logger.info(f"Prompts: {len(job.prompts)}")
        logger.info(f"Output prefix: {job.output_prefix}")
        
        # Load configuration
        config = GenerationConfig()
        if args.config and args.config.exists():
            # TODO: Implement config file loading
            logger.info(f"Using config file: {args.config}")
        
        # Initialize orchestrator
        logger.info("Initializing orchestrator...")
        orchestrator = GenerationOrchestrator(config=config)
        
        # Process job
        logger.info(f"Processing job {job.id}...")
        result = orchestrator.process_job(job)
        
        # Prepare output
        output_data = {
            "job_id": result.job_id,
            "success": result.failed == 0,
            "total_prompts": result.total_prompts,
            "successful": result.successful,
            "failed": result.failed,
            "duration_seconds": result.duration_seconds,
            "results": []
        }
        
        # Add result details based on output format
        if args.output_format == "json":
            output_data["results"] = [
                {
                    "prompt_index": r.prompt_index,
                    "prompt": r.prompt[:100] + "..." if len(r.prompt) > 100 else r.prompt,
                    "output_key": r.output_key,
                    "url": r.url,
                    "size_bytes": r.size_bytes,
                    "success": r.success,
                    "error": r.error
                }
                for r in result.results
            ]
        
        # Output results
        if args.output_format == "minimal":
            # Minimal output for orchestration
            print(json.dumps({
                "job_id": result.job_id,
                "success": result.failed == 0,
                "total": result.total_prompts,
                "successful": result.successful,
                "failed": result.failed
            }))
        else:
            # Full JSON output
            print(json.dumps(output_data, indent=2))
        
        # Log summary
        if result.failed == 0:
            logger.info(f"✅ Job {job.id} completed successfully")
            logger.info(f"   Generated: {result.successful} videos")
            if result.duration_seconds:
                logger.info(f"   Duration: {result.duration_seconds:.1f}s")
        else:
            logger.warning(f"⚠️  Job {job.id} completed with {result.failed} failures")
            for r in result.results:
                if not r.success:
                    logger.warning(f"   Prompt {r.prompt_index}: {r.error}")
        
        # Return appropriate exit code
        return 0 if result.failed == 0 else 1
        
    except json.JSONDecodeError as e:
        logger.error(f"Invalid JSON in --job argument: {e}")
        print(json.dumps({
            "success": False,
            "error": f"Invalid JSON: {e}"
        }))
        return 1
        
    except ValueError as e:
        logger.error(f"Invalid job specification: {e}")
        print(json.dumps({
            "success": False,
            "error": f"Invalid job: {e}"
        }))
        return 1
        
    except KeyboardInterrupt:
        logger.warning("Interrupted by user")
        return 130
        
    except Exception as e:
        logger.error(f"Unexpected error: {e}", exc_info=args.verbose)
        print(json.dumps({
            "success": False,
            "error": str(e)
        }))
        return 1
        
    finally:
        logger.info("=" * 60)
        logger.info("Worker finished")
        logger.info("=" * 60)


if __name__ == "__main__":
    sys.exit(main())
