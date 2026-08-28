"""
标题工具：从下载文件名还原 YouTube 原标题，并直译为中文标题。

标题直接用原视频名的翻译（不再让 LLM 重新总结），供发布文案与封面烧录共用。
翻译结果缓存在 output/gpt_log/title_translation.json（按视频文件名），
同一条视频只翻译一次。
"""
import json
import os
import re

TRANSLATION_CACHE = "output/gpt_log/title_translation.json"


def video_key():
    """当前视频的文件名（唯一标识，用于缓存）。"""
    try:
        from core._1_ytdlp import find_media_file
        media_path, _ = find_media_file()
        return os.path.basename(media_path)
    except Exception:
        return ""


def clean_source_title(name):
    """从下载文件名还原原标题（去掉 平台_ / 日期 / _字幕 等后缀）。"""
    name = os.path.splitext(name)[0]
    name = name.replace("YouTube_", "").replace("youtube_", "")
    name = re.sub(r"_\d{8}$", "", name)
    name = re.sub(r"_字幕$", "", name)
    name = re.sub(r"[-_]+", " ", name).strip()
    return name[:120]


def extract_source_title():
    """当前视频的原始标题（来自下载文件名）。"""
    return clean_source_title(video_key())


def _load_cache():
    try:
        with open(TRANSLATION_CACHE, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def _save_cache(data):
    try:
        os.makedirs(os.path.dirname(TRANSLATION_CACHE), exist_ok=True)
        with open(TRANSLATION_CACHE, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception:
        pass


def translate_video_title():
    """直译当前视频标题为中文；优先读缓存，翻译失败回退原标题。"""
    key = video_key()
    if not key:
        return ""
    cache = _load_cache()
    if key in cache and cache[key].get("title"):
        return str(cache[key]["title"]).strip()

    src = extract_source_title()
    if not src:
        return ""
    prompt = (
        "你是短视频标题翻译专家。请把下面的视频标题翻译成简体中文：\n"
        "1. 忠实原意，简洁自然，适合短视频封面展示；\n"
        "2. 控制在 15-30 个汉字；\n"
        "3. 不要引号、书名号、emoji、#话题符号；\n"
        "4. 如果标题本身已是中文，直接返回原文。\n"
        f"原文标题：{src}\n"
        '只输出 JSON：{"title": "中文标题"}'
    )
    try:
        from core.utils.ask_gpt import ask_gpt
        resp = ask_gpt(prompt, resp_type="json", log_title="video_title_translation")
        title = str(resp.get("title", "")).strip().strip('"')
        if title:
            cache[key] = {"title": title}
            _save_cache(cache)
            return title[:55]
    except Exception:
        pass
    return src
