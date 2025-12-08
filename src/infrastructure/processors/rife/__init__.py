"""RIFE processors package."""

# Export available wrappers under stable names. Avoid hard import of optional
# shell-based pytorch wrapper which may not be present in some working trees.
from infrastructure.processors.rife.native_wrapper import RIFENativeWrapper

# Try to import optional pytorch wrapper
try:
    from infrastructure.processors.rife.pytorch_wrapper import RifePytorchWrapper
except Exception:  # pragma: no cover - defensive
    RifePytorchWrapper = None

__all__ = ["RIFENativeWrapper", "RifePytorchWrapper"]
