#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
自动搬运：监控下载目录，把新下载的视频自动导入 VideoLingo 并触发字幕制作。

说明：项目数据目录由 YOUTUBE_REPOST_DATA_DIR 指定，默认是仓库内的 data/，
      下载 daemon 落盘到其中的 生肉视频/，新文件自动进入 VideoLingo 字幕流程。
      本脚本由仓库内 videolingo/start_detached.sh 随页面服务直接运行。
      修改后重启 com.videolingo.streamlit 生效。

部署：随 VideoLingo 页面服务启动，无独立 launchd 任务。
      修改后重启 com.videolingo.streamlit。

用法：
    python3 auto_import_watch.py                        # 默认监控 ~/Downloads，导入后移动文件
    python3 auto_import_watch.py --watch-dir ~/Downloads --keep   # 导入后保留原文件
    python3 auto_import_watch.py --no-open              # 不自动打开浏览器页面
    python3 auto_import_watch.py --import-existing      # 也处理监控目录里已存在的视频（默认只处理新出现的）
    python3 auto_import_watch.py --reset-state          # 清空"已见过"记录后启动

流程：发现新视频(等下载稳定) → 移入 videolingo/output/ → 写 input_manifest.json
      → 自动打开 http://localhost:8501/?auto_process=1 → 页面自动开始 识别→翻译→烧录
注意：启动时监控目录里已存在的旧视频会被标记为"已见"并跳过（避免误导入历史文件）；
      用 --import-existing 才会从旧文件开始处理。
提示：output 里有未清理的旧视频时脚本会等待，避免覆盖未发布成品；
      在页面点「Delete and Reselect」或「Archive to 'history'」清理后可继续导入下一个。
