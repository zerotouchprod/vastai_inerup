#!/usr/bin/env bash
set -e

echo "=== Container Entrypoint ==="
echo "Time: $(date)"

# Update project code from Git on every container start
if [ -d "/workspace/project/.git" ]; then
  echo "[entrypoint] Updating project from Git repository..."
  cd /workspace/project

  # Read git_branch from config.yaml if present
  GIT_BRANCH="main"
  if [ -f "config.yaml" ]; then
    BRANCH_FROM_CONFIG=$(python3 - <<'PY' 2>/dev/null || echo ""
import yaml
try:
    with open('config.yaml', 'r') as f:
        cfg = yaml.safe_load(f)
        if isinstance(cfg, dict):
            branch = cfg.get('git_branch', '').strip()
            if branch:
                print(branch)
except Exception:
    pass
PY
)
    if [ -n "$BRANCH_FROM_CONFIG" ]; then
      GIT_BRANCH="$BRANCH_FROM_CONFIG"
      echo "[entrypoint] Using git_branch from config.yaml: $GIT_BRANCH"
    fi
  fi

  # Fetch and checkout branch
  git fetch origin "$GIT_BRANCH"
  git reset --hard "origin/$GIT_BRANCH"
  echo "[entrypoint] Project updated to latest commit on branch '$GIT_BRANCH': $(git rev-parse --short HEAD)"

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
  echo "[entrypoint] Project not cloned yet (will be cloned by args_str command)"
fi

# --- New: fetch remote config_url (if present in config.yaml) on every start ---
# This ensures a remote config specified by 'config_url' is downloaded and applied
CONFIG_PATH="/workspace/project/config.yaml"
if [ -f "$CONFIG_PATH" ]; then
  echo "[entrypoint] Checking for remote config_url in $CONFIG_PATH"
  REMOTE_URL=$(python3 - <<'PY' 2>/dev/null
import yaml,sys
p='/workspace/project/config.yaml'
try:
    cfg=yaml.safe_load(open(p))
    if isinstance(cfg,dict):
        for k,v in cfg.items():
            if isinstance(k,str):
                k2=k.replace('\u0441','c').strip().lower()
                if k2=='config_url' and isinstance(v,str) and v.strip():
                    print(v.strip())
                    sys.exit(0)
    print('')
except Exception:
    print('')
PY
)
  if [ -n "$REMOTE_URL" ]; then
    echo "[entrypoint] Found remote config_url: $REMOTE_URL"
    TMP_REMOTE=$(mktemp /tmp/remote_config.XXXXXX)
    if curl -fsSL "$REMOTE_URL" -o "$TMP_REMOTE"; then
      echo "[entrypoint] Remote config downloaded — merging with existing $CONFIG_PATH"
      # Merge remote config with existing config.yaml using Python
      if python3 - "$TMP_REMOTE" "$CONFIG_PATH" 2>/tmp/entrypoint_config_parse.log <<'PY'
import sys, json
import yaml

src = sys.argv[1]  # Downloaded remote config
dst = sys.argv[2]  # Existing config.yaml

# Read remote config
try:
    raw = open(src, 'rb').read()
    text = raw.decode('utf-8')
except Exception as e:
    print(f'Failed to read downloaded remote config: {e}', file=sys.stderr)
    sys.exit(2)

# Parse remote config (try JSON first, then YAML)
remote_config = None
try:
    remote_config = json.loads(text)
    print('[entrypoint] Remote config parsed as JSON')
except Exception:
    try:
        remote_config = yaml.safe_load(text)
        print('[entrypoint] Remote config parsed as YAML')
    except Exception as e:
        print(f'Failed to parse remote config as JSON or YAML: {e}', file=sys.stderr)
        sys.exit(2)

if not isinstance(remote_config, dict):
    print('Remote config is not a mapping/object (expected dict)', file=sys.stderr)
    sys.exit(2)

# Read existing config.yaml
existing_config = {}
try:
    with open(dst, 'r', encoding='utf-8') as f:
        existing_config = yaml.safe_load(f) or {}
    if not isinstance(existing_config, dict):
        existing_config = {}
except Exception as e:
    print(f'Warning: Could not read existing config: {e}', file=sys.stderr)
    existing_config = {}

# Deep merge: remote config overrides existing config
def deep_merge(base, override):
    """Deep merge override into base."""
    result = base.copy()
    for key, value in override.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = deep_merge(result[key], value)
        else:
            result[key] = value
    return result

merged_config = deep_merge(existing_config, remote_config)

# Show what was merged
print(f'[entrypoint] Merged remote config keys: {list(remote_config.keys())}')
if 'video' in remote_config:
    print(f'[entrypoint]   video: {remote_config["video"]}')

# Write merged config back as YAML
try:
    with open(dst, 'w', encoding='utf-8') as f:
        yaml.safe_dump(merged_config, f, sort_keys=False, allow_unicode=True, default_flow_style=False)
    print(f'[entrypoint] Merged config written to {dst}')
except Exception as e:
    print(f'Failed to write merged config: {e}', file=sys.stderr)
    sys.exit(2)

sys.exit(0)
PY
      then
        echo "[entrypoint] ✓ Remote config merged successfully"
      else
        echo "[entrypoint] ✗ Failed to merge remote config (see /tmp/entrypoint_config_parse.log)"
        echo "[entrypoint] Parse log (tail):"; tail -n 50 /tmp/entrypoint_config_parse.log || true
      fi
     rm -f "$TMP_REMOTE" || true
     else
       echo "[entrypoint] ERROR: Failed to download remote config from $REMOTE_URL"
       rm -f "$TMP_REMOTE" || true
     fi
  else
    echo "[entrypoint] No remote config_url found in $CONFIG_PATH"
  fi
else
  echo "[entrypoint] No $CONFIG_PATH present to check for remote config_url"
fi
# --- End remote config fetch ---

# Execute the command passed to the container (if not skipped above)
echo "[entrypoint] Executing: $@"
exec "$@"
