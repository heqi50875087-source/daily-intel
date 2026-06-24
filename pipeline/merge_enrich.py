#!/usr/bin/env python3
"""把 workflow 产出的 概述/分析/社媒(/tmp/enrich.json)按 url 回填进 latest.json 的 libraries.items。"""
import json, os, sys, re, time
ROOT=os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LATEST=f"{ROOT}/docs/data/latest.json"
ENR=sys.argv[1] if len(sys.argv)>1 else "/tmp/enrich.json"

def nu(u): return re.sub(r'^https?://','',u or '').rstrip('/').lower().split('?')[0]

data=json.load(open(LATEST))
items=data['modules']['libraries']['items']
enr=json.load(open(ENR))
if isinstance(enr,dict): enr=enr.get('enriched',enr.get('items',[]))
emap={nu(e['url']):e for e in enr if e.get('url')}
print(f"items {len(items)} 条, 收到加工 {len(emap)} 条")

filled=0
for it in items:
    e=emap.get(nu(it.get('url','')))
    if not e: continue
    if e.get('overview'): it['overview']=e['overview'].strip()
    if e.get('analysis'): it['analysis']=e['analysis'].strip()
    if e.get('social'):
        sl=[{"who":(s.get('who') or '网友').strip(),"text":(s.get('text') or '').strip()}
            for s in e['social'] if s.get('text')]
        if sl: it['social']=sl
    filled+=1

data['generated_at']=time.strftime("%Y-%m-%dT%H:%M:%S+08:00")
json.dump(data,open(LATEST,'w'),ensure_ascii=False,indent=2)
# 统计
has_ana=sum(1 for it in items if it.get('analysis'))
has_soc=sum(1 for it in items if it.get('social'))
print(f"✅ 回填 {filled} 条 | 有分析 {has_ana} | 有社媒 {has_soc}")
# 抽样
for it in items[:2]:
    if it.get('analysis'):
        print(f"\n· {it['title_zh'][:30]}")
        print(f"  概述: {it.get('overview','')[:60]}...")
        print(f"  分析: {it.get('analysis','')[:60]}...")
        print(f"  社媒: {len(it.get('social',[]))}条 — {it['social'][0]['who'] if it.get('social') else ''}: {it['social'][0]['text'][:40] if it.get('social') else ''}")
