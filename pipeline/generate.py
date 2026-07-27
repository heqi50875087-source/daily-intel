#!/usr/bin/env python3
"""每日情报编排器
抓真实数据(RSS + Apple Podcasts) -> 模型做中文摘要/筛选 -> docs/data/latest.json
引擎:本地 Ollama 优先, DeepSeek 兜底(见 llm.pick_backend)。某模块失败则沿用上次,保证不空。
"""
import os, json, sys, time, pathlib, datetime, hashlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import sources, llm
from jsonio import save_json

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

def chat_items(system, user, backend):
    """本仓库的提示词一律要 {"items":[{...}]}。两道网:
    ① 给 ollama 传严格 schema,约束住"对象数组"(只给 {"type":"object"} 时模型会吐字符串数组);
    ② 出口再滤一遍非字典元素 —— 换模型/升级 ollama 后约束可能又静默失效,校验不能省。"""
    out = llm.chat_json(system, user, backend, schema=llm.ITEMS_SCHEMA)
    items = out.get("items")
    if isinstance(items, list):
        good = [i for i in items if isinstance(i, dict)]
        if len(good) != len(items):
            log(f"  ⚠ 丢掉 {len(items) - len(good)} 个不是对象的条目(模型用字符串糊弄了)")
        out["items"] = good
    return out


def do_ai(raw, backend):
    user = ("下面是抓取到的英文 AI 资讯(JSON 数组)。挑选最重要、最新、信息量最大的 7 条"
            "(去重;舍弃招聘/纯营销/促销),为每条写中文。严格按此 JSON 返回:"
            '{"items":[{"title_zh":"中文标题","eng":"原英文标题","summary":"1-2句中文摘要(用你自己的话)",'
            '"source":"来源","region":"美国/全球等(据内容判断)","published":"YYYY-MM-DD","tags":["中文标签"],"url":"必须用给定的原链接","overview":"详尽概述3-5句(基于事实,信息密度高)","analysis":"分析2-3句(有观点有洞察)","social":[{"who":"视角标签如研究者/工程师/投资人,不要真人姓名","text":"1-2句评论"}]}]}'
            "\n\n数据:\n" + json.dumps(raw[:30], ensure_ascii=False))
    return {"items": chat_items(SYS, user, backend).get("items", [])}

def do_libraries(global_raw, cn_raw, backend):
    user = ("有两组图书馆资讯:GLOBAL(英文,全球/欧美) 与 CHINA(中文,中国本土)。"
            "请共选 10-12 条,其中至少 5 条来自 CHINA(region 设为'中国',侧重国内讲座/论坛/征集/培训/通知等动态),其余来自 GLOBAL。为每条写中文。"
            "scope 用 public(公共) 或 academic(高校);published 用 YYYY-MM-DD(没有留空)。严格 JSON:"
            '{"items":[{"title_zh":"中文标题","eng":"原标题(中文源可留空)","summary":"1-2句中文摘要","source":"来源",'
            '"region":"全球/美国/中国等","scope":"public或academic","published":"","url":"原链接","overview":"详尽概述3-5句(基于事实)","analysis":"对上海少儿馆的借鉴2-3句","social":[{"who":"视角如馆员/研究者/读者","text":"1-2句评论"}]}]}'
            "\n\nGLOBAL:\n" + json.dumps(global_raw[:18], ensure_ascii=False)
            + "\n\nCHINA:\n" + json.dumps(cn_raw[:10], ensure_ascii=False))
    out = chat_items(SYS, user, backend)
    items = out.get("items", [])
    return {"items": items, "regions": sorted({i.get("region") for i in items if i.get("region")})}

def do_podcasts(raw, backend):
    flat = [{"podcast": p["podcast"], "host": p["host"], "region": zh, "url": p["url"]}
            for zh, lst in raw.items() for p in lst]
    user = ("下面是各地区真实播客(JSON)。为每个补 title(一句中文定位)、summary(1句中文,大体在聊什么)、"
            "topics(2-3个中文标签),保持 podcast/host/region/url 原样。严格 JSON:"
            '{"items":[{"podcast":"","title":"","summary":"","region":"","host":"","topics":[],"url":""}]}'
            "\n\n数据:\n" + json.dumps(flat, ensure_ascii=False))
    items = chat_items(SYS, user, backend).get("items", flat)
    return {"regions": list(raw.keys()), "items": items}

