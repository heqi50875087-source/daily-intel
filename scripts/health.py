#!/usr/bin/env python3
"""远见体检:不读日志、不看绿灯,直接量真东西。

2026-07-11 那次事故里,git 每天有提交、run.log 每小时写 done、小程序照常显示"今天更新",
三个量具同时说谎,内容却冻了 16 天。所以这里只认三种证据:
  ① 每个栏目最新条目的日期(不是整站时间戳,那个会被还活着的栏目刷新)
  ② 三路引擎各发一个最小真实请求(不是"配置里填了 key"就算通)
  ③ 线上 Pages 拿到的那份 JSON(不是本地文件,用户看到的是线上那份)
退出码:0 健康 / 1 有黄灯 / 2 有红灯。
"""
import json, os, sys, time, datetime, pathlib, subprocess

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "pipeline"))
LATEST = ROOT / "docs" / "data" / "latest.json"
PAGES = "https://heqi50875087-source.github.io/daily-intel/data/latest.json"
STALE_H, DEAD_H = 36, 72          # 栏目多久没新内容算黄灯 / 红灯
worst = 0

def say(level, msg, detail=""):
    global worst
    worst = max(worst, {"ok": 0, "warn": 1, "bad": 2}[level])
    print(f"{ {'ok':'✅','warn':'🟡','bad':'🔴'}[level] } {msg}" + (f"\n     {detail}" if detail else ""))

def hours_since(s):
    if not s:
        return None
    for fmt in ("%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d"):
        try:
            t = datetime.datetime.strptime(str(s)[:len(time.strftime(fmt))], fmt)
            return (datetime.datetime.now() - t).total_seconds() / 3600
        except ValueError:
            continue
    return None

print("=" * 58, "\n远见体检 ·", time.strftime("%Y-%m-%d %H:%M"), "\n" + "=" * 58)

# ---------- 1. 内容新鲜度:逐栏目量,别信整站时间戳 ----------
print("\n【内容】每个栏目最新一条是什么时候的")
try:
    doc = json.loads(LATEST.read_text(encoding="utf-8"))
except Exception as e:
    say("bad", f"读不到 latest.json:{e}")
    doc = {}
mods = doc.get("modules", {})
mu = doc.get("module_updated", {})
for k, v in sorted(mods.items()):
    items = (v or {}).get("items", []) if isinstance(v, dict) else []
    if not items:
        say("warn", f"{k:<10} 0 条(空栏目)")
        continue
    dates = sorted(d for d in ((i.get("published") or "")[:10] for i in items if isinstance(i, dict)) if d)
    newest = dates[-1] if dates else ""
    h = hours_since(mu.get(k)) if mu.get(k) else hours_since(newest)
    tag = f"{len(items):>3} 条 · 最新内容 {newest or '无日期'}" + (f" · 上次重算 {mu[k]}" if mu.get(k) else "")
    if h is None:
        say("warn", f"{k:<10} {tag}", "没有可判断的时间")
    elif h > DEAD_H:
        say("bad", f"{k:<10} {tag}", f"已 {h/24:.1f} 天没有新内容")
    elif h > STALE_H:
        say("warn", f"{k:<10} {tag}", f"已 {h:.0f} 小时没有新内容")
    else:
        say("ok", f"{k:<10} {tag}")

status = doc.get("generation_status")
if status == "degraded":
    say("bad", "管线处于降级状态", doc.get("generation_error", ""))
elif status == "ok":
    say("ok", "管线状态 ok")

# ---------- 2. 引擎:真发请求,不看配置 ----------
print("\n【引擎】每一路都真发一个最小请求")
print("     (本地那一路若有生成任务正在跑会排队,可能要等一两分钟,不是卡死)")
for ln in (ROOT / "pipeline" / ".env").read_text(encoding="utf-8").splitlines():
    ln = ln.strip()
    if ln and not ln.startswith("#") and "=" in ln:
        k, v = ln.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip())
import llm
chain = llm.available_backends()
if not chain:
    say("bad", "一路引擎都没有", "Ollama 无模型且未配置任何云端 key")
alive = 0
for kind, model in chain:
    t = time.time()
    try:
        llm._extract(llm._CHAT[kind](model, "只返回 JSON。", '回我 {"ok":true}'))
        say("ok", f"{kind:<9} 可用 · {time.time()-t:.1f}s · {model[:44]}")
        alive += 1
    except Exception as e:
        say("warn", f"{kind:<9} 不可用", f"{type(e).__name__}: {str(e)[:90]}")
    llm._BLOCKED.clear()
    # 本地这一路多验一件事:语法约束还在不在。ollama 升级或换模型后 schema 可能静默失效,
    # 表现是"还能出活,只是偶尔结构不对",极难发现。判别法:schema 要 zzq、提示词要 weekday,
    # 输出 zzq 才说明约束真的压过了提示词。
    if kind == "ollama":
        try:
            probe = llm._ollama_chat(model, None, "用 JSON 回答今天星期几,字段名用 weekday。",
                                     {"type": "object", "properties": {"zzq": {"type": "string"}},
                                      "required": ["zzq"]})
            say("ok" if "zzq" in probe else "bad",
                "本地引擎的 JSON 语法约束有效" if "zzq" in probe else "本地引擎语法约束已失效!",
                "" if "zzq" in probe else "ollama 升级或换模型后 schema 不再强制,长输出会变回坏 JSON")
        except Exception as e:
            say("warn", f"语法约束探针没跑成:{type(e).__name__}")
