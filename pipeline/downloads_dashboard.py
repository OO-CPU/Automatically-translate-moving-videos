#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
下载进度监控页（仿 Chrome 下载页面）
- 监控 Xiaoer VideoLab 的下载目录（~/Downloads）与自动搬运生肉视频区
- 显示进行中/已完成/失败的下载记录，进度与速度实时刷新
- 每条记录提供「打开文件位置」（Finder 显示）
用法：python3 downloads_dashboard.py [--port 7799]
页面：http://localhost:7799
"""
import json
import os
import re
import subprocess
import sys
import threading
import time
import urllib.request
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

PORT = 7799
DAEMON = "http://127.0.0.1:7788"
HISTORY_FILE = Path.home() / "Library" / "Logs" / "xiaoer-videolab-history.jsonl"
REPO_ROOT = Path(__file__).resolve().parents[1]
STATE_DIR = Path(os.environ.get("YOUTUBE_REPOST_DATA_DIR", REPO_ROOT / "data")).expanduser()
IGNORED_FILE = STATE_DIR / ".dashboard_ignored.json"
PAUSED_FILE = STATE_DIR / ".dashboard_paused.json"
WATCH_DIRS = [
    Path.home() / "Downloads",
    STATE_DIR / "生肉视频",
]
MEDIA_EXTS = {".mp4", ".webm", ".mov", ".mkv", ".flv", ".wmv", ".m4v", ".avi", ".mpg", ".mpeg", ".ts"}
_TEMP_TAIL = (".part", ".crdownload", ".download", ".tmp", ".ytdl")
_TEMP_RE = re.compile(r"\.f\d+\.\w+$", re.IGNORECASE)
_PLATFORMS = [
    ("douyin", "抖音"), ("iesdouyin", "抖音"),
    ("xiaohongshu", "小红书"), ("xhslink", "小红书"), ("xhscdn", "小红书"),
    ("bilibili", "B站"), ("b23.tv", "B站"),
    ("youtube", "YouTube"), ("youtu.be", "YouTube"),
    ("weibo", "微博"), ("zhihu", "知乎"), ("ixigua", "西瓜视频"),
    ("twitter", "X"), ("x.com", "X"), ("vimeo", "Vimeo"),
    ("instagram", "Instagram"), ("tiktok", "TikTok"), ("kuaishou", "快手"),
    ("youku", "优酷"), ("iqiyi", "爱奇艺"), ("facebook", "Facebook"),
    ("reddit", "Reddit"), ("dailymotion", "Dailymotion"),
]

_speed_cache = {}
_speed_lock = threading.Lock()
_ignored_cache = None
_paused_cache = None


def _load_state(path, default):
    try:
        if path.is_file():
            return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        pass
    return default


def _save_state(path, data):
    try:
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    except OSError:
        pass


def ignored_paths() -> set:
    """已删除记录的文件路径集合（这些记录不再显示）。"""
    global _ignored_cache
    if _ignored_cache is None:
        _ignored_cache = set(_load_state(IGNORED_FILE, {}).get("paths", []))
    return _ignored_cache


def add_ignored(path):
    ignored_paths().add(path)
    _save_state(IGNORED_FILE, {"paths": sorted(ignored_paths())})


def paused_entries() -> dict:
    """暂停中的下载：path -> {url, title, platform}。"""
    global _paused_cache
    if _paused_cache is None:
        _paused_cache = {}
        for e in _load_state(PAUSED_FILE, {}).get("paused", []):
            if e.get("path"):
                _paused_cache[e["path"]] = e
    return _paused_cache


def save_paused(entries: dict):
    global _paused_cache
    _paused_cache = dict(entries)
    _save_state(PAUSED_FILE, {"paused": [dict(v, path=k) for k, v in entries.items()]})


def daemon_post(path, payload):
    req = urllib.request.Request(
        DAEMON + path,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=5) as r:
            return json.loads(r.read() or b"{}")
    except Exception as e:
        return {"error": str(e)}


def active_totals():
    """从 daemon 获取进行中下载的视频总大小（path -> bytes）。"""
    try:
        with urllib.request.urlopen(DAEMON + "/active-totals", timeout=3) as r:
            return json.loads(r.read().decode("utf-8")).get("totals", {})
    except Exception:
        return {}


def is_temp(name: str) -> bool:
    n = name.lower()
    return n.endswith(_TEMP_TAIL) or bool(_TEMP_RE.search(n))


def final_name(name: str) -> str:
    """去掉 yt-dlp 中间流标记与临时后缀，还原最终文件名。"""
    n = re.sub(r"\.(part|crdownload|download|tmp|ytdl)$", "", name, flags=re.IGNORECASE)
    n = re.sub(r"\.f\d+(?=\.\w+$)", "", n)
    for ext in MEDIA_EXTS:
        if n.lower().endswith(ext):
            return n
    return n


def parse_meta(filename: str) -> dict:
    """从 daemon 命名格式 {平台}_{标题}_{日期}.{扩展名} 解析信息。"""
    stem = Path(final_name(filename)).stem
    date = ""
    m = re.search(r"_(\d{8})$", stem)
    if m:
        date = m.group(1)
        stem = stem[: -len(m.group(0))]
    platform = ""
    for key, label in _PLATFORMS:
        if stem.lower().startswith(key + "_"):
            platform = label
            stem = stem[len(key) + 1:]
            break
    return {"platform": platform, "title": stem.replace("_", " ").strip() or Path(filename).stem, "date": date}


def format_size(n):
    if n is None:
        return "未知大小"
    v = float(n)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if v < 1024 or unit == "TB":
            return f"{v:.1f} {unit}" if unit != "B" else f"{int(v)} B"
        v /= 1024


def format_time(ts: float) -> str:
    return datetime.fromtimestamp(ts).strftime("%Y/%m/%d %H:%M")


def speed_for(path, size):
    now = time.time()
    with _speed_lock:
        prev = _speed_cache.get(path)
        _speed_cache[path] = (size, now)
        if prev and now - prev[1] > 0:
            return max(0.0, (size - prev[0]) / (now - prev[1]))
    return 0.0


def scan_dirs():
    items = []
    seen = set()
    for base in WATCH_DIRS:
        if not base.is_dir():
            continue
        try:
            entries = list(base.iterdir())
        except OSError:
            continue
        for p in entries:
            if not p.is_file():
                continue
            name = p.name
            if not (p.suffix.lower() in MEDIA_EXTS or is_temp(name)):
                continue
            try:
                st = p.stat()
            except OSError:
                continue
            downloading = is_temp(name)
            stalled = downloading and (time.time() - st.st_mtime > 300)
            key = str(p)
            if key in ignored_paths():
                continue
            if key in seen:
                continue
            seen.add(key)
            meta = parse_meta(name)
            items.append({
                "id": f"f_{abs(hash(key)):x}",
                "filename": final_name(name),
                "path": key,
                "status": ("stalled" if stalled else "downloading") if downloading else "done",
                "platform": meta["platform"],
                "title": meta["title"],
                "bytes": st.st_size,
                "mtime": st.st_mtime,
                "speed": speed_for(key, st.st_size) if downloading else 0.0,
            })
    # 速度衰减：很久没变化的进行中任务速度归零（通过缓存条目 mtime 判断）
    return items


def load_history():
    if not HISTORY_FILE.is_file():
        return []
    out = []
    try:
        lines = HISTORY_FILE.read_text(encoding="utf-8").strip().splitlines()
    except OSError:
        return []
    for line in lines[-80:]:
        try:
            out.append(json.loads(line))
        except (json.JSONDecodeError, ValueError):
            continue
    return out


def merge_items():
    items = scan_dirs()
    by_path = {it["path"]: it for it in items}
    history = load_history()
    for h in history:
        fp = h.get("filepath") or ""
        if fp and fp in by_path:
            by_path[fp].update({
                "title": h.get("title") or by_path[fp]["title"],
                "timestamp": h.get("timestamp", ""),
                "url": h.get("url", ""),
                "status": "done" if h.get("status") == "done" else by_path[fp]["status"],
            })
        elif h.get("status") == "failed":
            items.append({
                "id": h.get("id", f"h_{abs(hash(fp)):x}"),
                "filename": h.get("filename") or Path(h.get("url", "download")).name,
                "path": "",
                "status": "failed",
                "platform": "",
                "title": h.get("title") or "下载失败",
                "bytes": None,
                "mtime": 0,
                "speed": 0.0,
                "timestamp": h.get("timestamp", ""),
                "url": h.get("url", ""),
            })
    paused = paused_entries()
    for it in items:
        pe = paused.get(it["path"])
        if pe and it["status"] in ("downloading", "stalled"):
            it["status"] = "paused"
            it["url"] = pe.get("url", "")
            it["exists"] = True
    for p, pe in paused.items():
        if p in by_path:
            continue
        try:
            st = Path(p).stat()
            exists = True
        except OSError:
            st = None
            exists = False
        items.append({
            "id": f"p_{abs(hash(p)):x}",
            "filename": Path(p).name,
            "path": p,
            "status": "paused",
            "platform": pe.get("platform", ""),
            "title": pe.get("title") or Path(p).stem,
            "bytes": st.st_size if st else 0,
            "mtime": st.st_mtime if st else 0,
            "speed": 0.0,
            "url": pe.get("url", ""),
            "exists": exists,
        })
    order = {"downloading": 0, "paused": 1, "done": 2, "stalled": 3, "failed": 4}
    items.sort(key=lambda it: (order.get(it["status"], 3), -it["mtime"]))
    totals = active_totals()
    for it in items:
        it["total"] = totals.get(it["path"], 0)
    return items


def reveal(path):
    if not path or not os.path.exists(path):
        return False, "文件不存在"
    try:
        subprocess.run(["open", "-R", path], check=False)
        return True, ""
    except Exception as e:
        return False, str(e)


def handle_action(data: dict) -> dict:
    """暂停 / 继续 / 删除下载记录。由监控页按钮调用。"""
    action = data.get("action", "")
    path = data.get("path", "")
    url = data.get("url", "")

    if action == "delete":
        if path:
            # 取消正在进行的下载（若进程还活着），静默——不产生 failed 记录。
            daemon_post("/cancel", {"path": path})
            p = Path(path)
            try:
                if p.is_file():
                    p.unlink()
            except OSError:
                pass
            paused = paused_entries()
            if path in paused:
                del paused[path]
                save_paused(paused)
            add_ignored(path)
            return {"ok": True}
        if url:
            daemon_post("/history-delete", {"url": url})
            return {"ok": True}
        return {"ok": False, "error": "缺少 path/url"}

    if action == "pause":
        paused = paused_entries()
        if path in paused:
            return {"ok": True}
        r = daemon_post("/cancel", {"path": path})
        u = r.get("url", "")
        if not u:
            return {"ok": False, "error": "暂停失败：找不到对应的下载进程"}
        meta = next((it for it in merge_items() if it["path"] == path), {})
        paused[path] = {
            "url": u,
            "title": meta.get("title") or Path(path).stem,
            "platform": meta.get("platform", ""),
            "filename": final_name(Path(path).name),
        }
        save_paused(paused)
        return {"ok": True}

    if action == "resume":
        paused = paused_entries()
        pe = paused.get(path)
        if not pe or not pe.get("url"):
            return {"ok": False, "error": "没有可继续的记录"}
        r = daemon_post("/download", {
            "url": pe["url"],
            "filename": pe.get("filename", ""),
        })
        if r.get("error"):
            return {"ok": False, "error": r["error"]}
        del paused[path]
        save_paused(paused)
        return {"ok": True}

    return {"ok": False, "error": f"未知操作 {action}"}


PAGE_HTML = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>下载内容</title>
<style>
  :root { --blue:#1a73e8; --text:#202124; --sub:#5f6368; --border:#e8eaed; --card:#f8f9fa; }
  * { box-sizing:border-box; margin:0; padding:0; }
  body { font-family:-apple-system,BlinkMacSystemFont,"Segoe UI","PingFang SC","Microsoft YaHei",sans-serif;
         background:#fff; color:var(--text); }
  .wrap { max-width:880px; margin:0 auto; padding:32px 24px 80px; }
  .head { display:flex; align-items:baseline; justify-content:space-between; margin-bottom:20px; }
  h1 { font-size:24px; font-weight:500; }
  .count { font-size:13px; color:var(--sub); }
  .card { background:var(--card); border:1px solid var(--border); border-radius:12px;
          padding:14px 16px; margin-bottom:10px; display:flex; align-items:center;
          gap:16px; box-shadow:0 1px 2px rgba(60,64,67,.08); }
  .icon { flex:0 0 32px; width:32px; height:32px; display:flex; align-items:center;
          justify-content:center; }
  .icon svg { width:22px; height:22px; display:block; }
  .icon.downloading svg { fill:var(--blue); }
  .icon.stalled svg { fill:#b06000; }
  .icon.done svg { fill:var(--sub); }
  .icon.failed svg { fill:#d93025; }
  .body { flex:1; min-width:0; }
  .name { font-size:14px; font-weight:500; line-height:1.4; white-space:nowrap;
          overflow:hidden; text-overflow:ellipsis; }
  .name .ext { color:var(--sub); font-weight:400; }
  .sub { font-size:12px; color:var(--sub); margin-top:3px; display:flex; gap:8px;
         align-items:center; flex-wrap:wrap; line-height:1.5; }
  .chip { font-size:11px; color:var(--sub); background:#fff; border:1px solid var(--border);
          border-radius:10px; padding:0 8px; line-height:18px; }
  .card.stalled { border-color:#fdd663; background:#fff8e1; }
  .progress { height:4px; background:#dadce0; border-radius:2px; margin-top:8px;
              overflow:hidden; }
  .progress > div { height:100%; background:var(--blue); border-radius:2px; width:35%;
                    animation:slide 1.2s linear infinite; }
  @keyframes slide { 0%{transform:translateX(-100%);} 100%{transform:translateX(400%);} }
  .actions { display:flex; gap:8px; flex:0 0 auto; align-items:center; }
  .btn { display:inline-flex; align-items:center; gap:6px; border:1px solid #dadce0;
         background:#fff; color:#3c4043; font-size:13px; padding:6px 12px;
         border-radius:4px; cursor:pointer; white-space:nowrap; flex:0 0 auto; }
  .btn:hover { background:#f8f9fa; border-color:#d2e3fc; }
  .btn:active { background:#e8f0fe; }
  .btn.icon-only { padding:7px 9px; }
  .btn svg { width:16px; height:16px; fill:currentColor; display:block; }
  .failed .sub { color:#d93025; }
  .empty { text-align:center; color:var(--sub); font-size:14px; padding:60px 0; }
  .footer { text-align:center; color:#9aa0a6; font-size:12px; margin-top:24px; }
  .toast { position:fixed; left:50%; bottom:36px; transform:translateX(-50%);
           background:#323232; color:#fff; font-size:13px; padding:10px 18px;
           border-radius:8px; opacity:0; pointer-events:none; transition:opacity .2s;
           z-index:10; max-width:80%; }
  .toast.show { opacity:1; }
</style>
</head>
<body>
<div class="wrap">
  <div class="head">
    <h1>下载内容</h1>
    <span class="count" id="count"></span>
  </div>
  <div id="list"></div>
  <div class="footer">Xiaoer VideoLab 下载监控 · 每 2 秒自动刷新</div>
</div>
<div class="toast" id="toast"></div>
<script>
const ICONS = {
  downloading: '<svg viewBox="0 0 24 24"><path d="M12 16l-5-5 1.4-1.4 2.6 2.6V3h2v9.2l2.6-2.6L17 11l-5 5zM5 20h14v-2H5v2z"/></svg>',
  stalled: '<svg viewBox="0 0 24 24"><path d="M12 2C6.48 2 2 6.48 2 12s4.48 10 10 10 10-4.48 10-10S17.52 2 12 2zm1 14h-2v-2h2v2zm0-4h-2V7h2v5z"/></svg>',
  paused: '<svg viewBox="0 0 24 24"><path d="M12 2C6.48 2 2 6.48 2 12s4.48 10 10 10 10-4.48 10-10S17.52 2 12 2zm-1 14H9V8h2v8zm4 0h-2V8h2v8z"/></svg>',
  done: '<svg viewBox="0 0 24 24"><path d="M12 2C6.48 2 2 6.48 2 12s4.48 10 10 10 10-4.48 10-10S17.52 2 12 2zm-2 15l-5-5 1.41-1.41L10 14.17l7.59-7.59L19 8l-9 9z"/></svg>',
  failed: '<svg viewBox="0 0 24 24"><path d="M12 2C6.48 2 2 6.48 2 12s4.48 10 10 10 10-4.48 10-10S17.52 2 12 2zm-1 14H9v-2h2v2zm0-4H9V7h2v5z"/></svg>'
};
const BTN = {
  folder: '<svg viewBox="0 0 24 24"><path d="M10 4H4c-1.1 0-1.99.9-1.99 2L2 18c0 1.1.9 2 2 2h16c1.1 0 2-.9 2-2V8c0-1.1-.9-2-2-2h-8l-2-2z"/></svg>',
  pause: '<svg viewBox="0 0 24 24"><path d="M6 19h4V5H6v14zm8-14v14h4V5h-4z"/></svg>',
  play: '<svg viewBox="0 0 24 24"><path d="M8 5v14l11-7z"/></svg>',
  close: '<svg viewBox="0 0 24 24"><path d="M19 6.41L17.59 5 12 10.59 6.41 5 5 6.41 10.59 12 5 17.59 6.41 19 12 13.41 17.59 19 19 17.59 13.41 12z"/></svg>'
};
function fmtSize(n){ if(n==null) return '未知大小'; const u=['B','KB','MB','GB','TB']; let v=n,i=0; while(v>=1024&&i<u.length-1){v/=1024;i++;} return v.toFixed(i?1:0)+' '+u[i]; }
function fmtTime(ts){ if(!ts) return ''; const d=new Date(ts*1000); const p=n=>String(n).padStart(2,'0'); return d.getFullYear()+'/'+p(d.getMonth()+1)+'/'+p(d.getDate())+' '+p(d.getHours())+':'+p(d.getMinutes()); }
function esc(s){ return String(s).replace(/[&<>"']/g, c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c])); }
function splitExt(name){
  name = String(name||'');
  const m = name.match(/^(.*?)(\.[A-Za-z0-9]{1,6})$/) || [name, name, ''];
  return [m[1]||name, m[2]||''];
}
function render(items){
  const list=document.getElementById('list');
  document.getElementById('count').textContent = items.length ? items.length+' 项' : '';
  if(!items.length){
    list.innerHTML='<div class="empty">您还没有下载任何内容</div>';
    return;
  }
  list.innerHTML = items.map(it=>{
    const icon = ICONS[it.status] || ICONS.done;
    const sub = it.status==='downloading'
      ? '<span style="color:#1a73e8">下载中</span><span>已下载 '+fmtSize(it.bytes)+'</span>'+(it.total>0?'<span>总大小 '+fmtSize(it.total)+'</span>':'')+(it.speed>0?'<span>速度 '+fmtSize(it.speed)+'/s</span>':'')
      : it.status==='stalled'
      ? '<span style="color:#b06000">下载已中断（超5分钟无进展）</span><span>已下载 '+fmtSize(it.bytes)+'</span>'+(it.total>0?'<span>总大小 '+fmtSize(it.total)+'</span>':'')
      : it.status==='paused'
      ? '<span style="color:#b06000">已暂停</span><span>已下载 '+fmtSize(it.bytes)+'</span>'+(it.total>0?'<span>总大小 '+fmtSize(it.total)+'</span>':'')
      : it.status==='done'
      ? '<span>'+fmtTime(it.mtime)+'</span><span>'+fmtSize(it.bytes)+'</span>'
      : '<span>下载失败</span>';
    const chip = it.platform ? '<span class="chip">'+esc(it.platform)+'</span>' : '';
    const progress = it.status==='downloading' ? '<div class="progress"><div></div></div>' : '';
    const [base, ext] = splitExt(it.title);
    return '<div class="card '+it.status+'">'
      +'<div class="icon '+it.status+'">'+icon+'</div>'
      +'<div class="body"><div class="name">'+esc(base)+'<span class="ext">'+esc(ext)+'</span></div>'
      +'<div class="sub">'+sub+chip+'</div>'+progress+'</div>'
      +actions(it)+'</div>';
  }).join('');
}
function actions(it){
  const b = [];
  const ap = 'data-path="'+esc(it.path)+'"';
  const au = it.url ? 'data-url="'+esc(it.url)+'"' : '';
  if (it.status==='downloading') b.push('<button class="btn" data-act="pause" '+ap+' title="暂停下载">'+BTN.pause+'<span>暂停</span></button>');
  else if (it.status==='paused') b.push('<button class="btn" data-act="resume" '+ap+' title="继续下载">'+BTN.play+'<span>继续</span></button>');
  if (it.status==='done'||it.status==='downloading'||(it.status==='paused'&&it.exists)) b.push('<button class="btn icon-only" data-act="reveal" '+ap+' title="打开文件位置">'+BTN.folder+'</button>');
  b.push('<button class="btn icon-only" data-act="delete" '+ap+' '+au+' title="删除记录">'+BTN.close+'</button>');
  return '<div class="actions">'+b.join('')+'</div>';
}
document.getElementById('list').addEventListener('click', async (e) => {
  const btn = e.target.closest('button[data-act]');
  if (!btn) return;
  const act = btn.dataset.act;
  const path = btn.dataset.path || '';
  const url = btn.dataset.url || '';
  const body = act === 'reveal' ? {path} : {action:act, path, url};
  try {
    const r = await fetch(act === 'reveal' ? '/api/reveal' : '/api/action', {
      method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify(body)
    });
    const d = await r.json().catch(() => ({}));
    if (d && d.ok === false) toast(d.error || '操作失败');
  } catch(err) {
    toast('操作失败，请重试');
  }
  refresh();
});
let toastTimer;
function toast(msg){
  const t = document.getElementById('toast');
  t.textContent = msg;
  t.classList.add('show');
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => t.classList.remove('show'), 3000);
}
async function refresh(){ try{ const r=await fetch('/api/downloads'); const d=await r.json(); render(d.items||[]); }catch(e){} }
refresh(); setInterval(refresh,2000);
</script>
</body>
</html>
"""


