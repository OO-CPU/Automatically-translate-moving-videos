import os
import re
import warnings
import time
import subprocess
import torch
import functools
from pathlib import Path

warnings.filterwarnings("ignore")

# =============================================================================
# Compatibility shim — applied BEFORE importing whisperx
# =============================================================================

# torch.load: default weights_only=False for pyannote checkpoints
# PyTorch >=2.6 changed torch.load default to weights_only=True.
# pyannote checkpoints contain omegaconf objects that fail the safety check.
# Monkey-patch torch.load to default to weights_only=False (matching <2.6
# behavior).  This is safe here because all model files come from trusted
# sources (HuggingFace / pyannote).
_original_torch_load = torch.load
@functools.wraps(_original_torch_load)
def _patched_torch_load(*args, **kwargs):
    if kwargs.get("weights_only") is None:
        kwargs["weights_only"] = False
    return _original_torch_load(*args, **kwargs)
torch.load = _patched_torch_load

# =============================================================================
# Now safe to import whisperx and the rest of the application
# =============================================================================
import whisperx
from whisperx.audio import load_audio as _whisperx_load_audio, SAMPLE_RATE as _WHISPERX_SR
from rich import print as rprint
from core.utils import *
MODEL_DIR = load_key("model_dir")


def _hf_cache_dir_for_repo(cache_root, repo_id):
    return Path(cache_root) / f"models--{repo_id.replace('/', '--')}"


def _has_complete_hf_snapshot(cache_root, repo_id):
    repo_dir = _hf_cache_dir_for_repo(cache_root, repo_id)
    snapshots = repo_dir / "snapshots"
    if not snapshots.exists():
        return False
    required_files = {"config.json", "model.bin", "tokenizer.json"}
    for snapshot in snapshots.iterdir():
        if snapshot.is_dir() and all((snapshot / name).exists() for name in required_files):
            return True
    return False

@except_handler("failed to check hf mirror", default_return=None)
def check_hf_mirror():
    mirrors = {'Official': 'huggingface.co', 'Mirror': 'hf-mirror.com'}
    fastest_url = f"https://{mirrors['Official']}"
    best_time = float('inf')
    rprint("[cyan]🔍 Checking HuggingFace mirrors...[/cyan]")
    for name, domain in mirrors.items():
        if os.name == 'nt':
            cmd = ['ping', '-n', '1', '-w', '3000', domain]
        else:
            cmd = ['ping', '-c', '1', '-W', '3', domain]
        start = time.time()
        result = subprocess.run(cmd, capture_output=True, text=True)
        response_time = time.time() - start
        if result.returncode == 0:
            if response_time < best_time:
                best_time = response_time
                fastest_url = f"https://{domain}"
            rprint(f"[green]✓ {name}:[/green] {response_time:.2f}s")
    if best_time == float('inf'):
        rprint("[yellow]⚠️ All mirrors failed, using default[/yellow]")
    rprint(f"[cyan]🚀 Selected mirror:[/cyan] {fastest_url} ({best_time:.2f}s)")
    return fastest_url

