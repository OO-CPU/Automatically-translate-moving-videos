"""
最终版熟肉视频一键生成：裁剪尾部广告 + 烧录字幕 + 烧录封面标题，一次 ffmpeg 完成。

流程：字幕识别/翻译就绪后，页面让用户确认标题和裁剪点（自动识别尾部广告：
LLM 分析片尾字幕判断广告起点），点击生成后一次编码输出：
  - output/output_sub.mp4                 （页面预览 / 配音用中间文件）
  - 熟肉视频/<视频名>_字幕.mp4              （唯一最终成品，直接用于上传抖音）

最终视频与发布文案保存成功后，当前 output 项目会自动归档到 history，
让自动导入 watcher 可以继续处理下一个等待中的视频。

不再像旧版那样先烧字幕、再裁剪、再加标题生成多个文件。
"""
import json
import os
import re
import shutil
import subprocess

import streamlit as st

from core._7_sub_into_vid import (
    SRC_FONT_SIZE, FONT_NAME as SRC_FONT_NAME, SRC_FONT_COLOR, SRC_OUTLINE_COLOR,
    SRC_OUTLINE_WIDTH, SRC_SHADOW_COLOR,
    TRANS_FONT_SIZE, TRANS_FONT_NAME, TRANS_FONT_COLOR, TRANS_OUTLINE_COLOR,
    TRANS_OUTLINE_WIDTH, TRANS_BACK_COLOR,
)
from core.utils.config_utils import load_key

OUTPUT_SUB = "output/output_sub.mp4"
SRC_SRT = "output/src.srt"
TRANS_SRT = "output/trans.srt"
_DEFAULT_DATA_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..", "data"))
RENDU_DIR = os.path.join(
    os.path.expanduser(os.environ.get("YOUTUBE_REPOST_DATA_DIR", _DEFAULT_DATA_DIR)),
    "熟肉视频",
)
FONT_FILE = "/System/Library/Fonts/STHeiti Medium.ttc"
AD_DETECT_CACHE = "output/gpt_log/ad_detect.json"
PREVIEW_DIR = "output/finalize_preview"


# ─── 基础工具 ───


def _probe(path):
    """返回 (width, height, duration)；失败返回 (0, 0, 0.0)。"""
    try:
        out = subprocess.run(
            [
                "ffprobe", "-v", "error",
                "-select_streams", "v:0",
                "-show_entries", "stream=width,height:format=duration",
                "-of", "json", path,
            ],
            capture_output=True, text=True, timeout=30,
        )
        data = json.loads(out.stdout)
        w = int(data["streams"][0]["width"])
        h = int(data["streams"][0]["height"])
        d = float(data["format"].get("duration", 0))
        return w, h, d
    except Exception:
        return 0, 0, 0.0


def _parse_time(value, default=0.0):
    """支持 秒 或 MM:SS / HH:MM:SS。"""
    try:
        v = value.strip()
        if not v:
            return default
        if ":" in v:
            parts = [float(x) for x in v.split(":")]
            t = 0.0
            for p in parts:
                t = t * 60 + p
            return t
        return float(v)
    except Exception:
        return default


def _fmt(seconds):
    """秒 → MM:SS 展示。"""
    s = int(round(seconds))
    return f"{s // 60}:{s % 60:02d}"


def _video_key():
    try:
        from core._1_ytdlp import find_media_file
        media_path, _ = find_media_file()
        return os.path.basename(media_path)
    except Exception:
        return ""


def _source_video():
    """当前源视频路径（output/ 里的原始下载文件）。"""
    from core._1_ytdlp import find_video_files
    return find_video_files()


def _rendu_target():
    """最终成品路径 熟肉视频/<stem>_字幕.mp4。"""
    try:
        stem = os.path.splitext(os.path.basename(_source_video()))[0]
    except Exception:
        stem = "output_sub"
    return os.path.join(RENDU_DIR, f"{stem}_字幕.mp4")


def _notify(title, message):
    try:
        subprocess.run(
            ["osascript", "-e",
             f'display notification "{message}" with title "{title}"'],
            check=False, timeout=5,
        )
    except Exception:
        pass


# ─── 尾部广告自动识别 ───


