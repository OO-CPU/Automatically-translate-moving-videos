# 博主新视频检测

这一目录用于扩展“自动发现博主新作品 → 去重 → 进入下载队列”的能力。

计划采用平台稳定 ID，而不是容易变化的显示名称。每个目标保存：平台、频道/用户 URL、是否启用、检查周期、发现后的动作。状态文件应放在 `data/creator-monitor-state.json`，不能提交到 Git。

默认安全策略：

1. 首次运行只建立基线，不下载历史全部作品。
2. 后续只处理基线之后出现的新作品。
3. 发现新作品后先写入队列并通知；是否自动下载由每个目标的 `action` 控制。
4. YouTube 请求必须使用项目代理，并设置合理检查间隔和退避，遇到风控立即停止。
5. 下载仍通过现有 Xiaoer daemon，避免出现两套下载和防重逻辑。

把 `config.example.yaml` 复制为不入库的 `config.yaml`，填写频道后先执行一次建立基线：

```bash
videolingo/.venv/bin/python creator_monitor/monitor.py --once
```

`action: notify` 只发送 macOS 通知；`action: download` 会把新增作品 URL 交给 Xiaoer daemon。当前尚未配置目标博主，因此不会启动监控任务。
