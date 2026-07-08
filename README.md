# 情报 · 每日情报简报

给个人使用的 PWA：每天自动汇集 **AI 进展 / 全球播客 / 图书馆 / 关键声音**，省掉到处搜集的功夫。

- **形态**：响应式网页 / PWA（手机加到主屏即用，日后可 Capacitor 打包）
- **内容**：抓取公开 RSS + 联网检索，经 **DeepSeek API 或本地 Ollama** 生成中文摘要；播客真实链接走 Apple Podcasts 接口
- **运行**：Mac 定时生成 → 推 GitHub Pages → 手机随时看最新，全程免费
- **原则**：只读聚合、链接归原作者；中文摘要 + 原标题/链接

## 快速预览

```bash
cd ~/daily-intel/docs && python3 -m http.server 8765
# 打开 http://localhost:8765
```

## 每日自动刷新（两步收尾）

1. **GitHub 登录**：`gh auth login` → 建公开仓库并推送，开启 Pages（main 分支 /docs）。也可用脚本一键：`bash scripts/deploy.sh`。
2. **配引擎（二选一）**：复制 `.env.example` 为 `pipeline/.env`，填入 `DEEPSEEK_API_KEY`；**或**装好本地 Ollama（则无需任何 key，脚本会自动检测）。⚠️ 代码实际读取的是 `DEEPSEEK_API_KEY` / Ollama，**不是** Anthropic。
3. 装定时任务：`cp launchd/com.kushim.daily-intel.plist ~/Library/LaunchAgents/ && launchctl load ~/Library/LaunchAgents/com.kushim.daily-intel.plist`
   - 换到别人机器、路径不同时：改用 `launchd/com.kushim.daily-intel.plist.example`，把其中 4 处 `/ABSOLUTE/PATH/TO/daily-intel` 替成本机绝对路径（模板顶部有一行 `sed` 示例）后再 `cp` + `load`。

手动生成当日内容：`python3 pipeline/generate.py`

## 上线还差什么（如实标注）

- **作为个人 PWA**：完成上面两步（Pages + DeepSeek key 或本地 Ollama）即可自用，无结构性障碍。
- **若要做成公开发布的微信小程序**（见关联项目 `yuanjian-miniapp`）：存在**结构性封顶**——**微信个人主体拿不到《互联网新闻信息服务许可证》**，"新闻/资讯"类目无法上线；合规路径需**单位主体**，或收窄为"行业情报/教育信息"类目，或降级为**内部工具**。
- 本仓定位：**内部基线 + 文档齐全**，不追商业上线。（作者工作区留有更详细的《上架与经营主体合规清单》）

## 许可与合规

- 代码在 **Apache License 2.0** 下分发（见 `LICENSE`）；第三方组件及其义务见 `NOTICE`。
- 只读聚合：新闻/播客内容版权归原作者，均保留原标题与原链接。

详见 [PLAN.md](PLAN.md)。
