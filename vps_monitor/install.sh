#!/bin/sh
set -eu

if [ "$(id -u)" -ne 0 ]; then
  echo "请使用 sudo 运行：sudo ./install.sh /path/to/config.env" >&2
  exit 1
fi

CONFIG="${1:-}"
if [ -z "$CONFIG" ] || [ ! -f "$CONFIG" ]; then
  echo "用法：sudo ./install.sh /path/to/config.env" >&2
  exit 2
fi

HERE=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
install -d -m 0755 /opt/youtube-channel-monitor
install -m 0755 "$HERE/youtube_email_monitor.py" /opt/youtube-channel-monitor/
install -m 0600 "$CONFIG" /etc/youtube-channel-monitor.env
install -m 0644 "$HERE/youtube-channel-monitor.service" /etc/systemd/system/
install -m 0644 "$HERE/youtube-channel-monitor.timer" /etc/systemd/system/
systemctl daemon-reload
systemctl enable --now youtube-channel-monitor.timer

echo "安装完成。"
echo "测试邮件：sudo sh -c 'set -a; . /etc/youtube-channel-monitor.env; set +a; python3 /opt/youtube-channel-monitor/youtube_email_monitor.py --test-email'"
echo "首次检查：sudo systemctl start youtube-channel-monitor.service"
echo "查看日志：journalctl -u youtube-channel-monitor.service -n 50 --no-pager"
echo "查看定时器：systemctl list-timers youtube-channel-monitor.timer"
