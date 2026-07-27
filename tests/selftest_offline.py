#!/usr/bin/env python3
"""离线自检:验证 2026-07-08 修复(F1 手工板块保留 / F2 whisper本地模型 / F5 双通道 /
F6 原子写 / F9 push日志控制流 / reprocess_full 导入)。
不联网、不加载真模型、不写运行态数据;网络与模型全用 monkeypatch。"""
import json, os, subprocess, sys, tempfile, time, types

TESTS = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(TESTS)
PIPE = os.path.join(ROOT, "pipeline")
sys.path.insert(0, PIPE)
# 自检会拿畸形 JSON 反复触发原文落盘,改道到临时目录,别往真实 logs/ 里堆垃圾
_DUMPDIR = tempfile.mkdtemp(prefix="selftest-dump-")
os.environ["INTEL_DUMP_DIR"] = _DUMPDIR
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

# ---------- F10 DeepSeek 永久错误单轮熔断 ----------
import llm

class _Resp:
    def __init__(self, status=200, payload=None):
        self.status_code = status; self._p = payload or {}
    def raise_for_status(self):
        if self.status_code >= 400: raise AssertionError("引擎级状态码应在 raise_for_status 前被识别")
    def json(self): return self._p

def _set_env(**kv):
    saved = {k: os.environ.get(k) for k in kv}
    for k, v in kv.items():
        os.environ.pop(k, None) if v is None else os.environ.__setitem__(k, v)
    return saved

def _restore_env(saved):
    for k, v in saved.items():
        os.environ.pop(k, None) if v is None else os.environ.__setitem__(k, v)

# ---------- E1-E3 引擎链自动改道(2026-07-27:DeepSeek 402 致全站冻结 16 天的根因) ----------
saved_post, saved_get = llm.requests.post, llm.requests.get
saved_env = _set_env(DEEPSEEK_API_KEY="offline-placeholder", OPENAI_API_KEY=None,
                     INTEL_ENGINE_ORDER="deepseek,ollama,openai")
try:
    llm.requests.get = lambda *a, **kw: _Resp(200, {"models": [{"name": "fake-local"}]})

    llm._BLOCKED.clear(); hits = []
    def _post_402_then_local(url, **kw):
        hits.append(url)
        return _Resp(402) if "deepseek" in url else _Resp(200, {"message": {"content": '{"ok": true}'}})
    llm.requests.post = _post_402_then_local
    out = llm.chat_json("s", "u")
    check("E1 DeepSeek 402 自动改道本地引擎",
          out == {"ok": True} and any("deepseek" in u for u in hits) and any("11434" in u for u in hits))
    hits.clear(); llm.chat_json("s", "u")
    check("E1 已拉黑的引擎本轮不再重撞", not any("deepseek" in u for u in hits))
    check("E1 记下真正出活的那一路(否则日志会写着 deepseek 实则跑本地)",
          llm.last_used == "ollama:fake-local")

    llm._BLOCKED.clear()
    def _post_all_dead(url, **kw):
        if "deepseek" in url: return _Resp(402)
        raise llm.requests.exceptions.ConnectionError("nope")
    llm.requests.post = _post_all_dead
    try:
        llm.chat_json("s", "u"); blocked_raised = False
    except llm.BackendBlockedError: blocked_raised = True
    check("E2 只有全链引擎级失败才熔断整轮", blocked_raised)

    llm._BLOCKED.clear()
    llm.requests.post = lambda url, **kw: (_Resp(402) if "deepseek" in url
                                           else _Resp(200, {"message": {"content": "这不是 JSON"}}))
    try:
        llm.chat_json("s", "u"); kind = "no-raise"
    except llm.BackendBlockedError: kind = "blocked"
    except Exception: kind = "content"
    check("E3 模型答了但 JSON 坏 → 只败该模块,不熔断整轮", kind == "content")

    # OpenAI 欠费也回 429。报成"请求限流"会让她以为等等就好,其实是要充值
    class _R429:
        status_code = 429
        text = '{"error":{"code":"insufficient_quota"}}'
        def raise_for_status(self): pass
        def json(self): return {}
    llm._BLOCKED.clear()
    llm.requests.post = lambda *a, **kw: _R429()
    try:
        llm._oai_chat("OpenAI", "http://x", "DEEPSEEK_API_KEY", "m", "s", "u"); msg = ""
    except llm.BackendBlockedError as e:
        msg = str(e)
    check("E3 429+insufficient_quota 报成额度不足而非限流", "额度不足" in msg)
