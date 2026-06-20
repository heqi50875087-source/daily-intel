#!/usr/bin/env python3
"""数据源:RSS(AI / 图书馆) + Apple Podcasts(iTunes)。引擎无关,只负责抓原始素材。"""
import time, html, re, requests, feedparser

UA = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) intel-bot/1.0"}

AI_FEEDS = [
    ("MIT Tech Review", "https://www.technologyreview.com/feed/"),
    ("VentureBeat AI", "https://venturebeat.com/category/ai/feed/"),
    ("The Verge", "https://www.theverge.com/rss/index.xml"),
    ("Ars Technica", "https://feeds.arstechnica.com/arstechnica/index"),
    ("TechCrunch AI", "https://techcrunch.com/category/artificial-intelligence/feed/"),
    ("Google Blog AI", "https://blog.google/technology/ai/rss/"),
    ("Hugging Face", "https://huggingface.co/blog/feed.xml"),
    ("arXiv cs.AI", "https://export.arxiv.org/rss/cs.AI"),
]
LIB_FEEDS = [
    ("IFLA", "https://www.ifla.org/feed/"),
    ("American Libraries", "https://americanlibrariesmagazine.org/feed/"),
    ("Library Journal", "https://www.libraryjournal.com/feed"),
    ("School Library Journal", "https://www.slj.com/feed"),
    ("C&RL News", "https://crln.acrl.org/index.php/crlnews/gateway/plugin/WebFeedGatewayPlugin/rss2"),
    ("Lead Pipe", "https://www.inthelibrarywiththeleadpipe.org/feed/"),
]
PODCAST_REGIONS = [
    ("美国", "US", "artificial intelligence"), ("英国", "GB", "artificial intelligence"),
    ("日本", "JP", "テクノロジー"), ("德国", "DE", "Technologie"),
    ("澳洲", "AU", "technology"), ("新加坡", "SG", "technology"), ("中国", "CN", "科技"),
]

def _clean(s, n=500):
    s = re.sub(r"<[^>]+>", "", s or "")
    s = html.unescape(s)
    return re.sub(r"\s+", " ", s).strip()[:n]

def _date(e):
    t = e.get("published_parsed") or e.get("updated_parsed")
    return time.strftime("%Y-%m-%d", t) if t else ""

def fetch_feed(name, url, limit=6):
    try:
        r = requests.get(url, timeout=15, headers=UA)
        d = feedparser.parse(r.content)
        return [{"source": name, "title": _clean(e.get("title", ""), 200),
                 "summary": _clean(e.get("summary", "") or e.get("description", "")),
                 "url": e.get("link", ""), "published": _date(e)}
                for e in d.entries[:limit] if e.get("title")]
    except Exception:
        return []

def fetch_many(feeds, per=5):
    out = []
    for name, url in feeds:
        out += fetch_feed(name, url, per)
    return out

def fetch_ai(per=5):
    return fetch_many(AI_FEEDS, per)

def fetch_libraries(per=5):
    return fetch_many(LIB_FEEDS, per)

def fetch_podcasts(limit=4):
    raw = {}
    for zh, cc, term in PODCAST_REGIONS:
        try:
            r = requests.get("https://itunes.apple.com/search",
                             params={"term": term, "entity": "podcast", "country": cc, "limit": limit}, timeout=20)
            raw[zh] = [{"podcast": x.get("collectionName"), "host": x.get("artistName"),
                        "genre": x.get("primaryGenreName"), "url": x.get("trackViewUrl")}
                       for x in r.json().get("results", []) if x.get("collectionName")]
        except Exception:
            raw[zh] = []
        time.sleep(0.25)
    return raw

CN_LIB_QUERIES = ["智慧图书馆", "公共图书馆 服务 创新", "图书馆 人工智能"]

def fetch_cn_library(max_each=4):
    """中文图书馆动态(DuckDuckGo 新闻, 免费无 key)。失败返回 []。"""
    try:
        from ddgs import DDGS
    except Exception:
        try:
            from duckduckgo_search import DDGS
        except Exception:
            return []
    out, seen = [], set()
    try:
        with DDGS() as d:
            for q in CN_LIB_QUERIES:
                for r in d.news(query=q, region="cn-zh", max_results=max_each):
                    u = r.get("url") or r.get("href") or ""
                    if not u or u in seen:
                        continue
                    seen.add(u)
                    out.append({"source": r.get("source") or "中文媒体",
                                "title": (r.get("title") or "")[:200],
                                "summary": (r.get("body") or "")[:500],
                                "url": u, "published": (r.get("date") or "")[:10]})
    except Exception:
        return out
    return out

if __name__ == "__main__":
    ai = fetch_ai(); lib = fetch_libraries(); pod = fetch_podcasts(); cn = fetch_cn_library()
    print("AI 条目:", len(ai), "| 来源:", sorted({i["source"] for i in ai}))
    print("图书馆条目:", len(lib), "| 来源:", sorted({i["source"] for i in lib}))
    print("中国馆界(搜索):", len(cn))
    print("播客地区:", {k: len(v) for k, v in pod.items()})