"""
import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = Path(os.environ.get("YOUTUBE_REPOST_DATA_DIR", REPO_ROOT / "data")).expanduser()
VIDEOLINGO = Path(os.environ.get("VIDEOLINGO_HOME", REPO_ROOT / "videolingo")).expanduser()
OUTPUT_DIR = VIDEOLINGO / "output"
MANIFEST = OUTPUT_DIR / "input_manifest.json"
STATE_FILE = DATA_DIR / ".auto_import_done.json"
PAGE_URL = "http://localhost:8501/?auto_process=1"

VIDEO_EXTS = {".mp4", ".mov", ".avi", ".mkv", ".flv", ".wmv", ".webm", ".m4v", ".mpg", ".mpeg", ".ts"}
AUDIO_EXTS = {".wav", ".mp3", ".flac", ".m4a", ".aac", ".ogg"}
ALL_EXTS = VIDEO_EXTS | AUDIO_EXTS
_TEMP_RE = re.compile(r"\.f\d+\.\w+$", re.IGNORECASE)

POLL_SECS = 3
STABLE_SECS = 6


def is_temp_file(name):
    """忽略未完成的下载/yt-dlp 多流中间文件（xxx.f399.mp4、xxx.part 等）。"""
    n = name.lower()
    if n.endswith((".part", ".ytdl", ".crdownload", ".download", ".tmp")):
        return True
    return bool(_TEMP_RE.search(n))


def log(msg):
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


def load_state():
    try:
        if STATE_FILE.exists():
            return json.loads(STATE_FILE.read_text(encoding="utf-8"))
    except Exception:
        pass
    return {}


def save_state(state):
    try:
        STATE_FILE.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception:
        pass


def output_busy():
    """output 里已有媒体/清单时视为忙，等待用户清理，避免覆盖未发布成品。"""
    if MANIFEST.exists():
        return True
    try:
        for p in OUTPUT_DIR.iterdir():
            if p.is_file() and p.suffix.lower() in ALL_EXTS:
                return True
    except FileNotFoundError:
        return False
    return False


def file_stable(path, wait=STABLE_SECS):
    """文件大小连续两次不变且 mtime 距今超过 2 秒，视为下载完成。"""
    try:
        s1 = os.stat(path)
        time.sleep(2)
        s2 = os.stat(path)
        now = time.time()
        return s1.st_size == s2.st_size and s2.st_size > 0 and (now - s2.st_mtime) > 2
    except FileNotFoundError:
        return False


def clear_output():
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    for p in OUTPUT_DIR.iterdir():
        try:
            if p.is_dir():
                shutil.rmtree(p)
            else:
                p.unlink()
        except OSError as exc:
            log(f"⚠️ 清理 output 失败：{exc}")


def import_video(src: Path, keep: bool):
    clear_output()
    dst = OUTPUT_DIR / src.name
    if keep:
        shutil.copy2(src, dst)
        log(f"📋 已复制 {src.name} -> output/")
    else:
        shutil.move(str(src), str(dst))
        log(f"📦 已移入 {src.name} -> output/")
    media_type = "video" if dst.suffix.lower() in VIDEO_EXTS else "audio"
    MANIFEST.write_text(
        json.dumps({"path": str(dst), "type": media_type}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    log(f"✅ 已写入 input_manifest.json（{media_type}）")


def trigger_page(open_browser: bool):
    if open_browser:
        subprocess.run(["open", PAGE_URL], check=False)
        log("🌐 已打开浏览器页面，即将自动开始字幕处理")
    else:
        subprocess.run(
            ["curl", "-s", "-o", "/dev/null", "--max-time", "10", PAGE_URL], check=False
        )
        log("🔔 已触发页面（--no-open，请在浏览器打开页面）")


def main():
    ap = argparse.ArgumentParser(description="监控下载目录并自动导入 VideoLingo")
    ap.add_argument("--watch-dir", default=str(DATA_DIR / "生肉视频"), help="要监控的目录（默认 data/生肉视频）")
    ap.add_argument("--keep", action="store_true", help="导入后保留原文件（默认移动）")
    ap.add_argument("--no-open", action="store_true", help="不自动打开浏览器")
    ap.add_argument("--import-existing", action="store_true", help="同时导入启动前已存在的视频")
    ap.add_argument("--reset-state", action="store_true", help="清空已见记录后启动")
    args = ap.parse_args()

    watch_dir = Path(args.watch_dir).expanduser()
    if not watch_dir.is_dir():
        log(f"❌ 监控目录不存在：{watch_dir}")
        sys.exit(1)

    log(f"👀 开始监控：{watch_dir}")
    log(f"   自动导入到：{OUTPUT_DIR}")
    log("   插件下载的视频（mp4/mov/webm 等）落盘后约 10 秒内自动开始字幕制作。")
    log("   按 Ctrl+C 停止。")

    if args.reset_state:
        state = {}
        log("♻️ 已清空导入记录")
    else:
        state = load_state()

    if not args.import_existing:
        try:
            existing = [p for p in watch_dir.iterdir() if p.is_file() and p.suffix.lower() in ALL_EXTS]
        except FileNotFoundError:
            existing = []
        for p in existing:
            try:
                stt = p.stat()
                key = f"{p.name}:{stt.st_size}:{int(stt.st_mtime)}"
                state.setdefault(key, "seen")
            except OSError:
                pass
        if existing:
            log(f"ℹ️ 已标记 {len(existing)} 个旧视频为「已见」（如需处理请用 --import-existing 或 --reset-state）")
    save_state(state)

    while True:
        try:
            files = sorted(
                p for p in watch_dir.iterdir()
                if p.is_file()
                and p.suffix.lower() in ALL_EXTS
                and not is_temp_file(p.name)
            )
        except FileNotFoundError:
            log(f"⚠️ 监控目录被移除，等待恢复：{watch_dir}")
            time.sleep(POLL_SECS * 3)
            continue

        for src in files:
            stt = src.stat()
            key = f"{src.name}:{stt.st_size}:{int(stt.st_mtime)}"
            # pending 表示文件已经下载完成，只是当时 output/ 正忙。
            # 服务重启后仍应继续处理，不能把它误当成历史文件永久跳过。
            if state.get(key) not in (None, "pending"):
                continue
            if not file_stable(src):
                continue
            if output_busy():
                if state.get(key) != "pending":
                    state[key] = "pending"
                    save_state(state)
                log("⏳ output/ 里还有未清理的旧视频，等待中…（完成后在页面点「Delete and Reselect」清理）")
                break
            try:
                import_video(src, keep=args.keep)
                state[key] = time.strftime("%Y-%m-%d %H:%M:%S")
                save_state(state)
                trigger_page(open_browser=not args.no_open)
            except Exception as exc:
                log(f"❌ 导入失败：{exc}")
        time.sleep(POLL_SECS)


if __name__ == "__main__":
    main()
