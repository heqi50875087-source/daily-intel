#!/usr/bin/env python3
"""每日情报生成
联网汇总 AI / 图书馆 / 关键声音 + Apple Podcasts 各地区播客 -> docs/data/latest.json
依赖: anthropic, requests ; 需要 pipeline/.env 内的 ANTHROPIC_API_KEY
"""
import os, re, json, sys, time, pathlib, datetime
import requests

ROOT = pathlib.Path(__file__).resolve().parent.parent
DATA = ROOT / "docs" / "data"
ARCH = DATA / "archive"
MODEL = os.environ.get("INTEL_MODEL", "claude-sonnet-4-6")  # 可用 INTEL_MODEL 覆盖

PODCAST_REGIONS = [
    ("美国", "US", "artificial intelligence"), ("英国", "GB", "artificial intelligence"),
    ("日本", "JP", "テクノロジー"), ("德国", "DE", "Technologie"),
    ("澳洲", "AU", "technology"), ("新加坡", "SG", "technology"), ("中国", "CN", "科技"),
]

def log(*a): print(time.strftime("%H:%M:%S"), *a, file=sys.stderr)

def load_env():
    f = ROOT / "pipeline" / ".env"
    if f.exists():
        for ln in f.read_text(encoding="utf-8").splitlines():
            ln = ln.strip()
            if ln and not ln.startswith("#") and "=" in ln:
                k, v = ln.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip())

def get_client():
    from anthropic import Anthropic
    key = os.environ.get("ANTHROPIC_API_KEY")
    if not key:
        log("✗ 缺少 ANTHROPIC_API_KEY(写入 pipeline/.env 即生效)")
        sys.exit(2)
    return Anthropic(api_key=key)

def ask_json(cli, prompt, max_tokens=4500):
    msg = cli.messages.create(
        model=MODEL, max_tokens=max_tokens,
        tools=[{"type": "web_search_20250305", "name": "web_search", "max_uses": 6}],
        messages=[{"role": "user", "content": prompt}],
    )
    text = "".join(getattr(b, "text", "") for b in msg.content if b.type == "text")
    m = re.search(r"\{.*\}", text, re.S)
    if not m:
        raise ValueError("模型未返回 JSON")
    return json.loads(m.group(0))

AI_PROMPT = """联网检索过去 24-48 小时全球最重要的 AI 进展(模型发布 / 研究突破 / 重大产品 / 行业大事)，挑选 7 条。
只返回 JSON，不要任何解释或 markdown：
{"items":[{"title_zh":"中文标题","eng":"英文原标题","summary":"1-2句中文摘要","source":"来源名","region":"美国/中国/全球等","published":"YYYY-MM-DD","tags":["标签"],"url":"原文链接"}]}
要求：url 必须真实可点；摘要用你自己的话；覆盖不同来源与地区。"""

LIB_PROMPT = """联网检索图书馆领域近一个月的热点与趋势，挑选 8-9 条，须覆盖两类：
(1) 全球 / 发达国家(IFLA、ALA、Library Journal、C&RL News 等)的公共与高校图书馆动态、AI 应用、政策；
(2) 中国本土(国家图书馆、各省市馆、高校馆、智慧图书馆)的动态。
只返回 JSON：
{"regions":["全球","美国","中国"],"items":[{"title_zh":"中文标题","eng":"原标题(可空)","summary":"1-2句中文摘要","source":"来源","region":"全球/美国/中国等","scope":"public或academic","published":"YYYY-MM","url":"链接"}]}"""

VOICE_PROMPT = """联网了解 AI、播客、图书馆三个领域里各地区有影响力的代表人物近期在讨论什么，挑选 7-8 位。
只返回 JSON：
{"items":[{"name":"姓名","role":"身份","region":"地区","domain":"ai/podcast/library","recent":"近期在讨论什么(1句中文)","url":"主页或社媒"}]}"""

def gen_podcasts(cli):
    raw = {}
    for zh, cc, term in PODCAST_REGIONS:
        try:
            r = requests.get("https://itunes.apple.com/search",
                             params={"term": term, "entity": "podcast", "country": cc, "limit": 4}, timeout=20)
            raw[zh] = [{"podcast": x.get("collectionName"), "host": x.get("artistName"),
                        "genre": x.get("primaryGenreName"), "url": x.get("trackViewUrl")}
                       for x in r.json().get("results", []) if x.get("collectionName")]
        except Exception as e:
            log("播客抓取失败", zh, e); raw[zh] = []
        time.sleep(0.3)
    flat = [{"podcast": p["podcast"], "host": p["host"], "region": zh, "url": p["url"]}
            for zh, lst in raw.items() for p in lst]
    prompt = ("下面是各地区真实播客列表(JSON)。为每个补充 title(一句中文定位)、summary(1句中文，大体在聊什么)、"
              "topics(2-3个中文标签)，保持 podcast/host/region/url 原样。只返回 JSON:{\"items\":[{...}]}。\n"
              + json.dumps(flat, ensure_ascii=False))
    try:
        items = ask_json(cli, prompt, max_tokens=4000)["items"]
    except Exception as e:
        log("播客润色失败，用原始数据", e)
        items = [{**p, "title": "", "summary": "", "topics": []} for p in flat]
    return {"regions": [z for z, _, _ in PODCAST_REGIONS], "items": items}

def main():
    load_env()
    cli = get_client()
    DATA.mkdir(parents=True, exist_ok=True); ARCH.mkdir(parents=True, exist_ok=True)
    mods = {}
    jobs = [("ai", lambda: ask_json(cli, AI_PROMPT)),
            ("libraries", lambda: ask_json(cli, LIB_PROMPT)),
            ("voices", lambda: ask_json(cli, VOICE_PROMPT)),
            ("podcasts", lambda: gen_podcasts(cli))]
    for key, fn in jobs:
        try:
            mods[key] = fn(); log("✓", key, "完成")
        except Exception as e:
            log("✗", key, "失败:", e); mods[key] = None
    # 某模块失败则沿用上次数据，保证页面不空
    old = {}
    if (DATA / "latest.json").exists():
        try: old = json.load(open(DATA / "latest.json", encoding="utf-8")).get("modules", {})
        except Exception: pass
    for k in ["ai", "libraries", "voices", "podcasts"]:
        if not mods.get(k):
            mods[k] = old.get(k, {"items": []}); log("·", k, "沿用上次")
    now = datetime.datetime.now().astimezone()
    out = {"generated_at": now.isoformat(timespec="seconds"),
           "date": now.strftime("%Y-%m-%d"), "modules": mods}
    (DATA / "latest.json").write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    (ARCH / f"{out['date']}.json").write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    log("✅ 已写入 latest.json 与归档", out["date"])

if __name__ == "__main__":
    main()
