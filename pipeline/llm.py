#!/usr/bin/env python3
"""统一 LLM 客户端:本地 Ollama 优先, 云端(DeepSeek, OpenAI 兼容) 兜底。始终返回 JSON。"""
import os, re, json, requests

OLLAMA = os.environ.get("OLLAMA_HOST", "http://localhost:11434")

def ollama_models():
    try:
        data = requests.get(f"{OLLAMA}/api/tags", timeout=3).json()
        return [m.get("name", "") for m in data.get("models", [])]
    except Exception:
        return []

def pick_backend():
    """本地为主:有 ollama 模型就用;否则用 DeepSeek 兜底。"""
    pref = os.environ.get("INTEL_LOCAL_MODEL")
    models = ollama_models()
    if models:
        return ("ollama", pref if (pref and pref in models) else models[0])
    if os.environ.get("DEEPSEEK_API_KEY"):
        return ("deepseek", os.environ.get("INTEL_CLOUD_MODEL", "deepseek-chat"))
    raise RuntimeError("无可用引擎:既无本地 Ollama 模型, 也无 DEEPSEEK_API_KEY")

def _extract(text):
    m = re.search(r"\{.*\}", text, re.S)
    if not m:
        raise ValueError("未找到 JSON: " + text[:300])
    return json.loads(m.group(0))

def _ollama_chat(model, system, user):
    msgs = ([{"role": "system", "content": system}] if system else []) + [{"role": "user", "content": user}]
    body = {"model": model, "stream": False, "format": "json",
            "options": {"temperature": 0.3, "num_ctx": 16384}, "messages": msgs}
    r = requests.post(f"{OLLAMA}/api/chat", json=body, timeout=900)
    r.raise_for_status()
    return r.json()["message"]["content"]

def _deepseek_chat(model, system, user):
    key = os.environ["DEEPSEEK_API_KEY"]
    msgs = ([{"role": "system", "content": system}] if system else []) + [{"role": "user", "content": user}]
    body = {"model": model, "temperature": 0.3, "response_format": {"type": "json_object"}, "messages": msgs}
    r = requests.post("https://api.deepseek.com/chat/completions",
                      headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
                      json=body, timeout=240)
    r.raise_for_status()
    return r.json()["choices"][0]["message"]["content"]

def chat_json(system, user, backend=None):
    kind, model = backend or pick_backend()
    text = _ollama_chat(model, system, user) if kind == "ollama" else _deepseek_chat(model, system, user)
    return _extract(text)

if __name__ == "__main__":
    b = pick_backend()
    print("当前引擎:", b)
    out = chat_json("只返回 JSON。", '用 JSON 回我:{"ok":true,"msg":"中文一句问候"}', backend=b)
    print("自检:", out)
