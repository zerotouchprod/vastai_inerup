# Fix imports script - run with: python fix_imports.py

import re
from pathlib import Path

def fix_imports_in_file(file_path):
    """Fix relative imports to absolute imports."""
    with open(file_path, 'r', encoding='utf-8') as f:
        content = f.read()

    original_content = content

    # Replace triple-dot imports (from ...domain -> from domain)
    content = re.sub(r'from \.\.\.domain', 'from domain', content)
    content = re.sub(r'from \.\.\.shared', 'from shared', content)
    content = re.sub(r'from \.\.\.infrastructure', 'from infrastructure', content)
    content = re.sub(r'from \.\.\.application', 'from application', content)

    # Replace double-dot imports (from ..domain -> from domain)
    content = re.sub(r'from \.\.domain', 'from domain', content)
    content = re.sub(r'from \.\.shared', 'from shared', content)
    content = re.sub(r'from \.\.infrastructure', 'from infrastructure', content)
    content = re.sub(r'from \.\.application', 'from application', content)

    # Replace single-dot imports for subdirectories (from .storage -> from infrastructure.storage)
    # This needs context awareness, skipping for now

    if content != original_content:
        with open(file_path, 'w', encoding='utf-8') as f:
            f.write(content)
        print(f"Fixed: {file_path}")
        return True
    return False

# Find all Python files
src_dir = Path('src')
fixed_count = 0

for py_file in src_dir.rglob('*.py'):
    if fix_imports_in_file(py_file):
        fixed_count += 1

print(f"\nFixed {fixed_count} files")

