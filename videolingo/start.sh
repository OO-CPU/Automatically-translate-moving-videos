#!/bin/bash
# VideoLingo 启动脚本（需 Clash 代理 127.0.0.1:7897 运行）
cd "$(dirname "$0")"
export PATH="/opt/homebrew/bin:/usr/local/bin:$PATH"
export HTTPS_PROXY=http://127.0.0.1:7897
export HTTP_PROXY=http://127.0.0.1:7897
export ALL_PROXY=http://127.0.0.1:7897
# NLTK 安全机制误伤项目内 venv，官方开关关闭（见 nltk/inisec.py）
export NLTK_DISABLE_IMPORT_SECURITY=1
exec .venv/bin/streamlit run st.py --server.port 8501 --server.headless true --browser.gatherUsageStats false
