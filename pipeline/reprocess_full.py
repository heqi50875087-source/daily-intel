#!/usr/bin/env python3
"""重处理已有播客集为【完整】转录+翻译(拆掉30MB/16000字两道截断闸门)。
用法:
  python reprocess_full.py "What Should I Read"   # 按档名子串处理一集
  python reprocess_full.py --category 图书馆        # 处理某分类全部
  python reprocess_full.py --all                   # 全部重处理
环境:
  WHISPER_MODEL=small|tiny|base (默认small)  TRANS_WORKERS=4
"""
import os, sys, json, time, re, requests, subprocess
from concurrent.futures import ThreadPoolExecutor, as_completed
sys.path.insert(0, os.path.dirname(__file__))
import podcast_fulltext, podcast_zh

ROOT=os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT=f"{ROOT}/docs/data/podcast_app.json"
WORK=f"{os.path.dirname(__file__)}/podcast_work"
FF="/Users/apple/.local/bin/ffmpeg"; FP="/Users/apple/.local/bin/ffprobe"
MAXB=250*1048576
UA={'User-Agent':'Mozilla/5.0 (Macintosh)'}
PROXY={'http':'http://127.0.0.1:18080','https':'http://127.0.0.1:18080'}
MODEL=os.environ.get("WHISPER_MODEL","small")
TW=int(os.environ.get("TRANS_WORKERS","4"))

# DeepSeek key
if "DEEPSEEK_API_KEY" not in os.environ:
    for line in open(f"{os.path.dirname(__file__)}/.env"):
        if line.startswith("DEEPSEEK_API_KEY"):
            os.environ["DEEPSEEK_API_KEY"]=line.split("=",1)[1].strip()

def dl_full(url, path):
    """全量下载音频, 跟随重定向, 直连优先代理兜底"""
    for tag, px in [("直连", None), ("代理", PROXY)]:
        try:
            r=requests.get(url, headers=UA, stream=True, timeout=60, allow_redirects=True, proxies=px)
            r.raise_for_status()
            n=0
            with open(path,'wb') as f:
                for chunk in r.iter_content(65536):
                    f.write(chunk); n+=len(chunk)
                    if n>=MAXB: break
            r.close()
            if n>100000:
                print(f"    {tag}下载 {n/1048576:.1f}MB", file=sys.stderr); return n
        except Exception as e:
            print(f"    {tag}失败 {type(e).__name__}", file=sys.stderr)
    return 0

def duration_min(path):
    try:
        r=subprocess.run([FP,"-v","error","-show_entries","format=duration","-of","csv=p=0",path],
                         capture_output=True,text=True)
        return float(r.stdout.strip())/60
    except: return 0

def transcribe(path, model):
    segs,_=model.transcribe(path, language="en")
    return " ".join(x.text for x in segs).strip()

def translate_full(en):
    """全文分段, 并行翻译, 保持顺序拼接"""
    chunks=podcast_fulltext.split_text(en)
    parts=[None]*len(chunks)
    with ThreadPoolExecutor(max_workers=TW) as ex:
        futs={ex.submit(podcast_fulltext.translate, c): i for i,c in enumerate(chunks)}
        done=0
        for fut in as_completed(futs):
            i=futs[fut]
            try: parts[i]=fut.result()
            except Exception as e: parts[i]=f"[第{i+1}段翻译失败]"
            done+=1; print(f"    译 {done}/{len(chunks)} 段", file=sys.stderr)
    return "\n\n".join(p for p in parts if p), len(chunks)

def pick(eps, arg, val):
    if arg=="--all": return list(eps.items())
    if arg=="--category": return [(k,v) for k,v in eps.items() if val in v.get('category','')]
    return [(k,v) for k,v in eps.items() if arg.lower() in v.get('show','').lower()]

def main():
    if len(sys.argv)<2:
        print(__doc__); return
    arg=sys.argv[1]; val=sys.argv[2] if len(sys.argv)>2 else ""
    out=json.load(open(OUT)); eps=out['episodes']
    targets=pick(eps, arg, val)
    print(f"将重处理 {len(targets)} 集 (模型={MODEL})", file=sys.stderr)
    from faster_whisper import WhisperModel
    model=WhisperModel(MODEL, device="cpu", compute_type="int8")
    os.makedirs(WORK, exist_ok=True)
    for idx,(k,v) in enumerate(targets):
        t0=time.time(); show=v.get('show','')
        old_zh=len(v.get('zh_full',''))
        print(f"\n[{idx+1}/{len(targets)}] {show[:30]} | 旧中文稿 {old_zh}字", file=sys.stderr)
        mp3=f"{WORK}/re_{idx}.mp3"
        n=dl_full(v['audio'], mp3)
        if not n: print(f"    ✗下载失败,跳过", file=sys.stderr); continue
        dur=duration_min(mp3)
        print(f"    音频时长 {dur:.1f}分钟, 转写中(small较慢请稍候)...", file=sys.stderr)
        tt=time.time()
        en=transcribe(mp3, model)
        print(f"    转写完成 {len(en)}字符 ({time.time()-tt:.0f}s)", file=sys.stderr)
        if len(en)<50: print(f"    ✗转写过短", file=sys.stderr); continue
        zhfull,nch=translate_full(en)
        # 更新记录
        v['en']=en; v['zh_full']=zhfull; v['duration_min']=round(dur,1)
        v['truncated']=(n>=MAXB)  # 仅当真超250MB才算截断
        out['generated']=time.strftime("%Y-%m-%d %H:%M")
        json.dump(out, open(OUT,'w'), ensure_ascii=False, indent=2)
        try: os.remove(mp3)
        except: pass
        print(f"    ✅完成: {dur:.0f}分钟音频 → 英文{len(en)}字 → 中文{len(zhfull)}字 "
              f"(旧{old_zh}字, ×{len(zhfull)/max(old_zh,1):.1f}) [{time.time()-t0:.0f}s]", file=sys.stderr)
    print(f"\n[全部完成]", file=sys.stderr)

if __name__=="__main__": main()
