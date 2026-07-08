#!/usr/bin/env python3
"""离线自检:验证 2026-07-08 修复(F1 手工板块保留 / F2 whisper本地模型 / F5 双通道 /
F6 原子写 / F9 push日志控制流 / reprocess_full 导入)。
不联网、不加载真模型、不写运行态数据;网络与模型全用 monkeypatch。"""
import json, os, subprocess, sys, tempfile, types

TESTS = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(TESTS)
PIPE = os.path.join(ROOT, "pipeline")
sys.path.insert(0, PIPE)
ok = 0

def check(name, cond):
    global ok
    assert cond, f"FAIL: {name}"
    ok += 1
    print(f"  ok {name}")

# ---------- F1 generate.keep_manual_modules ----------
import generate
mods = {"ai": {"items": [1]}, "hot": {"items": []}}
old = {"ai": {"items": ["OLD"]}, "kidlit": {"items": ["k"]}, "podcasts": {"items": ["p"]}}
generate.keep_manual_modules(mods, old)
check("F1 手工板块整体保留", mods["kidlit"] == {"items": ["k"]} and mods["podcasts"] == {"items": ["p"]})
check("F1 已知键不被覆盖", mods["ai"] == {"items": [1]})
m2 = {"x": 1}
generate.keep_manual_modules(m2, {})
check("F1 old为空无操作", m2 == {"x": 1})
gsrc = open(os.path.join(PIPE, "generate.py"), encoding="utf-8").read()
check("F1 main()已接入回填", "keep_manual_modules(mods, old)" in gsrc)

# ---------- F2 whisper 本地模型选择 + 守护回退 ----------
import podcast_pipeline as pp
local_default = os.path.join(PIPE, "models", "faster-whisper-tiny")
check("F2 本地模型已就位(model.bin)", os.path.isfile(os.path.join(local_default, "model.bin")))
check("F2 默认解析到本地目录", pp._whisper_model_ref({}) == local_default)
with tempfile.TemporaryDirectory() as td:
    open(os.path.join(td, "model.bin"), "wb").write(b"x")
    check("F2 WHISPER_LOCAL_MODEL优先", pp._whisper_model_ref({"WHISPER_LOCAL_MODEL": td}) == td)
check("F2 目录缺失回退tiny", pp._whisper_model_ref({"WHISPER_LOCAL_MODEL": "/nonexistent_zz"}) == "tiny")

calls = []
class _FakeWM:
    def __init__(self, ref, **kw): calls.append(ref)
fake = types.ModuleType("faster_whisper"); fake.WhisperModel = _FakeWM
_saved_fw = sys.modules.get("faster_whisper")
sys.modules["faster_whisper"] = fake
try:
    pp.load_whisper()
    check("F2 load_whisper传本地目录而非'tiny'", calls == [local_default])
    class _FailLocal:
        def __init__(self, ref, **kw):
            calls.append(ref)
            if ref != "tiny": raise RuntimeError("boom")
    calls.clear(); fake.WhisperModel = _FailLocal
    pp.load_whisper()
    check("F2 本地目录坏时守护回退tiny(旧行为)", calls == [local_default, "tiny"])
finally:
    if _saved_fw is not None: sys.modules["faster_whisper"] = _saved_fw
    else: del sys.modules["faster_whisper"]

# ---------- F5 RSS/下载 双通道(代理优先,直连兜底) ----------
RSS = (b"<?xml version='1.0'?><rss><channel><item><title>Ep1</title>"
       b"<enclosure url='http://x/a.mp3' type='audio/mpeg'/><guid>g1</guid></item></channel></rss>")
class _Resp:
    def iter_content(self, n): yield RSS
    def close(self): pass
class _FakeReq:
    calls = []
    @staticmethod
    def get(url, **kw):
        _FakeReq.calls.append(kw.get("proxies"))
        if kw.get("proxies"): raise ConnectionError("proxy down")
        return _Resp()
