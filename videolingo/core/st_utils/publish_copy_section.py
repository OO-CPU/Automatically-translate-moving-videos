"""
发布文案生成（手动上传抖音用）。

熟肉视频生成后调用：自动生成中文标题/简介/话题，
显示在页面并保存为 熟肉视频/<视频名>_发布文案.txt，方便手动上传时复制。
"""
import json
import os
import re

import streamlit as st

SUB_VIDEO = "output/output_sub.mp4"
_DEFAULT_DATA_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..", "data"))
RENDU_DIR = os.path.join(
    os.path.expanduser(os.environ.get("YOUTUBE_REPOST_DATA_DIR", _DEFAULT_DATA_DIR)),
    "熟肉视频",
)


def _clean_title(name):
    name = os.path.splitext(name)[0]              # 去掉扩展名
    name = re.sub(r"^(YouTube|youtube)[_-]?", "", name)
    name = re.sub(r"_\d{8}$", "", name)          # 去掉日期后缀 _20260804
    name = re.sub(r"_字幕$", "", name)
    name = re.sub(r"[-_]+", " ", name).strip()
    return name[:55]


def _default_title():
    try:
        from core._1_ytdlp import find_media_file
        media_path, _ = find_media_file()
        return _clean_title(os.path.basename(media_path))
    except Exception:
        return _clean_title(os.path.basename(SUB_VIDEO))


def _summary():
    """从 gpt_log/summary.json 提取 (中文简介, 话题列表)。"""
    theme, terms = "", []
    try:
        with open("output/gpt_log/summary.json", encoding="utf-8") as f:
            data = json.load(f)
        for item in data:
            resp = item.get("resp") or {}
            if not theme and resp.get("theme"):
                theme = str(resp["theme"]).strip()
            for term in resp.get("terms", []):
                tg = (term.get("tgt") or "").strip()
                if tg and tg not in terms and not re.search(r"[（）()]", tg):
                    terms.append(tg)
    except Exception:
        pass
    return theme, terms[:4]


def _gen_meta():
    """生成中文标题与话题：标题直接用 YouTube 原视频名的直译，话题沿用摘要术语。"""
    from core.st_utils.title_utils import translate_video_title

    title = translate_video_title()
    tags = []
    # 话题优先复用已生成的 douyin_meta，其次用摘要术语
    try:
        with open("output/gpt_log/douyin_meta.json", encoding="utf-8") as f:
            data = json.load(f)
        for item in data:
            resp = item.get("resp") or {}
            tags = [str(x).strip() for x in resp.get("tags", []) if str(x).strip()]
            if tags:
                break
    except Exception:
        pass
    if not tags:
        _, terms = _summary()
        tags = terms
    if not title:
        # 翻译失败：退回已生成的 douyin_meta 标题
        try:
            with open("output/gpt_log/douyin_meta.json", encoding="utf-8") as f:
                data = json.load(f)
            for item in data:
                resp = item.get("resp") or {}
                t = str(resp.get("title", "")).strip()
                if t:
                    title = t[:55]
                    break
        except Exception:
            pass
    if title:
        return title[:55], tags[:5]
    return None, None


def _video_key():
    try:
        from core._1_ytdlp import find_media_file
        media_path, _ = find_media_file()
        return os.path.basename(media_path)
    except Exception:
        return os.path.basename(SUB_VIDEO)


def _rendu_path(video_key):
    """成品路径，与 _7_sub_into_vid.py 的命名保持一致。"""
    stem = os.path.splitext(video_key)[0]
    return os.path.join(RENDU_DIR, f"{stem}_字幕.mp4")


def _save_copy_file(video_key, title, desc, tags):
    """把文案保存为 熟肉视频/<视频名>_发布文案.txt。"""
    txt_path = os.path.splitext(_rendu_path(video_key))[0] + "_发布文案.txt"
    tag_line = " ".join(f"#{t.strip()}" for t in tags if t and t.strip())
    content = f"标题：{title}\n简介：{desc}\n话题：{tag_line}\n"
    try:
        os.makedirs(RENDU_DIR, exist_ok=True)
        with open(txt_path, "w", encoding="utf-8") as f:
            f.write(content)
        return txt_path
    except Exception as exc:
        st.warning(f"发布文案保存失败: {exc}")
        return None


def save_publish_copy_for_final(title):
    """最终版生成后，在归档 output 前保存对应的发布文案。"""
    video_key = _video_key()
    theme, terms = _summary()
    return _save_copy_file(video_key, title, theme or "", terms)


def publish_copy_section():
    """在字幕视频生成后调用：展示并保存标题/简介/话题（手动上传用）。"""
    if not os.path.exists(SUB_VIDEO):
        return
    st.subheader("📝 发布文案（手动上传抖音用）")

    video_key = _video_key()
    meta = st.session_state.get("_copy_meta")
    if not (meta and meta.get("video") == video_key):
        theme, terms = _summary()
        confirmed = st.session_state.get("_copy_confirmed_title", "")
        if confirmed:
            auto_title, auto_tags = confirmed, None
        else:
            auto_title, auto_tags = _gen_meta()
        meta = {
            "video": video_key,
            "title": auto_title or _default_title(),
            "desc": theme or "",
            "tags": auto_tags or terms,
        }
        st.session_state["_copy_meta"] = meta
        st.session_state["_copy_saved_path"] = _save_copy_file(
            video_key, meta["title"], meta["desc"], meta["tags"]
        )

    with st.container(border=True):
        st.caption("已根据视频内容自动生成，可修改后手动复制；点「保存」会更新文案文件")
        title = st.text_input("标题", value=meta["title"], key="_copy_title")
        desc = st.text_area("简介", value=meta["desc"], key="_copy_desc", height=120)
        tags_default = ", ".join(meta["tags"] + ["熟肉", "搬运"]) if meta["tags"] else "熟肉,搬运"
        tags = st.text_input("话题（逗号分隔）", value=tags_default, key="_copy_tags")
        col1, col2 = st.columns([1, 4])
        with col1:
            if st.button("🔄 重新生成", key="_copy_regen", use_container_width=True):
                for k in ("_copy_meta", "_copy_title", "_copy_desc", "_copy_tags", "_copy_saved_path"):
                    st.session_state.pop(k, None)
                st.rerun()
        with col2:
            if st.button("💾 保存为发布文案文件", key="_copy_save", use_container_width=True):
                st.session_state["_copy_saved_path"] = _save_copy_file(
                    video_key,
                    title.strip(),
                    desc.strip(),
                    [t.strip() for t in tags.split(",") if t.strip()],
                )
                st.rerun()
        saved_path = st.session_state.get("_copy_saved_path")
        if saved_path and os.path.exists(saved_path):
            st.caption(f"✅ 文案文件：{saved_path}")
