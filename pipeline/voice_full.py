#!/usr/bin/env python3
"""为每集生成【完整】中文版配音:念 zh_full 全文(不再只念摘要)。
按节目主持人性别选音色;对谈/圆桌类多声轮换。edge-tts 免费, ffmpeg 重编码保证进度条可拖动。
输出 docs/data/voice_full/*.mp3, 并把 voice_full 路径写回 podcast_app.json。
用法: python voice_full.py [--force] [--only "节目名关键字"]"""
import json, asyncio, os, hashlib, sys, subprocess, tempfile, shutil
import edge_tts

APP  = "docs/data/podcast_app.json"
VDIR = "docs/data/voice_full"
os.makedirs(VDIR, exist_ok=True)

# ── 音色池(edge-tts 简体中文)──
F1 = "zh-CN-XiaoxiaoNeural"   # 女·温暖标准
F2 = "zh-CN-XiaoyiNeural"     # 女·偏年轻
M1 = "zh-CN-YunxiNeural"      # 男·清亮
M2 = "zh-CN-YunjianNeural"    # 男·浑厚
M3 = "zh-CN-YunyangNeural"    # 男·播音腔

# 每档节目 → (模式, 轮换音色)。solo=单人;duo/panel=多声按段落轮换。
SHOW_VOICE = {
  # 名流 / 思想对话
  "The Joe Rogan Experience": ("duo", [M1, M2]),
  "Naval": ("solo", [M1]),
  "Huberman Lab": ("solo", [M3]),
  "All-In with Chamath, Jason, Sacks & Friedberg": ("panel", [M1, M2, M3]),
  "Modern Wisdom": ("duo", [M1, M2]),
  "The Diary Of A CEO with Steven Bartlett": ("duo", [M1, F1]),
  "Making Sense with Sam Harris": ("solo", [M3]),
  # AI / 前沿科技
  "The AI Daily Brief: Artificial Intelligence News and Analysis": ("solo", [M1]),
  "Lex Fridman Podcast": ("duo", [M2, M1]),
  "Hard Fork": ("duo", [M1, M3]),
  "The TWIML AI Podcast (formerly This Week in Machine Learning & Artificial Intelligence)": ("duo", [M1, M2]),
  "Latent Space: The AI Engineer Podcast": ("duo", [M1, M2]),
  # 图书馆 / 教育 / 阅读
  "What Should I Read Next?": ("solo", [F1]),
  "Reading Glasses": ("duo", [F1, F2]),
  "The Librarian Is In": ("solo", [F1]),
  "TED Talks Daily": ("solo", [F1]),
  "The Knowledge Project": ("solo", [M2]),
  # 文化 / 历史 / 故事
  "99% Invisible": ("solo", [M1]),
  "Stuff You Should Know": ("duo", [M1, M2]),
  "Radiolab": ("duo", [M1, F1]),
  "This American Life": ("solo", [M3]),
  "Revisionist History": ("solo", [M2]),
  # 商业 / 创业 / 人物访谈
  "How I Built This with Guy Raz": ("duo", [M1, F1]),
  "The a16z Show": ("solo", [M1]),
  "Masters of Scale": ("duo", [M2, F1]),
  "The Tim Ferriss Show": ("duo", [M1, M2]),
  "Acquired": ("duo", [M1, M2]),
}
DEFAULT = ("solo", [F1])   # 未知 / 中性 → 女声(用户指定)

# 覆盖:从 build_lineup.py 生成的 voice_map.json 读取(35档完整性别映射)
try:
    for _k, _v in json.load(open("docs/data/voice_map.json")).items():
        SHOW_VOICE[_k] = (_v[0], list(_v[1]))
except Exception:
    pass

def paras_of(ep):
    txt = (ep.get("zh_full") or "").strip()
    ps = [p.strip() for p in txt.split("\n\n") if p.strip()]
    if not ps:                       # 没有全文 → 退回 导读+要点
        pts = "。".join(ep.get("points", []) or [])
        ps = [p for p in [ep.get("intro", ""), ("本期要点。" + pts) if pts else ""] if p]
    return ps

