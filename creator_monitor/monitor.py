#!/usr/bin/env python3
"""检测博主新作品，并通知或交给现有 Xiaoer daemon 下载。"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
import urllib.request
from datetime import datetime
from pathlib import Path

try:
    import yaml
except ImportError:  # pragma: no cover - 运行环境问题
    yaml = None


REPO_ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = Path(os.environ.get("YOUTUBE_REPOST_DATA_DIR", REPO_ROOT / "data")).expanduser()
DEFAULT_CONFIG = Path(__file__).with_name("config.yaml")
STATE_FILE = DATA_DIR / "creator-monitor-state.json"
DAEMON_URL = "http://127.0.0.1:7788/download"


def log(message: str) -> None:
    print(f"[{datetime.now():%Y-%m-%d %H:%M:%S}] {message}", flush=True)


def load_config(path: Path) -> dict:
    if yaml is None:
        raise RuntimeError("缺少 PyYAML，请在 VideoLingo 虚拟环境中运行")
    if not path.is_file():
        raise FileNotFoundError(f"配置文件不存在：{path}")
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(data.get("creators", []), list):
        raise ValueError("creators 必须是列表")
    return data


def load_state() -> dict:
    try:
        return json.loads(STATE_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"creators": {}}


def save_state(state: dict) -> None:
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    tmp = STATE_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(STATE_FILE)


def item_url(platform: str, item: dict) -> str:
    url = str(item.get("webpage_url") or item.get("url") or "").strip()
    item_id = str(item.get("id") or "").strip()
    if platform == "youtube" and not url.startswith(("http://", "https://")):
        return f"https://www.youtube.com/watch?v={item_id or url}"
    return url


def fetch_latest(creator: dict, defaults: dict) -> list[dict]:
    platform = str(creator.get("platform", "youtube")).lower()
    if platform != "youtube":
        raise ValueError(f"暂不支持的平台：{platform}")
    url = str(creator.get("url") or "").strip()
    if not url.startswith(("http://", "https://")):
        raise ValueError("博主 URL 无效")

    limit = max(1, int(defaults.get("scan_latest_items", 12)))
    cmd = [
        os.environ.get("YT_DLP", "/opt/homebrew/bin/yt-dlp"),
        "--flat-playlist",
        "--playlist-end",
        str(limit),
        "--dump-single-json",
        "--no-warnings",
    ]
    proxy = str(defaults.get("proxy") or os.environ.get("HTTPS_PROXY") or "").strip()
    if proxy:
        cmd += ["--proxy", proxy]
    cmd.append(url)
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
    if proc.returncode != 0:
        raise RuntimeError((proc.stderr or proc.stdout or "yt-dlp 检测失败")[-500:])
    payload = json.loads(proc.stdout)
    entries = payload.get("entries") or []
    return [entry for entry in entries if isinstance(entry, dict) and entry.get("id")]


def notify(creator_name: str, item: dict) -> None:
    title = str(item.get("title") or item.get("id") or "新视频")[:100]
    message = f"{creator_name} 发布了：{title}".replace('"', "'")
    try:
        subprocess.run(
            ["osascript", "-e", f'display notification "{message}" with title "博主新视频"'],
            check=False,
            timeout=8,
        )
    except (OSError, subprocess.TimeoutExpired):
        pass
    log(f"🔔 {message}")


def queue_download(url: str) -> None:
    body = json.dumps({"url": url}).encode("utf-8")
    request = urllib.request.Request(
        DAEMON_URL,
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=15) as response:
        if response.status != 202:
            raise RuntimeError(f"下载 daemon 返回 HTTP {response.status}")


def check_creator(creator: dict, defaults: dict, state: dict) -> int:
    creator_id = str(creator.get("id") or "").strip()
    if not creator_id:
        raise ValueError("博主配置缺少 id")
    entries = fetch_latest(creator, defaults)
    current_ids = [str(item["id"]) for item in entries]
    creator_state = state.setdefault("creators", {}).get(creator_id)

    if not creator_state:
        state["creators"][creator_id] = {
            "seen_ids": current_ids[:200],
            "last_checked_at": datetime.now().isoformat(timespec="seconds"),
        }
        log(f"📌 {creator_id} 首次建立基线，共记录 {len(current_ids)} 个作品，不下载历史视频")
        return 0

    seen = set(creator_state.get("seen_ids", []))
    new_items = [item for item in reversed(entries) if str(item["id"]) not in seen]
    max_new = max(1, int(creator.get("max_new_items_per_check", defaults.get("max_new_items_per_check", 3))))
    new_items = new_items[-max_new:]
    action = str(creator.get("action", defaults.get("action", "notify"))).lower()
    name = str(creator.get("name") or creator_id)

    for item in new_items:
        url = item_url(str(creator.get("platform", "youtube")).lower(), item)
        notify(name, item)
        if action == "download":
            if not url:
                log(f"⚠️ {item.get('id')} 缺少有效 URL，跳过下载")
                continue
            queue_download(url)
            log(f"⬇️ 已加入下载队列：{url}")

    creator_state["seen_ids"] = list(dict.fromkeys(current_ids + list(seen)))[:200]
    creator_state["last_checked_at"] = datetime.now().isoformat(timespec="seconds")
    return len(new_items)


def run_once(config: dict) -> int:
    defaults = config.get("defaults") or {}
    state = load_state()
    found = 0
    for creator in config.get("creators", []):
        if not creator.get("enabled", False):
            continue
        try:
            found += check_creator(creator, defaults, state)
        except Exception as exc:
            log(f"❌ {creator.get('id', 'unknown')} 检测失败：{exc}")
    save_state(state)
    return found


def main() -> int:
    parser = argparse.ArgumentParser(description="检测博主新视频")
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--once", action="store_true", help="只检查一次后退出")
    args = parser.parse_args()

    try:
        config = load_config(args.config.expanduser())
    except Exception as exc:
        log(f"❌ {exc}")
        return 2

    defaults = config.get("defaults") or {}
    if args.once:
        run_once(config)
        return 0

    interval = max(10, int(defaults.get("check_interval_minutes", 30))) * 60
    while True:
        run_once(config)
        time.sleep(interval)


if __name__ == "__main__":
    sys.exit(main())
