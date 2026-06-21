#!/usr/bin/env python3
"""把一集播客的英文转写 → 中文要点卡(标题/导读/要点/标签)。复用 llm.chat_json。"""
import sys, json, llm

def to_zh_brief(title_en, transcript):
    SYS = "你是资深中文播客编辑,擅长把英文播客提炼成让中国听众一看就懂的中文要点。只返回 JSON。"
    user = (
        "下面是一集英文播客的标题与自动转写文字(可能有口语和转写误差,请据上下文理解)。\n"
        f"标题: {title_en}\n\n转写: {transcript[:9000]}\n\n"
        "请输出中文要点卡,严格 JSON:\n"
        '{"title_zh":"中文标题(准确、有信息量)",'
        '"intro":"2-3句中文导读,说清这集到底在聊什么、为什么值得听",'
        '"points":["5-8条核心要点,每条一句完整中文,有具体信息不空泛"],'
        '"tags":["3个中文话题标签"]}'
    )
    return llm.chat_json(SYS, user)

if __name__ == "__main__":
    path = sys.argv[1] if len(sys.argv) > 1 else "podcast_work/ep.json"
    d = json.load(open(path))
    out = to_zh_brief(d.get("title", ""), d.get("en", ""))
    d["zh"] = out
    json.dump(d, open(path, "w"), ensure_ascii=False, indent=2)
    print(json.dumps(out, ensure_ascii=False, indent=2))
