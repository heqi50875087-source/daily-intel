#!/usr/bin/env python3
"""统一 LLM 客户端:多引擎按优先级自动改道,始终返回 JSON。

优先级默认 deepseek → ollama → openai(用 INTEL_ENGINE_ORDER 覆盖)。
任一路被拉黑(额度/鉴权/连不上)就自动降到下一路,全挂才抛 BackendBlockedError。
2026-07-27:此前是"启动时选一次引擎、中途不能改道",DeepSeek 402 后全站冻结 16 天。
"""
import os, re, sys, time, json, requests

OLLAMA = os.environ.get("OLLAMA_HOST", "http://localhost:11434")
DEFAULT_ORDER = ["deepseek", "ollama", "openai"]
# 本进程内已确认不可用的引擎 {kind: 原因};进程结束即忘,下轮重试(她充值后自动复活)
_BLOCKED = {}
# 最后一次真正出活的引擎。改道是静默发生的,不记下来的话日志里"引擎: deepseek"
# 会在实际跑本地时照样写着 deepseek —— 又一个说谎的量具。
last_used = None


def _note(msg, log=None):
    (log or (lambda m: print(m, file=sys.stderr)))(msg)


class BackendBlockedError(RuntimeError):
    """所有引擎都不可用。调用方据此熔断整轮,而非只跳过一个模块。"""


def ollama_models():
    try:
        data = requests.get(f"{OLLAMA}/api/tags", timeout=3).json()
        return [m.get("name", "") for m in data.get("models", [])]
    except Exception:
        return []


def available_backends():
    """按配置顺序列出这台机器上真的能用的引擎,不含已拉黑的。"""
    order = [s.strip() for s in os.environ.get("INTEL_ENGINE_ORDER", "").split(",") if s.strip()]
    out = []
    for kind in (order or DEFAULT_ORDER):
        if kind in _BLOCKED:
            continue
        if kind == "ollama":
            models = ollama_models()
            if models:
                pref = os.environ.get("INTEL_LOCAL_MODEL")
                out.append(("ollama", pref if (pref and pref in models) else models[0]))
        elif kind == "deepseek" and os.environ.get("DEEPSEEK_API_KEY"):
            out.append(("deepseek", os.environ.get("INTEL_CLOUD_MODEL", "deepseek-chat")))
        elif kind == "openai" and os.environ.get("OPENAI_API_KEY"):
            out.append(("openai", os.environ.get("INTEL_OPENAI_MODEL", "gpt-4o-mini")))
    return out


def pick_backend():
    """兼容旧调用:返回链首,只用于日志里报"当前引擎"。真正的改道在 chat_json。"""
    backends = available_backends()
    if not backends:
        raise RuntimeError("无可用引擎:Ollama 无模型、DEEPSEEK_API_KEY / OPENAI_API_KEY 均未配置")
    return backends[0]


def _salvage(s):
    """本地小模型常把长 JSON 说到一半就断。截到最后一个完整的数组元素、补上闭合括号,
    捞回大部分条目 —— 否则 json.loads 全有全无,7KB 里错一个字符就整批丢光。
    只认 {"items":[{…},{…}]} 这一种形状(本仓库所有提示词都是它)。"""
    depth = in_str = esc = 0
    last_complete = -1
    for i, ch in enumerate(s):
        if esc:
            esc = 0; continue
        if ch == "\\":
            esc = 1; continue
        if ch == '"':
            in_str = not in_str; continue
        if in_str:
            continue
        if ch in "{[":
            depth += 1
        elif ch in "}]":
            depth -= 1
            if depth == 2:          # 顶层 { =1, items [ =2, 一个元素 } 收回到 2
                last_complete = i
    if last_complete < 0:
        return None
    try:
        return json.loads(s[:last_complete + 1] + "]}")
    except Exception:
        return None


def _dump_raw(blob, why):
    """模型输出解析失败时把原文留下来。没有原文就只能靠猜,而猜出来的结论最像真结论。"""
    # 自检会拿畸形输入反复调这里,别让它往真实 logs/ 里堆垃圾 —— 测试用 INTEL_DUMP_DIR 改道
    outdir = os.environ.get("INTEL_DUMP_DIR") or \
        os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "logs")
    path = os.path.join(outdir, f"badjson-{time.strftime('%m%d-%H%M%S')}-{os.getpid()}.txt")
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            f.write(f"# {why}\n# 原文 {len(blob)} 字符\n\n{blob}")
        return path
    except Exception:
        return "(落盘失败)"


def _extract(text):
    start = text.find("{")
    if start < 0:
        raise ValueError("未找到 JSON: " + text[:300])
    blob = text[start:]
    try:
        # raw_decode 只吃第一个完整的 JSON 值,后面多出来的东西直接不管。
        # 旧写法是贪婪正则 \{.*\},模型多说一个对象就把 {甲}{乙} 抓成一坨非法 JSON,
        # 整批条目全废 —— 2026-07-27 libraries 11 条只剩 3 条就是栽在这。
        return json.JSONDecoder().raw_decode(blob)[0]
    except json.JSONDecodeError as e:
        rescued = _salvage(blob)
        n = len(rescued.get("items", [])) if rescued else 0
        # 解析一出问题就把原文落盘 —— 无论捞没捞回来。
        # 打捞成功也必须出声:否则"✓ libraries 3"看着像今天新闻少,其实是丢了七八条。
        dump = _dump_raw(blob, f"{e} / 救回 {n} 条")
        if rescued is None:
            _note(f"  ⚠ JSON 无法打捞({e}),原文见 {dump}")
            raise ValueError(f"JSON 不合法且无法打捞({e})") from e
        _note(f"  ⚠ JSON 打捞:原样解析失败({e}),救回 {n} 条,原文见 {dump}")
        return rescued


