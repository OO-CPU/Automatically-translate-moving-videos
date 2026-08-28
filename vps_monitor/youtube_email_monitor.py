#!/usr/bin/env python3
"""小型 VPS 用：检测 YouTube 频道新视频并通过 SMTP 发邮件。"""

from __future__ import annotations

import argparse
import json
import os
import smtplib
import ssl
import sys
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from email.message import EmailMessage
from pathlib import Path


USER_AGENT = "youtube-channel-email-monitor/1.0"
DEFAULT_STATE = "/var/lib/youtube-channel-monitor/state.json"


def env(name: str, default: str = "", required: bool = False) -> str:
    value = os.environ.get(name, default).strip()
    if required and not value:
        raise ValueError(f"缺少环境变量 {name}")
    return value


def log(message: str) -> None:
    print(f"[{datetime.now(timezone.utc).isoformat(timespec='seconds')}] {message}", flush=True)


def get_json(url: str) -> dict:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=30) as response:
        return json.load(response)


def api_url(path: str, **params: str) -> str:
    return "https://www.googleapis.com/youtube/v3/" + path + "?" + urllib.parse.urlencode(params)


def fetch_via_api(channel_id: str, api_key: str) -> tuple[str, list[dict]]:
    channel = get_json(api_url("channels", part="snippet,contentDetails", id=channel_id, key=api_key))
    items = channel.get("items") or []
    if not items:
        raise RuntimeError(f"YouTube API 找不到频道：{channel_id}")
    info = items[0]
    channel_name = info.get("snippet", {}).get("title") or channel_id
    uploads = info.get("contentDetails", {}).get("relatedPlaylists", {}).get("uploads")
    if not uploads:
        raise RuntimeError("频道响应中没有 uploads 播放列表")

    playlist = get_json(
        api_url(
            "playlistItems",
            part="snippet,contentDetails",
            playlistId=uploads,
            maxResults="10",
            key=api_key,
        )
    )
    videos = []
    for item in playlist.get("items") or []:
        snippet = item.get("snippet") or {}
        video_id = (item.get("contentDetails") or {}).get("videoId") or (
            snippet.get("resourceId") or {}
        ).get("videoId")
        if video_id:
            videos.append(
                {
                    "id": video_id,
                    "title": snippet.get("title") or video_id,
                    "published": snippet.get("publishedAt") or "",
                    "url": f"https://www.youtube.com/watch?v={video_id}",
                }
            )
    return channel_name, videos


def fetch_via_rss(channel_id: str) -> tuple[str, list[dict]]:
    url = "https://www.youtube.com/feeds/videos.xml?" + urllib.parse.urlencode({"channel_id": channel_id})
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=30) as response:
        root = ET.parse(response).getroot()
    atom = "{http://www.w3.org/2005/Atom}"
    yt = "{http://www.youtube.com/xml/schemas/2015}"
    channel_name = root.findtext(f"{atom}title") or channel_id
    videos = []
    for entry in root.findall(f"{atom}entry"):
        video_id = entry.findtext(f"{yt}videoId") or ""
        if not video_id:
            continue
        videos.append(
            {
                "id": video_id,
                "title": entry.findtext(f"{atom}title") or video_id,
                "published": entry.findtext(f"{atom}published") or "",
                "url": f"https://www.youtube.com/watch?v={video_id}",
            }
        )
    return channel_name, videos


def load_state(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def save_state(path: Path, state: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)


def build_email(channel_name: str, videos: list[dict], test: bool = False) -> EmailMessage:
    recipient = env("EMAIL_TO", required=True)
    sender = env("EMAIL_FROM", env("SMTP_USERNAME"), required=True)
    message = EmailMessage()
    message["From"] = sender
    message["To"] = recipient
    if test:
        message["Subject"] = "[测试成功] YouTube 新视频监控"
        message.set_content("VPS 的 YouTube 新视频邮件提醒配置正常。")
        return message

    message["Subject"] = f"[YouTube新视频] {channel_name} 发布了新内容"
    lines = [f"检测到 {channel_name} 发布了 {len(videos)} 个新视频：", ""]
    for video in videos:
        lines += [video["title"], video["url"], f"发布时间：{video.get('published') or '未知'}", ""]
    lines.append("请打开链接确认后再进行搬运。")
    message.set_content("\n".join(lines))
    return message


def send_email(message: EmailMessage) -> None:
    host = env("SMTP_HOST", required=True)
    port = int(env("SMTP_PORT", "465"))
    username = env("SMTP_USERNAME", required=True)
    password = env("SMTP_PASSWORD", required=True)
    security = env("SMTP_SECURITY", "ssl").lower()
    context = ssl.create_default_context()

    if security == "ssl":
        with smtplib.SMTP_SSL(host, port, timeout=30, context=context) as smtp:
            smtp.login(username, password)
            smtp.send_message(message)
    elif security == "starttls":
        with smtplib.SMTP(host, port, timeout=30) as smtp:
            smtp.ehlo()
            smtp.starttls(context=context)
            smtp.ehlo()
            smtp.login(username, password)
            smtp.send_message(message)
    else:
        raise ValueError("SMTP_SECURITY 只支持 ssl 或 starttls")


def check_once() -> int:
    channel_id = env("YOUTUBE_CHANNEL_ID", required=True)
    api_key = env("YOUTUBE_API_KEY")
    state_path = Path(env("STATE_FILE", DEFAULT_STATE))
    state = load_state(state_path)

    if api_key:
        channel_name, videos = fetch_via_api(channel_id, api_key)
        backend = "YouTube Data API"
    else:
        channel_name, videos = fetch_via_rss(channel_id)
        backend = "YouTube RSS"
    if not videos:
        raise RuntimeError("频道没有返回任何公开视频")

    current_ids = [video["id"] for video in videos]
    previous_ids = set(state.get("seen_video_ids") or [])
    if not state.get("initialized"):
        save_state(
            state_path,
            {
                "initialized": True,
                "channel_id": channel_id,
                "channel_name": channel_name,
                "seen_video_ids": current_ids[:100],
                "last_checked_at": datetime.now(timezone.utc).isoformat(),
                "backend": backend,
            },
        )
        log(f"首次运行：已为 {channel_name} 建立基线，不提醒历史视频")
        return 0

    new_videos = [video for video in reversed(videos) if video["id"] not in previous_ids]
    if new_videos:
        send_email(build_email(channel_name, new_videos))
        log(f"已发送邮件：{channel_name} 新增 {len(new_videos)} 个视频")
    else:
        log(f"{channel_name} 没有新视频")

    save_state(
        state_path,
        {
            "initialized": True,
            "channel_id": channel_id,
            "channel_name": channel_name,
            "seen_video_ids": list(dict.fromkeys(current_ids + list(previous_ids)))[:100],
            "last_checked_at": datetime.now(timezone.utc).isoformat(),
            "backend": backend,
        },
    )
    return len(new_videos)


def main() -> int:
    parser = argparse.ArgumentParser(description="检测 YouTube 频道新视频并发送邮件")
    parser.add_argument("--test-email", action="store_true", help="只测试 SMTP 邮件，不访问 YouTube")
    args = parser.parse_args()
    try:
        if args.test_email:
            send_email(build_email("测试频道", [], test=True))
            log("测试邮件发送成功")
        else:
            check_once()
        return 0
    except Exception as exc:
        log(f"检查失败：{exc}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
