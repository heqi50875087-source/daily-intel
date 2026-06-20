# 情报 · 每日情报简报 — 项目计划与说明

> 一个给何琦（上海少儿图书馆）个人使用的 PWA：每天自动汇集 **AI 进展 / 全球播客 / 图书馆 / 关键声音** 四大块，省掉到处搜集的功夫。

## 一、已锁定的方案（用户三轮确认）

| 维度 | 决定 |
|---|---|
| 形态 | **PWA**（响应式网页 + 加到主屏，日后可 Capacitor 打包成原生安装包） |
| 内容来源 | **AI 联网生成为主**：每天用 Anthropic API + 联网搜索生成摘要；播客真实链接用 Apple Podcasts(iTunes) 接口补齐 |
| 运行/更新 | **Mac 定时生成 → 推 GitHub 公开仓库 + Pages**，手机随时随地看最新，全程免费 |
| 范围 | 三块（+关键声音）先搭骨架跑通，再逐块加深 |
| 地区 | 美 / 英 / 日 / 德法 / 北欧 / 新加坡 / 澳洲 + 中国重点 |
| 其它默认 | 单用户、无登录；内容中文摘要 + 保留原标题/链接 |

## 二、设计系统

- **气质**：高级「每日情报简报」——书卷感 + 克制，适合每天阅读。
- **配色**：暖纸白 `#FAF7F0` / 深色暖墨 `#16140F`；品牌点缀克制朱砂红 `#C0452F`（仅激活态/链接/状态点）。模块语义色：AI=靛蓝、播客=琥珀、图书馆=黛绿、关键声音=紫。
- **字体**：标题 Noto Serif SC（思源宋体），正文 Noto Sans SC（思源黑体），元信息等宽。
- **结构**：移动优先、单栏、最宽 720px；报头 + 粘性标签 + 细线分隔卡片列表；播客/图书馆带地区筛选；深浅色（auto/浅/深）+ 字号（标准/大/特大）切换，偏好存 localStorage。
- 刻意规避 AI 套路：无紫粉渐变、不用 emoji 当图标、不用 Inter/Roboto、不编假数据（缺数据走示例占位并明确标注）。

## 三、目录结构

```
daily-intel/
├── docs/                    # GitHub Pages 网站根(main 分支 /docs)
│   ├── index.html           # 应用主体(设计系统+四模块渲染+交互, 单文件)
│   ├── manifest.json        # PWA 清单(可安装)
│   ├── sw.js                # Service Worker(离线缓存; 数据网络优先)
│   ├── icons/               # 应用图标(icon.svg + 待生成 PNG)
│   └── data/
│       ├── latest.json      # 当日情报(每日生成脚本写入; 前端读取)
│       └── archive/         # 历史归档 YYYY-MM-DD.json
├── pipeline/
│   ├── generate.py          # 每日生成(Anthropic API 联网搜索 + iTunes 接口) ← 待写
│   └── requirements.txt
├── scripts/
│   └── run_daily.sh         # cron 入口: 生成 → git commit → push ← 待写
├── launchd/
│   └── com.kushim.daily-intel.plist  # 每日定时(macOS) ← 待写
├── .env.example             # ANTHROPIC_API_KEY 模板(真 .env 不入库)
└── PLAN.md
```

## 四、数据格式 `docs/data/latest.json`

```jsonc
{
  "generated_at": "2026-06-20T22:00:00+08:00",  // ISO 时间(算"X 分钟前")
  "date": "2026-06-20",
  "modules": {
    "ai":        { "items": [ {"title_zh","eng","summary","source","region","published","tags":[],"url"} ] },
    "podcasts":  { "regions":[], "items": [ {"podcast","title","summary","region","host","topics":[],"url"} ] },
    "libraries": { "regions":[], "items": [ {"title_zh","eng","summary","source","region","scope":"public|academic","published","url"} ] },
    "voices":    { "items": [ {"name","role","region","domain":"ai|podcast|library","recent","url"} ] }
  }
}
```

前端无 latest.json 时回落到内置 SAMPLE，并在顶部显示「示例数据」横幅。

## 五、进度

- [x] 项目骨架 + git init
- [x] PWA 主体 `index.html`（设计系统、四模块、地区筛选、深浅色/字号、骨架/空/错误态、离线兜底）
- [x] `manifest.json` / `sw.js` / `icon.svg`
- [ ] PNG 图标（192/512/maskable/180）
- [ ] 当日真实 `latest.json`（联网搜集 AI/图书馆 + iTunes 播客）
- [ ] `pipeline/generate.py`（每日自动生成）
- [ ] `scripts/run_daily.sh` + launchd 定时
- [ ] 本地预览自检（无 console 报错、移动端布局、交互态）
- [ ] 部署 GitHub Pages

## 六、两个一次性手动步骤（需要用户）

1. **GitHub 登录**：`gh auth login`（登录后我才能建公开仓库 + 开 Pages）。
2. **Anthropic API key**：把 key 写进 `pipeline/.env`（照 `.env.example`），每日自动刷新即生效。在此之前 App 用「示例/手动生成」的内容也能正常浏览。

## 七、如何运行（开发）

```bash
# 本地预览
cd ~/daily-intel/docs && python3 -m http.server 8765
# 浏览器打开 http://localhost:8765

# 手动生成当日内容(配好 .env 后)
cd ~/daily-intel && python3 pipeline/generate.py
```
