#!/usr/bin/env python3
"""扩充内容整合: AI数字→ai, GitHub工具→github, 中国/国际资讯→hot。带URL核验(丢死链)。"""
import json, os, sys, re, time, requests, concurrent.futures, warnings
warnings.filterwarnings("ignore")
ROOT=os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LATEST=f"{ROOT}/docs/data/latest.json"
SRC=sys.argv[1] if len(sys.argv)>1 else "/tmp/expand.json"
UA={'User-Agent':'Mozilla/5.0 (Macintosh)'}
PROXY={'http':'http://127.0.0.1:18080','https':'http://127.0.0.1:18080'}
def nu(u): return re.sub(r'^https?://','',u or '').rstrip('/').lower().split('?')[0]

def alive(url):
    """死链(404/DNS失败)返回False; 200/403/429/超时等当作存活(反爬非假链)"""
    for px in [None,PROXY]:
        try:
            r=requests.head(url,headers=UA,timeout=10,allow_redirects=True,proxies=px)
            if r.status_code==404: return False
            if r.status_code in (200,301,302,403,405,429): return True
            if r.status_code==405:
                r=requests.get(url,headers=UA,timeout=10,stream=True,proxies=px); return r.status_code!=404
            return True
        except requests.exceptions.ConnectionError: continue
        except Exception: return True  # 超时等不算假链
    return False  # 两种方式都连不上→疑似死链

def clean(it,**ov):
    if not it or not it.get('url') or not it.get('title_zh'): return None
    d={k:(it.get(k) or '') for k in ['title_zh','eng','summary','source','region','scope','stars','lang','published','overview','analysis']}
    d['url']=it['url'].strip(); d['published']=d['published'][:10]
    soc=it.get('social') or []
    d['social']=[{"who":(s.get('who') or '网友').strip(),"text":(s.get('text') or '').strip()} for s in soc if s.get('text')]
    d.update(ov)
    return {k:v for k,v in d.items() if v not in ('',[],None) or k=='region'}

data=json.load(open(LATEST)); mods=data['modules']
bt=json.load(open(SRC))

# 收集所有url并发核验
allitems=[]
for task in bt.values():
    for it in task:
        if it.get('url'): allitems.append(it['url'])
print(f"核验 {len(allitems)} 个URL...")
dead=set()
with concurrent.futures.ThreadPoolExecutor(max_workers=10) as ex:
    futs={ex.submit(alive,u):u for u in allitems}
    for f in concurrent.futures.as_completed(futs):
        if not f.result(): dead.add(futs[f])
print(f"死链 {len(dead)} 个(已丢弃)")

def route(items,**ov):
    out=[]
    for it in items:
        if it.get('url') in dead: continue
        c=clean(it,**ov)
        if c: out.append(c)
    return out

def append(modkey, newitems, regions=None):
    cur=mods.setdefault(modkey,{}).get('items',[])
    seen={nu(i.get('url','')) for i in cur}
    add=[i for i in newitems if nu(i['url']) not in seen]
    mods[modkey]['items']=cur+add
    if regions: mods[modkey]['regions']=regions
    return len(add)

a1=append('ai', route(bt.get('AI数字',[])))
a2=append('github', route(bt.get('GitHub工具',[]), region="全球"))
hot_cn=route(bt.get('中国资讯',[]), region="中国")
hot_in=route(bt.get('国际资讯',[]), region="国外")
a3=append('hot', hot_cn+hot_in, regions=["中国","国外"])
# hot按日期排序
mods['hot']['items'].sort(key=lambda x:x.get('published',''), reverse=True)

data['generated_at']=time.strftime("%Y-%m-%dT%H:%M:%S+08:00")
json.dump(data,open(LATEST,'w'),ensure_ascii=False,indent=2)
print(f"✅ 整合: AI+{a1}→{len(mods['ai']['items'])} | GitHub+{a2}→{len(mods['github']['items'])} | 热点+{a3}→{len(mods['hot']['items'])}")