_saved_req = pp.requests
pp.requests = _FakeReq
try:
    ep = pp.latest("http://feed")
    check("F5 latest代理挂→直连兜底成功", bool(ep) and ep["audio"] == "http://x/a.mp3")
    check("F5 顺序=先代理后直连", _FakeReq.calls == [pp.PROXY, None])
    class _AllFail:
        @staticmethod
        def get(url, **kw): raise ConnectionError("all down")
    pp.requests = _AllFail
    check("F5 两路全挂语义不变返回None", pp.latest("http://feed") is None)
finally:
    pp.requests = _saved_req

class _OpFail:
    def open(self, req, timeout=None): raise OSError("proxy down")
class _OpOK:
    def open(self, req, timeout=None):
        class R:
            def read(self): return b"AUDIO" * 10
        return R()
_saved_ops = pp._openers
with tempfile.TemporaryDirectory() as td:
    p = os.path.join(td, "a.mp3")
    try:
        pp._openers = [_OpFail(), _OpOK()]
        ep = {"audio": "http://x/a.mp3"}
        check("F5 dl_one代理挂→直连兜底成功", pp.dl_one(ep, p) is True and os.path.isfile(p) and ep["mp3"] == p)
        pp._openers = [_OpFail(), _OpFail()]
        check("F5 dl_one两路全挂返回False", pp.dl_one({"audio": "http://x"}, p + "2") is False)
    finally:
        pp._openers = _saved_ops

# ---------- F6 手工整合脚本改原子写 ----------
for f, marker in [("merge_breadth.py", "save_json(data,LATEST)"),
                  ("merge_newsec.py", "save_json(data,LATEST)"),
                  ("merge_expand.py", "save_json(data,LATEST)"),
                  ("merge_lib_news.py", "save_json(data,LATEST)"),
                  ("merge_enrich.py", "save_json(data,LATEST)"),
                  ("merge_reenrich.py", "save_json(data,LATEST)"),
                  ("voice_gen.py", "save_json(d, APP)"),
                  ("build_lineup.py", 'save_json(shows, "docs/data/shows.json")')]:
    s = open(os.path.join(PIPE, f), encoding="utf-8").read()
    check(f"F6 {f} 已用save_json", marker in s and "json.dump(data,open(LATEST" not in s)
r = subprocess.run([sys.executable, os.path.join(PIPE, "jsonio.py")], capture_output=True, text=True)
check("F6 jsonio原子写自检", r.returncode == 0 and "jsonio selfcheck ok" in r.stdout)

# ---------- reprocess_full 导入不崩(无key环境/任意cwd) ----------
env = {k: v for k, v in os.environ.items() if k != "DEEPSEEK_API_KEY"}
r = subprocess.run([sys.executable, "-c",
                    f"import sys; sys.path.insert(0, {PIPE!r}); import reprocess_full; print('IMPORT_OK')"],
                   capture_output=True, text=True, env=env, cwd=tempfile.gettempdir())
check("reprocess_full 导入不崩(懒加载key)", r.returncode == 0 and "IMPORT_OK" in r.stdout)

# ---------- F9 push 日志控制流 ----------
sh = open(os.path.join(ROOT, "run_podcast_daily.sh"), encoding="utf-8").read()
check("F9 改为if/elif/else", "elif git push" in sh and '|| git push >> "$LOG" 2>&1 &&' not in sh)
r = subprocess.run(["bash", "-n", os.path.join(ROOT, "run_podcast_daily.sh")], capture_output=True)
check("F9 bash -n 通过", r.returncode == 0)
demo = 'set -e\nf(){ return 1; }\nif f; then echo A; elif f; then echo B; else echo C; fi\necho DONE'
r = subprocess.run(["bash", "-c", demo], capture_output=True, text=True)
check("F9 两路全败时set -e不再杀脚本", r.returncode == 0 and "C" in r.stdout and "DONE" in r.stdout)

print(f"\nPASS daily-intel 离线自检全部通过 ({ok} 项)")
