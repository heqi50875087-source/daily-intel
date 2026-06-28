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
            '"source":"来源","region":"美国/全球等(据内容判断)","published":"YYYY-MM-DD","tags":["中文标签"],"url":"必须用给定的原链接","overview":"详尽概述3-5句(基于事实,信息密度高)","analysis":"分析2-3句(有观点有洞察)","social":[{"who":"视角标签如研究者/工程师/投资人,不要真人姓名","text":"1-2句评论"}]}]}'
            "\n\n数据:\n" + json.dumps(raw[:30], ensure_ascii=False))
    return {"items": llm.chat_json(SYS, user, backend).get("items", [])}

def do_libraries(global_raw, cn_raw, backend):
    user = ("有两组图书馆资讯:GLOBAL(英文,全球/欧美) 与 CHINA(中文,中国本土)。"
            "请共选 10-12 条,其中至少 5 条来自 CHINA(region 设为'中国',侧重国内讲座/论坛/征集/培训/通知等动态),其余来自 GLOBAL。为每条写中文。"
            "scope 用 public(公共) 或 academic(高校);published 用 YYYY-MM-DD(没有留空)。严格 JSON:"
            '{"items":[{"title_zh":"中文标题","eng":"原标题(中文源可留空)","summary":"1-2句中文摘要","source":"来源",'
            '"region":"全球/美国/中国等","scope":"public或academic","published":"","url":"原链接","overview":"详尽概述3-5句(基于事实)","analysis":"对上海少儿馆的借鉴2-3句","social":[{"who":"视角如馆员/研究者/读者","text":"1-2句评论"}]}]}'
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

SPORTS_SYS = ("你是资深中文体育编辑。只输出合法 JSON,不要任何解释或 markdown 代码块。"
              "硬约束:只用我给的事实,绝不编造比分、赛果或不存在的赛事;不确定就不写。")

def do_sports(raw_by_sub, backend):
    """体育:按子类分别让模型选材+中文富化(overview/analysis/social)。region 强制为子类名。"""
    items_all = []
    for sub, raw in raw_by_sub.items():
        if not raw:
            continue
        n = 8 if sub == "综合" else (6 if sub.startswith("足球") else 4)
        user = (f"下面是「{sub}」的真实体育资讯(JSON 数组,英文为主)。挑选最新、最重要的 {n} 条"
                "(去重;舍弃纯八卦/转会传闻/付费墙预告),为每条写中文。严格按此 JSON 返回:"
                '{"items":[{"title_zh":"中文标题","eng":"原英文标题","summary":"1-2句中文摘要(自己的话)",'
                '"source":"来源","published":"YYYY-MM-DD","url":"必须用给定的原链接",'
                '"overview":"详尽概述3-5句(基于事实,信息密度高,但不编造比分)",'
                '"analysis":"看点/分析2-3句(有观点)",'
                '"social":[{"who":"视角标签如资深球迷/解说/教练,不要真人姓名","text":"1-2句评论"}]}]}'
                "\n\n数据:\n" + json.dumps(raw[:30], ensure_ascii=False))
        try:
            out = llm.chat_json(SPORTS_SYS, user, backend)
            for it in out.get("items", []):
                it["region"] = sub
            items_all += out.get("items", [])
        except Exception as e:
            log("  · 体育子类失败", sub, e)
    return {"items": items_all, "regions": list(raw_by_sub.keys())}

def do_github(raw, backend):
    user = ("下面是 GitHub 最近的高星新项目(JSON,含 stars/lang)。挑选 10-12 个最有价值的"
            "(侧重 AI/开发工具/应用/学习资源;跳过纯攻击性安全工具与灰产),为每个写中文。严格 JSON:"
            '{"items":[{"title_zh":"中文名或一句话定位","eng":"仓库名(原样)","summary":"1-2句中文(解决什么)",'
            '"source":"GitHub","stars":数字原样,"lang":"语言原样","published":"YYYY-MM-DD原样","url":"原链接",'
            '"overview":"介绍3-5句(功能/亮点)","analysis":"为何值得关注2-3句",'
            '"social":[{"who":"视角如开发者/研究者","text":"1-2句评论"}]}]}'
            "\n\n数据:\n" + json.dumps(raw[:15], ensure_ascii=False))
    return {"items": llm.chat_json(SYS, user, backend).get("items", [])}

def do_hot(raw_by_region, backend):
    flat = [dict(it, _region=region) for region, items in raw_by_region.items() for it in items]
    user = ("下面是实时热点资讯(JSON,_region 是 中国/国外)。挑选 12-15 条最重要的,去重,为每条写中文。"
            "region 用其 _region。严格 JSON:"
            '{"items":[{"title_zh":"中文标题","summary":"1-2句中文摘要","source":"来源","region":"中国或国外",'
            '"published":"YYYY-MM-DD","url":"原链接","overview":"概述3-5句","analysis":"看点2-3句",'
            '"social":[{"who":"视角","text":"1-2句"}]}]}'
            "\n\n数据:\n" + json.dumps(flat[:40], ensure_ascii=False))
    out = llm.chat_json(SYS, user, backend)
    items = out.get("items", [])
    return {"items": items, "regions": sorted({i.get("region") for i in items if i.get("region")})}

def main():
    load_env()
    backend = llm.pick_backend()
    log("引擎:", backend)
    DATA.mkdir(parents=True, exist_ok=True); ARCH.mkdir(parents=True, exist_ok=True)
    log("抓取数据源…")
    ai_raw = sources.fetch_ai(); lib_raw = sources.fetch_libraries()
    cn_raw = sources.fetch_cn_library() + sources.fetch_cn_library_official()
    sports_raw = sources.fetch_sports()
    gh_raw = sources.fetch_github()
    hot_raw = sources.fetch_hot()
    log(f"原始: AI {len(ai_raw)} / 图书馆 {len(lib_raw)}(+中国 {len(cn_raw)})"
        f" / 体育 {sum(len(v) for v in sports_raw.values())}"
        f" / GitHub {len(gh_raw)} / 热点 {sum(len(v) for v in hot_raw.values())}")
    mods = {}
    for key, fn in [("ai", lambda: do_ai(ai_raw, backend)),
                    ("libraries", lambda: do_libraries(lib_raw, cn_raw, backend)),
                    ("sports", lambda: do_sports(sports_raw, backend)),
                    ("github", lambda: do_github(gh_raw, backend)),
                    ("hot", lambda: do_hot(hot_raw, backend))]:
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
            merged = fresh + enr
            merged.sort(key=lambda i: i.get("published", ""), reverse=True)
            mods[k]["items"] = merged[:cap]
            if old.get(k, {}).get("regions"): mods[k]["regions"] = old[k]["regions"]
            log("· 保留加工", k, len(enr), "+新", len(fresh))
    # github/hot 无每日源,始终沿用上次; ai/libraries/voices/podcasts 生成失败时也沿用
    for k in ["ai", "libraries", "sports", "voices", "github", "hot"]:
        if not mods.get(k):
            mods[k] = old.get(k, {"items": []}); log("· 沿用上次", k)
    # 时间窗口:只保留当月+上月(滚动),清掉更早旧闻;无日期条目(如人物)不动
    cutoff = (datetime.date.today().replace(day=1) - datetime.timedelta(days=1)).replace(day=1).isoformat()
    for k in ["ai", "libraries", "sports", "github", "hot"]:
        if mods.get(k) and mods[k].get("items"):
            kept = [it for it in mods[k]["items"]
                    if not (it.get("published") or "").strip() or (it.get("published") or "").strip() >= cutoff]
            if len(kept) != len(mods[k]["items"]):
                log(f"· 时间窗口 {k}: {len(mods[k]['items'])}→{len(kept)} (留≥{cutoff})")
                mods[k]["items"] = kept
    now = datetime.datetime.now().astimezone()
    out = {"generated_at": now.isoformat(timespec="seconds"), "date": now.strftime("%Y-%m-%d"),
           "engine": f"{backend[0]}:{backend[1]}", "modules": mods}
    (DATA / "latest.json").write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    (ARCH / f"{out['date']}.json").write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    log("✅ 写入完成", out["date"], "| 引擎", out["engine"])

if __name__ == "__main__":
    main()
