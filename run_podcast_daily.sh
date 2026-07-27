#!/bin/bash
# 远音每日自动更新:抓各档最新集 → 转写 → 中文要点+全文 → 配音 → commit+push
# 由 launchd com.kushim.daily-podcast 每天调用
set -e
ROOT="$HOME/daily-intel"
mkdir -p "$ROOT/logs"
LOG="$ROOT/logs/podcast_daily.log"
PYTHON="$ROOT/.venv/bin/python"
[ -x "$PYTHON" ] || PYTHON=python3
echo "" >> "$LOG"
echo "======== $(date '+%Y-%m-%d %H:%M') 远音每日更新 ========" >> "$LOG"
# 单实例锁:走本地引擎时一轮可能超过预算窗口,别让明天那轮叠在今天这轮上抢同一块 GPU。
# 陈旧锁超过 6 小时自动清(比情报任务宽松,因为这活本来就长)。
LOCK="$ROOT/logs/.podcast.lock"
if ! mkdir "$LOCK" 2>/dev/null; then
  if [ -n "$(find "$LOCK" -maxdepth 0 -mmin +360 2>/dev/null)" ]; then
    rmdir "$LOCK" 2>/dev/null && mkdir "$LOCK" 2>/dev/null || { echo "  锁清理失败,跳过本轮" >> "$LOG"; exit 0; }
  else
    echo "  上一轮还在跑,跳过本轮" >> "$LOG"; exit 0
  fi
fi
trap 'rmdir "$LOCK" 2>/dev/null' EXIT

cd "$ROOT/pipeline" || exit 1
set -a; source .env 2>/dev/null; set +a
export OLLAMA_HOST=http://127.0.0.1:1     # 跳过本地大模型,DeepSeek 直连
export HF_HUB_OFFLINE=1                    # whisper 用本地缓存
unset HTTP_PROXY HTTPS_PROXY http_proxy https_proxy ALL_PROXY all_proxy   # 裸连:DeepSeek国内直连 + 音频CDN

# 1) 增量抓取+转写+中文要点+全文(只处理新集)
"$PYTHON" podcast_pipeline.py >> "$LOG" 2>&1 || echo "  管线异常(已容错继续)" >> "$LOG"

# 1.5) 有官网文字稿的档(Lex Fridman / Tim Ferriss 等)自动补全完整翻译:
#      抓官网文字稿(网页几百KB,绕开150MB音频下载瓶颈)→ 整篇翻译 → 覆盖截断版。幂等,作用于 podcast_work
"$PYTHON" podcast_transcript_daily.py >> "$LOG" 2>&1 || echo "  文字稿补全异常(已容错继续)" >> "$LOG"

# 2) 同步数据并给每集生成【完整】中文版配音(念全文,按性别配音,对谈多声)
cd "$ROOT" || exit 1
cp pipeline/podcast_work/podcast_app.json docs/data/podcast_app.json
export PATH="$HOME/.local/bin:$PATH"   # 确保 ffmpeg 可用
"$PYTHON" pipeline/voice_full.py >> "$LOG" 2>&1 || echo "  完整配音异常(已容错继续)" >> "$LOG"

# 3) 有变化才提交上线
git add docs/data docs/data/voice_full docs/podcast.html docs/sw.js docs/index.html 2>/dev/null || true
if ! git diff --cached --quiet; then
  git commit -m "远音每日更新 $(date +%F)" >> "$LOG" 2>&1
  # 推送优先使用本机既有网络出口；失败时直连兜底。本脚本不管理网络守护。
  # if/elif 替代 A&&B||C&&D:旧写法代理成功时两条日志都打,两路全败时 set -e 杀掉脚本连"完成"都不写
  if git -c http.proxy=http://127.0.0.1:18080 -c https.proxy=http://127.0.0.1:18080 push >> "$LOG" 2>&1; then
    echo "  ✓ 已更新并推送上线" >> "$LOG"
  elif git push >> "$LOG" 2>&1; then
    echo "  ✓ 已推送(直连)" >> "$LOG"
  else
    echo "  ✗ 推送失败(代理+直连都不通),提交已留本地,下次运行自动重推" >> "$LOG"
  fi
else
  echo "  今日无新集,内容已最新" >> "$LOG"
fi
echo "======== 完成 ========" >> "$LOG"
