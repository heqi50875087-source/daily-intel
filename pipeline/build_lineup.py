#!/usr/bin/env python3
"""远音 35 档精选名单 → 解析订阅源 → 写 shows.json + voice_map.json。
- 全球热门、**有公开RSS可下载完整音频**;排除 Spotify/YouTube 独占(如 Joe Rogan)。
- 已有的 22 档复用旧 feed(保留与已生成单集的关联);13 档新增用 iTunes Search 解析。
- 走 GreenHub 代理 18080。
配音音色(edge-tts):F1/F2 女, M1清亮/M2浑厚/M3播音 男。"""
import json, sys, os, time, urllib.parse, requests, difflib

PROXY = {'http': 'http://127.0.0.1:18080', 'https': 'http://127.0.0.1:18080'}
F1="zh-CN-XiaoxiaoNeural"; F2="zh-CN-XiaoyiNeural"
M1="zh-CN-YunxiNeural"; M2="zh-CN-YunjianNeural"; M3="zh-CN-YunyangNeural"

# (英文名, 中文大类, 配音模式 solo/duo/panel, [音色轮换])
# 前 22 档用与旧 shows.json 完全一致的名字(复用 feed + 保留已生成单集关联)
LINEUP = [
 # —— 思想 · 名人对话(10)——
 ("Lex Fridman Podcast", "思想 · 名人对话", "duo", [M2, M1]),
 ("The Tim Ferriss Show", "思想 · 名人对话", "duo", [M1, M2]),
 ("Huberman Lab", "思想 · 名人对话", "solo", [M3]),
 ("The Diary Of A CEO with Steven Bartlett", "思想 · 名人对话", "duo", [M1, F1]),
 ("Modern Wisdom", "思想 · 名人对话", "duo", [M1, M2]),
 ("The Knowledge Project", "思想 · 名人对话", "duo", [M2, M1]),
 ("On Purpose with Jay Shetty", "思想 · 名人对话", "duo", [M1, F1]),
 ("The School of Greatness", "思想 · 名人对话", "duo", [M1, M2]),
 ("Making Sense with Sam Harris", "思想 · 名人对话", "solo", [M3]),
 ("Naval", "思想 · 名人对话", "solo", [M1]),
 # —— 科技 · AI(7)——
 ("The AI Daily Brief: Artificial Intelligence News and Analysis", "科技 · AI", "solo", [M1]),
 ("Hard Fork", "科技 · AI", "duo", [M1, M3]),
 ("The a16z Show", "科技 · AI", "duo", [M1, M2]),
 ("Latent Space: The AI Engineer Podcast", "科技 · AI", "duo", [M1, M2]),
 ("The TWIML AI Podcast (formerly This Week in Machine Learning & Artificial Intelligence)", "科技 · AI", "duo", [M1, M2]),
 ("Decoder with Nilay Patel", "科技 · AI", "duo", [M1, M2]),
 ("Lenny's Podcast: Product | Growth | Career", "科技 · AI", "duo", [M1, M2]),
 # —— 商业 · 创业 · 投资(6)——
 ("How I Built This with Guy Raz", "商业 · 创业 · 投资", "duo", [M1, F1]),
 ("Masters of Scale", "商业 · 创业 · 投资", "duo", [M2, F1]),
 ("Acquired", "商业 · 创业 · 投资", "duo", [M1, M2]),
 ("All-In with Chamath, Jason, Sacks & Friedberg", "商业 · 创业 · 投资", "panel", [M1, M2, M3]),
 ("We Study Billionaires - The Investor’s Podcast Network", "商业 · 创业 · 投资", "duo", [M1, M2]),
 ("Founders", "商业 · 创业 · 投资", "solo", [M2]),
 # —— 科学 · 健康 · 心理(6)——
 ("Radiolab", "科学 · 健康 · 心理", "duo", [M1, F1]),
 ("Hidden Brain", "科学 · 健康 · 心理", "solo", [M3]),
 ("Science Vs", "科学 · 健康 · 心理", "solo", [F1]),
 ("Ologies with Alie Ward", "科学 · 健康 · 心理", "duo", [F1, M1]),
 ("Feel Better, Live More with Dr Rangan Chatterjee", "科学 · 健康 · 心理", "duo", [M1, M2]),
 ("The Rich Roll Podcast", "科学 · 健康 · 心理", "duo", [M2, M1]),
 # —— 文化 · 故事 · 新闻(6)——
 ("This American Life", "文化 · 故事 · 新闻", "solo", [M3]),
 ("99% Invisible", "文化 · 故事 · 新闻", "solo", [M1]),
 ("Stuff You Should Know", "文化 · 故事 · 新闻", "duo", [M1, M2]),
 ("Revisionist History", "文化 · 故事 · 新闻", "solo", [M2]),
 ("The Daily", "文化 · 故事 · 新闻", "duo", [M1, F1]),
 ("Planet Money", "文化 · 故事 · 新闻", "duo", [M1, F1]),
]

def itunes(name):
    url = "https://itunes.apple.com/search?" + urllib.parse.urlencode(
        {"term": name, "media": "podcast", "entity": "podcast", "limit": 8})
    r = requests.get(url, timeout=20, proxies=PROXY); r.raise_for_status()
    res = r.json().get("results", [])
    if not res: return None
    best = max(res, key=lambda x: difflib.SequenceMatcher(
        None, name.lower(), (x.get("collectionName", "")).lower()).ratio())
    return best

def main():
    old = {}
    try:
        for s in json.load(open("docs/data/shows.json")): old[s["name"]] = s
    except Exception: pass
    shows = []; vmap = {}; resolved = 0; reused = 0
    for name, cat, mode, voices in LINEUP:
        entry = None
        if name in old and old[name].get("feedUrl"):           # 复用已有 feed,保留单集关联
            entry = {**old[name], "category": cat}; reused += 1
        else:
            try:
                b = itunes(name)
                if b and b.get("feedUrl"):
                    entry = {"name": b.get("collectionName", name), "category": cat,
                             "feedUrl": b["feedUrl"], "author": b.get("artistName", ""),
                             "artwork": b.get("artworkUrl600") or b.get("artworkUrl100", "")}
                    resolved += 1
                    time.sleep(0.3)
            except Exception as e:
                print(f"  iTunes失败 {name[:30]}: {str(e)[:40]}", file=sys.stderr)
        if not entry:
            entry = {"name": name, "category": cat, "feedUrl": "", "author": "", "artwork": ""}
        shows.append(entry)
        vmap[entry["name"]] = [mode, voices]
        print(f"  {'复用' if name in old else '解析'} {entry['name'][:38]:38} feed={'✓' if entry['feedUrl'] else '✗缺'}", file=sys.stderr)
    json.dump(shows, open("docs/data/shows.json", "w"), ensure_ascii=False, indent=2)
    json.dump(vmap, open("docs/data/voice_map.json", "w"), ensure_ascii=False, indent=2)
    os.makedirs("pipeline/podcast_work", exist_ok=True)
    json.dump(shows, open("pipeline/podcast_work/shows.json", "w"), ensure_ascii=False, indent=2)
    print(f"[完成] {len(shows)} 档 | 复用 {reused} | iTunes解析 {resolved} | 缺feed {sum(1 for s in shows if not s['feedUrl'])}", file=sys.stderr)

if __name__ == "__main__":
    main()
