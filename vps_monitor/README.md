# VPS YouTube 新视频邮件监控

适用于小容量 Linux VPS。运行时只启动一次 Python 进程，检查完成即退出，不需要 Docker、数据库或常驻浏览器。

## 工作方式

1. 每天北京时间 08:00 运行。
2. 优先调用官方 YouTube Data API；没有 API Key 时使用频道 RSS。
3. 第一次运行只记录当前视频作为基线，不发送历史视频提醒。
4. 以后发现新视频时发送邮件，并把视频 ID 写入本地状态文件防止重复提醒。

## 准备信息

- 博主的 YouTube Channel ID（`UC...`，不是 `@handle`）。
- 可选的 YouTube Data API Key。推荐配置，稳定性高于 RSS。
- 发信邮箱的 SMTP 主机、端口、账号和“SMTP 授权码”。不要填写网页登录密码。
- 收件邮箱。

## 安装

支持使用 systemd 的 Debian、Ubuntu、AlmaLinux 等发行版：

```bash
cp config.env.example config.env
nano config.env
sudo ./install.sh ./config.env
```

首次运行并建立基线：

```bash
sudo systemctl start youtube-channel-monitor.service
journalctl -u youtube-channel-monitor.service -n 50 --no-pager
```

单独测试 SMTP 邮件，可先在项目目录临时加载配置：

```bash
set -a
. ./config.env
set +a
python3 youtube_email_monitor.py --test-email
```

安装后测试：

```bash
sudo sh -c 'set -a; . /etc/youtube-channel-monitor.env; set +a; python3 /opt/youtube-channel-monitor/youtube_email_monitor.py --test-email'
```

## 常用管理

```bash
systemctl list-timers youtube-channel-monitor.timer
sudo systemctl start youtube-channel-monitor.service
journalctl -u youtube-channel-monitor.service -f
sudo systemctl disable --now youtube-channel-monitor.timer
```

状态保存在 `/var/lib/youtube-channel-monitor/state.json`，邮箱密码保存在权限为 `0600` 的 `/etc/youtube-channel-monitor.env`。
