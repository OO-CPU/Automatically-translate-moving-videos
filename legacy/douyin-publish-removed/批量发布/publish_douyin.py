#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
批量发布视频到抖音（基于 social-auto-upload 的 sau CLI）。

用法（用 social-auto-upload 的 venv 运行）：
    ~/social-auto-upload/.venv/bin/python publish_douyin.py --csv videos.csv
    ~/social-auto-upload/.venv/bin/python publish_douyin.py --dry-run --csv videos.csv
    ~/social-auto-upload/.venv/bin/python publish_douyin.py            # 自动扫描熟肉视频目录

CSV 列（首行为表头，utf-8）：
    video_path,title,desc,tags,schedule
    schedule 为空 = 立即发布；格式 "YYYY-MM-DD HH:MM" = 定时发布。
"""
import argparse
import csv
import logging
import subprocess
import sys
from pathlib import Path

SAU_BIN = Path(sys.executable).parent / "sau"
DEFAULT_SOURCE_DIR = Path.home() / "视频自动搬运发布" / "熟肉视频"
TITLE_MAX = 55  # 抖音标题上限（工具会自行校验，这里先截断兜底）

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("publish_douyin")


def build_command(account: str, row: dict, headless: bool) -> list[str]:
    cmd = [
        str(SAU_BIN), "douyin", "upload-video",
        "--account", account,
        "--file", str(row["video_path"]),
        "--title", str(row["title"])[:TITLE_MAX],
    ]
    if row.get("desc"):
        cmd += ["--desc", str(row["desc"])]
    if row.get("tags"):
        cmd += ["--tags", str(row["tags"])]
    if row.get("schedule"):
        cmd += ["--schedule", str(row["schedule"])]
    if headless:
        cmd += ["--headless"]
    return cmd


def load_csv(path: Path) -> list[dict]:
    with open(path, encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        rows = [dict(r) for r in reader if r.get("video_path", "").strip()]
    return rows


def scan_source_dir(source_dir: Path) -> list[dict]:
    rows = []
    for video in sorted(source_dir.glob("*.mp4")):
        title = video.stem
        rows.append({"video_path": str(video), "title": title, "desc": "", "tags": "", "schedule": ""})
    return rows


def main() -> int:
    parser = argparse.ArgumentParser(description="批量发布视频到抖音")
    parser.add_argument("--account", default="main", help="账号名（对应 cookies/douyin_<账号>.json）")
    parser.add_argument("--csv", help="CSV 元数据文件；不填则自动扫描 --source-dir")
    parser.add_argument("--source-dir", default=str(DEFAULT_SOURCE_DIR), help="自动扫描的视频目录")
    parser.add_argument("--dry-run", action="store_true", help="只打印将执行的命令，不真正发布")
    parser.add_argument("--headed", action="store_true", help="使用有头浏览器（默认无头）")
    args = parser.parse_args()

    rows = load_csv(Path(args.csv)) if args.csv else scan_source_dir(Path(args.source_dir))
    if not rows:
        log.error("没有找到待发布视频（检查 --csv 或 --source-dir）")
        return 1

    log.info("待发布 %d 条", len(rows))
    success, failed = 0, []
    for i, row in enumerate(rows, 1):
        if not Path(row["video_path"]).exists():
            log.error("[%d/%d] 文件不存在，跳过: %s", i, len(rows), row["video_path"])
            failed.append((row["video_path"], "文件不存在"))
            continue
        cmd = build_command(args.account, row, headless=not args.headed)
        log.info("[%d/%d] 开始处理: %s", i, len(rows), row["video_path"])
        log.info("命令: %s", " ".join(cmd))
        if args.dry_run:
            continue
        proc = subprocess.run(cmd, capture_output=True, text=True)
        output = (proc.stdout + proc.stderr).strip()
        if proc.returncode == 0:
            log.info("[%d/%d] 发布成功 ✅", i, len(rows))
            success += 1
        else:
            log.error("[%d/%d] 发布失败 ❌\n%s", i, len(rows), output[-2000:])
            failed.append((row["video_path"], output[-500:]))

    log.info("=" * 40)
    log.info("完成：成功 %d 条，失败 %d 条", success, len(failed))
    for path, reason in failed:
        log.error("失败: %s -> %s", path, reason)
    return 0 if not failed else 2


if __name__ == "__main__":
    sys.exit(main())