class Handler(BaseHTTPRequestHandler):
    def _send(self, code, body: bytes, ctype: str):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        path = urlparse(self.path).path
        if path == "/":
            self._send(200, PAGE_HTML.encode("utf-8"), "text/html; charset=utf-8")
        elif path == "/api/downloads":
            body = json.dumps({"items": merge_items()}, ensure_ascii=False).encode("utf-8")
            self._send(200, body, "application/json; charset=utf-8")
        else:
            self._send(404, b'{"error":"not found"}', "application/json")

    def do_POST(self):
        path = urlparse(self.path).path
        if path == "/api/reveal":
            try:
                n = int(self.headers.get("Content-Length", "0"))
                data = json.loads(self.rfile.read(n) or b"{}")
                ok, err = reveal(data.get("path", ""))
                self._send(200 if ok else 404,
                           json.dumps({"ok": ok, "error": err}, ensure_ascii=False).encode("utf-8"),
                           "application/json")
            except Exception as e:
                self._send(400, json.dumps({"ok": False, "error": str(e)}).encode("utf-8"), "application/json")
        elif path == "/api/action":
            try:
                n = int(self.headers.get("Content-Length", "0"))
                data = json.loads(self.rfile.read(n) or b"{}")
                r = handle_action(data)
                self._send(200 if r.get("ok") else 400,
                           json.dumps(r, ensure_ascii=False).encode("utf-8"),
                           "application/json")
            except Exception as e:
                self._send(400, json.dumps({"ok": False, "error": str(e)}).encode("utf-8"), "application/json")
        else:
            self._send(404, b'{"error":"not found"}', "application/json")

    def log_message(self, fmt, *args):
        pass


def main():
    port = PORT
    if "--port" in sys.argv:
        port = int(sys.argv[sys.argv.index("--port") + 1])
    print(f"下载监控页: http://localhost:{port}", flush=True)
    ThreadingHTTPServer(("127.0.0.1", port), Handler).serve_forever()


if __name__ == "__main__":
    main()
