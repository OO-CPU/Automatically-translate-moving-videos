import os
import re
import shutil
import json
import time
from time import sleep

import streamlit as st
from core._1_ytdlp import download_video_ytdlp, find_media_file, write_input_manifest
from core.utils import *
from translations.translations import translate as t

OUTPUT_DIR = "output"
DL_LOCK = os.path.join(
    os.path.expanduser(os.environ.get("VIDEOLINGO_HOME", os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))),
    ".oneclick_dl.lock",
)


def _auto_start_url():
    """从 URL 参数读取一键下载的链接（?youtube_url=... 或 ?url=...）。"""
    params = st.query_params
    raw = params.get("youtube_url") or params.get("url")
    if isinstance(raw, list):
        raw = raw[-1] if raw else None
    url = str(raw or "").strip()
    return url if url.startswith(("http://", "https://")) else None


def _processing_busy():
    """任何会话正在处理字幕时返回 True（防止并发任务互相覆盖 output/）。"""
    try:
        from core.st_utils.task_runner import TaskRunner
        cur = TaskRunner._current
        if cur is not None and cur.is_active:
            return True
        runner = TaskRunner.get(st.session_state, "_text_runner")
        if runner.is_active:
            return True
    except Exception:
        pass
    return False


def _dl_lock_stale(path):
    """锁文件里的进程已退出或超过 1 小时视为失效。"""
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        pid, ts = int(data.get("pid") or 0), float(data.get("ts") or 0)
        if time.time() - ts > 3600:
            return True
        if pid > 0:
            os.kill(pid, 0)
            return False
    except Exception:
        pass
    return True


def _acquire_dl_lock():
    if os.path.exists(DL_LOCK) and not _dl_lock_stale(DL_LOCK):
        return False
    try:
        with open(DL_LOCK, "w", encoding="utf-8") as f:
            json.dump({"pid": os.getpid(), "ts": time.time()}, f)
    except OSError:
        pass
    return True


def _release_dl_lock():
    try:
        if os.path.exists(DL_LOCK):
            os.remove(DL_LOCK)
    except OSError:
        pass


def _css_text(value):
    return str(value).replace("\\", "\\\\").replace('"', '\\"')


def _inject_file_uploader_i18n():
    # Streamlit does not expose official i18n for file_uploader internals.
    # Streamlit 1.49 DOM:
    #   div[data-testid="stFileUploaderDropzoneInstructions"]
    #     > span    (cloud icon, must keep)
    #     > div     (column flex)
    #         > span  (1st: "Drag and drop ... here")
    #         > span  (2nd: "Limit ... · MP4, MOV ...")
    # So we target ONLY the two direct child spans of the inner div, leaving
    # the icon and other elements untouched.
    drag_text = _css_text(t("Drag and drop file here"))
    limit_text = _css_text(t("Limit 4GB per file · MP4, MOV, AVI, MKV, FLV, WMV, WEBM, WAV, MP3, FLAC, M4A"))
    browse_text = _css_text(t("Browse files"))
    st.markdown(
        f"""
        <style>
        /* Title line */
        div[data-testid="stFileUploaderDropzoneInstructions"] > div > span:nth-of-type(1) {{
            font-size: 0 !important;
            line-height: 1.4;
        }}
        div[data-testid="stFileUploaderDropzoneInstructions"] > div > span:nth-of-type(1)::before {{
            content: "{drag_text}";
            font-size: 1rem;
        }}
        /* Sub line (limit + accepted formats) */
        div[data-testid="stFileUploaderDropzoneInstructions"] > div > span:nth-of-type(2) {{
            font-size: 0 !important;
            line-height: 1.4;
        }}
        div[data-testid="stFileUploaderDropzoneInstructions"] > div > span:nth-of-type(2)::before {{
            content: "{limit_text}";
            font-size: 0.8rem;
        }}
        /* Browse files button */
        div[data-testid="stFileUploader"] button[kind="secondary"] {{
            font-size: 0 !important;
        }}
        div[data-testid="stFileUploader"] button[kind="secondary"]::before {{
            content: "{browse_text}";
            font-size: 0.875rem;
        }}
        </style>
        """,
        unsafe_allow_html=True,
    )

