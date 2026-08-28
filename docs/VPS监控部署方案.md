# VPS YouTube 新视频邮件监控部署方案

最后更新：2026-08-29

## 结论

这台小容量 VPS 适合运行 `vps_monitor/`：脚本只在定时检查时短暂启动，不需要 Docker，也不会在服务器下载视频。建议由 systemd 每天北京时间 08:45 左右执行一次。

## 已知服务器条件

从独立的 VPS 运维记录可确认：

- Linux 使用 systemd，已有多个 oneshot/timer 任务。
- 已启用 SSH 密钥登录、UFW 和 Fail2ban。
- 公网只保留必要端口；本服务仅发起出站 HTTPS 和 SMTP 连接，不需要新增入站端口。
- 已有本机和加密异地备份。
- 每日服务器备份约在 00:00 UTC 后运行，另有 06:30 UTC 的异地备份，因此监控定时器设为 00:45 UTC，并附加最多 5 分钟随机延迟。

敏感的服务器地址、SSH 别名和指纹不写入公开仓库。

## 安全部署门槛

运维记录中出现过 SSH Host Key 变化。连接前必须在 VPS 服务商网页 Console/VNC 中读取当前 SSH 公钥指纹，并与 Mac 实际收到的指纹逐项核对。只有完全一致时才能更新 `known_hosts` 并继续；不一致时停止部署并联系服务商。

## 部署结构

```text
/opt/youtube-channel-monitor/
└── youtube_email_monitor.py

/etc/youtube-channel-monitor.env       # 0600，API/SMTP 配置
/var/lib/youtube-channel-monitor/
└── state.json                          # 已见视频 ID

/etc/systemd/system/
├── youtube-channel-monitor.service
└── youtube-channel-monitor.timer
```

服务使用 `DynamicUser=yes`、`NoNewPrivileges=yes` 和只读系统保护；状态目录由 systemd 创建，不以 root 常驻。

## 推荐部署流程

### 1. 部署前只读检查

SSH 指纹核对完成后，先检查系统，不写入配置：

```bash
ssh <私密SSH别名> 'uname -a; cat /etc/os-release; python3 --version; df -h /; free -h; systemctl --version | head -1; systemctl list-timers --all --no-pager'
```

确认磁盘没有接近满载、Python 3 和 systemd 可用，并检查新任务不与现有高负载任务重叠。

### 2. 在 Mac 准备私密配置

```bash
cd /Users/limingyu/Documents/ChatGPT/youtube视频搬运/vps_monitor
cp config.env.example config.env
chmod 600 config.env
```

编辑 `config.env`，填写频道 ID、SMTP 信息和可选的 YouTube API Key。`config.env` 已被 Git 忽略。SMTP 密码必须使用邮箱提供的 SMTP 授权码，不使用网页登录密码。

### 3. 上传代码

推荐只上传 `vps_monitor/`，不把视频处理主项目放到小 VPS：

```bash
scp -r /Users/limingyu/Documents/ChatGPT/youtube视频搬运/vps_monitor <私密SSH别名>:/root/youtube-channel-monitor-deploy
```

### 4. 先测试邮件

在安装 timer 前先验证 SMTP：

```bash
ssh <私密SSH别名> "cd /root/youtube-channel-monitor-deploy && set -a && . ./config.env && set +a && python3 youtube_email_monitor.py --test-email"
```

收到测试邮件后再继续。测试失败时只排查 SMTP 主机、端口、安全模式、账号和授权码，不启用定时任务。

### 5. 安装并建立首次基线

```bash
ssh <私密SSH别名> 'cd /root/youtube-channel-monitor-deploy && ./install.sh ./config.env'
ssh <私密SSH别名> 'systemctl start youtube-channel-monitor.service'
```

第一次真实检查只保存当前视频，不发送历史提醒。

### 6. 验证

```bash
ssh <私密SSH别名> 'systemctl is-enabled youtube-channel-monitor.timer; systemctl list-timers youtube-channel-monitor.timer --no-pager; journalctl -u youtube-channel-monitor.service -n 80 --no-pager; ls -l /var/lib/youtube-channel-monitor/state.json'
```

验收条件：

- 测试邮件已收到。
- service 返回成功。
- `state.json` 已生成。
- timer 为 enabled/active，并显示下一次执行时间。
- UFW 无新增入站规则。

## 更新方式

在 Mac 修改并验证后，只覆盖脚本和 unit 文件，再执行 `systemctl daemon-reload`。配置文件和状态文件必须保留：

```bash
scp vps_monitor/youtube_email_monitor.py <私密SSH别名>:/tmp/youtube_email_monitor.py
ssh <私密SSH别名> 'install -m 0755 /tmp/youtube_email_monitor.py /opt/youtube-channel-monitor/youtube_email_monitor.py && systemctl start youtube-channel-monitor.service'
```

## 停用和回滚

```bash
ssh <私密SSH别名> 'systemctl disable --now youtube-channel-monitor.timer; rm -f /etc/systemd/system/youtube-channel-monitor.service /etc/systemd/system/youtube-channel-monitor.timer; systemctl daemon-reload'
```

停用时默认保留 `/etc/youtube-channel-monitor.env` 和 `/var/lib/youtube-channel-monitor/state.json`，便于恢复。若确认永久删除，应先安全备份，再单独移除这两个路径。

## 不在 VPS 上做的事情

- 不下载或转码视频。
- 不运行 VideoLingo、Whisper、浏览器或 Chrome 扩展。
- 不自动发布到任何平台。
- 不开放新的公网端口。
- 不把 SMTP 授权码或 API Key 提交到 GitHub。
