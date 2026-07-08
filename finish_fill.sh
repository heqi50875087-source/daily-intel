#!/bin/bash
# 等填充管线跑完 → 完整配音 → 清理孤儿音频 → 提交推送上线。一次性自动收尾。
cd "$HOME/daily-intel" || exit 1
LOG="logs/finish_fill.log"; echo "==== $(date '+%H:%M') 等待管线完成 ====" >> "$LOG"
while pgrep -f podcast_pipeline.py >/dev/null; do sleep 30; done
echo "$(date '+%H:%M') 管线结束,开始配音" >> "$LOG"
cp pipeline/podcast_work/podcast_app.json docs/data/podcast_app.json
export PATH="$HOME/.local/bin:$PATH"
~/kushim-cc/.venv-edge/bin/python pipeline/voice_full.py >> "$LOG" 2>&1
python3 - >> "$LOG" 2>&1 <<'PY'
# 清理孤儿音频:删除 voice_full/ 里没有被任何单集引用的 mp3(防止仓库膨胀)
import json, os, glob
d = json.load(open("docs/data/podcast_app.json"))
keep = {e.get("voice_full","").split("/")[-1] for e in d["episodes"].values()}
n=0
for f in glob.glob("docs/data/voice_full/*.mp3"):
    if os.path.basename(f) not in keep:
        os.remove(f); n+=1
print(f"清理孤儿音频 {n} 个")
PY
git add docs/data docs/data/voice_full docs/podcast.html 2>/dev/null
if ! git diff --cached --quiet; then
  git commit -m "远音填充:新增全球热门节目完整中文版配音上线 $(date +%F)" >> "$LOG" 2>&1
  git -c http.proxy=http://127.0.0.1:18080 -c https.proxy=http://127.0.0.1:18080 push >> "$LOG" 2>&1 \
    && echo "$(date '+%H:%M') ✓ 已推送上线" >> "$LOG" || echo "$(date '+%H:%M') ✗ 推送失败(稍后由每日任务补推)" >> "$LOG"
else
  echo "无新增内容" >> "$LOG"
fi
echo "==== 收尾完成 ====" >> "$LOG"
