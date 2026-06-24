#!/usr/bin/env python3
"""每日自动补全: 对发布免费官网文字稿的档(Lex Fridman / Tim Ferriss 等),
自动找到最新集的文字稿地址 → 抓取 → 整篇翻译 → 覆盖截断版。幂等(已补全的跳过)。
由 run_podcast_daily.sh 在 podcast_pipeline 之后调用。"""
import os, sys, json, re, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from podcast_transcript import fetch, extract, split_text, tr  # 复用
from concurrent.futures import ThreadPoolExecutor, as_completed

HERE=os.path.dirname(os.path.abspath(__file__))
# 默认作用于持久源 podcast_work(每日 cp 到 docs/data); 可传参覆盖
APP=sys.argv[1] if len(sys.argv)>1 else os.path.join(HERE,"podcast_work/podcast_app.json")
# 发布免费完整文字稿的档(精确show名)
TRANSCRIPT_SHOWS={"Lex Fridman Podcast","The Tim Ferriss Show"}

def find_transcript_url(ep):
    """据单集网页找文字稿地址"""
    link=(ep.get('link') or '').strip()
    show=ep.get('show','')
    # Lex: 嘉宾页 + '-transcript'
    if 'lexfridman.com' in link:
        cand=link.rstrip('/')+'-transcript/'
        return cand
    # 通用: 抓单集页, 找含 transcript 的链接
    if not link: return None
    html=fetch(link)
    if not html: return None
    # 找 <a href=...transcript...>
    cands=re.findall(r'href="([^"]*transcript[^"]*)"', html, re.I)
    for c in cands:
        if c.startswith('http') and 'comment' not in c.lower():
            return c
    return None

def complete_one(key, ep):
    url=find_transcript_url(ep)
    if not url: return (key, None, "未找到文字稿地址")
    html=fetch(url)
    if not html: return (key, None, f"抓取失败 {url}")
    en=extract(html)
    if len(en)<3000: return (key, None, f"文字稿过短({len(en)},疑付费墙)")
    chunks=split_text(en)
    parts=[None]*len(chunks)
    with ThreadPoolExecutor(max_workers=6) as ex:
        futs={ex.submit(tr,c):i for i,c in enumerate(chunks)}
        for f in as_completed(futs): parts[futs[f]]=f.result()
    zh="\n\n".join(p for p in parts if p)
    return (key, {"zh_full":zh,"truncated":False,"transcript_source":url,"en_chars":len(en)}, "ok")

def main():
    for k in ("HTTP_PROXY","HTTPS_PROXY","http_proxy","https_proxy"): os.environ.pop(k,None)
    d=json.load(open(APP)); eps=d['episodes']
    todo=[]
    for key,ep in eps.items():
        if ep.get('show') not in TRANSCRIPT_SHOWS: continue
        # 幂等: 已是文字稿来源且足够长 → 跳过
        if ep.get('transcript_source') and len(ep.get('zh_full',''))>15000:
            print(f"  · 已完整, 跳过 {ep['show'][:20]}", file=sys.stderr); continue
        todo.append((key,ep))
    if not todo:
        print("[完成] 无需补全的文字稿集", file=sys.stderr); return
    print(f"待补全 {len(todo)} 集", file=sys.stderr)
    for key,ep in todo:
        try:
            _,upd,msg=complete_one(key,ep)
            if upd:
                old=len(ep.get('zh_full',''))
                eps[key].update(upd)
                d['generated']=time.strftime("%Y-%m-%d %H:%M")
                json.dump(d,open(APP,'w'),ensure_ascii=False,indent=2)
                print(f"  ✓ {ep['show'][:20]}: {old}→{len(upd['zh_full'])}字 完整版", file=sys.stderr)
            else:
                print(f"  ✗ {ep['show'][:20]}: {msg}", file=sys.stderr)
        except Exception as e:
            print(f"  ✗ {ep['show'][:20]}: {type(e).__name__} {str(e)[:50]}", file=sys.stderr)
    print("[完成]", file=sys.stderr)

if __name__=="__main__": main()
