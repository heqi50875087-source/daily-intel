#!/usr/bin/env python3
"""远音管线(增量幂等):抓各档最新集,只处理新集(guid变),替换该档旧集。→ podcast_app.json"""
import os, sys, json, time, urllib.request, ssl, requests
from concurrent.futures import ThreadPoolExecutor, as_completed
import feedparser
import podcast_zh, podcast_fulltext
from jsonio import save_json
ctx=ssl._create_unverified_context()
UA={'User-Agent':'Mozilla/5.0 (Macintosh)'}
WORK=os.path.join(os.path.dirname(os.path.abspath(__file__)),"podcast_work")  # 锚定脚本目录,与 CWD 无关
OUT=f"{WORK}/podcast_app.json"; MAXB=30*1048576  # 下载上限放宽:覆盖更长音频
PROXY={'http':'http://127.0.0.1:18080','https':'http://127.0.0.1:18080'}  # GreenHub HTTP桥:音频/RSS走代理,DeepSeek保持直连
# 双通道(对齐 reprocess_full.dl_full):代理优先(多数源需翻),代理断(如UUID轮换窗口)时直连兜底,别让33档RSS整体no-op
_openers=[urllib.request.build_opener(urllib.request.ProxyHandler(PROXY), urllib.request.HTTPSHandler(context=ctx)),
          urllib.request.build_opener(urllib.request.ProxyHandler({}), urllib.request.HTTPSHandler(context=ctx))]
def _fetch_head(feed):
    """抓 RSS 头部(到首个</item>或400KB)。代理优先,直连兜底;两路都挂返回 None。"""
    for px in (PROXY, None):
        try:
            r=requests.get(feed,timeout=15,headers=UA,stream=True,proxies=px)
            buf=b""
            for chunk in r.iter_content(16384):
                buf+=chunk
                if b"</item>" in buf or len(buf)>400000: break
            r.close()
            return buf
        except Exception: continue
    return None
def latest(feed):
    try:
        buf=_fetch_head(feed)
        if buf is None: return None
        f=feedparser.parse(buf)
        if not f.entries: return None
        e=f.entries[0]; au=None
        if e.get('enclosures'): au=e.enclosures[0].get('href')
        if not au:
            for l in e.get('links',[]):
                if 'audio' in (l.get('type') or ''): au=l['href']
        return {"title":e.get('title',''),"audio":au,"published":e.get('published','')[:16],"guid":e.get('id',e.get('title','')),"link":e.get('link','')}
    except Exception: return None
def dl_one(ep,path):
    for op in _openers:  # 代理优先,直连兜底;语义不变:两路都失败返回 False
        try:
            req=urllib.request.Request(ep['audio'],headers={**UA,'Range':f'bytes=0-{MAXB}'})
            r=op.open(req,timeout=75)
            data=r.read(); open(path,'wb').write(data)
            ep['truncated']=(len(data)>=MAXB); ep['mp3']=path  # 以实际字节数为准:Range请求即使拿到完整文件服务器也回206,旧判法把完整集误标"节选"
            return True
        except Exception: continue
    return False
def _whisper_model_ref(env=None):
    """选模型:WHISPER_LOCAL_MODEL 或 pipeline/models/faster-whisper-tiny 本地目录(脱离外置盘HF缓存,
    launchd无可移动卷TCC授权也能读);目录缺失/不完整则回退 HF 名 "tiny"(旧行为)。"""
    env=os.environ if env is None else env
    p=env.get("WHISPER_LOCAL_MODEL") or os.path.join(os.path.dirname(os.path.abspath(__file__)),"models","faster-whisper-tiny")
    return p if os.path.isfile(os.path.join(p,"model.bin")) else "tiny"
def load_whisper():
    """下载前先验模型可加载:HF缓存符号链接到外置盘时,launchd裸任务无TCC权限会EPERM——立即失败,省去每天白下~900MB音频。"""
    try:
        from faster_whisper import WhisperModel
        ref=_whisper_model_ref()
        if ref!="tiny":
            try: return WhisperModel(ref,device="cpu",compute_type="int8")
            except Exception as e:
                print(f"! 本地模型目录加载失败({type(e).__name__}),回退HF缓存tiny: {ref}",file=sys.stderr)
        return WhisperModel("tiny",device="cpu",compute_type="int8")
    except (PermissionError,OSError) as e:
        hf=os.path.expanduser("~/.cache/huggingface")
        print(f"X whisper模型加载失败: {type(e).__name__} {e}\n"
              f"  提示: {hf} 若指向外置盘(如ORICO),launchd任务需TCC磁盘授权(applet壳)或把缓存移回本地盘;"
              f"或把模型快照拷到 pipeline/models/faster-whisper-tiny(见 _whisper_model_ref)",file=sys.stderr)
        raise
