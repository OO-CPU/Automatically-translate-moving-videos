# 项目状态记录

最后更新：2026-08-29

## 项目定位

本项目用于维护 YouTube 视频搬运辅助流程：检测博主新视频、下载、自动导入 VideoLingo、识别与翻译字幕、裁剪片尾广告、生成标题和发布文案。发布前仍由人工确认。

GitHub 仓库：`OO-CPU/Automatically-translate-moving-videos`，默认分支 `main`。

本目录是维护源；macOS 后台服务从 `~/youtube-repost-runtime` 运行，业务数据通过 `data/` 指向本机原数据目录，不纳入 Git。

## 当前可用能力

- Xiaoer 下载插件及本地下载 daemon。
- `yt-dlp` 底层下载器已同步更新。
- 下载完成后自动导入翻译流程，并能恢复未完成的导入任务。
- VideoLingo 字幕识别、翻译、字幕生成、片尾广告裁剪、标题和文案生成。
- 千问兼容层已修复数组形式的 JSON 返回处理。
- 本机博主新视频检测模块位于 `creator_monitor/`，尚未配置实际目标。
- 小容量 VPS 邮件提醒模块位于 `vps_monitor/`，代码已准备但尚未部署到服务器。

## VPS 监控决策

目标是每天早晨检查指定 YouTube 博主是否发布新视频；发现新视频时仅发邮件提醒，不在 VPS 下载、翻译或保存视频。

采用 Python 标准库脚本加 systemd oneshot/timer：

- 不使用 Docker、浏览器或数据库。
- 每次检查启动一次，完成即退出。
- 优先使用 YouTube Data API；没有 API Key 时回退到频道 RSS。
- 首次运行只建立基线，不补发历史视频。
- 本地状态文件负责去重。
- 默认北京时间 08:45 左右运行，避开服务器现有每日备份窗口。

详细步骤见 `docs/VPS监控部署方案.md`。

## VPS 部署状态

当前状态：**未部署**。

已从另一个 VPS 运维项目核对到服务器具备 systemd、Python、UFW、Fail2ban、SSH 密钥登录及每日备份，满足轻量部署条件。但记录显示 SSH 主机密钥曾发生变化，正式连接前必须先通过服务商网页控制台核对当前指纹。

服务器地址、SSH 别名、主机指纹和邮箱配置属于私密运维信息，只记录在本机已忽略的 `.private/` 目录，不提交到公开仓库。

## 部署前仍需确定

- 要监控的 YouTube 频道 URL 或 Channel ID。
- 发信邮箱服务商、发件地址、SMTP 授权码和收件地址。
- 是否提供 YouTube Data API Key；不提供也能先使用 RSS。
- 用户明确授权连接 VPS 并执行安装。

## 维护规则

- 修改本机服务后使用 `./scripts/deploy-local.sh --restart` 部署并健康检查。
- 不提交 API Key、SMTP 授权码、Cookie、登录态、视频文件或运行状态。
- VPS 部署前先备份现有配置；部署后依次验证测试邮件、首次基线、timer 和日志。
- 监控服务只负责提醒；自动下载和自动发布不得在没有明确授权时开启。
