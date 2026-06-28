#!/usr/bin/env python3
"""数据源:RSS(AI / 图书馆) + Apple Podcasts(iTunes)。引擎无关,只负责抓原始素材。"""
import time, html, re, datetime, requests, feedparser

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

SPORTS_FEEDS = {
    "足球·世界杯": [
        ("BBC Football", "http://feeds.bbci.co.uk/sport/football/rss.xml"),
        ("Guardian Football", "https://www.theguardian.com/football/rss"),
    ],
    "羽毛球": [
        ("BBC Badminton", "http://feeds.bbci.co.uk/sport/badminton/rss.xml"),
    ],
    "乒乓球": [
        ("BBC Table Tennis", "http://feeds.bbci.co.uk/sport/table-tennis/rss.xml"),
    ],
    "综合": [
        ("BBC Sport", "http://feeds.bbci.co.uk/sport/rss.xml"),
        ("Guardian Sport", "https://www.theguardian.com/sport/rss"),
        ("BBC Tennis", "http://feeds.bbci.co.uk/sport/tennis/rss.xml"),
        ("BBC Basketball", "http://feeds.bbci.co.uk/sport/basketball/rss.xml"),
        ("BBC Olympics", "http://feeds.bbci.co.uk/sport/olympics/rss.xml"),
        ("China Daily Sports", "http://www.chinadaily.com.cn/rss/sports_rss.xml"),
    ],
}

def fetch_sports(per=6):
    """体育:按子类(足球世界杯/羽毛球/乒乓球/综合)分组抓取,复用 fetch_feed。"""
    out = {}
    for sub, feeds in SPORTS_FEEDS.items():
        items = []
        for name, url in feeds:
            items += fetch_feed(name, url, per)
        out[sub] = items
    return out

HOT_FEEDS = {
    "国外": [
        ("BBC News", "http://feeds.bbci.co.uk/news/rss.xml"),
        ("Guardian World", "https://www.theguardian.com/world/rss"),
        ("China Daily World", "http://www.chinadaily.com.cn/rss/world_rss.xml"),
    ],
    "中国": [
        ("China Daily", "http://www.chinadaily.com.cn/rss/china_rss.xml"),
        ("36氪", "https://36kr.com/feed"),
    ],
}

def fetch_github(days=7, n=15):
    """GitHub 最近 days 天创建的高星新项目(官方 Search API,无需 key)。"""
    since = (datetime.date.today() - datetime.timedelta(days=days)).isoformat()
    try:
        r = requests.get("https://api.github.com/search/repositories",
                         params={"q": f"created:>{since}", "sort": "stars", "order": "desc", "per_page": n},
                         timeout=20, headers=UA)
        return [{"source": "GitHub", "title": it.get("full_name", ""),
                 "summary": (it.get("description") or "")[:300],
                 "stars": it.get("stargazers_count", 0), "lang": it.get("language") or "",
                 "url": it.get("html_url", ""), "published": (it.get("created_at") or "")[:10]}
                for it in r.json().get("items", []) if it.get("full_name")]
    except Exception:
        return []

def fetch_hot(per=6):
    """实时热点:按 中国/国外 分组抓取,复用 fetch_feed。"""
    out = {}
    for region, feeds in HOT_FEEDS.items():
        items = []
        for name, url in feeds:
            items += fetch_feed(name, url, per)
        out[region] = items
    return out

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

LIB_CN_SITES = [
    ("中国图书馆学会", "http://www.lsc.org.cn/", "http://www.lsc.org.cn"),
    ("国家图书馆", "http://www.nlc.cn/", "http://www.nlc.cn"),
]
_LIB_CN_KW = ["讲座", "征集", "培训", "活动", "通知", "公告", "研讨", "论坛", "展览",
              "阅读推广", "报名", "倡议", "服务", "计划", "评选", "大赛", "书目", "会员"]

def fetch_cn_library_official(per=8):
    """中国图书馆学会/国图官网的活动·讲座·征集·培训(无 RSS,解析首页链接)。published 记抓取日,保证排前。"""
    today = datetime.date.today().isoformat()
    out = []
    for name, url, base in LIB_CN_SITES:
        try:
            r = requests.get(url, timeout=12, headers=UA)
            html = r.content.decode(r.apparent_encoding or "utf-8", errors="replace")
            links = re.findall(r'<a[^>]+href="([^"]+)"[^>]*>\s*([^<]{8,60})\s*</a>', html)
            seen, cnt = set(), 0
            for href, title in links:
                title = title.strip()
                if title in seen or not any(k in title for k in _LIB_CN_KW):
                    continue
                seen.add(title)
                full = href if href.startswith("http") else (base + href if href.startswith("/") else base + "/" + href)
                out.append({"source": name, "title": title[:200], "summary": title[:200], "url": full, "published": today})
                cnt += 1
                if cnt >= per:
                    break
        except Exception:
            continue
    return out

if __name__ == "__main__":
    ai = fetch_ai(); lib = fetch_libraries(); pod = fetch_podcasts(); cn = fetch_cn_library()
    print("AI 条目:", len(ai), "| 来源:", sorted({i["source"] for i in ai}))
    print("图书馆条目:", len(lib), "| 来源:", sorted({i["source"] for i in lib}))
    print("中国馆界(搜索):", len(cn))
    print("播客地区:", {k: len(v) for k, v in pod.items()})
