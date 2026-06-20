# 情报 · 每日情报简报

给个人使用的 PWA：每天自动汇集 **AI 进展 / 全球播客 / 图书馆 / 关键声音**，省掉到处搜集的功夫。

- **形态**：响应式网页 / PWA（手机加到主屏即用，日后可 Capacitor 打包）
- **内容**：每天 Anthropic API + 联网搜索生成摘要；播客真实链接走 Apple Podcasts 接口
- **运行**：Mac 定时生成 → 推 GitHub Pages → 手机随时看最新，全程免费
- **原则**：只读聚合、链接归原作者；中文摘要 + 原标题/链接

## 快速预览

```bash
cd ~/daily-intel/docs && python3 -m http.server 8765
# 打开 http://localhost:8765
```

## 每日自动刷新（两步收尾）

1. **GitHub 登录**：`gh auth login` → 建公开仓库并推送，开启 Pages（main 分支 /docs）。
2. **填 API key**：复制 `.env.example` 为 `pipeline/.env`，填入 `ANTHROPIC_API_KEY`。
3. 装定时任务：`cp launchd/com.kushim.daily-intel.plist ~/Library/LaunchAgents/ && launchctl load ~/Library/LaunchAgents/com.kushim.daily-intel.plist`

手动生成当日内容：`python3 pipeline/generate.py`

详见 [PLAN.md](PLAN.md)。