def do_voices(ai_items, lib_items, backend):
    ctx = [{"t": i.get("title_zh"), "s": i.get("source")} for i in (ai_items + lib_items)][:20]
    user = ("参考近期 AI 与图书馆动态(下方),列出 6-7 位当前有影响力的代表人物(AI/播客/图书馆领域,覆盖不同地区),"
            "给出其近期关注方向(中文概括即可,不要编造具体新闻)。严格 JSON:"
            '{"items":[{"name":"姓名","role":"身份","region":"地区","domain":"ai/podcast/library",'
            '"recent":"近期关注(1句中文)","url":"主页或社媒;不确定就留空字符串"}]}'
            "\n\n参考:\n" + json.dumps(ctx, ensure_ascii=False))
    return {"items": chat_items(SYS, user, backend).get("items", [])}

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
            out = chat_items(SPORTS_SYS, user, backend)
            for it in out.get("items", []):
                it["region"] = sub
            items_all += out.get("items", [])
        except llm.BackendBlockedError:
            raise
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
    return {"items": chat_items(SYS, user, backend).get("items", [])}

def do_hot(raw_by_region, backend):
    flat = [dict(it, _region=region) for region, items in raw_by_region.items() for it in items]
    user = ("下面是实时热点资讯(JSON,_region 是 中国/国外)。挑选 12-15 条最重要的,去重,为每条写中文。"
            "region 用其 _region。严格 JSON:"
            '{"items":[{"title_zh":"中文标题","summary":"1-2句中文摘要","source":"来源","region":"中国或国外",'
            '"published":"YYYY-MM-DD","url":"原链接","overview":"概述3-5句","analysis":"看点2-3句",'
            '"social":[{"who":"视角","text":"1-2句"}]}]}'
            "\n\n数据:\n" + json.dumps(flat[:40], ensure_ascii=False))
    out = chat_items(SYS, user, backend)
    items = out.get("items", [])
    return {"items": items, "regions": sorted({i.get("region") for i in items if i.get("region")})}

def keep_manual_modules(mods, old):
    """手工整合板块(kidlit/research/creative/games/podcasts 等)不在定时回填名单里:
    整体沿用旧值,防止整点任务把 merge_* 脚本的成果静默抹掉。old 为空时无操作。"""
    for k in old:
        if k not in mods:
            mods[k] = old[k]; log("· 保留手工板块", k)

# 每小时全量重算 6 个栏目,但新闻源一天也变不了几次 —— 用原始素材指纹跳过无谓的 LLM 调用。
# 云端省额度,本地省这台机器(9B 全量一轮约十几分钟)。指纹变了才重算。
HASHES = pathlib.Path(__file__).resolve().parent / ".srchash.json"

# 只认"是不是同一批素材",不认易变字段。实测 github 源按 star 排序,星数每次抓都不同,
# 整条目做指纹就永远不命中 —— 那这个栏目每小时照样白调一次 LLM。
_FP_KEYS = ("url", "link", "guid", "title")

def _fp_view(x):
    if isinstance(x, dict):
        keep = {k: x[k] for k in _FP_KEYS if k in x}
        return keep or {k: _fp_view(v) for k, v in sorted(x.items())}
    if isinstance(x, list):
        return [_fp_view(i) for i in x]
    return x

def fingerprint(raw):
    blob = json.dumps(_fp_view(raw), ensure_ascii=False, sort_keys=True, default=str)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:16]

def load_hashes():
    try:
        return json.loads(HASHES.read_text(encoding="utf-8"))
    except Exception:
        return {}