finally:
    llm.requests.post, llm.requests.get = saved_post, saved_get
    llm._BLOCKED.clear()
    _restore_env(saved_env)
check("F10 generate 有降级不改生成时间分支", 'latest 内容与生成时间保持不变' in gsrc)
html_src = open(os.path.join(ROOT, "docs", "index.html"), encoding="utf-8").read()
check("F10 前端展示降级横幅", 'generation_status==="degraded"' in html_src)
saved_generate = {
    "DATA": generate.DATA, "ARCH": generate.ARCH, "pick_backend": generate.llm.pick_backend,
    "do_ai": generate.do_ai, "HASHES": generate.HASHES,
}
source_names = ["fetch_ai", "fetch_libraries", "fetch_cn_library", "fetch_cn_library_official",
                "fetch_sports", "fetch_github", "fetch_hot"]
saved_sources = {name: getattr(generate.sources, name) for name in source_names}
try:
    with tempfile.TemporaryDirectory() as td:
        generate.DATA = generate.pathlib.Path(td) / "data"
        generate.ARCH = generate.DATA / "archive"
        generate.DATA.mkdir(parents=True)
        generate.HASHES = generate.pathlib.Path(td) / "srchash.json"   # 别碰真实的指纹缓存
        old_doc = {"generated_at": "2026-07-21T20:00:00+08:00", "date": "2026-07-21",
                   "engine": "deepseek:deepseek-chat", "modules": {"ai": {"items": [{"id": 1}]}}}
        open(generate.DATA / "latest.json", "w", encoding="utf-8").write(json.dumps(old_doc))
        generate.llm.pick_backend = lambda: ("deepseek", "deepseek-chat")
        generate.sources.fetch_ai = lambda: [{"title": "x"}]
        generate.sources.fetch_libraries = lambda: [{"title": "x"}]
        generate.sources.fetch_cn_library = lambda: []
        generate.sources.fetch_cn_library_official = lambda: []
        generate.sources.fetch_sports = lambda: {"综合": [{"title": "x"}]}
        generate.sources.fetch_github = lambda: [{"title": "x"}]
        generate.sources.fetch_hot = lambda: {"中国": [{"title": "x"}]}
        ai_calls = []
        def _block(*args):
            ai_calls.append(1)
            raise llm.BackendBlockedError("DeepSeek 额度不足(HTTP 402)，本轮后续 AI 请求已熔断")
        generate.do_ai = _block
        generate.main()
        after = json.load(open(generate.DATA / "latest.json", encoding="utf-8"))
        check("F10 熔断后不再调用后续模块", len(ai_calls) == 1)
        check("F10 全部降级时保留旧内容与生成时间", after["generated_at"] == old_doc["generated_at"]
              and after["modules"] == old_doc["modules"] and after["generation_status"] == "degraded")
finally:
    generate.DATA = saved_generate["DATA"]
    generate.ARCH = saved_generate["ARCH"]
    generate.llm.pick_backend = saved_generate["pick_backend"]
    generate.do_ai = saved_generate["do_ai"]
    generate.HASHES = saved_generate["HASHES"]
    for name, fn in saved_sources.items(): setattr(generate.sources, name, fn)

# ---------- E9 残骸打捞:本地小模型的长 JSON 会说到一半断掉 ----------
_trunc = '{"items":[{"t":"甲","u":"https://a"},{"t":"乙","u":"https://b"},{"t":"丙","u":"htt'
check("E9 截断的 JSON 捞回完整部分", llm._extract(_trunc)["items"] == [
    {"t": "甲", "u": "https://a"}, {"t": "乙", "u": "https://b"}])