def _srt_entries(path):
    """解析 srt，返回 [(start_sec, end_sec, text), ...]。"""
    entries = []
    try:
        with open(path, encoding="utf-8") as f:
            content = f.read()
        for block in re.split(r"\n\s*\n", content.strip()):
            lines = [l for l in block.splitlines() if l.strip()]
            if len(lines) < 2:
                continue
            time_line = next((l for l in lines if "-->" in l), None)
            if not time_line:
                continue
            m = re.findall(r"(\d{1,2}):(\d{2}):(\d{2}),(\d{3})", time_line)
            if len(m) < 2:
                continue
            def _sec(g):
                return int(g[0]) * 3600 + int(g[1]) * 60 + int(g[2]) + int(g[3]) / 1000
            start, end = _sec(m[0]), _sec(m[1])
            text = " ".join(l for l in lines if "-->" not in l).strip()
            entries.append((start, end, text))
    except Exception:
        pass
    return entries


def _load_ad_cache():
    try:
        with open(AD_DETECT_CACHE, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def _save_ad_cache(data):
    try:
        os.makedirs(os.path.dirname(AD_DETECT_CACHE), exist_ok=True)
        with open(AD_DETECT_CACHE, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception:
        pass


def detect_ad_start(force=False):
    """用 LLM 分析片尾字幕，识别广告/赞助/片尾内容的起始秒数。

    返回 dict：{"is_ad": bool, "ad_start_seconds": float|None, "reason": str}
    失败时返回 {"is_ad": False, "ad_start_seconds": None, "reason": ""}。
    """
    key = _video_key()
    cache = _load_ad_cache()
    if not force and key in cache:
        return cache[key]

    entries = _srt_entries(TRANS_SRT)
    if not entries:
        return {"is_ad": False, "ad_start_seconds": None, "reason": "没有字幕"}
    # 取尾部字幕：最后 40 条（约覆盖片尾 2-4 分钟）
    tail = entries[-40:]
    lines = "\n".join(
        f"{i + 1}. {e[0]:.1f} --> {e[1]:.1f} {e[2]}"
        for i, e in enumerate(tail)
    )
    prompt = (
        "你是视频剪辑助手。下面是一个 YouTube 视频结尾的字幕片段"
        "（每行：编号. 开始秒 --> 结束秒 文本，已翻译为简体中文）：\n"
        f"{lines}\n\n"
        "请判断视频尾部是否存在与正片无关的广告/赞助/片尾内容，例如："
        "推广网站或产品（“访问xxx.com”“输入优惠码”“点击链接获取折扣”）、"
        "订阅引导、感谢赞助商、片尾动画等。\n"
        "如果存在，请给出第一条广告字幕的**编号**（上面列表里的数字）。"
        "注意：正片结尾的总结句、过渡句（如“而那个未来或许就有你”“感谢观看”）"
        "不算广告，广告必须明确提到品牌名、网站、折扣、订阅引导等推广内容；"
        "如果没有明确推广内容，is_ad 为 false，ad_start_index 为 null。\n"
        '只输出 JSON：{"is_ad": true或false, "ad_start_index": 编号或null, '
        '"reason": "不超过20字的原因"}'
    )
    result = {"is_ad": False, "ad_start_seconds": None, "reason": ""}
    try:
        from core.utils.ask_gpt import ask_gpt
        resp = ask_gpt(prompt, resp_type="json", log_title="ad_detect_gpt")
        is_ad = bool(resp.get("is_ad"))
        start = None
        idx = resp.get("ad_start_index")
        if is_ad and isinstance(idx, (int, float)) and 1 <= int(idx) <= len(tail):
            start = tail[int(idx) - 1][0]
        elif is_ad and resp.get("ad_start_seconds") is not None:
            start = float(resp["ad_start_seconds"])
        result = {
            "is_ad": is_ad,
            "ad_start_seconds": start,
            "reason": str(resp.get("reason", "")).strip()[:50],
        }
    except Exception:
        pass
    cache[key] = result
    _save_ad_cache(cache)
    return result


# ─── 封面标题渲染（沿用已验证的排版） ───


def _escape_drawtext(text):
    return (
        text.replace("\\", "\\\\")
        .replace("'", "’")
        .replace(":", "\\:")
        .replace(",", "\\,")
        .replace("%{", "%{{")
    )


def _wrap_title(title, max_chars):
    title = re.sub(r"\s+", " ", title).strip()
    if not title:
        return []
    lines = []
    while len(title) > max_chars:
        cut = max_chars
        for i in range(max_chars, 0, -1):
            if title[i - 1] in "，。！？、；：,.!?;: ":
                cut = i
                break
        lines.append(title[:cut].rstrip(" ，。！？、；：,.!?;:"))
        title = title[cut:].lstrip(" ，。！？、；：,.!?;:")
    if title:
        lines.append(title)
    return lines


def _make_scrim(w, h, position):
    """生成顶部/底部渐变压暗图（BGRA PNG），失败返回 None（退化为色带）。"""
    try:
        import cv2
        import numpy as np
    except Exception:
        return None
    try:
        scrim_h = int(h * 0.34)
        grad = np.zeros((h, w, 4), dtype=np.uint8)
        for i in range(scrim_h):
            alpha = int(245 * (1 - i / scrim_h) ** 1.15)
            row = (h - scrim_h + i) if position == "底部" else i
            grad[row, :, 3] = alpha
        path = "output/cover_scrim.png"
        cv2.imwrite(path, grad)
        return path
    except Exception:
        return None


# ─── 一键生成最终版 ───


def _subtitle_filter(w, h):
    """字幕烧录滤镜（沿用 _7_sub_into_vid 的样式与配置）。"""
    filters = [
        f"scale={w}:{h}:force_original_aspect_ratio=decrease",
        f"pad={w}:{h}:(ow-iw)/2:(oh-ih)/2",
    ]
    if load_key("burn_subtitles") and os.path.exists(TRANS_SRT):
        if load_key("subtitle.show_source_subtitle") and os.path.exists(SRC_SRT):
            filters.append(
                f"subtitles={SRC_SRT}:force_style='FontSize={SRC_FONT_SIZE},"
                f"FontName={SRC_FONT_NAME},PrimaryColour={SRC_FONT_COLOR},"
                f"OutlineColour={SRC_OUTLINE_COLOR},OutlineWidth={SRC_OUTLINE_WIDTH},"
                f"ShadowColour={SRC_SHADOW_COLOR},BorderStyle=1'"
            )
        filters.append(
            f"subtitles={TRANS_SRT}:force_style='FontSize={TRANS_FONT_SIZE},"
            f"FontName={TRANS_FONT_NAME},PrimaryColour={TRANS_FONT_COLOR},"
            f"OutlineColour={TRANS_OUTLINE_COLOR},OutlineWidth={TRANS_OUTLINE_WIDTH},"
            f"BackColour={TRANS_BACK_COLOR},Alignment=2,MarginV=27,BorderStyle=4'"
        )
    return ",".join(filters)


def _title_filters(w, h, title, seconds, position, font_scale, label_in):
    """封面标题滤镜（渐变遮罩 + 自适应大字号 + 阴影），返回 (filters, next_label)。"""
    max_fs = max(28, min(110, int(min(w, h) * font_scale)))
    max_chars = max(6, int(w * 0.9 / max_fs))
    lines = _wrap_title(title, max_chars)
    if not lines:
        return [], label_in

    scrim_h = int(h * 0.34)
    fs = max_fs
    while fs > 24 and (len(lines) * int(fs * 1.32) + 2 * int(fs * 0.5)) > scrim_h * 0.88:
        fs -= 2
    pad = int(fs * 0.5)
    line_h = int(fs * 1.32)
    block_h = len(lines) * line_h + 2 * pad
    y0 = (h - scrim_h) if position == "底部" else 0
    text_top = y0 + (scrim_h - block_h) // 2 + pad
    fade_from = max(seconds - 0.5, 0.0)

    scrim = _make_scrim(w, h, position)
    filters = []
    cur = label_in
    if scrim:
        nxt = f"{cur}x"
        filters.append(f"[{cur}][1:v]overlay=0:0:enable='lt(t,{seconds:.3f})'[{nxt}]")
        cur = nxt
    else:
        nxt = f"{cur}x"
        filters.append(
            f"[{cur}]drawbox=x=0:y={y0}:w={w}:h={scrim_h}:color=black@0.55:t=fill:"
            f"enable='lt(t,{seconds:.3f})'[{nxt}]"
        )
        cur = nxt
    for i, line in enumerate(lines):
        nxt = f"{cur}x"
        y = text_top + i * line_h
        filters.append(
            f"[{cur}]drawtext=fontfile={FONT_FILE}:text='{_escape_drawtext(line)}':"
            f"fontsize={fs}:fontcolor=white:"
            f"shadowcolor=black@0.6:shadowx=0:shadowy={max(2, fs // 24)}:"
            f"x=(w-text_w)/2:y={y}:line_spacing={max(4, fs // 8)}:"
            f"alpha='if(lt(t,{fade_from:.3f}),1,({seconds:.3f}-t)/0.5)':"
            f"enable='lt(t,{seconds:.3f})'[{nxt}]"
        )
        cur = nxt
    return filters, cur


def make_final_video(title, trim_at, title_seconds=3.0, position="顶部",
                     font_scale=0.075):
    """裁剪尾部广告 + 烧录字幕 + 烧录封面标题，一次编码生成最终版。

    返回 (ok, message, output_path)。
    """
    src = _source_video()
    w, h, dur = _probe(src)
    if w <= 0 or h <= 0:
        return False, "无法读取源视频信息", ""

    trim_at = max(0.0, min(float(trim_at), dur))
    target = _rendu_target()
    os.makedirs(RENDU_DIR, exist_ok=True)

    filters, last_label = _title_filters(
        w, h, title, max(0.8, float(title_seconds)), position, font_scale, "sub"
    )
    vf = f"[0:v]{_subtitle_filter(w, h)}[sub];" + ";".join(filters)

    scrim = "output/cover_scrim.png"
    cmd = ["ffmpeg", "-y", "-i", src]
    if os.path.exists(scrim):
        cmd += ["-i", scrim]
    tmp = OUTPUT_SUB + ".finalize_tmp.mp4"
    cmd += [
        "-filter_complex", vf,
        "-map", f"[{last_label}]", "-map", "0:a?",
        "-t", f"{trim_at:.3f}",
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "18",
        "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart",
        tmp,
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=7200)
    if proc.returncode != 0:
        if os.path.exists(tmp):
            os.remove(tmp)
        return False, (proc.stderr or "")[-600:], ""

    os.replace(tmp, OUTPUT_SUB)
    shutil.copy2(OUTPUT_SUB, target)
    _notify("VideoLingo 熟肉完成", "已生成最终版熟肉视频（裁剪+字幕+标题）")
    return True, f"已生成最终版：{target}", target


def _archive_current_video(source_path):
    """归档当前 output，并验证源视频确实进入 history。"""
    from core.utils.onekeycleanup import cleanup, sanitize_filename

    stem = sanitize_filename(os.path.splitext(os.path.basename(source_path))[0])
    archive_dir = os.path.join("history", stem)
    archived_source = os.path.join(
        archive_dir, sanitize_filename(os.path.basename(source_path))
    )
    cleanup()
    if os.path.exists(source_path) or not os.path.exists(archived_source):
        return False, "归档验证失败，当前项目没有被完整清理"
    return True, archive_dir


def _clear_final_project_state():
    """归档后清除当前视频的控件缓存，避免影响下一条视频。"""
    for key in list(st.session_state):
        if key.startswith("_final_") or key.startswith("_copy_"):
            st.session_state.pop(key, None)


# ─── 帧预览 ───


def _preview_frames(points):
    """在指定时间点提取帧，返回页面可显示的 PNG 路径列表。"""
    try:
        src = _source_video()
        os.makedirs(PREVIEW_DIR, exist_ok=True)
        paths = []
        for i, t in enumerate(points):
            out = os.path.join(PREVIEW_DIR, f"preview_{i}.png")
            subprocess.run(
                ["ffmpeg", "-y", "-loglevel", "error", "-ss", f"{t:.3f}",
                 "-i", src, "-frames:v", "1", "-q:v", "3", out],
                capture_output=True, timeout=60,
            )
            if os.path.exists(out):
                paths.append(out)
        return paths
    except Exception:
        return []


# ─── 页面区 ───


def finalize_section():
    """字幕就绪后调用：确认标题与裁剪点，一键生成最终版熟肉视频。"""
    if not (os.path.exists(TRANS_SRT) and os.path.exists(SRC_SRT)):
        return
    try:
        src = _source_video()
    except Exception:
        return
    if not os.path.exists(src):
        return

    st.subheader("🚀 生成最终版熟肉视频（裁剪广告 + 烧录字幕 + 封面标题）")
    w, h, dur = _probe(src)

    with st.container(border=True):
        st.caption(
            "先确认标题和裁剪点，点生成后一次完成：裁掉尾部广告、烧录字幕、"
            "烧录封面标题，直接输出唯一的最终成品；生成成功并保存发布文案后，"
            "当前视频会自动归档到 history/"
        )

        # 1) 标题
        from core.st_utils.title_utils import translate_video_title
        title = st.text_input(
            "封面标题（默认取 YouTube 原视频名的直译，可修改）",
            value=translate_video_title() or "视频标题",
            key="_final_title",
        )

        # 2) 自动识别尾部广告
        ad = detect_ad_start()
        if ad.get("is_ad") and ad.get("ad_start_seconds") is not None:
            start = float(ad["ad_start_seconds"])
            st.info(
                f"🔍 自动识别到尾部广告：建议从 **{_fmt(start)}（{start:.0f}s）** 开始裁剪"
                f"{('（' + ad['reason'] + '）') if ad.get('reason') else ''}"
            )
            default_trim = f"{start:.0f}"
        else:
            st.success(
                "🔍 未检测到明显的尾部广告"
                + (f"（{ad['reason']}）" if ad.get("reason") else "")
            )
            default_trim = f"{dur:.0f}"
        if st.button("🔄 重新识别广告", key="_ad_redetect"):
            detect_ad_start(force=True)
            st.rerun()

        # 3) 裁剪设置
        c1, c2 = st.columns([2, 1])
        trim_val = c1.text_input(
            "裁剪起点（秒或 MM:SS，此时间点之后的内容将删除；"
            f"视频总长 {_fmt(dur)}，默认=不裁剪）",
            value=default_trim,
            key="_final_trim",
        )
        c2.caption(f"视频总时长：{_fmt(dur)}（{dur:.1f}s）")

        # 4) 帧预览：裁剪点附近 + 结尾，帮助确认广告位置
        trim = _parse_time(trim_val, dur)
        if dur > 0:
            pts = []
            if trim < dur - 1:
                pts = [
                    max(0.0, trim - 3.0),
                    min(dur - 0.1, trim),
                    max(0.0, dur - 1.0),
                ]
            if pts:
                frames = _preview_frames(pts)
                if frames:
                    cols = st.columns(len(frames))
                    labels = ["裁剪点前 3s", "裁剪点", "视频结尾"]
                    for col, fp, lb in zip(cols, frames, labels):
                        with col:
                            st.image(fp, caption=lb)

        # 5) 封面标题样式
        c3, c4, c5 = st.columns(3)
        title_seconds = c3.number_input(
            "标题显示时长（秒）", min_value=1.0, max_value=10.0,
            value=3.0, step=0.5, key="_final_title_seconds",
        )
        position = c4.selectbox("标题位置", ["顶部", "底部"], key="_final_pos")
        size_label = c5.selectbox(
            "字号", ["自动", "大", "标准", "小"], key="_final_size"
        )
        scale = {"自动": 0.075, "大": 0.09, "标准": 0.075, "小": 0.06}[size_label]

        # 6) 一键生成
        if st.button(
            "🚀 一键生成最终版熟肉视频",
            key="_final_generate", type="primary", use_container_width=True,
        ):
            if not title.strip():
                st.warning("请先填写标题")
            elif trim <= 0:
                st.warning("裁剪起点必须大于 0")
            else:
                with st.spinner("正在生成（裁剪+字幕+标题，可能需要几分钟）..."):
                    ok, msg, out = make_final_video(
                        title.strip(), trim, title_seconds, position, scale
                    )
                if ok:
                    st.session_state["_copy_confirmed_title"] = title.strip()
                    from core.st_utils.publish_copy_section import save_publish_copy_for_final

                    copy_path = save_publish_copy_for_final(title.strip())
                    if not copy_path:
                        st.error("❌ 最终视频已生成，但发布文案保存失败；当前视频未归档")
                    else:
                        archived, archive_result = _archive_current_video(src)
                        if not archived:
                            st.error(
                                f"❌ 最终视频已生成，但{archive_result}；"
                                "请保留当前页面并手动检查"
                            )
                        else:
                            _clear_final_project_state()
                            st.session_state["_final_archive_notice"] = (
                                f"✅ 最终视频和发布文案已生成，当前视频已自动归档到 "
                                f"{archive_result}"
                            )
                            st.rerun()
                else:
                    st.error(f"❌ 生成失败：\n{msg}")

        if os.path.exists(OUTPUT_SUB):
            _, _, cur = _probe(OUTPUT_SUB)
            st.caption(
                f"当前成品：{_rendu_target()}（时长 {cur:.1f}s，"
                f"源视频 {dur:.1f}s，已裁掉 {dur - cur:.1f}s）"
            )
