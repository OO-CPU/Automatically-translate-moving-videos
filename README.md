# YouTube 视频自动搬运

本仓库是旧项目“视频自动搬运发布”的统一维护入口，包含：

- `pipeline/`：下载监控、视频自动导入与流程编排。
- `videolingo/`：语音识别、自动翻译、字幕烧录、片尾广告裁剪、标题和发布文案生成。
- `xiaoer-videolab/`：Chrome 下载扩展和本地下载 daemon。
- `creator_monitor/`：本机使用的博主新视频检测模块，配置目标前不会启动轮询。
- `vps_monitor/`：小容量 Linux VPS 使用的每日 YouTube 新视频邮件提醒服务。
- `legacy/`：已移除的抖音自动发布模块备份，仅供参考，不会运行。
- `data/`：视频与运行状态。本机迁移阶段通过符号链接复用旧数据，不纳入 Git。

## 当前链路

```text
博主新视频检测（待配置）
    ↓
Xiaoer / yt-dlp 下载 → data/生肉视频
    ↓
auto_import_watch.py
    ↓
VideoLingo 识别 → 翻译 → 字幕 → 裁剪片尾广告 → 标题
    ↓
data/熟肉视频 + 发布文案
    ↓
人工确认后发布
```

当前没有启用自动上传平台功能；`legacy/` 中是旧实现备份。恢复自动发布前必须重新评估平台风控、登录态和人工确认机制。

## 本机服务

- Xiaoer daemon：`http://127.0.0.1:7788`
- 下载监控页：`http://127.0.0.1:7799`
- VideoLingo：`http://127.0.0.1:8501`
- YouTube 底层下载器：Homebrew `yt-dlp`（本机当前版本 `2026.08.19`）

由于 macOS 不允许后台 `launchd` 直接读取 `Documents/ChatGPT`，本目录是维护源，服务从 `~/youtube-repost-runtime` 运行。修改后部署并重启：

```bash
./scripts/deploy-local.sh --restart
```

脚本会先检查是否有活动下载；检测到下载中任务时会拒绝重启。

详细交接信息见 [`pipeline/docs/交接文档.md`](pipeline/docs/交接文档.md)。

## 敏感数据

以下内容只保存在本机，禁止提交：

- `videolingo/config.yaml`：模型 API 密钥。
- `data/`：下载视频、熟肉视频及运行状态。
- 平台 Cookie、登录态和浏览器配置。

## 博主新视频监控

监控模块的目标是保存频道或博主的稳定 ID，定时读取其最新作品列表，通过状态文件去重，再把新视频 URL 交给现有下载队列。配置草案见 [`creator_monitor/config.example.yaml`](creator_monitor/config.example.yaml)。

在目标博主、平台、检查频率和“发现后自动下载还是先通知确认”确定前，该模块不会自动运行。
