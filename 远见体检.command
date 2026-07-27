#!/bin/bash
# 双击运行:看远见现在到底是不是活的。看完按任意键关窗。
cd "$(dirname "$0")"
PY="$PWD/.venv/bin/python"; [ -x "$PY" ] || PY=python3
"$PY" scripts/health.py
echo
echo "按任意键关闭…"
read -n 1 -s