def speakable(t):
    """是否含可朗读内容;纯标点/空白会让 edge-tts 报 NoAudioReceived。"""
    import re
    return bool(re.search(r"[一-鿿0-9A-Za-z]", t or ""))

async def tts(text, voice, path, tries=4):
    text = (text or "").strip() or "。"
    if not speakable(text):
        text = "。"
    last = None
    for k in range(tries):
        try:
            await edge_tts.Communicate(text, voice).save(path)
            if os.path.exists(path) and os.path.getsize(path) > 800:
                return
        except Exception as e:
            last = e
        await asyncio.sleep(1.5 * (k + 1))   # 退避重试
    raise last or RuntimeError("TTS 多次失败")

def reencode_concat(parts, out):
    """先解码拼接为连续PCM(消除段间padding/时间戳灌水),再一次性编码为干净CBR mp3。
    这样浏览器读到的时长=真实时长,进度条精准、可拖动(否则末尾会有~20s幽灵尾巴)。"""
    lst = out + ".lst"; wav = out + ".wav"
    with open(lst, "w") as f:
        for p in parts: f.write("file '%s'\n" % os.path.abspath(p))
    subprocess.run(["ffmpeg","-y","-f","concat","-safe","0","-i",lst,
                    "-ar","24000","-ac","1",wav], check=True, capture_output=True)
    subprocess.run(["ffmpeg","-y","-i",wav,
                    "-c:a","libmp3lame","-b:a","64k","-ar","24000","-ac","1",out],
                   check=True, capture_output=True)
    os.remove(lst); os.remove(wav)

async def gen(key, ep, force):
    fn  = hashlib.md5(key.encode()).hexdigest()[:12] + ".mp3"
    out = f"{VDIR}/{fn}"
    ep["voice_full"] = f"data/voice_full/{fn}"
    if os.path.exists(out) and os.path.getsize(out) > 5000 and not force:
        return None
    mode, voices = SHOW_VOICE.get(ep.get("show",""), DEFAULT)
    ps = paras_of(ep)
    if not ps: return False
    opener = f"本期节目,{ep.get('title_zh','')}。以下为完整中文版。"
    tmp = tempfile.mkdtemp(); parts = []
    try:
        await tts(opener, voices[0], f"{tmp}/000.mp3"); parts.append(f"{tmp}/000.mp3")
        if mode == "solo":
            await tts("\n".join(ps), voices[0], f"{tmp}/001.mp3"); parts.append(f"{tmp}/001.mp3")
        else:
            for i, para in enumerate(ps):
                v = voices[i % len(voices)]
                p = f"{tmp}/{i+1:03d}.mp3"
                await tts(para, v, p); parts.append(p)
        reencode_concat(parts, out)
        return True
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

async def main():
    force = "--force" in sys.argv
    only = None
    if "--only" in sys.argv: only = sys.argv[sys.argv.index("--only")+1]
    d = json.load(open(APP)); n=0; sk=0
    items = list(d["episodes"].items())
    for key, ep in items:
        if only and only.lower() not in ep.get("show","").lower(): continue
        try:
            r = await gen(key, ep, force)
            if r is True:
                fn = ep["voice_full"].split("/")[-1]
                kb = os.path.getsize(f"{VDIR}/{fn}")//1024
                mode = SHOW_VOICE.get(ep.get('show',''), DEFAULT)[0]
                print(f"  ✓ [{mode:5}] {ep.get('title_zh','')[:22]} · {ep['show'][:16]} {kb}KB", file=sys.stderr); n+=1
            elif r is None: sk+=1
        except Exception as e:
            print(f"  ✗ {ep.get('title_zh','')[:22]}: {type(e).__name__} {str(e)[:40]}", file=sys.stderr)
        json.dump(d, open(APP,"w"), ensure_ascii=False, indent=2)   # 边做边存,中断可续
    print(f"[完成] 新配 {n} 集, 跳过(已存在) {sk} 集", file=sys.stderr)

if __name__ == "__main__":
    asyncio.run(main())
