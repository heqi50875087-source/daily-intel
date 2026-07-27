#!/bin/bash
# 每日情报: 生成 -> 提交 -> 推送 (由 launchd 定时调用)
set -e
export PATH="/usr/bin:/bin:/usr/sbin:/sbin:/usr/local/bin:/opt/homebrew/bin:$HOME/.local/bin:$PATH"
# mihomo(18080) 在线则挂智能分流(墙外源走节点 / DeepSeek+GitHub 走国内直连);不在线则裸连兜底(仅国内源)
if curl -s -m 2 -x http://127.0.0.1:18080 http://www.gstatic.com/generate_204 -o /dev/null 2>/dev/null; then
  export HTTP_PROXY=http://127.0.0.1:18080 HTTPS_PROXY=http://127.0.0.1:18080
  export http_proxy=http://127.0.0.1:18080 https_proxy=http://127.0.0.1:18080
  export NO_PROXY=localhost,127.0.0.1,::1 no_proxy=localhost,127.0.0.1,::1
fi
cd "$(cd "$(dirname "$0")/.." && pwd)"
mkdir -p logs
# 单实例锁:本地引擎一轮可能跑过一小时,而整点任务每小时来一次。不加锁就会几轮叠在同一块 GPU 上
# 互相拖慢、越堆越糟。mkdir 是原子的,比 -f 判断可靠;陈旧锁超过 3 小时自动清掉(进程早没了)。
LOCK="logs/.run.lock"
if ! mkdir "$LOCK" 2>/dev/null; then
  if [ -n "$(find "$LOCK" -maxdepth 0 -mmin +180 2>/dev/null)" ]; then
    rmdir "$LOCK" 2>/dev/null && mkdir "$LOCK" 2>/dev/null || { echo "$(date) · 锁清理失败,跳过本轮" >> logs/run.log; exit 0; }
  else
    echo "$(date) · 上一轮还在跑,跳过本轮" >> logs/run.log; exit 0
  fi
fi
trap 'rmdir "$LOCK" 2>/dev/null' EXIT
LOG="logs/run.log"
PYTHON="$PWD/.venv/bin/python"
[ -x "$PYTHON" ] || PYTHON=python3
{
  echo "==== $(date) ===="
  # 别让 set -e 在这里杀掉脚本:生成脚本硬崩(如一路引擎都没有)恰恰是最该报警的情况,
  # 直接退出的话下面的告警根本不会跑 —— 又变成一次静默死亡。
  GENFAIL=0
  "$PYTHON" pipeline/generate.py || { GENFAIL=1; echo "⚠ 生成脚本异常退出"; }
  if [ -n "$(git status --porcelain docs/data)" ]; then
    git add docs/data
    git commit -m "每日情报 $(date '+%F %H:%M')" || true
    if git remote | grep -q origin; then
      git push || echo "⚠ push 失败(检查 gh 登录 / 远程仓库)"
    else
      echo "· 尚未配置远程仓库 origin, 跳过 push"
    fi
  else
    echo "· 数据无变化"
  fi
  # 降级要有人知道:2026-07-11 DeepSeek 402 后管线照常 commit、日志照常 done,内容却冻了 16 天没人发现。
  # 每天最多提醒一次(整点任务一天跑 18 轮),同时留一行到 ALERT.log 兜住通知被系统吞掉的情况。
  # 心跳:所有告警都以"管线跑起来了"为前提,而 launchd 自己停摆(系统升级/plist 被动/会话变化)
  # 时根本没人跑,也就没人报警。mtime 不会说谎,日志内容会 —— 体检看这个文件的时间。
  touch logs/.heartbeat
  [ "$GENFAIL" = 1 ] && export ALERT_FORCE="生成脚本异常退出,见 logs/run.log"
  PYTHON="$PYTHON" bash scripts/alert.sh docs/data/latest.json logs || true
  echo "done"
} >> "$LOG" 2>&1
