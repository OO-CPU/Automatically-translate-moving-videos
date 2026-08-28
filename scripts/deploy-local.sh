#!/bin/bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
RUNTIME="${YOUTUBE_REPOST_RUNTIME:-$HOME/youtube-repost-runtime}"
RESTART=0

if [[ "${1:-}" == "--restart" ]]; then
  RESTART=1
elif [[ $# -gt 0 ]]; then
  echo "用法：$0 [--restart]" >&2
  exit 2
fi

mkdir -p "$RUNTIME"

rsync -a --delete "$ROOT/pipeline/" "$RUNTIME/pipeline/"
rsync -a --delete \
  --exclude='.venv' \
  --exclude='config.yaml' \
  --exclude='_model_cache' \
  --exclude='history' \
  --exclude='output' \
  --exclude='__pycache__' \
  --exclude='*.pyc' \
  "$ROOT/videolingo/" "$RUNTIME/videolingo/"
rsync -a --delete --exclude='__pycache__' --exclude='*.pyc' \
  "$ROOT/xiaoer-videolab/" "$RUNTIME/xiaoer-videolab/"
rsync -a --delete "$ROOT/creator_monitor/" "$RUNTIME/creator_monitor/"
rsync -a --delete "$ROOT/legacy/" "$RUNTIME/legacy/"
rsync -a --delete "$ROOT/deploy/" "$RUNTIME/deploy/"
cp "$ROOT/README.md" "$ROOT/AGENTS.md" "$RUNTIME/"

ln -sfn "$HOME/视频自动搬运发布" "$RUNTIME/data"
ln -sfn "$HOME/videolingo/.venv" "$RUNTIME/videolingo/.venv"
ln -sfn "$HOME/videolingo/config.yaml" "$RUNTIME/videolingo/config.yaml"
ln -sfn "$HOME/videolingo/_model_cache" "$RUNTIME/videolingo/_model_cache"
ln -sfn "$HOME/videolingo/history" "$RUNTIME/videolingo/history"
ln -sfn "$HOME/videolingo/output" "$RUNTIME/videolingo/output"

echo "已部署源码到：$RUNTIME"

if [[ "$RESTART" -ne 1 ]]; then
  echo "未重启服务；确认无活动下载后执行：$0 --restart"
  exit 0
fi

DOWNLOADS="$(curl -fsS http://127.0.0.1:7799/api/downloads 2>/dev/null || true)"
if [[ "$DOWNLOADS" == *'"status":"downloading"'* ]]; then
  echo "检测到活动下载，拒绝重启。下载结束或暂停后再执行。" >&2
  exit 3
fi

PLIST="$HOME/Library/LaunchAgents/com.xiaoer.videolab.plist"
VIDEOLINGO_PLIST="$HOME/Library/LaunchAgents/com.videolingo.streamlit.plist"
cp "$PLIST" "$PLIST.pre-youtube-repost-runtime.bak"
cp "$ROOT/deploy/com.videolingo.streamlit.plist" "$VIDEOLINGO_PLIST"
/usr/libexec/PlistBuddy -c "Set :ProgramArguments:1 $RUNTIME/xiaoer-videolab/daemon/server.py" "$PLIST"
/usr/libexec/PlistBuddy -c "Set :EnvironmentVariables:VIDEOLAB_DOWNLOADS $RUNTIME/data/生肉视频" "$PLIST"

LAUNCH_DOMAIN="gui/$(id -u)"

restart_launch_agent() {
  label="$1"
  plist_path="$2"
  launchctl bootout "$LAUNCH_DOMAIN/$label" 2>/dev/null || true
  # macOS 偶尔需要一点时间完成 bootout，否则立即 bootstrap 会返回 I/O error。
  attempt=1
  while [ "$attempt" -le 3 ]; do
    sleep 1
    if launchctl bootstrap "$LAUNCH_DOMAIN" "$plist_path"; then
      return 0
    fi
    attempt=$((attempt + 1))
  done
  echo "无法启动 $label" >&2
  return 1
}

restart_launch_agent com.videolingo.streamlit "$VIDEOLINGO_PLIST"
restart_launch_agent com.xiaoer.videolab "$PLIST"

for _ in {1..12}; do
  if curl -fsS http://127.0.0.1:7788/health >/dev/null 2>&1 \
    && curl -fsS http://127.0.0.1:7799/api/downloads >/dev/null 2>&1 \
    && curl -fsS http://127.0.0.1:8501 >/dev/null 2>&1; then
    echo "服务已切换并通过健康检查。"
    exit 0
  fi
  sleep 1
done

echo "服务启动超时，请检查 /tmp/videolingo-streamlit.log 和 Xiaoer 日志。" >&2
exit 4