check("E9 完好 JSON 原样返回", llm._extract('{"items":[{"a":1}]}') == {"items": [{"a": 1}]})
# 模型多说一个对象时,旧的贪婪正则会把 {甲}{乙} 抓成一坨非法 JSON,整批条目全废
check("E9 模型多说一个对象不影响第一个",
      llm._extract('{"items":[{"t":1},{"t":2},{"t":3}]}\n{"note":"多说的"}')["items"] ==
      [{"t": 1}, {"t": 2}, {"t": 3}])
check("E9 前后带解说文字也能取到",
      llm._extract('好的，结果如下：\n{"items":[{"t":1}]}\n希望有帮助') == {"items": [{"t": 1}]})
check("E9 字符串里的转义引号与花括号不误判",
      len(llm._extract('{"items":[{"t":"他说\\"} 好\\"","u":1},{"t":"半')["items"]) == 1)
try:
    llm._extract('{"items":[{"t":"半'); _salvaged_bad = False
except ValueError:
    _salvaged_bad = True
check("E9 实在没救时如实报错(不静默返回空)", _salvaged_bad)
_llm_src = open(os.path.join(PIPE, "llm.py"), encoding="utf-8").read()
check("E9 本地引擎上下文已放宽到 32k", "INTEL_LOCAL_CTX" in _llm_src and '"32768"' in _llm_src)
# format 传字符串"json"对 9B 没约束力(实测长输出必崩);传 schema 才启用语法约束
check("E9 本地引擎用 schema 而非字符串 json 约束输出",
      '"format": schema or {"type": "object"}' in _llm_src and '"format": "json"' not in _llm_src)
# 只约束语法不约束形状时,模型会吐 {"items":["字符串",...]} —— 语法完美结构全错,比坏 JSON 更阴
check("E9 items 被约束成对象数组",
      llm.ITEMS_SCHEMA["properties"]["items"]["items"] == {"type": "object"}
      and llm.ITEMS_SCHEMA["required"] == ["items"])
_saved_cj = llm.chat_json
try:
    llm.chat_json = lambda s, u, b=None, log=None, schema=None: {"items": ["糊弄的字符串", {"t": 1}, 42]}
    check("E9 出口再滤一道:非对象条目被丢掉而不是让下游崩",
          generate.chat_items("s", "u", ("ollama", "m"))["items"] == [{"t": 1}])
finally:
    llm.chat_json = _saved_cj

# ---------- E4 素材指纹:没新料就别调 LLM(每小时全量重算 = 云端烧钱 / 本地烧机器) ----------
check("E4 同素材同指纹", generate.fingerprint([{"a": 1}]) == generate.fingerprint([{"a": 1}]))
check("E4 素材一变指纹就变", generate.fingerprint([{"a": 1}]) != generate.fingerprint([{"a": 2}]))
# github 源按 star 排序,星数每次抓都不同 —— 整条目做指纹就永远不命中,等于没缓存
check("E4 易变字段(star/浏览数)不改指纹",
      generate.fingerprint([{"title": "A", "url": "u", "stars": 100}]) ==
      generate.fingerprint([{"title": "A", "url": "u", "stars": 137}]))
check("E4 换了条目指纹必须变",
      generate.fingerprint([{"title": "A", "url": "u"}]) != generate.fingerprint([{"title": "B", "url": "v"}]))
check("E4 嵌套结构(sports 那种 dict of list)同理",
      generate.fingerprint({"足球": [{"title": "T", "url": "u", "views": 1}]}) ==
      generate.fingerprint({"足球": [{"title": "T", "url": "u", "views": 9}]}))
saved_all = {n: getattr(generate, n) for n in
             ["DATA", "ARCH", "HASHES", "do_ai", "do_libraries", "do_sports", "do_github", "do_hot", "do_voices"]}
