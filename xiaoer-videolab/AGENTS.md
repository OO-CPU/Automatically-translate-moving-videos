# AGENTS.md — Xiaoer VideoLab（下载扩展 + daemon）

Chrome 下载工具：扩展（`extension/`，MV3）+ 本地 daemon（`daemon/server.py`，127.0.0.1:7788）。下载监控页在 `~/视频自动搬运发布/downloads_dashboard.py`，完整文档见 `~/视频自动搬运发布/docs/交接文档.md`。

## 下载目录与全自动衔接

- 下载落盘目录由 plist 的 `VIDEOLAB_DOWNLOADS` 控制，**当前为 `~/视频自动搬运发布/生肉视频/`**（不要改回 `~/Downloads`）。
- `生肉视频/` 是自动导入入口：新文件落盘后由 `~/视频自动搬运发布/auto_import_watch.py` 自动移入 VideoLingo → 生成熟肉到 `~/视频自动搬运发布/熟肉视频/` 并生成发布文案 txt。
- 若调整下载目录，必须同步修改：plist `VIDEOLAB_DOWNLOADS`、`start_detached.sh` 的 `--watch-dir`、`downloads_dashboard.py` 的扫描目录。

## 铁律

1. **严禁** `--cookies-from-browser chrome`（YouTube 反爬会封账号）；`VIDEOLAB_COOKIES_BROWSER` 必须保持空。
2. 遇到 `Sign in to confirm you're not a bot` 立即停：换 Clash 节点或等风控，勿连续重试/反复测试同一 URL。
3. 重启 daemon（`launchctl remove com.xiaoer.videolab && launchctl load ~/Library/LaunchAgents/com.xiaoer.videolab.plist`）前确认无活跃下载（会中断，`.part` 保留可「继续」）。
4. 修改扩展后必须让用户在 `chrome://extensions` 重载才生效；修改 daemon 后重启 `com.xiaoer.videolab`。

## 结构要点

- `daemon/server.py`：纯 Python 标准库。`_active_downloads`（url→Popen）、`_active_files`（文件路径→url）、`_active_meta`（url→{platform,date}）、`_cancelled`（静默取消）。API：`/download`（可选 `filename` 精确名续传）、`/download-direct`、`/cancel`（按 url 或路径）、`/history-delete`、`/history`、`/health`、`/probe`、`/open`、`/reveal`。
- 平台代理：YouTube/TikTok/X/Vimeo/Instagram/Facebook/Reddit/Dailymotion 自动 `--proxy http://127.0.0.1:7897`；抖音/小红书直连。
- 防重：同一 URL 已有活跃进程时返回 `{"queued":true,"duplicate":true}`。
- 联动：接受下载后 AppleScript 聚焦监控页（需 macOS 授权「Python 控制 Google Chrome」，连续失败 3 次本会话禁用并回退 `open`）。
- 日志：`~/Library/Logs/xiaoer-videolab.{out,err}.log`；历史：`xiaoer-videolab-history.jsonl`。
