#!/bin/bash
# 一键部署到 GitHub Pages (需先 gh auth login)
set -e
cd "$(cd "$(dirname "$0")/.." && pwd)"
REPO="${1:-daily-intel}"
OWNER="$(gh api user -q .login)"
gh repo create "$REPO" --public --source=. --remote=origin --push
gh api -X POST "repos/$OWNER/$REPO/pages" -f "source[branch]=main" -f "source[path]=/docs" || true
echo "✅ 已推送; Pages 开启中(约1-2分钟生效): https://$OWNER.github.io/$REPO/"
