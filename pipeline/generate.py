#!/usr/bin/env python3
"""每日情报编排器
抓真实数据(RSS + Apple Podcasts) -> 模型做中文摘要/筛选 -> docs/data/latest.json
引擎:本地 Ollama 优先, DeepSeek 兜底(见 llm.pick_backend)。某模块失败则沿用上次,保证不空。
"""
import os, json, sys, time, pathlib, datetime
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import sources, llm

ROOT = pathlib.Path(__file__).resolve().parent.parent
DATA = ROOT / "docs" / "data"
ARCH = DATA / "archive"
SYS = "你是严谨的中文资讯编辑。只输出合法 JSON,不要任何解释或 markdown 代码块。"

def log(*a): print(time.strftime("%H:%M:%S"), *a, file=sys.stderr)

def load_env():
    f = ROOT / "pipeline" / ".env"
    if f.exists():
        for ln in f.read_text(encoding="utf-8").splitlines():
            ln = ln.strip()
            if ln and not ln.startswith("#") and "=" in ln:
                k, v = ln.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip())

def do_ai(raw, backend):
    user = ("下面是抓取到的英文 AI 资讯(JSON 数组)。挑选最重要、最新、信息量最大的 7 条"
            "(去重;舍弃招聘/纯营销/促销),为每条写中文。严格按此 JSON 返回:"
            '{"items":[{"title_zh":"中文标题","eng":"原英文标题","summary":"1-2句中文摘要(用你自己的话)",'
            '"source":"来源","region":"美国/全球等(据内容判断)","published":"YYYY-MM-DD","tags":["中文标签"],"url":"必须用给定的原链接"}]}'
            "\n\n数据:\n" + json.dumps(raw[:30], ensure_ascii=False))
    return {"items": llm.chat_json(SYS, user, backend).get("items", [])}

def do_libraries(global_raw, cn_raw, backend):
    user = ("有两组图书馆资讯:GLOBAL(英文,全球/欧美) 与 CHINA(中文,中国本土)。"
            "请共选 8-9 条,其中至少 3 条来自 CHINA(region 设为'中国'),其余来自 GLOBAL。为每条写中文。"
            "scope 用 public(公共) 或 academic(高校);published 用 YYYY-MM-DD(没有留空)。严格 JSON:"
            '{"items":[{"title_zh":"中文标题","eng":"原标题(中文源可留空)","summary":"1-2句中文摘要","source":"来源",'
            '"region":"全球/美国/中国等","scope":"public或academic","published":"","url":"原链接"}]}'
            "\n\nGLOBAL:\n" + json.dumps(global_raw[:18], ensure_ascii=False)
            + "\n\nCHINA:\n" + json.dumps(cn_raw[:10], ensure_ascii=False))
    out = llm.chat_json(SYS, user, backend)
    items = out.get("items", [])
    return {"items": items, "regions": sorted({i.get("region") for i in items if i.get("region")})}

def do_podcasts(raw, backend):
    flat = [{"podcast": p["podcast"], "host": p["host"], "region": zh, "url": p["url"]}
            for zh, lst in raw.items() for p in lst]
    user = ("下面是各地区真实播客(JSON)。为每个补 title(一句中文定位)、summary(1句中文,大体在聊什么)、"
            "topics(2-3个中文标签),保持 podcast/host/region/url 原样。严格 JSON:"
            '{"items":[{"podcast":"","title":"","summary":"","region":"","host":"","topics":[],"url":""}]}'
            "\n\n数据:\n" + json.dumps(flat, ensure_ascii=False))
    items = llm.chat_json(SYS, user, backend).get("items", flat)
    return {"regions": list(raw.keys()), "items": items}

