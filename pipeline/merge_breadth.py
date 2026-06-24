#!/usr/bin/env python3
"""把 breadth workflow 的采集结果(/tmp/breadth.json: {byTask:{...}})整合进 latest.json。
GitHub工具→github栏; AI新闻→扩充ai; 中国热点+国际热点→hot栏(两筛选中国/国外); 跨行业灵感→图书馆栏。"""
import json, os, sys, re, time
from collections import Counter
ROOT=os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LATEST=f"{ROOT}/docs/data/latest.json"
SRC=sys.argv[1] if len(sys.argv)>1 else "/tmp/breadth.json"

def nu(u): return re.sub(r'^https?://','',u or '').rstrip('/').lower().split('?')[0]
def clean(it, **ov):
    if not it or not it.get('url') or not it.get('title_zh'): return None
    d={k:(it.get(k) or '') for k in ['title_zh','eng','summary','source','region','scope','stars','lang','published','overview','analysis']}
    d['url']=it['url'].strip(); d['published']=d['published'][:10]
    soc=it.get('social') or []
    d['social']=[{"who":(s.get('who') or '网友').strip(),"text":(s.get('text') or '').strip()} for s in soc if s.get('text')]
    d.update(ov)
    return {k:v for k,v in d.items() if v not in ('',[],None) or k in ('region',)}

data=json.load(open(LATEST)); mods=data['modules']
bt=json.load(open(SRC)); bt=bt.get('byTask',bt)

def dedup(items):
    seen=set(); out=[]
    for it in items:
        if not it: continue
        k=nu(it.get('url',''))
        if k and k not in seen: seen.add(k); out.append(it)
    return out

# 1) GitHub工具 → github栏
gh=dedup([clean(x,region="全球") for x in bt.get('GitHub工具',[])])
mods['github']={"items":gh}

# 2) AI新闻 → 扩充ai(原有在前保留, 新的去重追加)
ai_old=mods.get('ai',{}).get('items',[])
ai_new=dedup([clean(x) for x in bt.get('AI新闻',[])])
seen={nu(i.get('url','')) for i in ai_old}
mods.setdefault('ai',{})['items']=ai_old+[i for i in ai_new if nu(i['url']) not in seen]

# 3) 中国热点+国际热点 → hot栏(强制region两值: 中国/国外)
hot_cn=[clean(x,region="中国") for x in bt.get('中国热点',[])]
hot_in=[clean(x,region="国外") for x in bt.get('国际热点',[])]
hot=dedup(hot_cn+hot_in)
hot.sort(key=lambda x:x.get('published',''),reverse=True)
mods['hot']={"items":hot,"regions":["中国","国外"]}

# 4) 跨行业灵感 → 图书馆栏(追加, scope标记)
lib=mods['libraries']['items']
insp=dedup([clean(x,scope=x.get('scope') or 'special') for x in bt.get('跨行业灵感',[])])
seen={nu(i.get('url','')) for i in lib}
add=[i for i in insp if nu(i['url']) not in seen]
lib2=lib+add
rc=Counter(x.get('region','') for x in lib2)
order=['中国','全球']; regions=[r for r in order if r in rc]+[r for r,_ in rc.most_common() if r not in order]
mods['libraries']['items']=lib2; mods['libraries']['regions']=regions

data['generated_at']=time.strftime("%Y-%m-%dT%H:%M:%S+08:00")
json.dump(data,open(LATEST,'w'),ensure_ascii=False,indent=2)

print(f"✅ 整合完成:")
print(f"   GitHub工具: {len(gh)} 条")
print(f"   AI进展: {len(mods['ai']['items'])} 条 (新增{len(mods['ai']['items'])-len(ai_old)})")
print(f"   实时热点: {len(hot)} 条 (中国{sum(1 for i in hot if i['region']=='中国')}/国外{sum(1 for i in hot if i['region']=='国外')})")
print(f"   图书馆: {len(lib2)} 条 (+灵感{len(add)})")
for it in gh[:2]:
    print(f"   · GitHub: {it['title_zh'][:34]} ★{it.get('stars','')}")
