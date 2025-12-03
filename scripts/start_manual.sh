#!/usr/bin/env bash
set -euo pipefail

# start_manual.sh
# Short helper to start processing inside the container.
# Place this file under /workspace/project/scripts/ (it will be cloned by the batch flow)
# or copy it to /workspace/start_manual.sh and `chmod +x /workspace/start_manual.sh`.

# Example environment variables you may want to export before running:
# export INPUT_URL="https://.../input.mp4"
# export B2_OUTPUT_KEY="output/result.mp4"
# export B2_BUCKET="noxfvr-videos"
# export B2_KEY="input/..."
# export B2_ENDPOINT="https://s3.us-west-004.backblazeb2.com"
# export B2_KEY="<access>"
# export B2_SECRET="<secret>"
# export MODE="interp"            # interp | upscale | both
# export SCALE="2"
# export TARGET_FPS="60"
# export USE_NATIVE_PROCESSORS="1"

REPO_DIR="/workspace/project"
GIT_BRANCH="${GIT_BRANCH:-oop2}"
GIT_REPO="${GIT_REPO:-https://github.com/zerotouchprod/vastai_inerup.git}"

usage() {
  cat <<EOF
Usage: $0 <command> [args...]

Commands:
  runner        Clone repo (if missing) and run the standard remote runner (recommended)
  pipeline [--input /path/to/input.mp4 --output /workspace/output --mode interp ...]
                Run the new Python pipeline entrypoint (pipeline_v2.py) with provided args
  clone         Only clone/update the repo branch to ${GIT_BRANCH}
  help          Show this help

Examples:
  # Run the full runner (will use config.yaml inside the repo)
  $0 runner

  # Run pipeline_v2.py manually on an existing input file
  INPUT_URL="https://..." B2_OUTPUT_KEY="output/out.mp4" $0 pipeline --input /workspace/input.mp4 --output /workspace/output --mode interp --target-fps 60

  # Clone repo to /workspace/project using branch OOP2
  $0 clone

Note: After copying to /workspace/start_manual.sh run: chmod +x /workspace/start_manual.sh
EOF
}

if [ $# -lt 1 ]; then
  usage
  exit 1
fi

cmd="$1"
shift || true

case "$cmd" in
  clone)
    echo "[start_manual] Ensuring repo at $REPO_DIR (branch: $GIT_BRANCH)"
    if [ -d "$REPO_DIR/.git" ]; then
      echo "[start_manual] Repo exists, attempting git fetch and checkout"
      git -C "$REPO_DIR" fetch --all --prune || true
      git -C "$REPO_DIR" checkout "$GIT_BRANCH" || git -C "$REPO_DIR" checkout -b "$GIT_BRANCH" origin/$GIT_BRANCH || true
      git -C "$REPO_DIR" pull --ff-only || true
    else
      echo "[start_manual] Cloning $GIT_REPO (branch $GIT_BRANCH) -> $REPO_DIR"
      git clone --depth 1 -b "$GIT_BRANCH" "$GIT_REPO" "$REPO_DIR" || git clone --depth 1 "$GIT_REPO" "$REPO_DIR"
    fi
    ;;

  runner)
    # Ensure repo exists and then run remote_runner.sh
    if [ ! -d "$REPO_DIR/.git" ]; then
      echo "[start_manual] Repo not found, cloning first..."
      "$0" clone
    fi

    echo "[start_manual] Running remote runner: bash $REPO_DIR/scripts/remote_runner.sh"
    bash "$REPO_DIR/scripts/remote_runner.sh"
    ;;

  pipeline)
    # Run pipeline_v2.py directly. Pass remaining args to the Python script.
    PY_CMD=(python3 "$REPO_DIR/pipeline_v2.py")
    if [ ! -f "$REPO_DIR/pipeline_v2.py" ]; then
      echo "[start_manual] pipeline_v2.py not found in $REPO_DIR. Have you cloned the repo?"
      echo "Hint: $0 clone"
      exit 2
    fi

    echo "[start_manual] Running pipeline_v2.py with args: $*"
    exec "${PY_CMD[@]}" "$@"
    ;;

  help|--help|-h)
    usage
    ;;

  *)
    echo "Unknown command: $cmd"
    usage
    exit 3
    ;;
esac

exit 0

