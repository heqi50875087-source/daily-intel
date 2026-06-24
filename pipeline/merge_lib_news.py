#!/usr/bin/env python3
"""把 workflow 收集的图书馆新闻 (/tmp/lib_items.json) 合并进 docs/data/latest.json。
去重(按url)、规范scope/region、按日期排序、更新地区筛选。保留少量原有条目。"""
import json, os, sys, time, re

ROOT=os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LATEST=f"{ROOT}/docs/data/latest.json"
NEW=sys.argv[1] if len(sys.argv)>1 else "/tmp/lib_items.json"

VALID_SCOPE={"academic","public","children","national","tech","policy","special"}
def norm_url(u): return re.sub(r'^https?://','',u or '').rstrip('/').lower().split('?')[0]

def clean(it):
    """规范一条目, 不合格返回None"""
    if not it or not it.get('url') or not it.get('title_zh'): return None
    sc=it.get('scope','')
    if sc not in VALID_SCOPE: sc='public'
    return {
        "title_zh": it['title_zh'].strip(),
        "eng": (it.get('eng') or '').strip(),
        "summary": (it.get('summary') or '').strip(),
        "source": (it.get('source') or '').strip(),
        "region": (it.get('region') or '全球').strip(),
        "scope": sc,
        "published": (it.get('published') or '').strip()[:10],
        "url": it['url'].strip(),
    }

def main():
    data=json.load(open(LATEST))
    lib=data['modules']['libraries']
    old=lib.get('items',[])
    new=json.load(open(NEW))
    if isinstance(new,dict): new=new.get('items',[])
    print(f"原有 {len(old)} 条, 新收集 {len(new)} 条")

    seen=set(); merged=[]
    # 新条目优先(更鲜), 再补原有未重复的
    for it in new:
        c=clean(it)
        if not c: continue
        k=norm_url(c['url'])
        if k in seen: continue
        seen.add(k); merged.append(c)
    kept_old=0
    for it in old:
        c=clean(it)
        if not c: continue
        k=norm_url(c['url'])
        if k in seen: continue
        seen.add(k); merged.append(c); kept_old+=1

    # 按日期倒序
    merged.sort(key=lambda x:x.get('published',''), reverse=True)
    merged=merged[:48]  # 上限48条

    # 地区筛选chip: 中国/全球优先, 其余按出现频率
    from collections import Counter
    rc=Counter(x['region'] for x in merged)
    order=['中国','全球']
    regions=[r for r in order if r in rc]+[r for r,_ in rc.most_common() if r not in order]

    lib['items']=merged
    lib['regions']=regions
    data['generated_at']=time.strftime("%Y-%m-%dT%H:%M:%S+08:00")
    data['date']=time.strftime("%Y-%m-%d")
    json.dump(data,open(LATEST,'w'),ensure_ascii=False,indent=2)

    print(f"✅ 合并完成: 共 {len(merged)} 条 (新{len(merged)-kept_old} + 保留旧{kept_old})")
    print(f"   地区: {regions}")
    from collections import Counter as C
    print(f"   scope分布: {dict(C(x['scope'] for x in merged))}")
    print(f"   region分布: {dict(rc)}")
    # 抽样展示
    print("\n   最新5条:")
    for x in merged[:5]:
        print(f"   · [{x['published']}|{x['region']}|{x['scope']}] {x['title_zh'][:36]} ({x['source']})")

if __name__=="__main__": main()
