#!/bin/bash
# Commit script for interpolation duration fix

set -e

echo "============================================================"
echo "Interpolation Duration Fix - Commit & Deploy"
echo "============================================================"
echo ""

# Colors
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# 1. Show what changed
echo "📝 Files changed:"
echo "  Modified: src/application/orchestrator.py"
echo "  Created:  test_interp_fps_fix.py"
echo "  Created:  INTERP_DURATION_FIX_COMPLETE.md"
echo ""

# 2. Run tests
echo "🧪 Running tests..."
if python3 test_interp_fps_fix.py; then
    echo -e "${GREEN}✅ All tests passed!${NC}"
else
    echo -e "${YELLOW}❌ Tests failed! Please fix before committing.${NC}"
    exit 1
fi
echo ""

# 3. Show diff summary
echo "📊 Checking git status..."
git status --short
echo ""

# 4. Confirm commit
echo -e "${YELLOW}Ready to commit these changes?${NC}"
echo "  Press ENTER to continue, or Ctrl+C to cancel"
read -r

# 5. Add files
echo "📦 Adding files to git..."
git add src/application/orchestrator.py
git add test_interp_fps_fix.py
git add INTERP_DURATION_FIX_COMPLETE.md
git add DEPLOYMENT_CHECKLIST.md 2>/dev/null || true

# 6. Commit
echo "💾 Committing..."
git commit -m "fix(interp): preserve video duration by calculating FPS from interp_factor

Problem: Videos became shorter after interpolation (8s → 6.38s)
Root cause: Explicit target_fps=60 from config was overriding calculated FPS

Changes:
- Reordered FPS calculation logic in orchestrator.py
- Interpolation mode now always calculates: FPS = original_fps × interp_factor
- Added warning when explicit target_fps is ignored for interp mode
- Enhanced duration analysis logging

Testing:
- Created comprehensive test suite (test_interp_fps_fix.py)
- All 4 tests passing
- Verified duration preservation within 0.1s tolerance

Impact:
- Fixes: Interpolation duration bug
- Preserves: Audio sync
- Compatible: Backward compatible, no API changes

Closes: #duration-bug"

echo ""
echo -e "${GREEN}✅ Committed successfully!${NC}"
echo ""

# 7. Show commit
echo "📋 Commit details:"
git log -1 --stat

echo ""
echo "============================================================"
echo "🎉 Ready to push!"
echo "============================================================"
echo ""
echo "Next steps:"
echo "  1. Review the commit above"
echo "  2. Push to remote: git push origin <branch>"
echo "  3. Test in staging environment"
echo "  4. Monitor first 10 interpolation jobs in production"
echo ""

