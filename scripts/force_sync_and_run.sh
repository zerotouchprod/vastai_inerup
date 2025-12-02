#!/usr/bin/env bash
set -euo pipefail

# force_sync_and_run.sh
# Safe helper to ensure /workspace/project is checked out to desired branch
# and then run the repo's remote_runner.sh. Intended for use as onstart command
# in environments that accept only a script path.

GIT_BRANCH_OVERRIDE="${GIT_BRANCH:-}"
DEFAULT_BRANCH="oop2"
BRANCH="${GIT_BRANCH_OVERRIDE:-$DEFAULT_BRANCH}"

echo "[force_sync] Starting force_sync_and_run.sh"
echo "[force_sync] Desired branch: $BRANCH"

# If repo doesn't exist, clone desired branch
if [ ! -d "/workspace/project/.git" ]; then
  echo "[force_sync] /workspace/project not present; attempting clone branch $BRANCH"
  rm -rf /workspace/project || true
  mkdir -p /workspace/project
  if git clone --depth 1 -b "$BRANCH" https://github.com/zerotouchprod/vastai_inerup.git /workspace/project; then
    echo "[force_sync] Clone successful"
  else
    echo "[force_sync] Clone failed; attempting shallow clone of main and reading remote config as fallback"
    rm -rf /workspace/project || true
    git clone --depth 1 https://github.com/zerotouchprod/vastai_inerup.git /workspace/project || true
  fi
else
  echo "[force_sync] /workspace/project exists - performing safe fetch+reset to origin/$BRANCH"
  # fetch branch and reset if possible
  git -C /workspace/project fetch origin "$BRANCH" --depth=1 || echo "[force_sync] git fetch failed (continuing)"
  if git -C /workspace/project rev-parse --verify "origin/$BRANCH" >/dev/null 2>&1; then
    git -C /workspace/project reset --hard "origin/$BRANCH" || echo "[force_sync] git reset failed (continuing)"
    echo "[force_sync] Reset to origin/$BRANCH completed"
  else
    echo "[force_sync] origin/$BRANCH not found; leaving existing checkout (you can set GIT_BRANCH env to override)"
  fi
fi

# Optionally show top-level files (diagnostic)
echo "[force_sync] Repo top-level listing (first 50 entries):"
ls -la /workspace/project | sed -n '1,50p' || true

# Ensure remote_runner exists and is executable
if [ -f "/workspace/project/scripts/remote_runner.sh" ]; then
  chmod +x /workspace/project/scripts/remote_runner.sh || true
  echo "[force_sync] Executing repo remote_runner.sh"
  # Exec to replace shell with runner (preserves PID/logging)
  exec bash /workspace/project/scripts/remote_runner.sh
else
  echo "[force_sync] ERROR: /workspace/project/scripts/remote_runner.sh not found"
  echo "[force_sync] Printing /workspace/project listing for debugging:"
  ls -la /workspace/project || true
  exit 2
fi

