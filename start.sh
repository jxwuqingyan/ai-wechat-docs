#!/usr/bin/env bash
# 启动「公众号排版工作台」Web 服务
#
#   ./start.sh                  # 前台运行，默认 http://127.0.0.1:8765
#   ./start.sh --open           # 同时自动打开浏览器
#   PORT=9000 ./start.sh        # 换端口
#   HOST=0.0.0.0 PORT=8765 ./start.sh   # 对外开放（请先读 README.md 的「部署前必读」）
#
# 可用环境变量：PORT / HOST / PYTHON

set -euo pipefail

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SERVER="$DIR/wechat-mp-formatter/scripts/server.py"

PORT="${PORT:-8765}"
HOST="${HOST:-127.0.0.1}"
PYTHON="${PYTHON:-}"

if [ ! -f "$SERVER" ]; then
  echo "找不到服务脚本：$SERVER" >&2
  exit 1
fi

# 选一个可用的 Python 3
if [ -z "$PYTHON" ]; then
  for cand in python3 python /usr/bin/python3; do
    if command -v "$cand" >/dev/null 2>&1; then
      if "$cand" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 8) else 1)' >/dev/null 2>&1; then
        PYTHON="$cand"
        break
      fi
    fi
  done
fi

if [ -z "$PYTHON" ]; then
  echo "未找到 Python 3.8+，请先安装 Python。" >&2
  exit 1
fi

# 允许命令行参数覆盖，让下面打印的地址与真实监听一致
args=("$@")
i=0
while [ "$i" -lt "${#args[@]}" ]; do
  case "${args[$i]}" in
    --port) PORT="${args[$((i + 1))]:-$PORT}"; i=$((i + 2)) ;;
    --host) HOST="${args[$((i + 1))]:-$HOST}"; i=$((i + 2)) ;;
    *) i=$((i + 1)) ;;
  esac
done

echo "Python : $("$PYTHON" -V 2>&1)"
echo "监听   : http://$HOST:$PORT/   （可用 PORT=9000 ./start.sh 修改）"
echo "停止   : 按 Control + C"
echo

exec "$PYTHON" "$SERVER" --host "$HOST" --port "$PORT" "$@"