def download_video_section():
    st.header(t("a. Download or Upload Video"))
    with st.container(border=True):
        auto_url = _auto_start_url()
        auto_start = st.query_params.get("auto_process") == "1"
        if auto_start:
            st.query_params.clear()
        if auto_url:
            st.query_params.clear()
            if _processing_busy():
                st.error("⚠️ 已有任务正在处理中，请先完成或停止当前任务，再下载新的视频。")
            elif not _acquire_dl_lock():
                st.warning("⚠️ 另一个下载正在进行中，请稍候几秒再试。")
            else:
                try:
                    with st.spinner(t("Downloading video...")):
                        if os.path.exists(OUTPUT_DIR):
                            shutil.rmtree(OUTPUT_DIR)
                        os.makedirs(OUTPUT_DIR, exist_ok=True)
                        download_video_ytdlp(auto_url, resolution=load_key("ytb_resolution"))
                    st.session_state["_auto_start_text"] = True
                    st.success("✅ 视频下载完成，正在自动识别、翻译、烧录字幕…")
                except Exception as exc:
                    st.error(f"❌ 下载失败：{exc}")
                finally:
                    _release_dl_lock()
                st.rerun()
        try:
            media_file, media_type = find_media_file()
            if auto_start:
                if _processing_busy():
                    st.info("⚠️ 已有任务正在处理中，请稍候；完成后再刷新页面继续。")
                else:
                    st.session_state["_auto_start_text"] = True
                    st.rerun()
            if media_type == "video":
                st.video(media_file)
            else:
                st.audio(media_file)
            if st.button(t("Delete and Reselect"), key="delete_video_button"):
                os.remove(media_file)
                if os.path.exists(OUTPUT_DIR):
                    shutil.rmtree(OUTPUT_DIR)
                st.session_state.pop("_processed_upload_id", None)
                sleep(1)
                st.rerun()
            return True
        except ValueError as e:
            if "No media file found" not in str(e):
                st.error(t("Media file detection failed: {error}").replace("{error}", str(e)))
                if st.button(t("Clear output and reselect"), key="clear_output_button"):
                    if os.path.exists(OUTPUT_DIR):
                        shutil.rmtree(OUTPUT_DIR)
                    st.session_state.pop("_processed_upload_id", None)
                    st.rerun()
                return False
        except Exception:
            pass

        col1, col2 = st.columns([3, 1])
        with col1:
            url = st.text_input(t("Enter YouTube link:"))
        with col2:
            res_dict = {
                "360p": "360",
                "1080p": "1080",
                t("Best"): "best"
            }
            target_res = load_key("ytb_resolution")
            res_options = list(res_dict.keys())
            default_idx = list(res_dict.values()).index(target_res) if target_res in res_dict.values() else 0
            res_display = st.selectbox(t("Resolution"), options=res_options, index=default_idx)
            res = res_dict[res_display]
        if st.button(t("Download Video"), key="download_button", width="stretch"):
            if url:
                with st.spinner(t("Downloading video...")):
                    download_video_ytdlp(url, resolution=res)
                st.session_state["_auto_start_text"] = True
                st.rerun()

        _inject_file_uploader_i18n()
        uploaded_file = st.file_uploader(t("Upload local media file"), type=load_key("allowed_video_formats") + load_key("allowed_audio_formats"))
        if uploaded_file:
            upload_id = f"{uploaded_file.name}:{uploaded_file.size}"
            if st.session_state.get("_processed_upload_id") == upload_id:
                try:
                    find_media_file()
                    st.warning(t("Upload was already processed. Delete and reselect to upload again."))
                    return False
                except Exception:
                    st.session_state.pop("_processed_upload_id", None)

            if os.path.exists(OUTPUT_DIR):
                shutil.rmtree(OUTPUT_DIR)
            os.makedirs(OUTPUT_DIR, exist_ok=True)

            raw_name = uploaded_file.name.replace(' ', '_')
            name, ext = os.path.splitext(raw_name)
            clean_name = re.sub(r'[^\w\-_\.]', '', name) + ext.lower()
                
            with open(os.path.join(OUTPUT_DIR, clean_name), "wb") as f:
                f.write(uploaded_file.getbuffer())

            media_path = os.path.join(OUTPUT_DIR, clean_name)
            media_ext = ext.lower().lstrip(".")
            media_type = "video" if media_ext in load_key("allowed_video_formats") else "audio"
            write_input_manifest(media_path, media_type)

            st.session_state["_processed_upload_id"] = upload_id
            st.rerun()
        else:
            return False
