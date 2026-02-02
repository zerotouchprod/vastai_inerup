#!/bin/bash
# Comprehensive test suite for video generation module

set -e

echo "🧪 Running comprehensive test suite..."
echo "======================================"
echo ""

FAILED=0
PASSED=0

# Function to run test
run_test() {
    local name="$1"
    local command="$2"

    echo "▶️  $name"
    if eval "$command" > /dev/null 2>&1; then
        echo "   ✅ PASSED"
        ((PASSED++))
    else
        echo "   ❌ FAILED"
        ((FAILED++))
    fi
    echo ""
}

# 1. Import tests
echo "📦 Phase 1: Import Tests"
echo "------------------------"
run_test "Module imports" "python tests/test_generation_imports.py"

# 2. Unit tests
echo "🔬 Phase 2: Unit Tests"
echo "----------------------"
run_test "Config tests" "pytest tests/unit/services/generation/test_config.py -v --tb=short"
run_test "Models tests" "pytest tests/unit/services/generation/test_models.py -v --tb=short"
run_test "Base engine tests" "pytest tests/unit/services/generation/engines/test_base_engine.py -v --tb=short"
run_test "T2V engine tests" "pytest tests/unit/services/generation/engines/test_text2video_engine.py -v --tb=short"

# 3. Integration tests
echo "🔗 Phase 3: Integration Tests"
echo "------------------------------"
run_test "T2V workflow" "pytest tests/integration/generation/test_text2video_workflow.py -v --tb=short"

# 4. CLI tests
echo "🖥️  Phase 4: CLI Tests"
echo "----------------------"
run_test "Dry-run T2V" "python -m src.entrypoints.run_gen --job '{\"prompts\": [\"test\"]}' --dry-run"
run_test "Dry-run with params" "python -m src.entrypoints.run_gen --job '{\"prompts\": [\"test\"], \"guidance_scale\": 7.0}' --dry-run"

# 5. Validation tests
echo "✅ Phase 5: Validation Tests"
echo "----------------------------"
run_test "Valid job creation" "python -c 'from src.services.generation.models import GenJob; GenJob(prompts=[\"test\"])'"
run_test "Invalid params" "python -c 'from src.services.generation.models import GenJob; import sys; job = GenJob(prompts=[\"test\"], guidance_scale=25.0) or sys.exit(1)' && exit 1 || exit 0"

# 6. Config tests
echo "⚙️  Phase 6: Configuration Tests"
echo "--------------------------------"
run_test "Default config" "python -c 'from src.services.generation.config import GenerationConfig; GenerationConfig()'"
run_test "Config validation" "python -c 'from src.services.generation.config import GenerationConfig; c = GenerationConfig(); c.validate_generation_params(6.0, 50, 49)'"

# Summary
echo "======================================"
echo "📊 Test Results Summary"
echo "======================================"
echo "✅ Passed: $PASSED"
echo "❌ Failed: $FAILED"
echo "📈 Total:  $((PASSED + FAILED))"
echo ""

if [ $FAILED -eq 0 ]; then
    echo "🎉 All tests passed!"
    echo ""
    echo "✅ Module is ready for GPU testing"
    echo ""
    echo "Next steps:"
    echo "  1. Build Docker: ./tests/docker/build_and_test_gen.sh"
    echo "  2. Test on GPU with real model"
    echo "  3. Deploy to Vast.ai/RunPod"
    exit 0
else
    echo "⚠️  Some tests failed. Please review."
    exit 1
fi
