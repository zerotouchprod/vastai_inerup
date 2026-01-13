"""
Native Python implementation of RIFE interpolation processing.

Replaces run_rife_pytorch.sh with pure Python code.
Provides same functionality but with full Python debugging support.

Usage:
    from src.infrastructure.processors.rife.native import RIFENative

    processor = RIFENative(factor=2)
    output_frames = processor.process_frames(input_frames, output_dir)
"""

import sys
import time
from pathlib import Path
from typing import List, Optional
import logging

# Try to import torch
try:
    import torch
    TORCH_AVAILABLE = True
except ImportError:
    # Ensure name exists even if torch not installed (helps static checks)
    torch = None  # type: ignore
    TORCH_AVAILABLE = False


class RIFENative:
    """
    Native Python implementation of RIFE interpolation.

    Replaces run_rife_pytorch.sh with pure Python.
    """

    def __init__(
        self,
        factor: float = 2.0,
        model_path: Optional[Path] = None,
        scale: float = 1.0,
        device: str = 'cuda',
        logger: Optional[logging.Logger] = None
    ):
        """
        Initialize RIFE processor.

        Args:
            factor: Interpolation factor (2 = double frames)
            model_path: Path to RIFE model directory
            scale: Spatial scaling (default 1.0 = no scaling)
            device: Device to use
            logger: Logger instance
        """
        self.factor = factor
        self.scale = scale
        self.device = device
        self.logger = logger or logging.getLogger(__name__)

        # MULTI-GPU SUPPORT: Detect available GPUs
        if TORCH_AVAILABLE and torch is not None and torch.cuda.is_available():
            self.num_gpus = torch.cuda.device_count()
            self.devices = [torch.device(f'cuda:{i}') for i in range(self.num_gpus)]
            if self.num_gpus > 1:
                self.logger.info(f"🚀 Multi-GPU detected: {self.num_gpus} GPUs available")
                for i in range(self.num_gpus):
                    gpu_name = torch.cuda.get_device_name(i)
                    gpu_mem = torch.cuda.get_device_properties(i).total_memory / 1024**3
                    self.logger.info(f"  GPU {i}: {gpu_name} ({gpu_mem:.1f}GB)")
            else:
                self.logger.info(f"Single GPU detected: {torch.cuda.get_device_name(0)}")
        else:
            self.num_gpus = 1
            self.devices = [torch.device('cpu')]
            self.logger.info("Using CPU (no CUDA available)")

        # Find model
        if model_path is None:
            model_path = self._find_model_path()
        self.model_path = model_path

        # Models will be loaded on first use (one per GPU for multi-GPU)
        self._models = {}  # Dict[int, model] - one model per GPU
        self._model = None  # Backward compatibility

    def _find_model_path(self) -> Path:
        """
        Find RIFE model weights directory.

        Note: This is for model WEIGHTS (train_log/*.pkl), not the code.
        The code is loaded from external/RIFE.
        """
        possible_paths = [
            Path('/opt/rife_models/train_log'),  # Docker container preinstalled models (PRIORITY!)
            Path('/workspace/project/RIFEv4.26_0921'),  # Preinstalled weights
            Path('/workspace/project/external/RIFE/train_log'),  # Cloned repo weights
            Path('RIFEv4.26_0921'),  # Local dev
            Path('external/RIFE/train_log'),  # Local dev
        ]

        for path in possible_paths:
            if path.exists() and list(path.glob('*.pkl')):  # Check for .pkl files
                self.logger.info(f"Found RIFE model weights: {path}")
                return path

        raise FileNotFoundError(
            f"RIFE model weights not found. Searched: {[str(p) for p in possible_paths]}"
        )

    def _setup_model_package(self, rife_repo_path: Path):
        """
        Set up model package for RIFE imports.

        RIFE_HDv3.py needs 'from model.warplayer import warp' to work.
        We need to ensure the model/ directory is properly on the Python path.
        """
        # Add the RIFE repo root to sys.path (so "import model" works)
        rife_root = str(rife_repo_path.absolute())
        if rife_root not in sys.path:
            sys.path.insert(0, rife_root)
            self.logger.info(f"Added {rife_root} to sys.path")

        # Check if RIFE_HDv3.py was copied to root (done by remote_runner.sh)
        rife_hdv3_root = rife_repo_path / 'RIFE_HDv3.py'
        if rife_hdv3_root.exists():
            self.logger.info(f"✓ Found RIFE_HDv3.py in root: {rife_hdv3_root}")
            # Also copy warplayer.py if needed
            warplayer_root = rife_repo_path / 'warplayer.py'
            warplayer_model = rife_repo_path / 'model' / 'warplayer.py'
            if not warplayer_root.exists() and warplayer_model.exists():
                import shutil
                shutil.copy(warplayer_model, warplayer_root)
                self.logger.info(f"Copied warplayer.py to root")

        # Find model directory
        model_dir = rife_repo_path / 'model'
        if model_dir.exists():
            self.logger.info(f"Setting up model package from {model_dir}")

            # Create __init__.py in model/ if it doesn't exist (for Python package)
            init_file = model_dir / '__init__.py'
            if not init_file.exists():
                init_file.write_text("# RIFE model package\n")
                self.logger.info(f"Created {init_file}")

            # Verify model package can be imported
            try:
                # Force reload if already imported
                import importlib
                if 'model' in sys.modules:
                    importlib.reload(sys.modules['model'])
                if 'model.warplayer' in sys.modules:
                    importlib.reload(sys.modules['model.warplayer'])

                # Now try importing
                import model
                import model.warplayer
                self.logger.info("✓ model.warplayer loaded successfully")
            except ImportError as e:
                self.logger.warning(f"Could not import model.warplayer from model/: {e}")
                # Try to copy files to root as fallback
                try:
                    import shutil
                    for f in ['warplayer.py', 'IFNet_HDv3.py']:
                        src = model_dir / f
                        dst = rife_repo_path / f
                        if src.exists() and not dst.exists():
                            shutil.copy(src, dst)
                            self.logger.info(f"Copied {f} to root as fallback")
                except Exception as copy_err:
                    self.logger.warning(f"Fallback copy failed: {copy_err}")
        else:
            self.logger.warning(f"model/ directory not found in {rife_repo_path}, will try root files")

    def _check_cuda_compatibility(self) -> str:
        """
        Check if CUDA device is compatible with current PyTorch.
        Returns: torch.device('cuda:0') or torch.device('cpu')
        """
        if not torch.cuda.is_available():
            self.logger.warning("CUDA not available, using CPU")
            return torch.device('cpu')

        try:
            # Get GPU compute capability
            device_props = torch.cuda.get_device_properties(0)
            compute_capability = f"sm_{device_props.major}{device_props.minor}"

            # Try a simple CUDA operation to test compatibility
            test_tensor = torch.randn(10, 10).to('cuda:0')
            _ = test_tensor * 2

            self.logger.info(f"CUDA is available and compatible: {device_props.name} ({compute_capability})")
            return torch.device('cuda:0')

        except RuntimeError as e:
            if "no kernel image is available" in str(e) or "not compatible" in str(e):
                self.logger.warning(f"CUDA device not compatible with PyTorch: {e}")
                self.logger.warning("Falling back to CPU processing (will be slower)")
                return torch.device('cpu')
            raise

    def _move_model_to_device(self, model, target_device) -> None:
        """
        Robustly move model parameters and buffers to target device.
        
        Handles nested modules and custom model structures that might not
        have standard .to() method or .parameters()/.buffers() attributes.
        
        Args:
            model: The model to move
            target_device: Target device (torch.device or convertible to str)
        """
        # Convert to torch.device if torch is available
        if TORCH_AVAILABLE and torch is not None:
            if not isinstance(target_device, torch.device):
                try:
                    target_device = torch.device(str(target_device))
                except Exception:
                    target_device = torch.device('cpu')
        
        self.logger.info(f"Moving model to device: {target_device}")
        
        # Try standard .to() method first
        if hasattr(model, 'to') and callable(getattr(model, 'to')):
            try:
                model.to(target_device)
                self.logger.debug(f"Successfully used model.to({target_device})")
                return
            except Exception as e:
                self.logger.debug(f"model.to() failed: {e}, falling back to manual movement")
        
        # Manual movement for parameters and buffers
        moved_params = 0
        moved_buffers = 0
        
        # Check if model has named_modules (standard torch.nn.Module)
        if hasattr(model, 'named_modules'):
            # Recursively move all parameters
            def move_parameters(module):
                nonlocal moved_params
                for name, param in module.named_parameters(recurse=False):
                    if param is not None:
                        try:
                            param.data = param.data.to(target_device)
                            moved_params += 1
                        except Exception as e:
                            self.logger.warning(f"Failed to move parameter {name}: {e}")
            
            # Recursively move all buffers
            def move_buffers(module):
                nonlocal moved_buffers
                for name, buf in module.named_buffers(recurse=False):
                    if buf is not None:
                        try:
                            buf.data = buf.data.to(target_device)
                            moved_buffers += 1
                        except Exception as e:
                            self.logger.warning(f"Failed to move buffer {name}: {e}")
            
            # Apply recursively to all submodules
            for module_name, module in model.named_modules():
                move_parameters(module)
                move_buffers(module)
        else:
            # Model doesn't have named_modules - try to move parameters and buffers directly
            self.logger.debug("Model doesn't have named_modules, trying direct parameter/buffer access")
            
            # Try to move parameters if model has parameters() method
            if hasattr(model, 'parameters') and callable(getattr(model, 'parameters')):
                try:
                    for param in model.parameters():
                        if param is not None:
                            param.data = param.data.to(target_device)
                            moved_params += 1
                except Exception as e:
                    self.logger.warning(f"Failed to move parameters: {e}")
            
            # Try to move buffers if model has buffers() method
            if hasattr(model, 'buffers') and callable(getattr(model, 'buffers')):
                try:
                    for buf in model.buffers():
                        if buf is not None:
                            buf.data = buf.data.to(target_device)
                            moved_buffers += 1
                except Exception as e:
                    self.logger.warning(f"Failed to move buffers: {e}")
        
        self.logger.info(f"Moved {moved_params} parameters and {moved_buffers} buffers to {target_device}")
    
    def _verify_model_device(self, model, expected_device) -> bool:
        """
        Verify that all model parameters are on the expected device.
        
        Returns:
            True if all parameters are on expected device, False otherwise
        """
        # Convert to torch.device if needed
        if TORCH_AVAILABLE and torch is not None:
            if not isinstance(expected_device, torch.device):
                try:
                    expected_device = torch.device(str(expected_device))
                except Exception:
                    expected_device = torch.device('cpu')
        
        mismatched = []
        
        # Check if model has named_parameters (standard torch.nn.Module)
        if hasattr(model, 'named_parameters'):
            for name, param in model.named_parameters():
                if param.device != expected_device:
                    mismatched.append((name, param.device))
        elif hasattr(model, 'parameters') and callable(getattr(model, 'parameters')):
            # Model doesn't have named_parameters, but has parameters()
            for i, param in enumerate(model.parameters()):
                if param.device != expected_device:
                    mismatched.append((f"param_{i}", param.device))
        else:
            # Cannot verify parameters
            self.logger.warning("Cannot verify model device: model has no named_parameters or parameters method")
            return True  # Assume OK
        
        if mismatched:
            self.logger.error(f"Model device mismatch: {len(mismatched)} parameters on wrong device")
            for name, dev in mismatched[:5]:  # Show first 5 mismatches
                self.logger.error(f"  {name}: expected {expected_device}, got {dev}")
            return False
        
        self.logger.debug(f"All model parameters verified on device: {expected_device}")
        return True

    def _load_model(self):
        """Load RIFE model (lazy loading)."""
        if self._model is not None:
            return

        if not TORCH_AVAILABLE:
            raise ImportError("PyTorch not found. Install: pip install torch")

        # Check CUDA compatibility and fall back to CPU if needed
        self.device = self._check_cuda_compatibility()
        # Normalize to torch.device
        if not isinstance(self.device, torch.device):
            try:
                self.device = torch.device(str(self.device))
            except Exception:
                self.device = torch.device('cpu')

        if self.device.type == 'cpu':
            self.logger.warning("⚠️ Using CPU for RIFE - processing will be much slower!")
        else:
            # Log GPU memory info
            if torch.cuda.is_available():
                gpu_name = torch.cuda.get_device_name(0)
                gpu_mem_total = torch.cuda.get_device_properties(0).total_memory / 1024**3
                gpu_mem_allocated = torch.cuda.memory_allocated(0) / 1024**3
                gpu_mem_reserved = torch.cuda.memory_reserved(0) / 1024**3
                self.logger.info(f"GPU: {gpu_name}")
                self.logger.info(f"GPU Memory: {gpu_mem_total:.2f}GB total, {gpu_mem_allocated:.2f}GB allocated, {gpu_mem_reserved:.2f}GB reserved")

                # Set CUDA memory allocator config to reduce fragmentation
                import os
                if 'PYTORCH_CUDA_ALLOC_CONF' not in os.environ:
                    os.environ['PYTORCH_CUDA_ALLOC_CONF'] = 'expandable_segments:True'
                    self.logger.info("Set PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True for better memory management")

        self.logger.info(f"Loading RIFE model (weights from: {self.model_path})")

        # Find RIFE repository - prioritize preinstalled RIFE over cloned repo
        rife_repo_paths = [
            Path('/workspace/project/RIFEv4.26_0921'),  # Preinstalled RIFE (priority!)
            Path('RIFEv4.26_0921'),  # Local dev preinstalled
            Path('/workspace/project/external/RIFE'),  # Cloned repo
            Path('external/RIFE'),  # Local dev cloned
            Path(__file__).parent.parent.parent.parent.parent / 'external' / 'RIFE',  # From src/
        ]

        rife_repo_path = None
        for path in rife_repo_paths:
            # Check if this path has the actual RIFE code (not just empty model/__init__.py)
            if path and path.exists():
                # Check for train_log directory (contains actual RIFE implementation)
                has_train_log = (path / 'train_log').exists()
                # Or check for model/RIFE_HDv3.py or model/RIFE.py
                has_model_code = (path / 'model' / 'RIFE_HDv3.py').exists() or \
                                 (path / 'model' / 'RIFE.py').exists()

                if has_train_log or has_model_code:
                    rife_repo_path = path
                    self.logger.info(f"✓ Found RIFE repository with code: {path}")
                    break

        if not rife_repo_path:
            raise ImportError(
                f"RIFE repository with model code not found. Searched: {[str(p) for p in rife_repo_paths if p]}"
            )

        # Set up model package (needed for model.warplayer imports)
        self._setup_model_package(rife_repo_path)

        # Find RIFE_HDv3.py or model/RIFE.py
        # Priority: root (copied by remote_runner.sh) -> model/ -> train_log/
        model_class_paths = [
            (rife_repo_path / 'RIFE_HDv3.py', 'RIFE_HDv3_root', 'Model'),  # Copied to root by remote_runner.sh (PRIORITY!)
            (rife_repo_path / 'model' / 'RIFE_HDv3.py', 'RIFE_HDv3_model', 'Model'),  # v4.6 (model dir)
            (rife_repo_path / 'train_log' / 'RIFE_HDv3.py', 'RIFE_HDv3_train', 'Model'),  # v4.6+ (train_log)
            (rife_repo_path / 'model' / 'RIFE.py', 'RIFE_model', 'Model'),  # v4.x
            (rife_repo_path / 'train_log' / 'RIFE_HD.py', 'RIFE_HD', 'Model'),  # Older version
        ]

        model_class = None
        last_error = None

        for model_file, module_name, class_name in model_class_paths:
            if not model_file.exists():
                continue

            self.logger.info(f"Trying model file: {model_file}")
            try:
                # Import the module
                import importlib.util
                spec = importlib.util.spec_from_file_location(module_name, model_file)
                if spec is None or spec.loader is None:
                    self.logger.warning(f"Could not create spec for {model_file}")
                    continue

                module = importlib.util.module_from_spec(spec)
                sys.modules[module_name] = module
                spec.loader.exec_module(module)

                # Get the Model class
                if hasattr(module, class_name):
                    model_class = getattr(module, class_name)
                    self.logger.info(f"✓ Successfully loaded {module_name}.{class_name} from {model_file}")
                    break
                else:
                    self.logger.warning(f"Module {module_name} does not have {class_name} class")

            except Exception as e:
                last_error = e
                self.logger.warning(f"Failed to load {model_file}: {e}")
                import traceback
                self.logger.debug(traceback.format_exc())
                continue

        if not model_class:
            tried_files = [str(p[0]) for p in model_class_paths if p[0].exists()]
            error_msg = f"Could not load RIFE Model class. Tried: {tried_files}"
            if last_error:
                error_msg += f"\nLast error: {last_error}"
            raise ImportError(error_msg)

        try:
            # Create model instance
            self._model = model_class()

            # Load model weights
            weights_path = self.model_path
            if not (weights_path / 'flownet.pkl').exists():
                # If model_path doesn't have pkl files directly, check parent
                if (weights_path.parent / 'flownet.pkl').exists():
                    weights_path = weights_path.parent

            self.logger.info(f"Loading model weights from {weights_path}")
            self._model.load_model(str(weights_path), -1)
            self._model.eval()
            self._model.device()

            # --- Ensure model parameters/buffers are on the selected device ---
            try:
                target_dev = getattr(self, 'model_device', None) or self.device
                target_dev = torch.device(str(target_dev)) if torch and not isinstance(target_dev, torch.device) else target_dev
                
                # Use robust model movement
                self._move_model_to_device(self._model, target_dev)
                
                # Verify all parameters are on the correct device
                if not self._verify_model_device(self._model, target_dev):
                    self.logger.warning("Some model parameters may not be on the target device")
                
                # Set model_device based on actual parameter device
                try:
                    # Get device from first parameter
                    for p in self._model.parameters():
                        model_dev = p.device
                        break
                    else:
                        model_dev = target_dev
                    self.model_device = torch.device(str(model_dev))
                    self.logger.info(f"Model parameters confirmed on device: {self.model_device}")
                    
                    # Log detailed device info for debugging (especially for RTX 5070)
                    if torch.cuda.is_available():
                        device_props = torch.cuda.get_device_properties(0)
                        compute_capability = f"sm_{device_props.major}{device_props.minor}"
                        self.logger.info(f"GPU: {device_props.name} (Compute: {compute_capability}, VRAM: {device_props.total_memory / 1e9:.1f} GB)")
                        
                except Exception as e:
                    self.logger.warning(f"Could not determine model device: {e}")
                    self.model_device = target_dev

            except Exception as e:
                self.logger.warning(f"Failed to move model to device: {e}")
                # Re-raise if it's a critical error
                if "CUDA" in str(e) or "device" in str(e):
                    raise

            self.logger.info("\u2713 RIFE model loaded successfully")

        except Exception as e:
            raise ImportError(
                f"Failed to load RIFE model. Weights from {self.model_path}: {e}"
            ) from e

    def _load_model_on_device(self, gpu_id: int):
        """
        Load RIFE model on specific GPU (for multi-GPU processing).

        Args:
            gpu_id: GPU index (0, 1, 2, ...)

        Returns:
            Loaded model on specified device
        """
        # Check if model already loaded for this GPU
        if gpu_id in self._models:
            return self._models[gpu_id]

        self.logger.info(f"Loading RIFE model on GPU {gpu_id}...")

        # Use the standard _load_model but override device temporarily
        original_device = self.device
        try:
            # Set device to specific GPU
            self.device = self.devices[gpu_id] if gpu_id < len(self.devices) else torch.device(f'cuda:{gpu_id}')

            # Load model (will use self.device internally)
            self._load_model()

            # Store model for this GPU
            self._models[gpu_id] = self._model

            self.logger.info(f"✓ RIFE model loaded on GPU {gpu_id}")

            return self._model

        finally:
            # Restore original device
            self.device = original_device

    def _calculate_mids_per_pair(self) -> int:
        """Calculate how many intermediate frames per pair."""
        # factor 2 -> 1 mid, factor 3 -> 2 mids, factor 4 -> 3 mids, etc.
        # For factor=3: we want frame_A, mid1, mid2, frame_B (2 mids between each pair)
        mids = max(1, int(round(self.factor)) - 1)
        self.logger.debug(f"Factor {self.factor} -> {mids} intermediate frames per pair")
        return mids

    def _pad_to_multiple(self, tensor: 'torch.Tensor', multiple: int = 64) -> tuple:
        """
        Pad tensor to multiple of given size.

        Args:
            tensor: Input tensor [1, C, H, W]
            multiple: Pad to multiple of this value (default 64)

        Returns:
            Tuple of (padded_tensor, original_height, original_width)
        """
        n, c, h, w = tensor.shape
        ph = ((h - 1) // multiple + 1) * multiple
        pw = ((w - 1) // multiple + 1) * multiple

        # Calculate padding (left, right, top, bottom)
        pad = (0, pw - w, 0, ph - h)

        if pad[1] != 0 or pad[3] != 0:
            import torch.nn.functional as F
            tensor = F.pad(tensor, pad)

        return tensor, h, w

    def _interpolate_pair(
        self,
        frame1: 'torch.Tensor',
        frame2: 'torch.Tensor',
        mids_count: int
    ) -> List['torch.Tensor']:
        """
        Interpolate between two frames.

        Args:
            frame1: First frame (tensor)
            frame2: Second frame (tensor)
            mids_count: Number of intermediate frames

        Returns:
            List of intermediate frames
        """
        # Store original dimensions
        _, _, orig_h, orig_w = frame1.shape

        # Determine target device for inference (prefer model_device if set)
        model_dev = getattr(self, 'model_device', None) or self.device
        try:
            model_dev = torch.device(str(model_dev))
        except Exception:
            model_dev = torch.device('cpu')

        # ADAPTIVE MEMORY MANAGEMENT: Calculate optimal scale_factor based on available VRAM
        scale_factor = 1.0
        if torch.cuda.is_available() and model_dev.type == 'cuda':
            gpu_mem_total = torch.cuda.get_device_properties(0).total_memory
            gpu_mem_allocated = torch.cuda.memory_allocated(0)
            gpu_mem_reserved = torch.cuda.memory_reserved(0)
            gpu_mem_free = gpu_mem_total - gpu_mem_allocated

            # Calculate estimated memory needed for this frame pair at full resolution
            # Empirical formula: input frames (2x) + padded (2x) + intermediate buffers (4x) + output (2x) = ~10x frame size
            bytes_per_pixel = 4  # float32
            frame_size_bytes = orig_h * orig_w * 3 * bytes_per_pixel
            estimated_needed_full = frame_size_bytes * 10  # Conservative estimate for all buffers

            # Reserve 20% of total VRAM for model weights and other overhead
            # Use 70% of free memory for frame processing (safety margin)
            available_for_frames = gpu_mem_free * 0.7

            # Calculate if we need to downscale
            if estimated_needed_full > available_for_frames:
                # Calculate optimal scale_factor to fit in available memory
                # Memory needed scales with (scale^2) for 2D images
                optimal_scale_squared = available_for_frames / estimated_needed_full
                optimal_scale = optimal_scale_squared ** 0.5

                # Round down to safe values: 0.9, 0.8, 0.7, 0.6, 0.5, 0.4, 0.3, 0.25
                if optimal_scale >= 0.9:
                    scale_factor = 0.9
                elif optimal_scale >= 0.8:
                    scale_factor = 0.8
                elif optimal_scale >= 0.7:
                    scale_factor = 0.7
                elif optimal_scale >= 0.6:
                    scale_factor = 0.6
                elif optimal_scale >= 0.5:
                    scale_factor = 0.5
                elif optimal_scale >= 0.4:
                    scale_factor = 0.4
                elif optimal_scale >= 0.3:
                    scale_factor = 0.3
                else:
                    scale_factor = 0.25  # Minimum scale

                new_h = int(orig_h * scale_factor)
                new_w = int(orig_w * scale_factor)
                estimated_needed_scaled = frame_size_bytes * (scale_factor ** 2) * 10

                self.logger.warning(
                    f"⚠️ Adaptive downscaling: {orig_w}x{orig_h} → {new_w}x{new_h} (scale={scale_factor:.2f})"
                )
                self.logger.info(
                    f"GPU Memory: {gpu_mem_free/1024**3:.2f}GB free, "
                    f"need {estimated_needed_full/1024**3:.2f}GB @ full res, "
                    f"{estimated_needed_scaled/1024**3:.2f}GB @ {scale_factor:.2f}x"
                )
            else:
                # Enough memory, log that we're using full resolution
                self.logger.debug(
                    f"GPU Memory OK: {gpu_mem_free/1024**3:.2f}GB free, "
                    f"need {estimated_needed_full/1024**3:.2f}GB - processing at full resolution"
                )


        # --- FIX: ensure inputs are on the same device as the model parameters ---
        # Log device info for debugging (especially for RTX 5070)
        self.logger.debug(f"Input tensor devices - frame1: {frame1.device}, frame2: {frame2.device}")
        self.logger.debug(f"Target model device: {model_dev}")
        
        # Move input tensors to model device before any ops (use non_blocking when possible)
        try:
            if frame1.device != model_dev:
                self.logger.debug(f"Moving frame1 from {frame1.device} to {model_dev}")
                try:
                    frame1 = frame1.to(model_dev, non_blocking=True)
                except Exception:
                    frame1 = frame1.to(model_dev)
            if frame2.device != model_dev:
                self.logger.debug(f"Moving frame2 from {frame2.device} to {model_dev}")
                try:
                    frame2 = frame2.to(model_dev, non_blocking=True)
                except Exception:
                    frame2 = frame2.to(model_dev)
                    
            # Verify movement succeeded
            if frame1.device != model_dev or frame2.device != model_dev:
                self.logger.warning(f"Tensor device mismatch after movement: frame1={frame1.device}, frame2={frame2.device}, expected={model_dev}")
                
        except Exception as e:
            # If moving tensors fails, log devices and re-raise with context
            self.logger.error(f"Failed to move input tensors to device {model_dev}: {e}")
            self.logger.error(f"frame1.device={getattr(frame1, 'device', 'unknown')}, frame2.device={getattr(frame2, 'device', 'unknown')}")
            
            # Log model parameter devices for additional context
            try:
                param_devices = set(str(p.device) for p in self._model.parameters())
                self.logger.error(f"Model parameter devices: {param_devices}")
            except Exception:
                pass
                
            raise

        # Apply adaptive downscaling if needed
        if scale_factor < 1.0:
            import torch.nn.functional as F
            new_h = int(orig_h * scale_factor)
            new_w = int(orig_w * scale_factor)
            # Make dimensions even for better compatibility
            new_h = new_h - (new_h % 2)
            new_w = new_w - (new_w % 2)
            frame1 = F.interpolate(frame1, size=(new_h, new_w), mode='bilinear', align_corners=False)
            frame2 = F.interpolate(frame2, size=(new_h, new_w), mode='bilinear', align_corners=False)
            self.logger.debug(f"Downscaled frames to {new_w}x{new_h}")

        # Pad to multiples of 64 (RIFE model requirement)
        frame1_padded, _, _ = self._pad_to_multiple(frame1, 64)
        frame2_padded, _, _ = self._pad_to_multiple(frame2, 64)

        mids: List['torch.Tensor'] = []

        with torch.no_grad():
            for i in range(mids_count):
                # Calculate timestep
                timestep = (i + 1) / (mids_count + 1)

                # Log debug info about device placement before inference
                try:
                    model_param_devices = set()
                    for p in self._model.parameters():
                        model_param_devices.add(str(p.device))
                except Exception:
                    model_param_devices = {str(getattr(self, 'model_device', 'unknown'))}

                self.logger.debug(
                    "Calling RIFE inference: timestep=%s frame1.device=%s frame2.device=%s model_param_devices=%s",
                    timestep, getattr(frame1_padded, 'device', 'unknown'), getattr(frame2_padded, 'device', 'unknown'), model_param_devices
                )

                # Interpolate
                try:
                    mid = self._model.inference(frame1_padded, frame2_padded, timestep)
                except RuntimeError as e:
                    # Collect model parameter devices for debugging
                    model_param_devices = set()
                    try:
                        for p in self._model.parameters():
                            model_param_devices.add(str(p.device))
                    except Exception:
                        model_param_devices.add('unknown')

                    # Log detailed device mismatch info
                    self.logger.error(
                        "RuntimeError during RIFE inference: %s | frame1.device=%s frame2.device=%s model_param_devices=%s",
                        e, getattr(frame1, 'device', 'unknown'), getattr(frame2, 'device', 'unknown'), model_param_devices
                    )
                    raise

                # Crop back to (possibly downscaled) dimensions
                _, _, current_h, current_w = frame1.shape
                mid = mid[:, :, :current_h, :current_w]

                # Upscale back to original resolution if we downscaled
                if scale_factor < 1.0:
                    import torch.nn.functional as F
                    mid = F.interpolate(mid, size=(orig_h, orig_w), mode='bilinear', align_corners=False)

                mids.append(mid)

                # Clean up intermediate tensors
                del mid

        return mids

    def _load_frame_as_tensor(self, frame_path: Path) -> 'torch.Tensor':
        """Load image file as torch tensor."""
        try:
            import cv2
            import numpy as np
        except ImportError as e:
            raise ImportError("opencv-python not found. Install: pip install opencv-python") from e

        img = cv2.imread(str(frame_path))
        if img is None:
            raise ValueError(f"Failed to load image: {frame_path}")

        # Convert BGR to RGB
        img = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)

        # Convert to tensor [1, 3, H, W]
        img = torch.from_numpy(img).permute(2, 0, 1).unsqueeze(0).float() / 255.0

        # Move to device (prefer model_device if available)
        target_dev = getattr(self, 'model_device', None) or self.device
        try:
            target_dev = torch.device(str(target_dev))
        except Exception:
            target_dev = torch.device('cpu')
        img = img.to(target_dev)

        return img

    def _save_tensor_as_frame(self, tensor: 'torch.Tensor', output_path: Path):
        """Save torch tensor as image file."""
        try:
            import cv2
            import numpy as np
        except ImportError as e:
            raise ImportError("opencv-python not found. Install: pip install opencv-python") from e

        # Tensor is [1, 3, H, W], convert to [H, W, 3]
        img = tensor.squeeze(0).permute(1, 2, 0).cpu().numpy()

        # Scale to 0-255
        img = (img * 255).clip(0, 255).astype(np.uint8)

        # Convert RGB to BGR
        img = cv2.cvtColor(img, cv2.COLOR_RGB2BGR)

        # Save
        cv2.imwrite(str(output_path), img)

    def _process_pairs_on_gpu(
        self,
        pairs: List[tuple],  # List of (pair_idx, frame1_path, frame2_path)
        output_dir: Path,
        gpu_id: int,
        mids_per_pair: int
    ) -> List[tuple]:  # Returns List of (pair_idx, output_frames)
        """
        Process a batch of frame pairs on a specific GPU.

        Args:
            pairs: List of tuples (pair_idx, frame1_path, frame2_path)
            output_dir: Output directory for frames
            gpu_id: GPU index to use
            mids_per_pair: Number of intermediate frames per pair

        Returns:
            List of (pair_idx, [output_frame_paths]) tuples
        """
        device = self.devices[gpu_id] if gpu_id < len(self.devices) else torch.device(f'cuda:{gpu_id}')

        # Load model on this GPU
        self._load_model_on_device(gpu_id)
        model = self._models[gpu_id]

        # Temporarily set model for interpolation
        original_model = self._model
        self._model = model

        results = []

        try:
            for pair_idx, frame1_path, frame2_path in pairs:
                # Load frames
                frame1 = self._load_frame_as_tensor(frame1_path)
                frame2 = self._load_frame_as_tensor(frame2_path)

                # Interpolate on this GPU
                mids = self._interpolate_pair(frame1, frame2, mids_per_pair)

                # Save intermediate frames
                mid_paths = []
                for mid_idx, mid in enumerate(mids):
                    mid_path = output_dir / f"pair_{pair_idx:06d}_mid_{mid_idx:02d}.png"
                    self._save_tensor_as_frame(mid.cpu(), mid_path)
                    mid_paths.append(mid_path)

                results.append((pair_idx, mid_paths))

                # Cleanup
                del frame1, frame2, mids

                # Aggressive cleanup for this GPU
                if torch.cuda.is_available():
                    torch.cuda.empty_cache()

        finally:
            # Restore original model
            self._model = original_model

        return results

    def process_frames(
        self,
        input_frames: List[Path],
        output_dir: Path,
        progress_callback: Optional[callable] = None
    ) -> List[Path]:
        """
        Interpolate frames using RIFE.

        Automatically uses multi-GPU if available.

        Args:
            input_frames: List of input frame paths
            output_dir: Output directory
            progress_callback: Optional callback(current, total)

        Returns:
            List of output frame paths (interleaved: orig1, mid, orig2, mid, ...)
        """
        output_dir.mkdir(parents=True, exist_ok=True)

        total_pairs = len(input_frames) - 1
        mids_per_pair = self._calculate_mids_per_pair()

        self.logger.info(f"Interpolating {len(input_frames)} frames")
        self.logger.info(f"  Factor: {self.factor}x")
        self.logger.info(f"  Pairs to process: {total_pairs}")
        self.logger.info(f"  Mids per pair: {mids_per_pair}")

        # Choose processing strategy based on GPU count
        if self.num_gpus > 1 and total_pairs >= self.num_gpus * 2:
            self.logger.info(f"🚀 Using MULTI-GPU mode with {self.num_gpus} GPUs")
            return self._process_frames_multi_gpu(
                input_frames, output_dir, progress_callback
            )
        else:
            if self.num_gpus > 1:
                self.logger.info(f"Using single GPU (too few pairs: {total_pairs} < {self.num_gpus * 2})")
            return self._process_frames_single_gpu(
                input_frames, output_dir, progress_callback
            )

    def _process_frames_multi_gpu(
        self,
        input_frames: List[Path],
        output_dir: Path,
        progress_callback: Optional[callable] = None
    ) -> List[Path]:
        """Process frames using multiple GPUs in parallel."""
        from concurrent.futures import ThreadPoolExecutor, as_completed
        import threading

        total_pairs = len(input_frames) - 1
        mids_per_pair = self._calculate_mids_per_pair()

        # Distribute pairs across GPUs (round-robin)
        pairs_per_gpu = [[] for _ in range(self.num_gpus)]
        for idx in range(total_pairs):
            gpu_id = idx % self.num_gpus
            pairs_per_gpu[gpu_id].append((idx, input_frames[idx], input_frames[idx + 1]))

        # Log distribution
        for gpu_id, pairs in enumerate(pairs_per_gpu):
            self.logger.info(f"  GPU {gpu_id}: {len(pairs)} pairs")

        # Process pairs in parallel on different GPUs
        start_time = time.time()
        all_mid_results = []

        progress_lock = threading.Lock()
        completed_pairs = [0]  # Mutable for closure

        def process_gpu_batch(gpu_id, pairs):
            """Process batch on specific GPU with progress tracking."""
            results = self._process_pairs_on_gpu(pairs, output_dir, gpu_id, mids_per_pair)

            # Update progress
            with progress_lock:
                completed_pairs[0] += len(pairs)
                if progress_callback:
                    progress_callback(completed_pairs[0], total_pairs)

                # Log progress
                if completed_pairs[0] % 10 == 0 or completed_pairs[0] == total_pairs:
                    elapsed = time.time() - start_time
                    fps = completed_pairs[0] / elapsed if elapsed > 0 else 0
                    eta = (total_pairs - completed_pairs[0]) / fps if fps > 0 else 0
                    self.logger.info(
                        f"Processed {completed_pairs[0]}/{total_pairs} pairs "
                        f"({100*completed_pairs[0]/total_pairs:.1f}%) | "
                        f"{fps:.2f} fps | ETA: {eta:.0f}s"
                    )

            return results

        # Submit tasks to thread pool
        with ThreadPoolExecutor(max_workers=self.num_gpus) as executor:
            futures = []
            for gpu_id, pairs in enumerate(pairs_per_gpu):
                if pairs:  # Only submit if there are pairs to process
                    future = executor.submit(process_gpu_batch, gpu_id, pairs)
                    futures.append(future)

            # Collect results
            for future in as_completed(futures):
                try:
                    results = future.result()
                    all_mid_results.extend(results)
                except Exception as e:
                    self.logger.error(f"GPU processing failed: {e}")
                    raise

        # Sort results by pair index
        all_mid_results.sort(key=lambda x: x[0])

        # Assemble final output with interleaved frames
        output_frames = []
        frame_counter = 1

        for pair_idx in range(total_pairs):
            # Original frame
            orig_frame = input_frames[pair_idx]
            orig_output_path = output_dir / f"frame_{frame_counter:06d}.png"
            if not orig_output_path.exists():
                try:
                    orig_output_path.symlink_to(orig_frame.absolute())
                except (OSError, NotImplementedError):
                    import shutil
                    shutil.copy2(orig_frame, orig_output_path)
            output_frames.append(orig_output_path)
            frame_counter += 1

            # Intermediate frames (find in results)
            mid_paths = None
            for res_idx, res_mid_paths in all_mid_results:
                if res_idx == pair_idx:
                    mid_paths = res_mid_paths
                    break

            if mid_paths:
                for mid_path in mid_paths:
                    final_mid_path = output_dir / f"frame_{frame_counter:06d}.png"
                    if mid_path != final_mid_path:
                        import shutil
                        shutil.move(str(mid_path), str(final_mid_path))
                    output_frames.append(final_mid_path)
                    frame_counter += 1

        # Last original frame
        last_frame = input_frames[-1]
        last_output_path = output_dir / f"frame_{frame_counter:06d}.png"
        if not last_output_path.exists():
            try:
                last_output_path.symlink_to(last_frame.absolute())
            except (OSError, NotImplementedError):
                import shutil
                shutil.copy2(last_frame, last_output_path)
        output_frames.append(last_output_path)

        elapsed = time.time() - start_time
        avg_fps = total_pairs / elapsed if elapsed > 0 else 0

        self.logger.info(f"✅ Multi-GPU completed {total_pairs} pairs in {elapsed:.1f}s ({avg_fps:.2f} fps)")
        self.logger.info(f"Generated {len(output_frames)} total frames")

        return output_frames

    def _process_frames_single_gpu(
        self,
        input_frames: List[Path],
        output_dir: Path,
        progress_callback: Optional[callable] = None
    ) -> List[Path]:
        """Process frames using single GPU (original implementation)."""
        # Load model
        self._load_model()

        total_pairs = len(input_frames) - 1
        mids_per_pair = self._calculate_mids_per_pair()

        # Log initial GPU memory state and determine cache clearing frequency
        cache_clear_interval = 10  # Default: every 10 pairs
        if torch.cuda.is_available():
            gpu_mem_total = torch.cuda.get_device_properties(0).total_memory / 1024**3
            gpu_mem_allocated = torch.cuda.memory_allocated(0) / 1024**3
            gpu_mem_reserved = torch.cuda.memory_reserved(0) / 1024**3
            self.logger.info(f"GPU Memory: {gpu_mem_allocated:.2f}GB allocated, {gpu_mem_reserved:.2f}GB reserved, {gpu_mem_total:.2f}GB total")

            # ADAPTIVE CACHE CLEARING: Adjust frequency based on total VRAM
            # More VRAM = less frequent clearing (better performance)
            # Less VRAM = more frequent clearing (prevent OOM)
            if gpu_mem_total >= 20:  # 20GB+ (RTX 3090, 4090, A100, etc.)
                cache_clear_interval = 20
                self.logger.info("High VRAM detected (20GB+): cache clearing every 20 pairs")
            elif gpu_mem_total >= 16:  # 16GB+ (RTX 4080, 4070 Ti Super, etc.)
                cache_clear_interval = 15
                self.logger.info("Medium-High VRAM detected (16GB+): cache clearing every 15 pairs")
            elif gpu_mem_total >= 12:  # 12GB+ (RTX 3060, 4070, etc.)
                cache_clear_interval = 10
                self.logger.info("Medium VRAM detected (12GB+): cache clearing every 10 pairs")
            elif gpu_mem_total >= 8:   # 8GB+ (RTX 3060 Ti, 3070, etc.)
                cache_clear_interval = 5
                self.logger.info("Low-Medium VRAM detected (8GB+): cache clearing every 5 pairs")
            else:  # <8GB
                cache_clear_interval = 3
                self.logger.warning("Low VRAM detected (<8GB): aggressive cache clearing every 3 pairs")

        output_frames = []
        start_time = time.time()
        frame_counter = 1  # Sequential frame counter for output

        # Debug: Log expected output frame count
        expected_output_frames = len(input_frames) + (total_pairs * mids_per_pair)
        self.logger.info(f"Expected output: {expected_output_frames} frames ({len(input_frames)} orig + {total_pairs} pairs × {mids_per_pair} mids)")

        # Process pairs
        for idx in range(total_pairs):
            frame1_path = input_frames[idx]
            frame2_path = input_frames[idx + 1]

            try:
                # PREVENTIVE CLEANUP: Check memory before loading frames
                if torch.cuda.is_available():
                    gpu_mem_total = torch.cuda.get_device_properties(0).total_memory
                    gpu_mem_allocated = torch.cuda.memory_allocated(0)
                    gpu_mem_free = gpu_mem_total - gpu_mem_allocated

                    # If less than 1GB free, do preventive cleanup
                    if gpu_mem_free < 1 * 1024**3:
                        torch.cuda.empty_cache()
                        torch.cuda.synchronize()

                        gpu_mem_free_after = gpu_mem_total - torch.cuda.memory_allocated(0)
                        if idx % 10 == 0:  # Log every 10 pairs
                            self.logger.warning(
                                f"⚠️ Preventive cleanup before pair {idx+1}: "
                                f"freed {(gpu_mem_free_after - gpu_mem_free)/1024**3:.2f}GB, "
                                f"now {gpu_mem_free_after/1024**3:.2f}GB free"
                            )

                # Load frames as tensors
                frame1 = self._load_frame_as_tensor(frame1_path)
                frame2 = self._load_frame_as_tensor(frame2_path)

                # Save original frame1 with sequential numbering
                orig_output_path = output_dir / f"frame_{frame_counter:06d}.png"
                if not orig_output_path.exists():
                    try:
                        # Try symlink first (faster)
                        orig_output_path.symlink_to(frame1_path.absolute())
                    except (OSError, NotImplementedError):
                        # Fall back to copy if symlink not supported
                        import shutil
                        shutil.copy2(frame1_path, orig_output_path)
                output_frames.append(orig_output_path)

                # Debug log every first pair
                if idx == 0:
                    self.logger.debug(f"Frame {frame_counter}: Original {frame1_path.name}")
                frame_counter += 1

                # Generate intermediate frames
                mids = self._interpolate_pair(frame1, frame2, mids_per_pair)

                # Verify we got the expected number of mids
                if len(mids) != mids_per_pair:
                    self.logger.warning(f"Pair {idx}: Expected {mids_per_pair} mids, got {len(mids)}")

                # Save intermediate frames with sequential numbering
                for mid_idx, mid in enumerate(mids, 1):
                    mid_path = output_dir / f"frame_{frame_counter:06d}.png"
                    self._save_tensor_as_frame(mid, mid_path)
                    output_frames.append(mid_path)

                    # Debug log first pair's mids
                    if idx == 0:
                        self.logger.debug(f"Frame {frame_counter}: Interpolated mid {mid_idx}/{len(mids)}")
                    frame_counter += 1

                # MEMORY CLEANUP: Explicitly delete tensors and free GPU memory
                del frame1, frame2, mids

                # Check if we need aggressive cleanup (reserved but unused memory is high)
                if torch.cuda.is_available():
                    gpu_mem_allocated = torch.cuda.memory_allocated(0)
                    gpu_mem_reserved = torch.cuda.memory_reserved(0)
                    gpu_mem_free_actual = torch.cuda.get_device_properties(0).total_memory - gpu_mem_allocated
                    reserved_unused = gpu_mem_reserved - gpu_mem_allocated

                    # If reserved-but-unused > 2GB or free < 1GB, force aggressive cleanup
                    needs_aggressive_cleanup = (reserved_unused > 2 * 1024**3) or (gpu_mem_free_actual < 1 * 1024**3)

                    if needs_aggressive_cleanup:
                        # AGGRESSIVE: Clear cache after EVERY pair
                        torch.cuda.empty_cache()
                        torch.cuda.synchronize()  # Wait for all operations to complete

                        if (idx + 1) % 5 == 0:  # Log every 5 pairs
                            gpu_mem_allocated_after = torch.cuda.memory_allocated(0) / 1024**3
                            gpu_mem_reserved_after = torch.cuda.memory_reserved(0) / 1024**3
                            freed = (gpu_mem_reserved - torch.cuda.memory_reserved(0)) / 1024**3
                            self.logger.warning(
                                f"⚠️ Aggressive cleanup after pair {idx+1}: "
                                f"allocated={gpu_mem_allocated_after:.2f}GB, "
                                f"reserved={gpu_mem_reserved_after:.2f}GB, "
                                f"freed={freed:.2f}GB"
                            )
                    elif (idx + 1) % cache_clear_interval == 0:
                        # NORMAL: Clear cache at adaptive intervals
                        torch.cuda.empty_cache()

                        # Log memory usage at double the cache clear interval
                        if (idx + 1) % (cache_clear_interval * 2) == 0:
                            gpu_mem_allocated_gb = gpu_mem_allocated / 1024**3
                            gpu_mem_reserved_gb = gpu_mem_reserved / 1024**3
                            self.logger.debug(f"GPU Memory after pair {idx+1}: {gpu_mem_allocated_gb:.2f}GB allocated, {gpu_mem_reserved_gb:.2f}GB reserved")

                # Progress
                if (idx + 1) % 10 == 0 or (idx + 1) == total_pairs:
                    elapsed = time.time() - start_time
                    fps = (idx + 1) / elapsed if elapsed > 0 else 0
                    eta = (total_pairs - idx - 1) / fps if fps > 0 else 0

                    self.logger.info(
                        f"Processed {idx+1}/{total_pairs} pairs "
                        f"({100*(idx+1)/total_pairs:.1f}%) | "
                        f"{fps:.2f} fps | "
                        f"ETA: {eta:.0f}s"
                    )

                    if progress_callback:
                        progress_callback(idx + 1, total_pairs)

            except Exception as e:
                self.logger.error(f"Failed to process pair {idx+1}/{total_pairs}: {e}")

                # If CUDA OOM, try to recover by clearing cache
                if torch.cuda.is_available() and "out of memory" in str(e).lower():
                    self.logger.error("❌ CUDA OOM detected! Attempting aggressive recovery...")

                    # Log current memory state
                    gpu_mem_allocated_before = torch.cuda.memory_allocated(0) / 1024**3
                    gpu_mem_reserved_before = torch.cuda.memory_reserved(0) / 1024**3
                    gpu_mem_total = torch.cuda.get_device_properties(0).total_memory / 1024**3
                    reserved_unused = gpu_mem_reserved_before - gpu_mem_allocated_before

                    self.logger.error(
                        f"Memory before cleanup: "
                        f"total={gpu_mem_total:.2f}GB, "
                        f"allocated={gpu_mem_allocated_before:.2f}GB, "
                        f"reserved={gpu_mem_reserved_before:.2f}GB, "
                        f"reserved-unused={reserved_unused:.2f}GB"
                    )

                    # ULTRA AGGRESSIVE cleanup
                    try:
                        # Delete tensors
                        try:
                            del frame1, frame2
                        except:
                            pass

                        try:
                            del mids
                        except:
                            pass

                        # Collect Python garbage
                        import gc
                        gc.collect()

                        # Empty CUDA cache
                        torch.cuda.empty_cache()

                        # Synchronize all CUDA operations
                        torch.cuda.synchronize()

                        # Reset peak memory stats (helps with fragmentation)
                        torch.cuda.reset_peak_memory_stats()

                        # Try to defragment by allocating and freeing a small tensor
                        try:
                            dummy = torch.zeros(1, device='cuda')
                            del dummy
                            torch.cuda.empty_cache()
                        except:
                            pass

                    except Exception as cleanup_error:
                        self.logger.error(f"Cleanup failed: {cleanup_error}")

                    # Log memory state after cleanup
                    gpu_mem_allocated_after = torch.cuda.memory_allocated(0) / 1024**3
                    gpu_mem_reserved_after = torch.cuda.memory_reserved(0) / 1024**3
                    freed_allocated = gpu_mem_allocated_before - gpu_mem_allocated_after
                    freed_reserved = gpu_mem_reserved_before - gpu_mem_reserved_after
                    gpu_mem_free = gpu_mem_total - gpu_mem_allocated_after

                    self.logger.info(
                        f"Memory after cleanup: "
                        f"allocated={gpu_mem_allocated_after:.2f}GB (freed {freed_allocated:.2f}GB), "
                        f"reserved={gpu_mem_reserved_after:.2f}GB (freed {freed_reserved:.2f}GB), "
                        f"free={gpu_mem_free:.2f}GB"
                    )

                    # Set environment variable for memory fragmentation (as suggested by PyTorch)
                    import os
                    if 'PYTORCH_CUDA_ALLOC_CONF' not in os.environ:
                        os.environ['PYTORCH_CUDA_ALLOC_CONF'] = 'expandable_segments:True'
                        self.logger.info("Set PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True")

                    # If still very low memory, suggest to user
                    if gpu_mem_free < 2:
                        self.logger.error(
                            f"⚠️ Still only {gpu_mem_free:.2f}GB free after cleanup! "
                            f"Consider processing at lower resolution or using a GPU with more VRAM."
                        )

                raise

        # Copy/symlink last frame to output directory with sequential numbering
        last_frame_path = input_frames[-1]
        last_output_path = output_dir / f"frame_{frame_counter:06d}.png"
        if not last_output_path.exists():
            try:
                last_output_path.symlink_to(last_frame_path.absolute())
            except (OSError, NotImplementedError):
                import shutil
                shutil.copy2(last_frame_path, last_output_path)
        output_frames.append(last_output_path)
        self.logger.debug(f"Frame {frame_counter}: Last original frame {last_frame_path.name}")

        elapsed = time.time() - start_time
        avg_fps = total_pairs / elapsed if elapsed > 0 else 0

        # Verify frame count matches expectation
        actual_frames = len(output_frames)
        if actual_frames != expected_output_frames:
            self.logger.warning(
                f"⚠️ Frame count mismatch! Expected {expected_output_frames}, got {actual_frames} "
                f"(difference: {actual_frames - expected_output_frames})"
            )
        else:
            self.logger.info(f"✓ Frame count verified: {actual_frames} frames as expected")

        self.logger.info(
            f"✅ Completed {total_pairs} pairs in {elapsed:.1f}s "
            f"({avg_fps:.2f} fps)"
        )
        self.logger.info(f"Generated {len(output_frames)} total frames")

        # Final verification: check for gaps in frame numbering
        frame_numbers = []
        for f in output_frames:
            try:
                # Extract frame number from filename (frame_000001.png -> 1)
                num = int(f.stem.split('_')[1])
                frame_numbers.append(num)
            except (IndexError, ValueError):
                pass

        if frame_numbers:
            missing = []
            for expected in range(1, max(frame_numbers) + 1):
                if expected not in frame_numbers:
                    missing.append(expected)

            if missing:
                self.logger.error(f"❌ Missing frame numbers: {missing[:10]}{'...' if len(missing) > 10 else ''}")
            else:
                self.logger.info(f"✓ No gaps in frame numbering (1-{max(frame_numbers)})")

        return output_frames

    def process_video(
        self,
        input_video: Path,
        output_video: Path,
        fps: Optional[float] = None
    ) -> Path:
        """
        Interpolate entire video file.

        Args:
            input_video: Input video path
            output_video: Output video path
            fps: Output frame rate (auto-calculate if None)

        Returns:
            Output video path
        """
        # import media helpers dynamically to avoid static import resolution issues
        import importlib
        media_mod = importlib.import_module('infrastructure.media')
        FFmpegExtractor = getattr(media_mod, 'FFmpegExtractor')
        FFmpegAssembler = getattr(media_mod, 'FFmpegAssembler')

        # Create temporary directories
        import tempfile

        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            frames_dir = temp_path / "frames"
            output_frames_dir = temp_path / "output"
            frames_dir.mkdir()
            output_frames_dir.mkdir()

            # Extract frames
            self.logger.info(f"Extracting frames from {input_video}")
            extractor = FFmpegExtractor()
            frames = extractor.extract_frames(input_video, frames_dir)

            # Get video info
            info = extractor.get_video_info(input_video)
            if fps is None:
                fps = info.fps * self.factor

            # Interpolate
            output_frames = self.process_frames(frames, output_frames_dir)

            # Assemble video
            self.logger.info(f"Assembling video to {output_video}")
            assembler = FFmpegAssembler()
            result = assembler.assemble_video(
                output_frames,
                output_video,
                fps=fps,
                resolution=(info.width, info.height)
            )

            return output_video


# CLI interface (for backward compatibility)
def main():
    """CLI entry point - mimics shell script interface."""
    import argparse

    parser = argparse.ArgumentParser(
        description='RIFE Interpolation (Native Python Implementation)'
    )
    parser.add_argument('input', help='Input file (video or directory of frames)')
    parser.add_argument('output', help='Output file or directory')
    parser.add_argument('factor', type=float, nargs='?', default=2.0,
                       help='Interpolation factor (default: 2.0)')
    parser.add_argument('--model-path', type=Path, help='Path to RIFE model')

    args = parser.parse_args()

    # Setup logging
    logging.basicConfig(
        level=logging.INFO,
        format='[%(asctime)s] %(message)s',
        datefmt='%H:%M:%S'
    )

    input_path = Path(args.input)
    output_path = Path(args.output)

    # Create processor
    processor = RIFENative(
        factor=args.factor,
        model_path=args.model_path
    )

    # Process
    if input_path.is_file():
        # Video file
        processor.process_video(input_path, output_path)
    elif input_path.is_dir():
        # Directory of frames
        frames = sorted(input_path.glob('*.png')) or sorted(input_path.glob('*.jpg'))
        output_path.mkdir(parents=True, exist_ok=True)
        processor.process_frames(frames, output_path)
    else:
        print(f"Error: Input not found: {input_path}")
        sys.exit(1)

    print(f"✅ Success: {output_path}")


if __name__ == '__main__':
    main()
