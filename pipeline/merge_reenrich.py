#!/usr/bin/env python3
"""通用回填: 把详细版 overview/analysis/social 按 url 覆盖到 latest.json 所有模块对应条目。"""
import json, os, sys, re, time
ROOT=os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LATEST=f"{ROOT}/docs/data/latest.json"
ENR=sys.argv[1] if len(sys.argv)>1 else "/tmp/reenrich.json"
def nu(u): return re.sub(r'^https?://','',u or '').rstrip('/').lower().split('?')[0]

data=json.load(open(LATEST))
enr=json.load(open(ENR))
if isinstance(enr,dict): enr=enr.get('enriched',enr.get('items',[]))
emap={nu(e['url']):e for e in enr if e.get('url') and e.get('analysis')}
print(f"收到详细加工 {len(emap)} 条")

filled=0; bymod={}
for mk,mod in data['modules'].items():
    for it in mod.get('items',[]):
        e=emap.get(nu(it.get('url','')))
        if not e: continue
        if e.get('overview'): it['overview']=e['overview'].strip()
        if e.get('analysis'): it['analysis']=e['analysis'].strip()
        if e.get('social'):
            sl=[{"who":(s.get('who') or '网友').strip(),"text":(s.get('text') or '').strip()} for s in e['social'] if s.get('text')]
            if sl: it['social']=sl
        filled+=1; bymod[mk]=bymod.get(mk,0)+1

data['generated_at']=time.strftime("%Y-%m-%dT%H:%M:%S+08:00")
json.dump(data,open(LATEST,'w'),ensure_ascii=False,indent=2)
print(f"✅ 回填 {filled} 条: {bymod}")
# 复核详细度
m=data['modules']
for k in ['ai','github','hot','libraries']:
    its=m[k]['items']; bare=sum(1 for i in its if not i.get('analysis'))
    ov=[len(i.get('overview','')) for i in its if i.get('overview')]
    an=[len(i.get('analysis','')) for i in its if i.get('analysis')]
    avg=lambda x:sum(x)/len(x) if x else 0
    print(f"  {k:10}: {len(its)}条 无分析{bare} 概述均{avg(ov):.0f} 分析均{avg(an):.0f}")
