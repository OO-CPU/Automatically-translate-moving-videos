# AGENTS.md — YouTube 视频自动搬运项目

接手任务前阅读 `README.md` 与 `pipeline/docs/交接文档.md`。

## 安全铁律

1. 禁止对 YouTube 使用 `--cookies-from-browser chrome`，避免 Google 账号风控。
2. 出现 `Sign in to confirm you're not a bot` 后立即停止重试；切换 Clash 节点或等待风控消退。
3. 外网下载沿用 Clash 代理 `127.0.0.1:7897`。
4. 不提交 `videolingo/config.yaml`、平台 Cookie、登录态、视频文件或运行状态。
5. 不新增独立常驻服务；博主检测应由现有服务托管，除非用户明确要求改变部署方式。
6. 修改 Python 服务后要重启并执行健康检查；重启下载 daemon 前确认没有活动下载。

## 仓库结构

- `pipeline/`：流程编排和下载监控。
- `videolingo/`：字幕与翻译核心。
- `xiaoer-videolab/`：浏览器扩展与下载 daemon。
- `creator_monitor/`：博主新作品检测。
- `legacy/`：只读历史备份，不直接恢复运行。

运行数据目录由 `YOUTUBE_REPOST_DATA_DIR` 指定，默认是仓库下的 `data/`；VideoLingo 根目录由 `VIDEOLINGO_HOME` 指定。
