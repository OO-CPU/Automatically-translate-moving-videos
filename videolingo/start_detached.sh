#!/bin/bash
# launchd 托管启动（等效 start.sh，日志写到 /tmp/videolingo-streamlit.log）
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$SCRIPT_DIR"
export PATH="/opt/homebrew/bin:/usr/local/bin:$PATH"
export HTTPS_PROXY=http://127.0.0.1:7897
export HTTP_PROXY=http://127.0.0.1:7897
export ALL_PROXY=http://127.0.0.1:7897
export NLTK_DISABLE_IMPORT_SECURITY=1
export YOUTUBE_REPOST_DATA_DIR="${YOUTUBE_REPOST_DATA_DIR:-$REPO_ROOT/data}"
export VIDEOLINGO_HOME="$SCRIPT_DIR"
PYTHON_BIN="${VIDEOLINGO_PYTHON:-$SCRIPT_DIR/.venv/bin/python}"
STREAMLIT_BIN="${VIDEOLINGO_STREAMLIT:-$SCRIPT_DIR/.venv/bin/streamlit}"
# 自动导入监控：随页面服务一起启停（不额外占用 launchd 任务）
pkill -f "auto_import_watch.py" 2>/dev/null
nohup "$PYTHON_BIN" "$REPO_ROOT/pipeline/auto_import_watch.py" --watch-dir "$YOUTUBE_REPOST_DATA_DIR/生肉视频" >> /tmp/auto-import-watch.log 2>&1 &
# 下载监控页：http://localhost:7799（随页面服务一起启停）
pkill -f "downloads_dashboard.py" 2>/dev/null
nohup "$PYTHON_BIN" "$REPO_ROOT/pipeline/downloads_dashboard.py" >> /tmp/downloads-dashboard.log 2>&1 &
exec "$STREAMLIT_BIN" run st.py --server.port 8501 --server.headless true --browser.gatherUsageStats false >> /tmp/videolingo-streamlit.log 2>&1