def _msgs(system, user):
    return ([{"role": "system", "content": system}] if system else []) + [{"role": "user", "content": user}]


def _ollama_chat(model, system, user, schema=None):
    # format 传字符串 "json" 对本地小模型只是"请你输出 JSON",没有约束力
    # ——实测 Ornith-9B 出 10 条以上带长文本的条目时必崩(漏逗号/多说一个对象),整批全废。
    # 传 JSON Schema 才会启用语法约束:实测给 {"required":["zzq"]} 时,即使提示词要求字段叫
    # weekday,模型也只能输出 zzq。
    # 但只给 {"type":"object"} 约的是语法不是形状 —— 实测它会吐 {"items":["字符串",...]},
    # 语法完美结构全错,比坏 JSON 更阴(坏 JSON 当场炸,形状错的会一路流到前端)。所以调用方给 schema。
    ctx = int(os.environ.get("INTEL_LOCAL_CTX", "32768"))
    body = {"model": model, "stream": False, "format": schema or {"type": "object"},
            "options": {"temperature": 0.3, "num_ctx": ctx}, "messages": _msgs(system, user)}
    try:
        r = requests.post(f"{OLLAMA}/api/chat", json=body, timeout=900)
    except requests.exceptions.RequestException as e:
        raise BackendBlockedError(f"Ollama 连不上({e.__class__.__name__});服务未启动?")
    r.raise_for_status()
    return r.json()["message"]["content"]


# 额度/鉴权类错误 = 这一路本轮彻底不可用,拉黑以免每个模块都白撞一次
_BLOCKING_HTTP = {401: "密钥无效", 402: "额度不足", 403: "访问被拒绝", 429: "请求限流"}


def _oai_chat(kind, url, key_env, model, system, user):
    """DeepSeek 与 OpenAI 都是 OpenAI 兼容接口,共用一份实现。"""
    body = {"model": model, "temperature": 0.3,
            "response_format": {"type": "json_object"}, "messages": _msgs(system, user)}
    try:
        r = requests.post(url,
                          headers={"Authorization": f"Bearer {os.environ[key_env]}",
                                   "Content-Type": "application/json"},
                          json=body, timeout=240)
    except requests.exceptions.RequestException as e:
        raise BackendBlockedError(f"{kind} 网络不可达({e.__class__.__name__})")
    if r.status_code in _BLOCKING_HTTP:
        why = _BLOCKING_HTTP[r.status_code]
        # OpenAI 欠费也回 429。报成"请求限流"会让她以为等等就好,其实要充值 —— 差别很大。
        if r.status_code == 429 and "insufficient_quota" in r.text:
            why = "额度不足"
        raise BackendBlockedError(f"{kind} {why}(HTTP {r.status_code})")
    r.raise_for_status()
    return r.json()["choices"][0]["message"]["content"]


# 本仓库绝大多数提示词都要 {"items":[{...}]}:显式约束住"对象数组",
# 否则模型会用字符串数组糊弄过去(语法合法、结构错)。
ITEMS_SCHEMA = {"type": "object",
                "properties": {"items": {"type": "array", "items": {"type": "object"}}},
                "required": ["items"]}

_CHAT = {
    "ollama": _ollama_chat,
    "deepseek": lambda m, s, u: _oai_chat("DeepSeek", "https://api.deepseek.com/chat/completions",
                                          "DEEPSEEK_API_KEY", m, s, u),
    "openai": lambda m, s, u: _oai_chat("OpenAI", "https://api.openai.com/v1/chat/completions",
                                        "OPENAI_API_KEY", m, s, u),
}


def chat_json(system, user, backend=None, log=None, schema=None):
    """按引擎链依次尝试,首个成功即返回。

    backend 若给定则排到链首(兼容 generate.py 那种"开局选一次"的调用方)。
    区分两类失败:引擎级(拉黑并改道)与内容级(模型答了但 JSON 不合法)。
    全链引擎级失败 → BackendBlockedError(调用方熔断整轮);
    否则抛最后一个内容级错误 → 调用方只跳过这一个模块,其余照常。
    """
    chain = available_backends()
    if backend and backend[0] not in _BLOCKED:
        chain = [tuple(backend)] + [b for b in chain if b[0] != backend[0]]
    if not chain:
        raise BackendBlockedError("全部引擎不可用 · " + " | ".join(f"{k}:{v}" for k, v in _BLOCKED.items()))
    global last_used
    content_err = None
    for kind, model in chain:
        try:
            out = _extract(_CHAT[kind](model, system, user, schema) if kind == "ollama"
                           else _CHAT[kind](model, system, user))
            if last_used != f"{kind}:{model}":
                _note(f"  → 本次由 {kind}:{model} 出活", log)
            last_used = f"{kind}:{model}"
            return out
        except BackendBlockedError as e:
            _BLOCKED[kind] = str(e)
            _note(f"  ⚠ {kind} 不可用({e}),改道下一路", log)
        except Exception as e:
            content_err = e
            _note(f"  ⚠ {kind} 返回不可用({e.__class__.__name__}),改道下一路", log)
    if content_err:
        raise content_err
    raise BackendBlockedError("全部引擎不可用 · " + " | ".join(f"{k}:{v}" for k, v in _BLOCKED.items()))


if __name__ == "__main__":
    print("可用引擎链:", available_backends())
    out = chat_json("只返回 JSON。", '用 JSON 回我:{"ok":true,"msg":"中文一句问候"}', log=print)
    print("自检:", out)