def main():
    load_env()
    backend = llm.pick_backend()
    log("引擎:", backend)
    DATA.mkdir(parents=True, exist_ok=True); ARCH.mkdir(parents=True, exist_ok=True)
    old_doc = {}
    old = {}
    if (DATA / "latest.json").exists():
        try:
            old_doc = json.load(open(DATA / "latest.json", encoding="utf-8"))
            old = old_doc.get("modules", {})
        except Exception:
            pass
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
    generated_keys = set()
    unchanged_keys = set()
    empty_sources = []
    blocked_reason = ""
    hashes = load_hashes()
    new_hashes = dict(hashes)
    # 原始抓取为空(网络全断)时跳过该模块的 LLM 生成:防止模型对空数据编造条目,也省 token;走下方"沿用上次"
    for key, fn, has_raw, raw in [
            ("ai", lambda: do_ai(ai_raw, backend), bool(ai_raw), ai_raw),
            ("libraries", lambda: do_libraries(lib_raw, cn_raw, backend), bool(lib_raw or cn_raw), [lib_raw, cn_raw]),
            ("sports", lambda: do_sports(sports_raw, backend), any(sports_raw.values()), sports_raw),
            ("github", lambda: do_github(gh_raw, backend), bool(gh_raw), gh_raw),
            ("hot", lambda: do_hot(hot_raw, backend), any(hot_raw.values()), hot_raw)]:
        if not has_raw:
            # "源抓不到" 和 "源没新内容" 在数据上长得一模一样,都表现为栏目不更新。
            # 必须分开记:否则上游 feed 悄悄死掉时,指纹缓存会把它伪装成"合法地没有新料"。
            log("✗", key, "原始抓取为空,跳过生成(沿用上次)")
            mods[key] = None; empty_sources.append(key); continue
        if blocked_reason:
            log("·", key, "AI 熔断，本轮跳过(沿用上次)"); mods[key] = None; continue
        fp = fingerprint(raw)
        if fp == hashes.get(key) and old.get(key, {}).get("items"):
            log("·", key, "素材未变,跳过重算(沿用上次)"); mods[key] = None; unchanged_keys.add(key); continue
        try:
            mods[key] = fn(); log("✓", key, len(mods[key]["items"]))
            if mods[key].get("items"):
                generated_keys.add(key); new_hashes[key] = fp  # 只有真出了内容才记指纹,失败的下轮还会重试
        except llm.BackendBlockedError as e:
            blocked_reason = str(e)
            log("✗", key, blocked_reason)
            mods[key] = None
        except Exception as e:
            log("✗", key, e); mods[key] = None
    try:
        if blocked_reason:
            raise llm.BackendBlockedError(blocked_reason)
        ai_i = mods["ai"]["items"] if mods.get("ai") else []
        lib_i = mods["libraries"]["items"] if mods.get("libraries") else []
        if not (generated_keys & {"ai", "libraries"}) and old.get("voices", {}).get("items"):
            log("· voices 上游未变,跳过重算(沿用上次)"); mods["voices"] = None; unchanged_keys.add("voices")
        elif not (ai_i or lib_i):
            log("✗ voices 无上下文,跳过生成(沿用上次)"); mods["voices"] = None
        else:
            mods["voices"] = do_voices(ai_i, lib_i, backend); log("✓ voices", len(mods["voices"]["items"]))
            if mods["voices"].get("items"):
                generated_keys.add("voices")
    except llm.BackendBlockedError:
        log("· voices AI 熔断，本轮跳过(沿用上次)")
        mods["voices"] = None
    except Exception as e:
        log("✗ voices", e); mods["voices"] = None
    if not generated_keys and not blocked_reason and unchanged_keys and old_doc:
        # 素材一字未变 = 正常的无事发生,不是降级。不动 latest.json,也不谎报新的生成时间。
        save_json(new_hashes, HASHES)
        log("· 素材无变化,本轮无需重算:", " ".join(sorted(unchanged_keys)))
        return
    if not generated_keys and old_doc:
        reason = blocked_reason or "本轮没有任何模块成功生成，继续展示上次成功内容"
        changed = (old_doc.get("generation_status") != "degraded"
                   or old_doc.get("generation_error") != reason)
        if changed:
            old_doc["generation_status"] = "degraded"
            old_doc["generation_error"] = reason
            save_json(old_doc, DATA / "latest.json")
            log("⚠ 已标记降级；latest 内容与生成时间保持不变")
        else:
            log("⚠ 降级状态未变化；latest.json 保持不变")
        return
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
    keep_manual_modules(mods, old)
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
    # 逐栏目的真实更新时间:一个活着的栏目不该替其他栏目盖上新鲜的时间戳(2026-07-27 学术栏目就干过这事)
    mod_updated = dict(old_doc.get("module_updated") or {})
    for k in generated_keys:
        mod_updated[k] = now.strftime("%Y-%m-%d %H:%M")
    out = {"generated_at": now.isoformat(timespec="seconds"), "date": now.strftime("%Y-%m-%d"),
           "engine": llm.last_used or f"{backend[0]}:{backend[1]}",  # 记真正出活的那一路,不是开局挑的那一路
           "generation_status": "degraded" if blocked_reason else "ok",
           "generation_error": blocked_reason,
           # 首选引擎挂了但兜底扛住了:内容是新的,所以不算降级,但她得知道"充个值就回到秒级"
           "engine_fallback": "；".join(f"{k} {v}" for k, v in llm._BLOCKED.items()),
           # 上游源抓不到 ≠ 上游没新内容。不分开记的话,feed 悄悄死掉会被指纹缓存伪装成"合法没新料"
           "empty_sources": empty_sources,
           "module_updated": mod_updated,
           "modules": mods}
    save_json(out, DATA / "latest.json")
    save_json(out, ARCH / f"{out['date']}.json")
    save_json(new_hashes, HASHES)
    log("✅ 写入完成", out["date"], "| 引擎", out["engine"], "| 本轮重算", " ".join(sorted(generated_keys)) or "无")

if __name__ == "__main__":
    main()