saved_pick = generate.llm.pick_backend
saved_sources2 = {name: getattr(generate.sources, name) for name in source_names}
try:
    with tempfile.TemporaryDirectory() as td:
        generate.DATA = generate.pathlib.Path(td) / "data"
        generate.ARCH = generate.DATA / "archive"
        generate.HASHES = generate.pathlib.Path(td) / "srchash.json"
        generate.DATA.mkdir(parents=True)
        generate.llm.pick_backend = lambda: ("ollama", "fake-local")
        generate.sources.fetch_ai = lambda: [{"title": "a"}]
        generate.sources.fetch_libraries = lambda: [{"title": "l"}]
        generate.sources.fetch_cn_library = lambda: []
        generate.sources.fetch_cn_library_official = lambda: []
        generate.sources.fetch_sports = lambda: {"综合": [{"title": "s"}]}
        generate.sources.fetch_github = lambda: [{"title": "g"}]
        generate.sources.fetch_hot = lambda: {"中国": [{"title": "h"}]}
        llm_calls = []
        def _fake(name):
            def f(*a, **kw):
                llm_calls.append(name)
                return {"items": [{"title_zh": name, "url": "https://x/" + name, "published": "2026-07-27"}]}
            return f
        for n in ["do_ai", "do_libraries", "do_sports", "do_github", "do_hot", "do_voices"]:
            setattr(generate, n, _fake(n))
        generate.main()
        first = json.load(open(generate.DATA / "latest.json", encoding="utf-8"))
        n_first = len(llm_calls)
        check("E4 首轮正常全量生成", n_first == 6 and first["generation_status"] == "ok")
        check("E4 module_updated 只记真重算过的栏目",
              set(first["module_updated"]) == {"ai", "libraries", "sports", "github", "hot", "voices"})
        llm_calls.clear()
        generate.main()   # 素材一字未变
        second = json.load(open(generate.DATA / "latest.json", encoding="utf-8"))
        check("E4 素材未变时零 LLM 调用", llm_calls == [])
        check("E4 素材未变时不谎报新的生成时间", second["generated_at"] == first["generated_at"])
        generate.sources.fetch_hot = lambda: {"中国": [{"title": "h2"}]}   # 只有热点来了新料
        llm_calls.clear()
        generate.main()
        check("E4 只重算有新料的栏目", llm_calls == ["do_hot"])
finally:
    for n, v in saved_all.items(): setattr(generate, n, v)
    generate.llm.pick_backend = saved_pick
    for name, fn in saved_sources2.items(): setattr(generate.sources, name, fn)

# ---------- E5 时间戳不再互相冒充 ----------
for f in ["merge_breadth.py", "merge_newsec.py", "merge_expand.py",
          "merge_lib_news.py", "merge_enrich.py", "merge_reenrich.py"]:
    s = open(os.path.join(PIPE, f), encoding="utf-8").read()
    check(f"E5 {f} 不再改写整站 generated_at", "data['generated_at']=" not in s and "merged_at" in s)

# ---------- E6 小程序端不再对降级失明 ----------
mini = os.path.join(os.path.dirname(ROOT), "yuanjian-miniapp", "miniprogram", "pages", "index")
if os.path.isdir(mini):
    js = open(os.path.join(mini, "index.js"), encoding="utf-8").read()
    wxml = open(os.path.join(mini, "index.wxml"), encoding="utf-8").read()
    check("E6 小程序消费 generation_status", "generation_status === 'degraded'" in js)
    check("E6 小程序展示逐栏目新鲜度", "tabUpdatedText" in js and "tabUpdatedText" in wxml)

# ---------- E7 ollama 守护能在 launchd 环境里看到 ORICO 上的模型 ----------
plist = os.path.expanduser("~/Library/LaunchAgents/com.kushim.ollama.plist")
if os.path.isfile(plist):
    p = open(plist, encoding="utf-8").read()
    check("E7 守护显式给了 OLLAMA_MODELS(launchd 不读 .zshrc)", "OLLAMA_MODELS" in p and "ai-models/ollama" in p)

# ---------- E8 降级要惊动到人(真跑 alert.sh,不查字符串) ----------
ALERT = os.path.join(ROOT, "scripts", "alert.sh")
check("E8 run_daily 调用了告警", "alert.sh" in open(os.path.join(ROOT, "scripts", "run_daily.sh"), encoding="utf-8").read())
check("E8 generate 写 engine_fallback(内容新但走了兜底)", "engine_fallback" in gsrc)

