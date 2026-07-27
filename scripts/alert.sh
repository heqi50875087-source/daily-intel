#!/bin/bash
# 用法: alert.sh <latest.json 路径> [状态文件目录]
# 读一份 latest.json,判断要不要惊动人。每天同一种提醒最多发一次。
# 单独成文件是为了能被自检直接调用 —— 埋在 run_daily.sh 里的告警,哑了也没人知道。
set -u
JSON="${1:?用法: alert.sh <latest.json> [状态目录]}"
STATEDIR="${2:-$(dirname "$(dirname "$JSON")")/../logs}"
mkdir -p "$STATEDIR"
PY="${PYTHON:-python3}"

get() { "$PY" -c "import json,sys;print(json.load(open(sys.argv[1])).get(sys.argv[2],''))" "$JSON" "$1" 2>/dev/null || echo ""; }
STATUS=$(get generation_status)
REASON=$(get generation_error)
FALLBACK=$(get engine_fallback)

TITLE=""; BODY=""
if [ -n "${ALERT_FORCE:-}" ]; then
  # 生成脚本硬崩时 latest.json 还停在上一轮的 ok,读它什么都看不出来 —— 由调用方直接指定原因
  TITLE="远见 · 管线异常"; BODY="$ALERT_FORCE"
elif [ "$STATUS" = "degraded" ]; then
  TITLE="远见 · 情报管线降级"; BODY="$REASON"
elif [ -n "$FALLBACK" ]; then
  # 内容是新的(兜底引擎扛住了),只是慢。提示她花几块钱就能换回秒级。
  TITLE="远见 · 正在用兜底引擎"; BODY="$FALLBACK —— 内容照常更新,只是慢"
fi

if [ -z "$TITLE" ]; then
  rm -f "$STATEDIR/.alerted_on"      # 全好了,下次再坏还会提醒
  echo "· 一切正常,无需提醒"
  exit 0
fi
if [ "$(cat "$STATEDIR/.alerted_on" 2>/dev/null)" = "$(date +%F)|$TITLE" ]; then
  echo "· 今天已就「${TITLE}」提醒过,不重复"   # 花括号不能省:中文标点紧跟变量名会被当成名字的一部分
  exit 0
fi
echo "$(date +%F)|$TITLE" > "$STATEDIR/.alerted_on"
echo "$(date '+%F %H:%M') $TITLE: $BODY" >> "$STATEDIR/ALERT.log"
osascript -e "display notification \"$BODY\" with title \"$TITLE\" sound name \"Basso\"" 2>/dev/null || true
echo "⚠ 已提醒: $TITLE — $BODY"
