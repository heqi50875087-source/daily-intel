#!/usr/bin/env python3
"""远音管线(增量幂等):抓各档最新集,只处理新集(guid变),替换该档旧集。→ podcast_app.json"""
import os, sys, json, time, urllib.request, ssl, requests
from concurrent.futures import ThreadPoolExecutor, as_completed
import feedparser
import podcast_zh, podcast_fulltext
ctx=ssl._create_unverified_context()
UA={'User-Agent':'Mozilla/5.0 (Macintosh)'}
WORK="podcast_work"; OUT=f"{WORK}/podcast_app.json"; MAXB=30*1048576  # 下载上限放宽:覆盖更长音频
PROXY={'http':'http://127.0.0.1:18080','https':'http://127.0.0.1:18080'}  # GreenHub HTTP桥:音频/RSS走代理,DeepSeek保持直连
_proxy_opener=urllib.request.build_opener(urllib.request.ProxyHandler(PROXY), urllib.request.HTTPSHandler(context=ctx))
def latest(feed):
    try:
        r=requests.get(feed,timeout=15,headers=UA,stream=True,proxies=PROXY)
        buf=b""
        for chunk in r.iter_content(16384):
            buf+=chunk
            if b"</item>" in buf or len(buf)>400000: break
        r.close()
        f=feedparser.parse(buf)
        if not f.entries: return None
        e=f.entries[0]; au=None
        if e.get('enclosures'): au=e.enclosures[0].get('href')
        if not au:
            for l in e.get('links',[]):
                if 'audio' in (l.get('type') or ''): au=l['href']
        return {"title":e.get('title',''),"audio":au,"published":e.get('published','')[:16],"guid":e.get('id',e.get('title',''))}
    except Exception: return None
def dl_one(ep,path):
    try:
        req=urllib.request.Request(ep['audio'],headers={**UA,'Range':f'bytes=0-{MAXB}'})
        r=_proxy_opener.open(req,timeout=75)
        data=r.read(); open(path,'wb').write(data)
        ep['truncated']=(getattr(r,'status',200)==206 or len(data)>=MAXB); ep['mp3']=path
        return True
    except Exception: return False
def main():
    shows=json.load(open(f"{WORK}/shows.json"))
    try: out=json.load(open(OUT))
    except: out={"generated":"","episodes":{}}
    out.setdefault("episodes",{})
    print(f"抓 {len(shows)} 档最新集...",file=sys.stderr)
    metas=[]
    with ThreadPoolExecutor(max_workers=4) as ex:
        futs={ex.submit(latest,s['feedUrl']):s for s in shows}
        for fut in as_completed(futs):
            s=futs[fut]; ep=fut.result()
            if ep and ep.get('audio'): metas.append((s,ep))
    todo=[(s,ep) for s,ep in metas if f"{s['name']}|{ep['guid']}" not in out['episodes']]
    print(f"抓到 {len(metas)} 档, 新集 {len(todo)} 个",file=sys.stderr)
    if not todo:
        print("[完成] 无新集,已是最新",file=sys.stderr); return
    downloaded=[]
    with ThreadPoolExecutor(max_workers=4) as ex:
        futs={ex.submit(dl_one,ep,f"{WORK}/dl_{i}.mp3"):(s,ep) for i,(s,ep) in enumerate(todo)}
        for fut in as_completed(futs):
            s,ep=futs[fut]
            if fut.result(): downloaded.append((s,ep)); print(f"  OK下载 {s['name'][:28]}",file=sys.stderr)
            else: print(f"  X下载 {s['name'][:28]}",file=sys.stderr)
    from faster_whisper import WhisperModel
    model=WhisperModel("tiny",device="cpu",compute_type="int8")
    for s,ep in downloaded:
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
                "artwork":s.get('artwork',''),"title":ep['title'],"published":ep['published'],"audio":ep['audio'],
                "title_zh":zh.get('title_zh',''),"intro":zh.get('intro',''),"points":zh.get('points',[]),
                "tags":zh.get('tags',[]),"zh_full":zhfull,"truncated":bool(ep.get('truncated') or len(en)>CAP)}
            out['generated']=time.strftime("%Y-%m-%d %H:%M")
            json.dump(out,open(OUT,'w'),ensure_ascii=False,indent=2)
            try: os.remove(ep['mp3'])
            except Exception: pass
            print(f"  OK[{len(out['episodes'])}] {s['name'][:22]} -> {zh.get('title_zh','')[:20]} ({time.time()-t:.0f}s)",file=sys.stderr)
        except Exception as ex:
            print(f"  X翻译 {s['name'][:22]}: {type(ex).__name__}",file=sys.stderr)
    print(f"[完成] 共 {len(out['episodes'])} 集",file=sys.stderr)
if __name__=="__main__": main()
