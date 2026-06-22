#!/bin/bash
# 远音每日自动更新:抓各档最新集 → 转写 → 中文要点+全文 → 配音 → commit+push
# 由 launchd com.kushim.daily-podcast 每天调用
set -e
ROOT="$HOME/daily-intel"
mkdir -p "$ROOT/logs"
LOG="$ROOT/logs/podcast_daily.log"
echo "" >> "$LOG"
echo "======== $(date '+%Y-%m-%d %H:%M') 远音每日更新 ========" >> "$LOG"

cd "$ROOT/pipeline" || exit 1
set -a; source .env 2>/dev/null; set +a
export OLLAMA_HOST=http://127.0.0.1:1     # 跳过本地大模型,DeepSeek 直连
export HF_HUB_OFFLINE=1                    # whisper 用本地缓存
unset HTTP_PROXY HTTPS_PROXY http_proxy https_proxy ALL_PROXY all_proxy   # 裸连:DeepSeek国内直连 + 音频CDN

# 1) 增量抓取+转写+中文要点+全文(只处理新集)
python3 podcast_pipeline.py >> "$LOG" 2>&1 || echo "  管线异常(已容错继续)" >> "$LOG"

# 2) 同步数据并给每集生成【完整】中文版配音(念全文,按性别配音,对谈多声)
cd "$ROOT" || exit 1
cp pipeline/podcast_work/podcast_app.json docs/data/podcast_app.json
export PATH="$HOME/.local/bin:$PATH"   # 确保 ffmpeg 可用
VENV_EDGE="$HOME/kushim-cc/.venv-edge/bin/python"
[ -x "$VENV_EDGE" ] || VENV_EDGE="python3"
"$VENV_EDGE" pipeline/voice_full.py >> "$LOG" 2>&1 || echo "  完整配音异常(已容错继续)" >> "$LOG"

# 3) 有变化才提交上线
git add docs/data docs/data/voice_full docs/podcast.html docs/sw.js docs/index.html 2>/dev/null || true
if ! git diff --cached --quiet; then
  git commit -m "远音每日更新 $(date +%F)" >> "$LOG" 2>&1
  git push >> "$LOG" 2>&1 && echo "  ✓ 已更新并推送上线" >> "$LOG"
else
  echo "  今日无新集,内容已最新" >> "$LOG"
fi
echo "======== 完成 ========" >> "$LOG"