if alive == 0:
    say("bad", "三路引擎全挂 —— 内容一定不会再更新")
elif alive == 1:
    say("warn", f"只剩一路可用,没有余量")

# ---------- 3. 本地引擎的两个隐形前提 ----------
print("\n【本地引擎的前提】")
r = subprocess.run(["launchctl", "list"], capture_output=True, text=True)
say("ok" if "com.kushim.ollama" in r.stdout else "warn",
    "ollama 守护常驻" if "com.kushim.ollama" in r.stdout else "ollama 守护未加载",
    "" if "com.kushim.ollama" in r.stdout else "launchctl load -w ~/Library/LaunchAgents/com.kushim.ollama.plist")
orico = pathlib.Path("/Volumes/ORICO/ai-models/ollama")
say("ok" if orico.is_dir() else "warn",
    "模型盘 ORICO 已挂载" if orico.is_dir() else "模型盘 ORICO 未挂载 → 本地这一路失效",
    "" if orico.is_dir() else "插上 ORICO,或改用云端引擎")

# ---------- 4. 心跳:管线"根本没跑"是唯一没人负责发现的失效 ----------
hb = ROOT / "logs" / ".heartbeat"
if hb.exists():
    age = (time.time() - hb.stat().st_mtime) / 3600
    active = 7 <= datetime.datetime.now().hour <= 23   # 整点任务 6:00-23:00,夜里本就没有心跳
    say("bad" if (active and age > 3) else ("warn" if age > 14 else "ok"),
        f"上一轮跑完于 {age:.1f} 小时前",
        "launchd 任务可能已停摆:launchctl list | grep daily-intel" if (active and age > 3) else "")
else:
    say("warn", "还没有心跳文件", "装了本次更新后,下一个整点任务会创建 logs/.heartbeat")

# ---------- 5. 磁盘:主盘满会让 git / ollama 一起出怪病,连 ALERT.log 都写不进去 ----------
st = os.statvfs("/System/Volumes/Data")
free_gb = st.f_bavail * st.f_frsize / 1e9
say("bad" if free_gb < 5 else ("warn" if free_gb < 20 else "ok"), f"主盘可用 {free_gb:.1f} GB",
    "磁盘写满时告警自己也发不出来 —— 这是唯一能连看门狗一起杀死的故障" if free_gb < 5 else "")

# ---------- 6. 上游源:抓不到 ≠ 没新内容,后者正常,前者是 feed 死了 ----------
empty = doc.get("empty_sources") or []
say("bad" if empty else "ok",
    f"上游源抓取为空的栏目:{' '.join(empty)}" if empty else "所有上游源都抓到了内容",
    "指纹缓存会把'源死了'伪装成'合法地没有新料',所以这条要单独看" if empty else "")

# ---------- 5. 线上那份才是用户看到的 ----------
print("\n【线上】小程序真正拉到的那份")
try:
    import requests
    live = requests.get(PAGES, timeout=15).json()
    # 按"最旧的那个栏目"判,不按整站 generated_at —— 后者正是会被冒充的那个数
    ages = {k: hours_since((v or {}).get("items", [{}])[0].get("published", ""))
            for k, v in (live.get("modules") or {}).items() if (v or {}).get("items")}
    ages = {k: a for k, a in ages.items() if a is not None}
    if ages:
        oldest_k = max(ages, key=ages.get)
        h = ages[oldest_k]
        say("bad" if h > DEAD_H else ("warn" if h > STALE_H else "ok"),
            f"线上最旧的栏目是「{oldest_k}」,{h/24:.1f} 天前的内容")
    h = hours_since(live.get("generated_at"))
    print(f"     (整站 generated_at = {live.get('generated_at','?')},仅供参考,别拿它当新鲜度)")
    if live.get("generation_status") == "degraded":
        say("bad", "线上那份正标着降级", live.get("generation_error", ""))
    # 对两块表:本地全绿而远端是旧的(推送链路断了),本地所有量具都结构性看不见这条失效
    lmu, rmu = doc.get("module_updated") or {}, live.get("module_updated") or {}
    diff = [k for k in set(lmu) | set(rmu) if lmu.get(k) != rmu.get(k)]
    if diff:
        say("bad", f"本地与线上不一致的栏目:{' '.join(sorted(diff))}",
            "推送链路可能断了(token 过期 / 代理故障)。本地看什么都是绿的,只有这一条能抓到")
    elif lmu:
        say("ok", f"本地与线上逐栏目时间戳一致({len(lmu)} 个栏目)")
except Exception as e:
    say("warn", f"取不到线上数据:{type(e).__name__}", "网络问题时不代表管线有病")

# ---------- 6. 播客 ----------
pod = ROOT / "docs" / "data" / "podcast_app.json"
if pod.exists():
    g = json.loads(pod.read_text(encoding="utf-8")).get("generated", "")
    h = hours_since(g)
    say("bad" if (h or 0) > 24 * 7 else ("warn" if (h or 0) > 24 * 3 else "ok"), f"远音播客数据生成于 {g or '?'}")

print("\n" + "=" * 58)
print({0: "全部正常。", 1: "有黄灯,能用但要留意。", 2: "有红灯,内容多半已经不再更新了。"}[worst])
sys.exit(worst)
