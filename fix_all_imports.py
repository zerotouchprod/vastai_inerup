"""
Script to fix imports in the entire project by replacing relative imports with absolute imports.
"""

import os
import re
from pathlib import Path

def fix_imports_in_file(file_path):
    """Fix imports in a single Python file."""
    with open(file_path, 'r', encoding='utf-8') as f:
        content = f.read()
    
    # Patterns to match
    patterns = [
        # from src.domain. -> from src.domain.
        (r'from domain\.', 'from src.domain.'),
        # from src.infrastructure. -> from src.infrastructure.
        (r'from infrastructure\.', 'from src.infrastructure.'),
        # from src.application. -> from src.application.
        (r'from application\.', 'from src.application.'),
        # from src.shared. -> from src.shared.
        (r'from shared\.', 'from src.shared.'),
        # from src.presentation. -> from src.presentation.
        (r'from presentation\.', 'from src.presentation.'),
        # from src.core. -> from src.core.
        (r'from core\.', 'from src.core.'),
        # from src.services. -> from src.services.
        (r'from services\.', 'from src.services.'),
        # from src.io. -> from src.io.
        (r'from io\.', 'from src.io.'),
        # from src.models. -> from src.models.
        (r'from models\.', 'from src.models.'),
        # from src.pipeline. -> from src.pipeline.
        (r'from pipeline\.', 'from src.pipeline.'),
        # from src.utils. -> from src.utils.
        (r'from utils\.', 'from src.utils.'),
        # from src.config. -> from src.config.
        (r'from config\.', 'from src.config.'),
    ]
    
    original_content = content
    for pattern, replacement in patterns:
        content = re.sub(pattern, replacement, content)
    
    if content != original_content:
        with open(file_path, 'w', encoding='utf-8') as f:
            f.write(content)
        return True
    return False

def find_python_files(root_dir):
    """Find all Python files in the project."""
    python_files = []
    for root, dirs, files in os.walk(root_dir):
        # Skip hidden directories
        dirs[:] = [d for d in dirs if not d.startswith('.') and d != '__pycache__']
        
        for file in files:
            if file.endswith('.py'):
                python_files.append(Path(root) / file)
    return python_files

def main():
    """Main function to fix imports in the entire project."""
    project_root = Path('.')
    
    print("Finding Python files...")
    python_files = find_python_files(project_root)
    print(f"Found {len(python_files)} Python files")
    
    fixed_count = 0
    for file_path in python_files:
        try:
            if fix_imports_in_file(file_path):
                print(f"Fixed imports in: {file_path}")
                fixed_count += 1
        except Exception as e:
            print(f"Error processing {file_path}: {e}")
    
    print(f"\nFixed imports in {fixed_count} files")
    
    # Also fix __init__.py files that might have incorrect imports
    print("\nChecking for remaining import issues...")
    
    # Test import of key modules
    test_imports = [
        "from src.application.factories import ProcessorFactory",
        "from src.domain.models import Job",
        "from src.infrastructure.config import ConfigLoader",
        "from src.shared.logging import get_logger",
    ]
    
    print("\nTest imports:")
    for import_stmt in test_imports:
        print(f"  {import_stmt}")
    
    print("\nTo test the fixes, run:")
    print("  python -c \"from src.application.factories import ProcessorFactory; print('Import successful')\"")

if __name__ == "__main__":
    main()
