"""
Environment manager for ProPainterAdapter.
Handles GPU detection, patching, and environment setup.
"""

import os
from typing import Dict, Any, List
from pathlib import Path
from src.core.config import AppConfig


class EnvironmentManager:
    """Manages GPU environment and ProPainter patching."""
    
    def __init__(self, config: AppConfig):
        self.config = config
        self.logger = None  # Will be set by parent
    
    def setup_gpu_environment(self) -> Dict[str, Any]:
        """
        Setup GPU environment and detect available resources.
        
        Returns:
            Dictionary with GPU information
        """
        import torch
        import os
        
        # Handle CUDA_VISIBLE_DEVICES
        cuda_visible = os.environ.get('CUDA_VISIBLE_DEVICES', None)
        original_cuda_visible = cuda_visible
        
        if cuda_visible is not None and cuda_visible != '':
            # Clear temporarily to detect all GPUs
            del os.environ['CUDA_VISIBLE_DEVICES']
            # Force CUDA reinitialization
            if torch.cuda.is_available():
                torch.cuda.init()
            # Restore after detection
            os.environ['CUDA_VISIBLE_DEVICES'] = original_cuda_visible
        
        gpu_info = {
            'cuda_available': torch.cuda.is_available(),
            'cuda_visible_devices': original_cuda_visible,
            'gpus': [],
            'total_vram_gb': 0,
        }
        
        if torch.cuda.is_available():
            torch.cuda.init()
            num_gpus = torch.cuda.device_count()
            gpu_info['num_gpus'] = num_gpus
            gpu_info['devices'] = [f"cuda:{i}" for i in range(num_gpus)]
            
            total_vram_gb = 0
            for i in range(num_gpus):
                gpu_name = torch.cuda.get_device_name(i)
                gpu_mem = torch.cuda.get_device_properties(i).total_memory / 1024**3
                total_vram_gb += gpu_mem
                gpu_info['gpus'].append({
                    'id': i,
                    'name': gpu_name,
                    'vram_gb': gpu_mem,
                })
            gpu_info['total_vram_gb'] = total_vram_gb
        else:
            gpu_info['num_gpus'] = 1
            gpu_info['devices'] = ["cpu"]
        
        return gpu_info
    
    def patch_propainter(self, propainter_root: Path) -> bool:
        """
        Patch ProPainter misc.py file if needed.
        
        Args:
            propainter_root: Path to ProPainter installation
            
        Returns:
            True if patching was successful or not needed
        """
        misc_file = propainter_root / "model" / "misc.py"
        
        if not misc_file.exists():
            return False
        
        try:
            content = misc_file.read_text(encoding='utf-8')
            
            # Check if already patched
            if "# PATCHED by vastai_inerup" in content:
                return True
            
            # Look for the problematic line
            buggy_marker = "IS_HIGH_VERSION = [int(m) for m in list(re.findall"
            
            if buggy_marker not in content:
                return False
            
            # Simple and robust fix: replace the entire version detection block
            old_code = """IS_HIGH_VERSION = [int(m) for m in list(re.findall(r"^([0-9]+)\\.([0-9]+)\\.([0-9]+)([^0-9][a-zA-Z0-9]*)?(\\+git.*)?$",\\
                       torch.__version__)[0])]"""

            new_code = """# PATCHED by vastai_inerup: fix torch version parsing for non-standard builds
try:
    IS_HIGH_VERSION = [int(m) for m in list(re.findall(r"^([0-9]+)\\.([0-9]+)\\.([0-9]+)([^0-9][a-zA-Z0-9]*)?(\\+git.*)?$",\\
                       torch.__version__)[0])]
except (IndexError, AttributeError, ValueError):
    # Fallback for non-standard torch versions (dev builds, custom compiles)
    import torch
    version_parts = torch.__version__.split('.')
    IS_HIGH_VERSION = [int(version_parts[0]) if len(version_parts) > 0 else 1,
                       int(version_parts[1].split('+')[0].split('a')[0].split('b')[0].split('rc')[0]) if len(version_parts) > 1 else 7,
                       0]"""

            if old_code in content:
                patched_content = content.replace(old_code, new_code)
                misc_file.write_text(patched_content, encoding='utf-8')
                return True
            else:
                # Try alternative format (different whitespace)
                lines = content.split('\n')
                patched_lines = []
                i = 0
                patched = False

                while i < len(lines):
                    line = lines[i]

                    if "IS_HIGH_VERSION = [int(m)" in line and "re.findall" in line:
                        # Found the start of the problematic block
                        indent = len(line) - len(line.lstrip())
                        patched_lines.append(" " * indent + "# PATCHED by vastai_inerup: fix torch version parsing")
                        patched_lines.append(" " * indent + "try:")
                        patched_lines.append(" " * (indent + 4) + line.strip())

                        # Continue copying until we find the closing bracket and end of statement
                        i += 1
                        while i < len(lines) and (lines[i].strip().endswith('\\') or
                                                   not lines[i-1].strip().endswith(')]')):
                            patched_lines.append(" " * (indent + 4) + lines[i].strip())
                            i += 1
                            if i < len(lines) and ')]' in lines[i-1]:
                                break

                        # Add except block
                        patched_lines.append(" " * indent + "except (IndexError, AttributeError, ValueError):")
                        patched_lines.append(" " * (indent + 4) + "import torch")
                        patched_lines.append(" " * (indent + 4) + "version_parts = torch.__version__.split('.')")
                        patched_lines.append(" " * (indent + 4) + "IS_HIGH_VERSION = [int(version_parts[0]) if len(version_parts) > 0 else 1,")
                        patched_lines.append(" " * (indent + 19) + "int(version_parts[1].split('+')[0].split('a')[0].split('b')[0].split('rc')[0]) if len(version_parts) > 1 else 7,")
                        patched_lines.append(" " * (indent + 19) + "0]")
                        patched = True
                    else:
                        patched_lines.append(line)
                        i += 1

                if patched:
                    misc_file.write_text('\n'.join(patched_lines), encoding='utf-8')
                    return True
                else:
                    return False
        except Exception:
            return False
    
    def get_available_gpus(self) -> List[int]:
        """
        Get list of available GPU IDs.
        
        Returns:
            List of GPU IDs
        """
        import torch
        if torch.cuda.is_available():
            return list(range(torch.cuda.device_count()))
        return []
    
    def clear_cuda_cache(self, gpu_id: int = None) -> None:
        """
        Clear CUDA cache for specific GPU or all GPUs.
        
        Args:
            gpu_id: Specific GPU ID to clear, or None for all
        """
        import torch
        import gc
        
        if torch.cuda.is_available():
            if gpu_id is not None:
                with torch.cuda.device(gpu_id):
                    torch.cuda.empty_cache()
                    torch.cuda.synchronize()
            else:
                torch.cuda.empty_cache()
                torch.cuda.synchronize()
            gc.collect()
    
    def patch_propainter_misc(self, propainter_root: Path) -> bool:
        """
        Patch ProPainter misc.py file (alias for patch_propainter).
        
        Args:
            propainter_root: Path to ProPainter installation
            
        Returns:
            True if patching was successful or not needed
        """
        return self.patch_propainter(propainter_root)
    
    def validate_raft_availability(self) -> bool:
        """
        Validate that RAFT models are available.
        
        Returns:
            True if RAFT models are available
        """
        import torch
        raft_dir = Path(__file__).parent.parent.parent.parent / "models" / "raft"
        if raft_dir.exists():
            return True
        # If not found, check if we can download
        return False
    
    def setup_amp_environment(self) -> None:
        """
        Setup AMP (Automatic Mixed Precision) environment.
        
        Enables TF32 for better performance on Ampere+ GPUs.
        """
        import torch
        if torch.cuda.is_available():
            # Enable TensorFloat32 for Ampere+ GPUs (RTX 30/40/50 series)
            torch.backends.cuda.matmul.allow_tf32 = True
            torch.backends.cudnn.allow_tf32 = True
            
            # Log AMP settings
            if self.logger:
                self.logger.info(f"AMP environment: TF32 enabled (matmul.allow_tf32={torch.backends.cuda.matmul.allow_tf32})")
