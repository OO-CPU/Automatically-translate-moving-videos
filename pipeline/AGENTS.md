# AGENTS.md — 视频自动搬运项目

本机自动化项目：「视频下载 → 中文字幕熟肉制作 → 发布文案生成」。接手任何任务前先读本文件与 `docs/交接文档.md`（完整版，含数据格式、排障、验收清单）。

## 项目构成

- **下载**：Chrome 扩展 Xiaoer VideoLab（`~/xiaoer-videolab/extension/`）+ 本地 daemon（`~/xiaoer-videolab/daemon/server.py`，127.0.0.1:7788，yt-dlp 下载到 `~/视频自动搬运发布/生肉视频/`）。
- **监控页**：`~/视频自动搬运发布/downloads_dashboard.py`（127.0.0.1:7799，进度/暂停/继续/删除/打开位置）。
- **字幕**：VideoLingo（`~/videolingo/`，Streamlit :8501，识别/翻译/烧录，成品复制到 `~/视频自动搬运发布/熟肉视频/`）。
- **自动导入**：`~/视频自动搬运发布/auto_import_watch.py`（监控 `生肉视频/` → 自动进字幕流程）。
- **发布文案**：熟肉生成后自动生成中文标题/简介/话题，保存为 `熟肉视频/<视频名>_发布文案.txt`，供手动上传抖音时复制（本机已移除抖音自动化发布模块）。
- **一键生成最终版**：字幕就绪后页面提供「🚀 生成最终版熟肉视频」——先由 LLM 分析片尾字幕自动识别尾部广告起点（`videolingo/core/st_utils/finalize_section.py`，缓存于 `output/gpt_log/ad_detect.json`），用户确认标题（默认取 YouTube 原视频名直译，`title_utils.py`）与裁剪点（附帧预览）后，一次 ffmpeg 完成「裁剪尾部广告 + 烧录字幕 + 封面标题」，直接输出唯一成品 `熟肉视频/<视频名>_字幕.mp4`；发布文案保存成功后，当前 `output/` 项目自动归档到 `history/`，让 watcher 继续导入下一条视频。标题样式：渐变遮罩+自适应大字号，时长/位置/字号可在页面调整。

## 服务与重启（修改代码后无热加载，必须重启对应服务）

| 服务 | 任务 | 重启命令 |
|---|---|---|
| 字幕页+监控页+自动导入 | `com.videolingo.streamlit` | `launchctl remove com.videolingo.streamlit && launchctl submit -l com.videolingo.streamlit -- /Users/limingyu/videolingo/start_detached.sh` |
| Xiaoer daemon | `com.xiaoer.videolab` | `launchctl remove com.xiaoer.videolab && launchctl load ~/Library/LaunchAgents/com.xiaoer.videolab.plist` |

- 日志：`/tmp/videolingo-streamlit.log`、`/tmp/downloads-dashboard.log`、`/tmp/auto-import-watch.log`、`~/Library/Logs/xiaoer-videolab.{out,err}.log`、历史 `xiaoer-videolab-history.jsonl`。
- 健康检查：`curl http://127.0.0.1:7788/health`、`curl http://localhost:7799/api/downloads`。
- 重启 daemon 前先确认监控页没有进行中的下载（会中断，`.part` 保留可「继续」）。
- 扩展代码改动后需用户在 `chrome://extensions` 重载 Xiaoer 扩展才生效。

## 铁律（用户明确要求）

1. **严禁**用 `--cookies-from-browser chrome` 碰 YouTube（Google 账号风控风险）。
2. 触发反爬（`Sign in to confirm you're not a bot`）**立即停止重试**：换 Clash 节点或等风控消退，不要连续点下载、不要反复测试同一 URL。
3. 不新增后台常驻服务/launchd 任务；能用现有服务就复用。
4. 敏感文件勿外传：`~/videolingo/config.yaml`（DeepSeek key）、`~/social-auto-upload/cookies/douyin_main.json`（抖音登录态，本项目已不再使用）。
5. 外网访问必须经 Clash 代理 127.0.0.1:7897（daemon 对 YouTube 等平台自动加 `--proxy`，勿改）。

## 常用约定

- 下载文件名 `平台_标题_日期.ext`；`.part`/`.f\d+\.\w+` 是未完成临时文件；暂停/继续靠 `.dashboard_paused.json` 里的 `url+filename` 断点续传。
- 测试下载流程：用本地 HTTP 服务器 + 小文件（如 `python3 -m http.server` 或项目外临时脚本），**不要**反复请求真实 YouTube 触发风控；测试后清理 `生肉视频/` 测试文件与 daemon 历史。
- 监控页状态：`downloading`（.part 有进展）/ `stalled`（.part 超 5 分钟无变化，仅删除按钮）/ `paused`（暂停中）/ `done` / `failed`。
- daemon 对同一 URL 有防重（重复请求返回 `duplicate:true`，不重复下载）。
- 本目录 git 仓库：改动后保持提交历史整洁（不要提交敏感文件与临时产物）。

## 详细文档

- `docs/交接文档.md`：完整交接文档（架构、目录树、数据格式、排障、验收、重建）。
