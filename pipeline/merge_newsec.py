#!/usr/bin/env python3
"""整合新板块内容进 latest.json。输入 JSON: {modKey:[items...]} 或 {byMod:{...}}。
模块: kidlit/research/creative/sports/games。按url去重、按日期倒序、补regions(sports/kidlit)。"""
import json, os, sys, re, time
from collections import Counter
ROOT=os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LATEST=f"{ROOT}/docs/data/latest.json"
SRC=sys.argv[1] if len(sys.argv)>1 else "/tmp/newsec.json"
def nu(u): return re.sub(r'^https?://','',u or '').rstrip('/').lower().split('?')[0]
def clean(it):
    if not it or not it.get('url') or not it.get('title_zh'): return None
    d={k:(it.get(k) or '') for k in ['title_zh','eng','summary','source','region','scope','published','overview','analysis']}
    d['url']=it['url'].strip(); d['published']=d['published'][:10]
    soc=it.get('social') or []
    d['social']=[{"who":(s.get('who') or '网友').strip(),"text":(s.get('text') or '').strip()} for s in soc if s.get('text')]
    return {k:v for k,v in d.items() if v not in ('',[],None) or k=='region'}

data=json.load(open(LATEST)); mods=data['modules']
src=json.load(open(SRC))
bm=src.get('byMod',src)  # 支持 {byMod:{...}} 或直接 {mod:[...]}

# sports/kidlit 的 region 作为子类筛选
REGION_ORDER={'sports':['羽毛球','乒乓球','足球'],'games':['DOTA2','Switch','综合'],'kidlit':['中国','全球']}
for mk, items in bm.items():
    if not isinstance(items,list) or not items: continue
    cur=mods.get(mk,{}).get('items',[])
    seen={nu(i.get('url','')) for i in cur}
    add=[]
    for it in items:
        c=clean(it)
        if not c or nu(c['url']) in seen: continue
        seen.add(nu(c['url'])); add.append(c)
    allit=cur+add
    allit.sort(key=lambda x:x.get('published',''), reverse=True)
    mods[mk]={"items":allit}
    # 子类筛选chip
    rc=Counter(x.get('region','') for x in allit)
    order=REGION_ORDER.get(mk,[])
    regions=[r for r in order if r in rc]+[r for r,_ in rc.most_common() if r not in order]
    if len(regions)>=2: mods[mk]["regions"]=regions
    print(f"  {mk}: +{len(add)} → {len(allit)}条  region={regions[:5]}")

data['generated_at']=time.strftime("%Y-%m-%dT%H:%M:%S+08:00")
json.dump(data,open(LATEST,'w'),ensure_ascii=False,indent=2)
print("✅ 整合完成")
