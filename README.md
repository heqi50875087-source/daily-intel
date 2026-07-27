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

## 它坏了怎么办（2026-07-27 起）

**先双击仓库根目录的 `远见体检.command`**，不要先看日志。它不读日志、不看绿灯，直接量三样真东西：每个栏目最新一条是哪天的、三路引擎各真发一次请求、线上 Pages 上那份 JSON。看红灯那行写的是什么，再动手。

之所以这么设计：2026-07-11 DeepSeek 额度耗尽后，管线每小时照常跑、git 每天照常提交、日志照常写 `done`、小程序照常显示"今天更新"——**四个量具同时显示正常，内容却冻了 16 天**。唯一还在更新的学术栏目每次合并还会把整站 `generated_at` 刷成当前时间，替其他六个死掉的栏目盖了新鲜时间戳。所以现在：

- **引擎三路自动改道**：`DeepSeek → 本地 Ollama → OpenAI`，任一路额度耗尽/鉴权失败/连不上，自动降到下一路；三路全挂才标降级。顺序可用 `INTEL_ENGINE_ORDER` 改。
- **降级会惊动人**：macOS 通知 + `logs/ALERT.log` + 小程序顶部横幅，每天最多提醒一次。
- **时间戳不再互相冒充**：`generated_at` 只有真生成才写，每个栏目另有自己的 `module_updated`，小程序显示"本栏 N 天前"。
- **日志记真正出活的那一路**：`engine` 字段写的是实际改道后跑通的引擎，不是开局挑的那个。

**每月做一次「按测试钮」**（这条比任何代码都重要）：故意断一路——最省事是 `launchctl unload ~/Library/LaunchAgents/com.kushim.ollama.plist` 并断开网络，等下一个整点，确认收到了 macOS 通知、小程序顶部出现横幅。**报警器没响过，你无法区分"零故障"和"报警器坏了"。** 演练完 `launchctl load -w` 装回去。

另外每月扫一眼 `logs/ALERT.log` 的修改时间：如果 30 天纹丝不动，要么真的零故障（存疑），要么报警线已经死了——直接去做上面那次演练。

常见几种红灯：

| 体检说什么 | 做什么 |
|---|---|
| `deepseek 不可用 · 额度不足` | 给 DeepSeek 充值；不充也能跑，只是走本地、慢一些 |
| `模型盘 ORICO 未挂载` | 插上 ORICO 移动硬盘（本地模型放在那儿，主盘装不下） |
| `ollama 守护未加载` | `launchctl load -w ~/Library/LaunchAgents/com.kushim.ollama.plist` |
| `三路引擎全挂` | 内容一定不会再更新了，先解决其中任意一路 |
| `主盘可用 < 5 GB` | 清理主盘，磁盘满会让 git 和 ollama 一起出怪病 |

**省算力**：原始 RSS 没变化就不重算（`pipeline/.srchash.json` 存素材指纹）。此前每小时全量重算 6 个栏目，云端是白烧额度、本地是白烧机器。要强制重算就删掉这个文件。

**本地模型出结构化输出的坑**（换模型时别踩回去）：ollama 的 `format` 必须传 **JSON Schema**（`{"type":"object"}`），不能传字符串 `"json"`。后者只是"请你输出 JSON"，对 9B 级模型没有约束力——出 10 条以上带长文本的条目时必崩（漏逗号、正文后多说一个对象），而日志里 `truncated=0`，说明不是上下文不够，是模型自由发挥。传 schema 才启用真语法约束。

## 上线还差什么（如实标注）

- **作为个人 PWA**：完成上面两步（Pages + DeepSeek key 或本地 Ollama）即可自用，无结构性障碍。
- **若要做成公开发布的微信小程序**（见关联项目 `yuanjian-miniapp`）：存在**结构性封顶**——**微信个人主体拿不到《互联网新闻信息服务许可证》**，"新闻/资讯"类目无法上线；合规路径需**单位主体**，或收窄为"行业情报/教育信息"类目，或降级为**内部工具**。
- 本仓定位：**内部基线 + 文档齐全**，不追商业上线。（作者工作区留有更详细的《上架与经营主体合规清单》）

## 许可与合规

- 代码在 **Apache License 2.0** 下分发（见 `LICENSE`）；第三方组件及其义务见 `NOTICE`。
- 只读聚合：新闻/播客内容版权归原作者，均保留原标题与原链接。

详见 [PLAN.md](PLAN.md)。
