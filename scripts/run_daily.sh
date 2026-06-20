#!/bin/bash
# 每日情报: 生成 -> 提交 -> 推送 (由 launchd 定时调用)
set -e
export PATH="/usr/bin:/bin:/usr/sbin:/sbin:/usr/local/bin:/opt/homebrew/bin:$HOME/.local/bin:$PATH"
cd "$(cd "$(dirname "$0")/.." && pwd)"
mkdir -p logs
LOG="logs/run.log"
{
  echo "==== $(date) ===="
  python3 pipeline/generate.py
  if [ -n "$(git status --porcelain docs/data)" ]; then
    git add docs/data
    git commit -m "每日情报 $(date +%F)" || true
    if git remote | grep -q origin; then
      git push || echo "⚠ push 失败(检查 gh 登录 / 远程仓库)"
    else
      echo "· 尚未配置远程仓库 origin, 跳过 push"
    fi
  else
    echo "· 数据无变化"
  fi
  echo "done"
} >> "$LOG" 2>&1