@except_handler("WhisperX processing error:")
def transcribe_audio(raw_audio_file, vocal_audio_file, start, end):
    os.environ['HF_ENDPOINT'] = check_hf_mirror()
    WHISPER_LANGUAGE = load_key("whisper.language")
    device = "cuda" if torch.cuda.is_available() else "cpu"
    rprint(f"🚀 Starting WhisperX using device: {device} ...")
    
    if device == "cuda":
        gpu_mem = torch.cuda.get_device_properties(0).total_memory / (1024**3)
        batch_size = 16 if gpu_mem > 8 else 2
        compute_type = "float16" if torch.cuda.is_bf16_supported() else "int8"
        rprint(f"[cyan]🎮 GPU memory:[/cyan] {gpu_mem:.2f} GB, [cyan]📦 Batch size:[/cyan] {batch_size}, [cyan]⚙️ Compute type:[/cyan] {compute_type}")
    else:
        batch_size = 1
        compute_type = "int8"
        rprint(f"[cyan]📦 Batch size:[/cyan] {batch_size}, [cyan]⚙️ Compute type:[/cyan] {compute_type}")
    rprint(f"[green]▶️ Starting WhisperX for segment {start:.2f}s to {end:.2f}s...[/green]")
    
    download_root = MODEL_DIR
    if WHISPER_LANGUAGE == 'zh':
        model_name = "Huan69/Belle-whisper-large-v3-zh-punct-fasterwhisper"
        local_model = os.path.join(MODEL_DIR, "Belle-whisper-large-v3-zh-punct-fasterwhisper")
    else:
        model_name = load_key("whisper.model")
        local_model = os.path.join(MODEL_DIR, model_name)
        
    if os.path.exists(local_model):
        rprint(f"[green]📥 Loading local WHISPER model:[/green] {local_model} ...")
        model_name = local_model
        download_root = None
    else:
        rprint(f"[green]📥 Using WHISPER model from HuggingFace:[/green] {model_name} ...")
        # If the project-local cache is missing or only partially downloaded,
        # let HuggingFace use the default global cache. This avoids getting
        # stuck on a half-created ./_model_cache after a network interruption.
        repo_id = model_name if "/" in model_name else f"Systran/faster-whisper-{model_name}"
        if not _has_complete_hf_snapshot(MODEL_DIR, repo_id):
            rprint(
                "[yellow]⚠️ Project model cache is incomplete; "
                "falling back to the global HuggingFace cache.[/yellow]"
            )
            download_root = None

    vad_options = {"vad_onset": 0.500,"vad_offset": 0.363}
    asr_options = {"temperatures": [0],"initial_prompt": "",}
    whisper_language = None if 'auto' in WHISPER_LANGUAGE else WHISPER_LANGUAGE
    rprint("[bold yellow] You can ignore warning of `Model was trained with torch 1.10.0+cu102, yours is 2.0.0+cu118...`[/bold yellow]")

    def load_audio_segment(audio_file, start, end):
        # Use whisperx's ffmpeg-based loader instead of librosa.load() which
        # deadlocks inside Streamlit's ScriptRunner thread.
        full_audio = _whisperx_load_audio(audio_file, sr=_WHISPERX_SR)
        start_sample = int(start * _WHISPERX_SR)
        end_sample = int(end * _WHISPERX_SR)
        return full_audio[start_sample:end_sample]

    raw_audio_segment = load_audio_segment(raw_audio_file, start, end)
    vocal_audio_segment = load_audio_segment(vocal_audio_file, start, end)

    if whisper_language is None:
        # ---------------- 自动语言模式：分段检测，支持英韩/中英等混合语言 ----------------
        # WhisperX 管线只对整段做一次语言检测；这里先用 VAD 切出语音段，
        # 逐段自动检测语言并转写，混用语言（如英语旁白 + 韩语采访）也能正确产出两种语言字幕。
        import faster_whisper
        from faster_whisper.vad import get_speech_timestamps, VadOptions
        rprint("[green]🌐 自动语言模式：按语音段分段检测语言（支持混合语言视频）[/green]")
        fw_model = faster_whisper.WhisperModel(
            local_model, device=device, compute_type=compute_type, cpu_threads=4
        )
        speech_chunks = get_speech_timestamps(
            raw_audio_segment,
            VadOptions(min_silence_duration_ms=300, speech_pad_ms=200),
        )
        # 先把间隔小于 0.8s 的相邻语音段合并成“话语”，减少检测/转写调用次数
        merged = []
        for sc in speech_chunks:
            if merged and sc["start"] - merged[-1]["end"] < int(0.8 * _WHISPERX_SR):
                merged[-1]["end"] = sc["end"]
            else:
                merged.append({"start": int(sc["start"]), "end": int(sc["end"])})

        # 逐话语检测语言（开销小），按语言分组
        groups = {}
        for sc in merged:
            chunk = raw_audio_segment[sc["start"]:sc["end"]]
            try:
                lang, prob, _ = fw_model.detect_language(chunk)
            except Exception:
                lang = "en"
            groups.setdefault(lang, []).append((int(sc["start"]), int(sc["end"])))
        lang_counter = {k: len(v) for k, v in groups.items()}
        rprint(f"[cyan]🌐 语音段语言分布（检测）: {dict(lang_counter)}[/cyan]")

        auto_segments = []
        for lang, group in groups.items():
            if not group:
                continue
            # 同语言的语音段拼接成一段音频，只调用一次转写，大幅降低 CPU 开销
            concat = __import__("numpy").concatenate(
                [raw_audio_segment[s:e] for s, e in group]
            )
            segs, _info = fw_model.transcribe(
                concat,
                language=lang,
                beam_size=1,
                condition_on_previous_text=False,
                vad_filter=False,
                word_timestamps=True,
            )
            # 组内偏移表：每个原始语音段在拼接音频中的起始秒与时长
            offsets = []
            gpos = 0.0
            for s, e in group:
                dur = (e - s) / _WHISPERX_SR
                offsets.append((s / _WHISPERX_SR, gpos, dur))
                gpos += dur
            for s in segs:
                text = (s.text or "").strip()
                if not text:
                    continue
                g_start, g_end = s.start, s.end
                base = None
                for orig_start, g0, dur in offsets:
                    if g0 <= g_start < g0 + dur + 1e-6:
                        base = start + orig_start - g0
                        break
                if base is None:
                    base = start + offsets[-1][0] - offsets[-1][1]
                seg_start = base + g_start
                seg_end = base + g_end
                words = []
                for w in (s.words or []):
                    wt = (w.word or "").strip()
                    if not wt:
                        continue
                    words.append({
                        "word": wt,
                        "start": base + (w.start or 0),
                        "end": base + (w.end or 0),
                    })
                if not words:
                    # faster-whisper 未返回词级时间戳时：按空格分词（无空格语言按字符切分），
                    # 并按段时长均分时间，避免整句被下游当作超长词丢弃。
                    if re.search(r"\s", text):
                        tokens = text.split()
                        n = len(tokens)
                        words = [
                            {
                                "word": tok,
                                "start": seg_start + (seg_end - seg_start) * j / n,
                                "end": seg_start + (seg_end - seg_start) * (j + 1) / n,
                            }
                            for j, tok in enumerate(tokens)
                        ]
                    else:
                        chars = list(text)
                        n = len(chars)
                        words = [
                            {
                                "word": ch,
                                "start": seg_start + (seg_end - seg_start) * j / n,
                                "end": seg_start + (seg_end - seg_start) * (j + 1) / n,
                            }
                            for j, ch in enumerate(chars)
                        ]
                auto_segments.append({
                    "start": seg_start,
                    "end": seg_end,
                    "text": text,
                    "words": words,
                })
        auto_segments.sort(key=lambda x: x["start"])
        dominant = max(lang_counter, key=lang_counter.get) if lang_counter else "en"
        result = {"segments": auto_segments, "language": dominant}
        rprint(
            f"[cyan]🌐 语言分布: {dict(lang_counter)}，主语言: {dominant}，"
            f"共 {len(auto_segments)} 段[/cyan]"
        )
        # 自动模式保留 faster-whisper 的段级时间戳，不做逐语言对齐，
        # 避免为每个语种额外下载对齐模型；process_transcription 兼容无 word 级时间戳。
        del fw_model
        torch.cuda.empty_cache()
    else:
        # ---------------- 固定语言模式：原 WhisperX + 对齐流程 ----------------
        load_kwargs = dict(
            device=device,
            compute_type=compute_type,
            language=whisper_language,
            vad_options=vad_options,
            asr_options=asr_options,
        )
        if download_root:
            load_kwargs["download_root"] = download_root
        model = whisperx.load_model(model_name, **load_kwargs)

        # 1. transcribe raw audio
        transcribe_start_time = time.time()
        rprint("[bold green]Note: You will see Progress if working correctly ↓[/bold green]")
        result = model.transcribe(raw_audio_segment, batch_size=batch_size, print_progress=True)
        transcribe_time = time.time() - transcribe_start_time
        rprint(f"[cyan]⏱️ time transcribe:[/cyan] {transcribe_time:.2f}s")
        del model
        torch.cuda.empty_cache()

        if result['language'] == 'zh' and WHISPER_LANGUAGE != 'zh':
            raise ValueError("Please specify the transcription language as zh and try again!")

        # 2. align by vocal audio
        align_start_time = time.time()
        model_a, metadata = whisperx.load_align_model(language_code=result["language"], device=device)
        result = whisperx.align(result["segments"], model_a, metadata, vocal_audio_segment, device, return_char_alignments=False)
        align_time = time.time() - align_start_time
        rprint(f"[cyan]⏱️ time align:[/cyan] {align_time:.2f}s")
        torch.cuda.empty_cache()
        del model_a

        # Adjust timestamps
        for segment in result['segments']:
            segment['start'] += start
            segment['end'] += start
            for word in segment['words']:
                if 'start' in word:
                    word['start'] += start
                if 'end' in word:
                    word['end'] += start

    # 记录本次实际检测到的语言（不要覆盖用户配置的 auto/en/zh…）
    update_key("whisper.detected_language", result['language'])
    return result
