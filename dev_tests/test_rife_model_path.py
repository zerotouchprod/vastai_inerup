"""
Test RIFE model path discovery.
"""
import sys
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent / "src"))

from infrastructure.processors.rife.native import RIFENative
from shared.logging import setup_logger

setup_logger(debug=True)

print("Testing RIFE model path discovery...")
print()

# Create temporary test directories to simulate Docker environment
test_paths = [
    Path("/opt/rife_models/train_log"),  # Docker path (won't exist locally)
    Path("RIFEv4.26_0921"),
    Path("external/RIFE/train_log"),
]

print("Expected search paths (in order):")
for i, path in enumerate(test_paths, 1):
    status = "✓ EXISTS" if path.exists() else "✗ NOT FOUND"
    has_pkl = "with .pkl files" if path.exists() and list(path.glob('*.pkl')) else "no .pkl files"
    print(f"  {i}. {path} - {status} ({has_pkl})")

print()
print("=" * 60)
print()

# Try to create RIFENative (will fail if no models found, but that's expected locally)
try:
    processor = RIFENative(factor=2)
    print(f"✅ SUCCESS: Found RIFE model at: {processor.model_path}")
except FileNotFoundError as e:
    print(f"⚠️  Expected failure (no models in local dev environment):")
    print(f"   {e}")
    print()
    print("This is normal - the Docker container has models at /opt/rife_models/train_log/")
except Exception as e:
    print(f"❌ Unexpected error: {e}")
    import traceback
    traceback.print_exc()

