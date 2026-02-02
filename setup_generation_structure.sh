#!/bin/bash
# Setup script for Video Generation module structure

set -e

echo "🚀 Creating directory structure for Video Generation module..."

# Domain layer
mkdir -p src/domain

# Services layer
mkdir -p src/services/generation/engines
mkdir -p src/services/generation/utils

# Entrypoints
mkdir -p src/entrypoints

# Tests structure
mkdir -p tests/unit/domain
mkdir -p tests/unit/services/generation/engines
mkdir -p tests/unit/services/generation/utils
mkdir -p tests/integration/generation
mkdir -p tests/integration/entrypoints
mkdir -p tests/docker

# Examples
mkdir -p examples/generation

# Create __init__.py files
touch src/services/generation/__init__.py
touch src/services/generation/engines/__init__.py
touch src/services/generation/utils/__init__.py

touch tests/unit/domain/__init__.py
touch tests/unit/services/__init__.py
touch tests/unit/services/generation/__init__.py
touch tests/unit/services/generation/engines/__init__.py
touch tests/unit/services/generation/utils/__init__.py

touch tests/integration/__init__.py
touch tests/integration/generation/__init__.py
touch tests/integration/entrypoints/__init__.py

echo "✅ Directory structure created!"
echo ""
echo "📁 Created directories:"
echo "  - src/domain/"
echo "  - src/services/generation/engines/"
echo "  - src/services/generation/utils/"
echo "  - src/entrypoints/"
echo "  - tests/unit/domain/"
echo "  - tests/unit/services/generation/engines/"
echo "  - tests/unit/services/generation/utils/"
echo "  - tests/integration/generation/"
echo "  - tests/integration/entrypoints/"
echo "  - tests/docker/"
echo "  - examples/generation/"
echo ""
echo "📋 Next steps:"
echo "  1. Review IMPLEMENTATION_PLAN_GENERATION.md"
echo "  2. Start with Domain Layer (src/domain/generation.py)"
echo "  3. Implement Configuration (src/services/generation/config.py)"
echo "  4. Follow TODO_GENERATION.md checklist"
echo ""
echo "🧪 Run tests:"
echo "  pytest tests/unit/services/generation/ -v"
