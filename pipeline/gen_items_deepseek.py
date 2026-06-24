#!/usr/bin/env python3
"""用 DeepSeek(直连,绕开卡住的代理节点)把真实事实扩写成富资讯条目。
输入: JSON 配置文件 [{module,region,published_hint,facts,urls,n}, ...]
输出: {byMod:{module:[items]}} → 指定文件。严格基于提供的事实与真实URL,不编造。"""
import os, sys, json, re, requests, time
HERE=os.path.dirname(os.path.abspath(__file__))
if "DEEPSEEK_API_KEY" not in os.environ:
    for line in open(os.path.join(HERE,".env")):
        if line.startswith("DEEPSEEK_API_KEY"): os.environ["DEEPSEEK_API_KEY"]=line.split("=",1)[1].strip()
KEY=os.environ["DEEPSEEK_API_KEY"]
for k in ("HTTP_PROXY","HTTPS_PROXY","http_proxy","https_proxy"): os.environ.pop(k,None)

SYS=("你是资深中文资讯编辑。我会给你某一主题的【真实事实】和【可用真实URL列表】。"
     "请据此产出 JSON 数组,每个元素是一条资讯,字段:"
     "title_zh(中文标题)、eng(原文名,可空)、summary(1-2句简介)、source(来源)、"
     "region(我指定的子类标签,原样填)、published(YYYY-MM-DD)、url(从URL列表里选一个最贴切的,每条尽量不同,严禁编造新URL)、"
     "overview(详尽概述4-7句,基于事实展开,信息密度高)、analysis(我的分析3-5句,有观点有洞察)、"
     "social(3-4条,每条{who:视角标签如资深球迷/玩家/解说/研究者等不要真人姓名, text:1-2句评论,观点有交锋))。"
     "硬约束:① 只用我给的事实,不确定的不写、不编造比分或事件;② url 必须来自我给的列表;③ 只输出 JSON 数组,无任何解释或markdown标记。")

def gen(cfg):
    user=(f"主题: {cfg['module']} / 子类region='{cfg['region']}'\n"
          f"参考日期: {cfg.get('published_hint','2026-06')}\n"
          f"需要 {cfg['n']} 条。\n\n【真实事实】\n{cfg['facts']}\n\n【可用真实URL列表】\n"+
          "\n".join(cfg['urls']))
    for a in range(3):
        try:
            r=requests.post("https://api.deepseek.com/chat/completions",
                headers={"Authorization":f"Bearer {KEY}"},
                json={"model":"deepseek-chat","temperature":0.6,
                      "messages":[{"role":"system","content":SYS},{"role":"user","content":user}]},
                timeout=180)
            r.raise_for_status()
            txt=r.json()["choices"][0]["message"]["content"].strip()
            txt=re.sub(r'^```(json)?|```$','',txt,flags=re.M).strip()
            m=re.search(r'\[.*\]', txt, re.S)
            arr=json.loads(m.group(0) if m else txt)
            # 强制 region
            for it in arr: it['region']=cfg['region']
            return arr
        except Exception as e:
            if a==2: print(f"  ✗ {cfg['region']}: {type(e).__name__} {str(e)[:60]}", file=sys.stderr); return []
            time.sleep(3)

def main():
    cfgs=json.load(open(sys.argv[1]))
    out_path=sys.argv[2] if len(sys.argv)>2 else "/tmp/gen_out.json"
    byMod={}
    for cfg in cfgs:
        items=gen(cfg)
        byMod.setdefault(cfg['module'],[]).extend(items)
        print(f"  ✓ {cfg['module']}/{cfg['region']}: {len(items)} 条", file=sys.stderr)
    json.dump({"byMod":byMod}, open(out_path,'w'), ensure_ascii=False, indent=2)
    print(f"→ {out_path}", file=sys.stderr)

if __name__=="__main__": main()