def _alert(doc, state, force=None):
    j = os.path.join(state, "latest.json")
    open(j, "w", encoding="utf-8").write(json.dumps(doc))
    env = {**os.environ, "PYTHON": sys.executable}
    env.pop("ALERT_FORCE", None)
    if force:
        env["ALERT_FORCE"] = force
    r = subprocess.run(["bash", ALERT, j, state], capture_output=True, text=True, env=env)
    return r.stdout + r.stderr

with tempfile.TemporaryDirectory() as td:
    check("E8 一切正常时不打扰", "无需提醒" in _alert({"generation_status": "ok", "engine_fallback": ""}, td))
    out = _alert({"generation_status": "ok", "engine_fallback": "deepseek 额度不足"}, td)
    check("E8 兜底引擎在用时提醒(内容新但慢)", "正在用兜底引擎" in out)
    check("E8 同一天同一种不重复打扰", "不重复" in _alert({"generation_status": "ok", "engine_fallback": "deepseek 额度不足"}, td))
    out = _alert({"generation_status": "degraded", "generation_error": "三路全挂"}, td)
    check("E8 情况升级为全面降级时会再提醒一次", "情报管线降级" in out)
    check("E8 留了 ALERT.log 兜住通知被系统吞掉",
          os.path.isfile(os.path.join(td, "ALERT.log"))
          and "三路全挂" in open(os.path.join(td, "ALERT.log"), encoding="utf-8").read())
    _alert({"generation_status": "ok", "engine_fallback": ""}, td)
    check("E8 恢复后清状态,再坏还会提醒",
          "情报管线降级" in _alert({"generation_status": "degraded", "generation_error": "又挂了"}, td))
    # 生成脚本硬崩时 latest.json 还停在上一轮的 ok,只读文件什么都看不出来 —— 最该报警的情况不能哑
    check("E8 生成脚本硬崩时也报警(latest 仍显示 ok)",
          "管线异常" in _alert({"generation_status": "ok", "engine_fallback": ""}, td, force="生成脚本异常退出"))
rd2 = open(os.path.join(ROOT, "scripts", "run_daily.sh"), encoding="utf-8").read()
check("E8 set -e 不会在生成崩溃时跳过告警", "GENFAIL=1" in rd2 and "ALERT_FORCE" in rd2)
check("E8 每轮留心跳(launchd 停摆是唯一没人负责发现的失效)", "touch logs/.heartbeat" in rd2)

# ---------- E11 单实例锁:本地一轮可能跑过一小时,而整点任务每小时来一次 ----------
_LOCKSH = '''cd "$1"; LOCK="logs/.run.lock"
if ! mkdir "$LOCK" 2>/dev/null; then
  if [ -n "$(find "$LOCK" -maxdepth 0 -mmin +180 2>/dev/null)" ]; then
    rmdir "$LOCK" 2>/dev/null && mkdir "$LOCK" 2>/dev/null || { echo SKIP; exit 0; }
  else echo BUSY; exit 0; fi
fi
trap 'rmdir "$LOCK" 2>/dev/null' EXIT
echo GOT'''
check("E11 run_daily 用了单实例锁", ".run.lock" in rd2 and "trap 'rmdir" in rd2)
_pod = open(os.path.join(ROOT, "run_podcast_daily.sh"), encoding="utf-8").read()
check("E11 播客任务也有单实例锁(它一轮可能超过一天的预算窗口)",
      ".podcast.lock" in _pod and "trap 'rmdir" in _pod)
with tempfile.TemporaryDirectory() as td:
    os.makedirs(os.path.join(td, "logs"))
    def _lock(): return subprocess.run(["bash", "-c", _LOCKSH, "_", td],
                                       capture_output=True, text=True).stdout.strip()
    check("E11 空闲时拿得到锁", _lock() == "GOT")
    check("E11 用完自动释放", _lock() == "GOT")
    os.makedirs(os.path.join(td, "logs", ".run.lock"))          # 模拟"上一轮还在跑"
    check("E11 有人在跑时跳过本轮", _lock() == "BUSY")
    old = time.time() - 4 * 3600
    os.utime(os.path.join(td, "logs", ".run.lock"), (old, old))  # 模拟陈旧锁
    check("E11 陈旧锁(>3h)自动清掉,不会永久卡死", _lock() == "GOT")

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