def do_voices(ai_items, lib_items, backend):
    ctx = [{"t": i.get("title_zh"), "s": i.get("source")} for i in (ai_items + lib_items)][:20]
    user = ("参考近期 AI 与图书馆动态(下方),列出 6-7 位当前有影响力的代表人物(AI/播客/图书馆领域,覆盖不同地区),"
            "给出其近期关注方向(中文概括即可,不要编造具体新闻)。严格 JSON:"
            '{"items":[{"name":"姓名","role":"身份","region":"地区","domain":"ai/podcast/library",'
            '"recent":"近期关注(1句中文)","url":"主页或社媒;不确定就留空字符串"}]}'
            "\n\n参考:\n" + json.dumps(ctx, ensure_ascii=False))
    return {"items": llm.chat_json(SYS, user, backend).get("items", [])}

def main():
    load_env()
    backend = llm.pick_backend()
    log("引擎:", backend)
    DATA.mkdir(parents=True, exist_ok=True); ARCH.mkdir(parents=True, exist_ok=True)
    log("抓取数据源…")
    ai_raw = sources.fetch_ai(); lib_raw = sources.fetch_libraries()
    cn_raw = sources.fetch_cn_library(); pod_raw = sources.fetch_podcasts()
    log(f"原始: AI {len(ai_raw)} / 图书馆 {len(lib_raw)}(+中国 {len(cn_raw)}) / 播客 {sum(len(v) for v in pod_raw.values())}")
    mods = {}
    for key, fn in [("ai", lambda: do_ai(ai_raw, backend)),
                    ("libraries", lambda: do_libraries(lib_raw, cn_raw, backend)),
                    ("podcasts", lambda: do_podcasts(pod_raw, backend))]:
        try:
            mods[key] = fn(); log("✓", key, len(mods[key]["items"]))
        except Exception as e:
            log("✗", key, e); mods[key] = None
    try:
        ai_i = mods["ai"]["items"] if mods.get("ai") else []
        lib_i = mods["libraries"]["items"] if mods.get("libraries") else []
        mods["voices"] = do_voices(ai_i, lib_i, backend); log("✓ voices", len(mods["voices"]["items"]))
    except Exception as e:
        log("✗ voices", e); mods["voices"] = None
    old = {}
    if (DATA / "latest.json").exists():
        try: old = json.load(open(DATA / "latest.json", encoding="utf-8")).get("modules", {})
        except Exception: pass
    # 保护 workflow 深加工产物: 旧条目里带 analysis 的(概述/分析/社媒)优先保留, 新抓取的去重追加
    import re as _re
    def _nu(u): return _re.sub(r"^https?://", "", u or "").rstrip("/").lower().split("?")[0]
    for k in ["ai", "libraries"]:
        enr = [i for i in old.get(k, {}).get("items", []) if i.get("analysis")]
        if enr and mods.get(k) and mods[k].get("items"):
            seen = {_nu(i.get("url", "")) for i in enr}
            fresh = [i for i in mods[k]["items"] if _nu(i.get("url", "")) not in seen]
            cap = 60 if k == "libraries" else 30
            mods[k]["items"] = (enr + fresh)[:cap]
            if old.get(k, {}).get("regions"): mods[k]["regions"] = old[k]["regions"]
            log("· 保留加工", k, len(enr), "+新", len(fresh))
    # github/hot 无每日源,始终沿用上次; ai/libraries/voices/podcasts 生成失败时也沿用
    for k in ["ai", "libraries", "voices", "podcasts", "github", "hot"]:
        if not mods.get(k):
            mods[k] = old.get(k, {"items": []}); log("· 沿用上次", k)
    now = datetime.datetime.now().astimezone()
    out = {"generated_at": now.isoformat(timespec="seconds"), "date": now.strftime("%Y-%m-%d"),
           "engine": f"{backend[0]}:{backend[1]}", "modules": mods}
    (DATA / "latest.json").write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    (ARCH / f"{out['date']}.json").write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    log("✅ 写入完成", out["date"], "| 引擎", out["engine"])

if __name__ == "__main__":
    main()
