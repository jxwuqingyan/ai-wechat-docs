#!/bin/bash
# macOS 双击启动：公众号排版工作台
# 关闭服务：回到本终端窗口按 Control + C

cd "$(dirname "$0")" || exit 1

if [ ! -x "./start.sh" ]; then
  chmod +x ./start.sh 2>/dev/null
fi

if [ -x "./start.sh" ]; then
  echo "═══════════════════════════════════════════"
  echo "  公众号排版工作台"
  echo "  浏览器会自动打开；按 Control+C 停止服务"
  echo "═══════════════════════════════════════════"
  echo
  exec ./start.sh --open
fi

# 兜底：项目里的 start.sh 不在时，直接用 WorkBuddy 技能目录里的服务
SERVER="$HOME/.workbuddy/skills/wechat-mp-formatter/scripts/server.py"
PY="$(command -v python3)"
if [ -z "$PY" ] || [ ! -f "$SERVER" ]; then
  echo "找不到可用的 Python 或服务脚本。"
  echo "请确认本目录完整（应包含 start.sh 与 wechat-mp-formatter/），"
  echo "或先执行 ./install.sh 把技能安装到 ~/.workbuddy/skills/。"
  read -r -p "按回车关闭…" _
  exit 1
fi

echo "═══════════════════════════════════════════"
echo "  公众号排版工作台（技能目录模式）"
echo "  浏览器会自动打开；按 Control+C 停止服务"
echo "═══════════════════════════════════════════"
exec "$PY" "$SERVER" --open
