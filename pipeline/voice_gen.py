#!/usr/bin/env python3
"""给每集生成 1-2 分钟中文导读配音(念 标题+导读+要点)。edge-tts, 写 docs/data/voice/。"""
import json, asyncio, os, hashlib, sys
import edge_tts
APP="docs/data/podcast_app.json"; VDIR="docs/data/voice"
os.makedirs(VDIR, exist_ok=True)
d=json.load(open(APP))
async def gen(text, path):
    c=edge_tts.Communicate(text, "zh-CN-XiaoxiaoNeural")
    await c.save(path)
async def main():
    n=0
    for key, ep in d['episodes'].items():
        fn=hashlib.md5(key.encode()).hexdigest()[:12]+".mp3"
        path=f"{VDIR}/{fn}"
        ep['voice']=f"data/voice/{fn}"
        if os.path.exists(path) and os.path.getsize(path)>1000: continue
        pts="。".join(f"第{i+1}点,{p}" for i,p in enumerate(ep.get('points',[])))
        text=f"{ep['title_zh']}。{ep.get('intro','')}。本期要点如下。{pts}"
        try:
            await gen(text, path); n+=1
            print(f"  配音 {ep['title_zh'][:22]} {os.path.getsize(path)//1024}KB", file=sys.stderr)
        except Exception as e:
            print(f"  失败 {ep['title_zh'][:22]}: {str(e)[:40]}", file=sys.stderr); ep.pop('voice', None)
    json.dump(d, open(APP,'w'), ensure_ascii=False, indent=2)
    print(f"[完成] 本次新配音 {n} 集", file=sys.stderr)
asyncio.run(main())