def main():
    shows=json.load(open(f"{WORK}/shows.json"))
    try: out=json.load(open(OUT))
    except FileNotFoundError: out={"generated":"","episodes":{}}
    except Exception as e:
        print(f"⚠ {OUT} 读取失败({type(e).__name__}),从空库重建(旧集将重新处理)",file=sys.stderr)
        out={"generated":"","episodes":{}}
    out.setdefault("episodes",{})
    print(f"抓 {len(shows)} 档最新集...",file=sys.stderr)
    metas=[]
    with ThreadPoolExecutor(max_workers=4) as ex:
        futs={ex.submit(latest,s['feedUrl']):s for s in shows}
        for fut in as_completed(futs):
            s=futs[fut]; ep=fut.result()
            if ep and ep.get('audio'): metas.append((s,ep))
    if not metas:
        print("⚠ 全部 RSS 抓取失败(网络/代理不可用?),本次跳过——不是\"无新集\"",file=sys.stderr); return
    todo=[(s,ep) for s,ep in metas if f"{s['name']}|{ep['guid']}" not in out['episodes']]
    print(f"抓到 {len(metas)} 档, 新集 {len(todo)} 个",file=sys.stderr)
    if not todo:
        print("[完成] 无新集,已是最新",file=sys.stderr); return
    model=load_whisper()   # 先验模型再下载(见 load_whisper 注释)
    downloaded=[]
    with ThreadPoolExecutor(max_workers=4) as ex:
        futs={ex.submit(dl_one,ep,f"{WORK}/dl_{i}.mp3"):(s,ep) for i,(s,ep) in enumerate(todo)}
        for fut in as_completed(futs):
            s,ep=futs[fut]
            if fut.result(): downloaded.append((s,ep)); print(f"  OK下载 {s['name'][:28]}",file=sys.stderr)
            else: print(f"  X下载 {s['name'][:28]}",file=sys.stderr)
    # 时间预算:本任务 09:00 开跑,正是她开工时间。云端引擎时一集几十秒无所谓,
    # 但本地 9B 全文翻译一集要好几分钟,十几集就能把整个上午的机器磨钝。
    # 超预算就停手,剩下的明天再补 —— 本管线是增量的,做过的集不会重做。
    budget=float(os.environ.get("PODCAST_BUDGET_MIN","45"))*60
    t0=time.time()
    for s,ep in downloaded:
        if time.time()-t0>budget:
            print(f"⏸ 已用满 {budget/60:.0f} 分钟预算,剩 {len(downloaded)-downloaded.index((s,ep))} 集留到明天",file=sys.stderr)
            break
        t=time.time()
        try:
            segs,_=model.transcribe(ep['mp3'],language="en")
            en=" ".join(x.text for x in segs).strip()
            if len(en)<50: print(f"  转写短 {s['name'][:24]}",file=sys.stderr); continue
            zh=podcast_zh.to_zh_brief(ep['title'],en)
            CAP=16000  # 翻译覆盖上限放宽,中文稿更完整
            src=en if len(en)<=CAP else en[:CAP]
            zhfull="\n\n".join(podcast_fulltext.translate(c) for c in podcast_fulltext.split_text(src))
            for k in [k for k,v in out['episodes'].items() if v['show']==s['name']]: del out['episodes'][k]
            out['episodes'][f"{s['name']}|{ep['guid']}"]={"show":s['name'],"category":s['category'],"author":s.get('author',''),
                "artwork":s.get('artwork',''),"title":ep['title'],"published":ep['published'],"audio":ep['audio'],"link":ep.get('link',''),
                "title_zh":zh.get('title_zh',''),"intro":zh.get('intro',''),"points":zh.get('points',[]),
                "tags":zh.get('tags',[]),"zh_full":zhfull,"truncated":bool(ep.get('truncated') or len(en)>CAP)}
            out['generated']=time.strftime("%Y-%m-%d %H:%M")
            save_json(out,OUT)
            try: os.remove(ep['mp3'])
            except Exception: pass
            print(f"  OK[{len(out['episodes'])}] {s['name'][:22]} -> {zh.get('title_zh','')[:20]} ({time.time()-t:.0f}s)",file=sys.stderr)
        except Exception as ex:
            print(f"  X翻译 {s['name'][:22]}: {type(ex).__name__}",file=sys.stderr)
    print(f"[完成] 共 {len(out['episodes'])} 集",file=sys.stderr)
if __name__=="__main__": main()
