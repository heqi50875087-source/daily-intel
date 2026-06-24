#!/usr/bin/env python3
"""绕开音频下载: 抓官网完整文字稿 → 整篇翻译 → 更新 podcast_app.json。
适用于发布免费文字稿的播客(Lex Fridman / Tim Ferriss 等)。
用法: python podcast_transcript.py "<show匹配子串>" "<transcript_url>"
"""
import os, sys, json, re, time, requests, warnings
from concurrent.futures import ThreadPoolExecutor, as_completed
warnings.filterwarnings("ignore")
HERE=os.path.dirname(os.path.abspath(__file__))
APP=os.path.join(os.path.dirname(HERE),"docs/data/podcast_app.json")
UA={'User-Agent':'Mozilla/5.0 (Macintosh)'}
PROXY={'http':'http://127.0.0.1:18080','https':'http://127.0.0.1:18080'}
if "DEEPSEEK_API_KEY" not in os.environ:
    for line in open(os.path.join(HERE,".env")):
        if line.startswith("DEEPSEEK_API_KEY"): os.environ["DEEPSEEK_API_KEY"]=line.split("=",1)[1].strip()
KEY=os.environ["DEEPSEEK_API_KEY"]

def fetch(url):
    for px in [None,PROXY]:
        try:
            r=requests.get(url,headers=UA,timeout=30,proxies=px)
            if r.status_code==200 and len(r.text)>5000: return r.text
        except: pass
    return None

def extract(html):
    """抽文字稿: 优先 Lex 的 ts-text span, 否则正文 <p>。过滤过短/样板段。"""
    segs=re.findall(r'<span class="ts-text">(.*?)</span>', html, re.S)
    if len(segs)<10:
        body=re.search(r'class="[^"]*entry-content[^"]*"[^>]*>(.*?)</(?:div|article)>\s*(?:<footer|</article)', html, re.S)
        seg_src=body.group(1) if body else html
        segs=re.findall(r'<p[^>]*>(.*?)</p>', seg_src, re.S)
    clean=[]
    for s in segs:
        t=re.sub(r'<[^>]+>','',s)
        t=re.sub(r'&#8217;|&#8216;',"'",t); t=re.sub(r'&#8220;|&#8221;','"',t)
        t=re.sub(r'&#8230;','...',t); t=re.sub(r'&amp;','&',t); t=re.sub(r'&nbsp;',' ',t)
        t=t.strip()
        if len(t)>15 and not t.lower().startswith(('subscribe','sign up','get the','this episode is brought')):
            clean.append(t)
    text=re.sub(r'\s+',' '," ".join(clean)).strip()
    return text

def split_text(t,size=3500):
    sents=re.split(r'(?<=[.!?])\s+',t); chunks=[];cur=""
    for s in sents:
        if len(cur)+len(s)>size and cur: chunks.append(cur);cur=s
        else: cur=(cur+" "+s).strip()
    if cur: chunks.append(cur)
    return chunks

def tr(c):
    sysp=("你是专业中英翻译。把这段英文播客转写翻成流畅自然的简体中文,忠实原意、不遗漏、不加评论;口语适当顺滑成书面中文。只输出中文译文。")
    for a in range(3):
        try:
            r=requests.post("https://api.deepseek.com/chat/completions",headers={"Authorization":f"Bearer {KEY}"},
                json={"model":"deepseek-chat","temperature":0.3,"messages":[{"role":"system","content":sysp},{"role":"user","content":c}]},timeout=180)
            r.raise_for_status(); return r.json()["choices"][0]["message"]["content"].strip()
        except Exception:
            if a==2: return "[翻译失败]"
            time.sleep(3)

def main():
    show_q, url = sys.argv[1], sys.argv[2]
    for k in ("HTTP_PROXY","HTTPS_PROXY","http_proxy","https_proxy"): os.environ.pop(k,None)
    print(f"抓取文字稿: {url}", file=sys.stderr)
    html=fetch(url)
    if not html: print("✗ 抓取失败"); return
    en=extract(html)
    print(f"提取英文稿 {len(en)}字符 ({len(en.split())}词)", file=sys.stderr)
    if len(en)<3000: print("✗ 文字稿过短(可能付费墙)"); return
    chunks=split_text(en)
    print(f"分 {len(chunks)} 段并行翻译...", file=sys.stderr)
    parts=[None]*len(chunks)
    with ThreadPoolExecutor(max_workers=6) as ex:
        futs={ex.submit(tr,c):i for i,c in enumerate(chunks)}
        done=0
        for f in as_completed(futs):
            parts[futs[f]]=f.result(); done+=1
            if done%10==0: print(f"  {done}/{len(chunks)}",file=sys.stderr)
    zh="\n\n".join(p for p in parts if p)
    fail=sum(1 for p in parts if p=="[翻译失败]")
    d=json.load(open(APP))
    hit=None
    for kk,v in d['episodes'].items():
        if show_q.lower() in v.get('show','').lower(): hit=v; break
    if not hit: print(f"✗ 未找到匹配 '{show_q}' 的集"); return
    old=len(hit.get('zh_full',''))
    hit['zh_full']=zh; hit['truncated']=False; hit['transcript_source']=url
    d['generated']=time.strftime("%Y-%m-%d %H:%M")
    json.dump(d,open(APP,'w'),ensure_ascii=False,indent=2)
    print(f"✅ {hit['show'][:24]}: {old}字 → {len(zh)}字 完整版 (失败{fail}段)")

if __name__=="__main__": main()
