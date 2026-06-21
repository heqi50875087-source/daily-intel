#!/usr/bin/env python3
"""把播客英文转写翻成完整中文稿(长稿自动分段翻译)。复用 .env 的 DeepSeek。"""
import os, sys, json, re, requests

def translate(text):
    key = os.environ["DEEPSEEK_API_KEY"]
    sysp = ("你是专业中英翻译。把下面这段英文播客转写翻成流畅自然的简体中文,"
            "忠实原意、不遗漏、不加评论;口语适当顺滑成书面中文。只输出中文译文。")
    body = {"model": "deepseek-chat", "temperature": 0.3,
            "messages": [{"role": "system", "content": sysp}, {"role": "user", "content": text}]}
    r = requests.post("https://api.deepseek.com/chat/completions",
                      headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
                      json=body, timeout=240)
    r.raise_for_status()
    return r.json()["choices"][0]["message"]["content"].strip()

def split_text(t, size=3500):
    sents = re.split(r'(?<=[.!?])\s+', t)
    chunks, cur = [], ""
    for s in sents:
        if len(cur) + len(s) > size and cur:
            chunks.append(cur); cur = s
        else:
            cur = (cur + " " + s).strip()
    if cur: chunks.append(cur)
    return chunks

if __name__ == "__main__":
    path = sys.argv[1] if len(sys.argv) > 1 else "podcast_work/ep.json"
    d = json.load(open(path))
    chunks = split_text(d.get("en", ""))
    print(f"分 {len(chunks)} 段翻译...", file=sys.stderr)
    parts = []
    for i, c in enumerate(chunks):
        print(f"  第 {i+1}/{len(chunks)} 段...", file=sys.stderr)
        parts.append(translate(c))
    zh_full = "\n\n".join(parts)
    d["zh_full"] = zh_full
    json.dump(d, open(path, "w"), ensure_ascii=False, indent=2)
    print(f"[完整中文稿 {len(zh_full)} 字]\n", file=sys.stderr)
    print(zh_full[:900])
