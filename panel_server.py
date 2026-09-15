# -*- coding: utf-8 -*-
"""控制面板：浏览器点按钮启动程序（本机可视化操作）。

用法：
  双击「启动控制面板.bat」
  或：C:\\python\\python.exe panel_server.py
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
import time
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from utils import ensure_dirs, load_config, project_root

PYTHON = Path(r"C:\python\python.exe")
if not PYTHON.exists():
    PYTHON = Path(sys.executable)

# 后台常驻任务
PROCS: dict[str, subprocess.Popen] = {}
LAST_LOG: list[str] = []
LOCK = threading.Lock()


def _log(msg: str) -> None:
    with LOCK:
        LAST_LOG.append(f"{time.strftime('%H:%M:%S')} {msg}")
        del LAST_LOG[:-30]


def _is_running(name: str) -> bool:
    p = PROCS.get(name)
    if p is None:
        return False
    return p.poll() is None


def _start_bg(name: str, script: str) -> dict:
    if _is_running(name):
        return {"ok": True, "msg": f"「{name}」已在运行", "running": True}
    script_path = ROOT / script
    if not script_path.exists():
        return {"ok": False, "msg": f"找不到 {script}"}
    # 新控制台窗口，学员能看到输出；也方便单独关掉
    creationflags = 0
    if sys.platform == "win32":
        creationflags = subprocess.CREATE_NEW_CONSOLE  # type: ignore[attr-defined]
    p = subprocess.Popen(
        [str(PYTHON), str(script_path)],
        cwd=str(ROOT),
        creationflags=creationflags,
    )
    PROCS[name] = p
    _log(f"已启动 {name}（pid={p.pid}）")
    return {"ok": True, "msg": f"已启动「{name}」", "pid": p.pid, "running": True}


def _stop_bg(name: str) -> dict:
    p = PROCS.get(name)
    if not p or p.poll() is not None:
        PROCS.pop(name, None)
        return {"ok": True, "msg": f"「{name}」本来就没在跑", "running": False}
    try:
        p.terminate()
        try:
            p.wait(timeout=5)
        except subprocess.TimeoutExpired:
            p.kill()
    except Exception as e:
        return {"ok": False, "msg": str(e)}
    PROCS.pop(name, None)
    _log(f"已停止 {name}")
    return {"ok": True, "msg": f"已停止「{name}」", "running": False}


def _run_once() -> dict:
    _log("开始跑周报…")
    env = os.environ.copy()
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONUTF8"] = "1"
    try:
        completed = subprocess.run(
            [str(PYTHON), "-X", "utf8", str(ROOT / "main.py"), "--once"],
            cwd=str(ROOT),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=300,
            env=env,
        )
        out = (completed.stdout or "")[-2000:]
        err = (completed.stderr or "")[-1000:]
        ok = completed.returncode == 0

        tip = ""
        stats = {}
        summary_path = ROOT / "data" / "digests" / "last_run_summary.json"
        # 从最新 digest 取 mode
        digests = sorted((ROOT / "data" / "digests").glob("digest-*.json"), reverse=True)
        mode = ""
        note = ""
        if digests:
            try:
                latest = json.loads(digests[0].read_text(encoding="utf-8"))
                mode = latest.get("mode") or ""
                note = latest.get("note") or ""
                stats = latest.get("_stats") or {}
            except Exception:
                pass

        if ok:
            sm = stats.get("summary_mode") or ""
            msg = "快讯已生成" if mode == "flash" else "周报已生成"
            _log("周报完成 mode=" + (mode or "new") + " summary=" + sm)
        else:
            msg = "周报运行失败"
            _log(f"周报失败 code={completed.returncode}")

        return {
            "ok": ok,
            "msg": msg,
            "note": "",
            "mode": mode,
            "stdout": "",
            "stderr": err if not ok else "",
            "content": (_latest_content().get("content") if ok else None),
        }
    except Exception as e:
        _log(f"日报异常：{e}")
        return {"ok": False, "msg": str(e)}


def _reset_store() -> dict:
    """清空去重库，下次可重新采到内容。"""
    cfg = load_config()
    paths = ensure_dirs(cfg)
    store = paths["store_file"]
    if store.exists():
        bak = store.with_suffix(store.suffix + f".bak-{time.strftime('%Y%m%d%H%M%S')}")
        store.replace(bak)
        _log(f"已备份并清空采集记录 → {bak.name}")
        return {"ok": True, "msg": f"已清空采集记录（备份为 {bak.name}）。请再点「一键生成周报」。"}
    return {"ok": True, "msg": "采集记录本来就是空的。"}


def _run_flash() -> dict:
    """重大监管快讯：临时推送，不等周五周报。"""
    _log("开始跑快讯…")
    env = os.environ.copy()
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONUTF8"] = "1"
    try:
        completed = subprocess.run(
            [str(PYTHON), "-X", "utf8", str(ROOT / "main.py"), "--once", "--flash"],
            cwd=str(ROOT),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=300,
            env=env,
        )
        ok = completed.returncode == 0
        err = (completed.stderr or "")[-1000:]
        msg = "快讯已生成" if ok else "快讯失败"
        _log(msg)
        return {
            "ok": ok,
            "msg": msg,
            "stderr": err if not ok else "",
            "content": (_latest_content().get("content") if ok else None),
        }
    except Exception as e:
        return {"ok": False, "msg": str(e)}


def _run_quarterly() -> dict:
    _log("开始跑季度合集…")
    env = os.environ.copy()
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONUTF8"] = "1"
    try:
        completed = subprocess.run(
            [str(PYTHON), "-X", "utf8", str(ROOT / "main.py"), "--quarterly"],
            cwd=str(ROOT),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=300,
            env=env,
        )
        ok = completed.returncode == 0
        err = (completed.stderr or "")[-1000:]
        msg = "季度合集已生成" if ok else "季度合集失败"
        _log(msg)
        return {
            "ok": ok,
            "msg": msg,
            "stderr": err if not ok else "",
            "content": (_latest_content().get("content") if ok else None),
        }
    except Exception as e:
        return {"ok": False, "msg": str(e)}


def _open_latest_html() -> dict:
    d = ROOT / "data" / "digests"
    latest = d / "weekly-latest.html"
    files = [latest] if latest.exists() else []
    files += sorted(d.glob("weekly-*.html"), reverse=True) + sorted(d.glob("flash-*.html"), reverse=True)
    # 去重且优先 latest
    seen = set()
    ordered = []
    for f in files:
        if f.name in seen or not f.exists():
            continue
        seen.add(f.name)
        ordered.append(f)
    if not ordered:
        ordered = sorted(d.glob("*.html"), reverse=True)
    if not ordered:
        return {"ok": False, "msg": "还没有 HTML 周报，请先生成"}
    target = ordered[0]
    if sys.platform == "win32":
        os.startfile(str(target))  # type: ignore[attr-defined]
    else:
        subprocess.Popen(["xdg-open", str(target)])
    return {"ok": True, "msg": f"已打开：{target.name}"}


def _latest_content(max_items: int = 40) -> dict:
    """读取最新周报/日报，供面板直接展示。"""
    d = ROOT / "data" / "digests"
    files = sorted(d.glob("digest-*.json"), reverse=True)
    if not files:
        return {"ok": False, "msg": "还没有内容，请先点「一键生成周报」", "content": None}
    try:
        data = json.loads(files[0].read_text(encoding="utf-8"))
    except Exception as e:
        return {"ok": False, "msg": f"读取失败：{e}", "content": None}

    ai = data.get("ai_summary") or {}
    weekly = data.get("weekly") or {}
    items = []
    for it in (data.get("items") or [])[:max_items]:
        items.append({
            "title": it.get("title") or "",
            "source": it.get("source") or "",
            "summary": it.get("summary") or "",
            "key_info": it.get("key_info") or "",
            "legal_focus": it.get("legal_focus") or "",
            "url": it.get("url") or "",
            "tags": it.get("tags") or [],
            "impact_scenes": it.get("impact_scenes") or [],
            "section_label": it.get("section_label") or "",
            "importance": it.get("importance") or "",
            "review_status": it.get("review_status") or "",
            "is_flash": bool(it.get("is_flash")),
            "think_questions": it.get("think_questions") or "",
            "action_suggestions": it.get("action_suggestions") or "",
        })
    pending = []
    # 对外预览不展示待人审条目

    content = {
        "file": files[0].name,
        "title": data.get("title") or "",
        "generated_at": data.get("generated_at") or "",
        "counts": data.get("counts") or {},
        "mode": data.get("mode") or "",
        "note": data.get("note") or "",
        "briefing": ai.get("briefing") or "",
        "summary_mode": ai.get("mode") or "",
        "provider": ai.get("provider") or "",
        "model": ai.get("model") or "",
        "positioning": weekly.get("positioning") or "",
        "mainline": weekly.get("mainline") or "",
        "date_range": weekly.get("date_range") or "",
        "html": (data.get("_paths") or {}).get("html") or "",
        "items": items,
        "pending": pending,
        "week_legal_reference": "",
        "week_think_question": "",
        "week_action_suggestion": "",
        "sections": {
            k: [
                {
                    "title": x.get("title"),
                    "source": x.get("source"),
                    "region": x.get("region") or "",
                    "extended_source": x.get("extended_source") or "",
                    "key_info": x.get("key_info") or x.get("summary"),
                    "legal_focus": x.get("legal_focus"),
                    "action_suggestions": x.get("action_suggestions") or "",
                    "think_questions": x.get("think_questions") or "",
                    "impact_scenes": x.get("impact_scenes") or [],
                    "impact_scene_tags": x.get("impact_scene_tags") or [],
                    "tags": x.get("tags") or [],
                    "importance": x.get("importance") or "",
                    "published_date": x.get("published_date") or (x.get("published_at") or "")[:10],
                    "published_at": x.get("published_at") or "",
                    "url": x.get("url"),
                    "is_flash": bool(x.get("is_flash")),
                }
                for x in (v or [])[:20]
            ]
            for k, v in (data.get("sections") or {}).items()
        },
    }
    try:
        from report_html import _collect_week_legal_reference

        ref = _collect_week_legal_reference(data)
        content["week_legal_reference"] = ref
        content["week_think_question"] = ref
        content["week_action_suggestion"] = ""
    except Exception:
        pass
    return {"ok": True, "msg": "已加载最新周报", "content": content}


def _open_latest_briefing() -> dict:
    d = ROOT / "data" / "digests"
    files = sorted(d.glob("briefing-*.md"), reverse=True)
    if not files:
        files = sorted(d.glob("digest-*.md"), reverse=True)
    if not files:
        return {"ok": False, "msg": "还没有总结文件，请先点「一键生成周报」"}
    target = files[0]
    if sys.platform == "win32":
        os.startfile(str(target))  # type: ignore[attr-defined]
    else:
        subprocess.Popen(["xdg-open", str(target)])
    return {"ok": True, "msg": f"已打开总结：{target.name}"}


def _open_dir(key: str) -> dict:
    cfg = load_config()
    paths = ensure_dirs(cfg)
    mapping = {
        "saved": paths.get("saved_dir") or (project_root() / "data" / "saved"),
        "digests": paths.get("digest_dir") or (project_root() / "data" / "digests"),
        "inbox": paths.get("inbox_dir") or (project_root() / "data" / "inbox"),
        "code": project_root(),
    }
    target = Path(mapping.get(key) or mapping["code"])
    target.mkdir(parents=True, exist_ok=True)
    if sys.platform == "win32":
        os.startfile(str(target))  # type: ignore[attr-defined]
    else:
        subprocess.Popen(["xdg-open", str(target)])
    return {"ok": True, "msg": f"已打开：{target}"}


def _status() -> dict:
    latest = _latest_content()
    return {
        "ok": True,
        "python": str(PYTHON),
        "root": str(ROOT),
        "watchlist": [
            r.get("name")
            for r in (load_config().get("accounts") or {}).get("wechat_watchlist") or []
            if r.get("name")
        ],
        "logs": list(LAST_LOG),
        "content": latest.get("content"),
    }


def handle_api(action: str) -> dict:
    if action == "status":
        return _status()
    if action == "run_digest":
        return _run_once()
    if action == "run_flash":
        return _run_flash()
    if action == "run_quarterly":
        return _run_quarterly()
    if action == "latest_content":
        return _latest_content()
    if action == "reset_store":
        return _reset_store()
    if action == "open_briefing":
        return _open_latest_briefing()
    if action == "open_html":
        return _open_latest_html()
    if action == "open_saved":
        return _open_dir("saved")
    if action == "open_digests":
        return _open_dir("digests")
    if action == "open_inbox":
        return _open_dir("inbox")
    return {"ok": False, "msg": f"未知操作：{action}"}


class Handler(BaseHTTPRequestHandler):
    def _send(self, code: int, body: bytes, content_type: str) -> None:
        self.send_response(code)
        self.send_header("Content-Type", content_type)
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        path = parsed.path.rstrip("/") or "/"

        if path == "/api/status":
            data = json.dumps(handle_api("status"), ensure_ascii=False).encode("utf-8")
            self._send(200, data, "application/json; charset=utf-8")
            return

        if path.startswith("/api/"):
            action = path[len("/api/") :]
            qs = parse_qs(parsed.query)
            # 也支持 /api/do?action=xxx
            if action == "do":
                action = (qs.get("action") or [""])[0]
            data = json.dumps(handle_api(action), ensure_ascii=False).encode("utf-8")
            self._send(200, data, "application/json; charset=utf-8")
            return

        # 静态页
        if path == "/" or path == "/index.html":
            html_path = ROOT / "panel" / "index.html"
            if not html_path.exists():
                self._send(404, b"index.html missing", "text/plain")
                return
            self._send(200, html_path.read_bytes(), "text/html; charset=utf-8")
            return

        # panel 下静态资源
        if path.startswith("/panel/"):
            rel = path[len("/panel/") :]
            file_path = (ROOT / "panel" / rel).resolve()
            if not str(file_path).startswith(str((ROOT / "panel").resolve())):
                self._send(403, b"forbidden", "text/plain")
                return
            if file_path.exists() and file_path.is_file():
                ctype = "text/plain"
                if file_path.suffix == ".css":
                    ctype = "text/css; charset=utf-8"
                elif file_path.suffix == ".js":
                    ctype = "application/javascript; charset=utf-8"
                elif file_path.suffix == ".html":
                    ctype = "text/html; charset=utf-8"
                self._send(200, file_path.read_bytes(), ctype)
                return

        self._send(404, b"not found", "text/plain")

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        path = parsed.path.rstrip("/")
        length = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(length) if length else b"{}"
        try:
            payload = json.loads(raw.decode("utf-8") or "{}")
        except json.JSONDecodeError:
            payload = {}
        action = payload.get("action") or path.split("/")[-1]
        data = json.dumps(handle_api(action), ensure_ascii=False).encode("utf-8")
        self._send(200, data, "application/json; charset=utf-8")

    def log_message(self, fmt: str, *args) -> None:
        return


def main() -> None:
    host = "127.0.0.1"
    port = 8787
    ensure_dirs(load_config())
    server = ThreadingHTTPServer((host, port), Handler)
    url = f"http://{host}:{port}/"
    print("=" * 56)
    print("法律AI周报 · 控制面板")
    print(f"请用浏览器打开：{url}")
    print("关掉本窗口 = 关闭面板")
    print("=" * 56)
    threading.Timer(0.8, lambda: webbrowser.open(url)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n面板已关闭")


if __name__ == "__main__":
    main()
