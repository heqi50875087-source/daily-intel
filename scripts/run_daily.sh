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
LOG="logs/run.log"
{
  echo "==== $(date) ===="
  python3 pipeline/generate.py
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
  echo "done"
} >> "$LOG" 2>&1
