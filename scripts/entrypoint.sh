#!/usr/bin/env bash
set -e

echo "=== Container Entrypoint ==="
echo "Time: $(date)"

# Update project code from Git on every container start
if [ -d "/workspace/project/.git" ]; then
  echo "[entrypoint] Updating project from Git repository..."
  cd /workspace/project
  git fetch origin main
  git reset --hard origin/main
  echo "[entrypoint] Project updated to latest commit: $(git rev-parse --short HEAD)"

  # IMPORTANT: If project already exists and updated, skip the command's git clone part
  # Check if command tries to clone project again (rm -rf /workspace/project && git clone)
  if echo "$@" | grep -q "rm -rf /workspace/project"; then
    echo "[entrypoint] WARNING: Command tries to delete and re-clone project, but project is already up-to-date"
    echo "[entrypoint] Skipping project deletion, executing rest of command..."

    # Extract and execute only the part AFTER git clone (the actual work)
    # Assuming format: bash -c 'cd / && rm -rf /workspace/project && git clone ... && ACTUAL_WORK'
    # We want to skip up to "git clone" and execute everything after it
    NEW_CMD=$(echo "$@" | sed 's|.*git clone[^&]*&&||')

    if [ -n "$NEW_CMD" ]; then
      echo "[entrypoint] Executing: $NEW_CMD"
      eval "$NEW_CMD"
    else
      echo "[entrypoint] No additional commands to execute after git clone"
    fi
    exit $?
  fi
else
  echo "[entrypoint] Project not cloned yet (first run)"
fi

# --- Install project requirements if present (non-fatal) ---
# NOTE: This runs only on container start when project is present; it helps ensure
# that updated requirements are installed when the project repo changes.
REQ_FILE="/workspace/project/requirements.txt"
if [ -f "$REQ_FILE" ]; then
  echo "[entrypoint] Found project requirements at $REQ_FILE — attempting pip install"
  # If a virtualenv exists at /opt/venv activate it
  if [ -d "/opt/venv" ] && [ -f "/opt/venv/bin/activate" ]; then
    echo "[entrypoint] Activating venv /opt/venv"
    # shellcheck disable=SC1091
    source /opt/venv/bin/activate || true
  fi
  # Install; tolerate failures but log them
  if command -v pip >/dev/null 2>&1; then
    if pip install --no-cache-dir -r "$REQ_FILE"; then
      echo "[entrypoint] requirements installed successfully"
    else
      echo "[entrypoint] WARNING: pip install returned non-zero exit code (continuing)"
    fi
  else
    echo "[entrypoint] WARNING: pip not found in PATH — cannot install requirements"
  fi
fi

# Execute the command passed to the container (if not skipped above)
echo "[entrypoint] Executing: $@"
exec "$@"
