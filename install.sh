#!/usr/bin/env bash
# 把本项目安装（或同步更新）为 WorkBuddy 技能
#
#   ./install.sh
#   WORKBUDDY_SKILLS=/path/to/skills ./install.sh   # 自定义技能根目录
#
# 本项目是唯一源码位置；本脚本把 wechat-mp-formatter/ 同步到技能目录，
# 使 WorkBuddy 能自动识别并调用这个技能。改完代码再跑一次即可。

set -euo pipefail

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SRC="$DIR/wechat-mp-formatter"
DEST_ROOT="${WORKBUDDY_SKILLS:-$HOME/.workbuddy/skills}"
DEST="$DEST_ROOT/wechat-mp-formatter"

if [ ! -f "$SRC/SKILL.md" ]; then
  echo "找不到技能本体：$SRC/SKILL.md" >&2
  exit 1
fi

mkdir -p "$DEST"

if command -v rsync >/dev/null 2>&1; then
  # --delete-excluded：连目标里的 .DS_Store / __pycache__ 一起清掉
  # （只写 --delete 的话，被 exclude 的文件不受删除影响，会残留）
  rsync -a --delete --delete-excluded \
    --exclude '.DS_Store' --exclude '__pycache__' --exclude '*.pyc' \
    "$SRC/" "$DEST/"
else
  echo "（未找到 rsync，改用逐目录复制）"
  for item in scripts assets references; do
    if [ -d "$SRC/$item" ]; then
      rm -rf "$DEST/$item"
      cp -R "$SRC/$item" "$DEST/"
    fi
  done
  cp -f "$SRC/SKILL.md" "$DEST/SKILL.md"
  find "$DEST" \( -name '.DS_Store' -o -name '__pycache__' \) -exec rm -rf {} + 2>/dev/null || true
fi

echo "✅ 已安装到：$DEST"
echo
echo "验证："
echo "  python3 \"$DEST/scripts/convert.py\" \\"
echo "      \"$DEST/assets/sample.md\" -o /tmp/smoke.html --theme blue"
echo "  python3 \"$DEST/scripts/check_html.py\" /tmp/smoke.html"
echo
echo "重启 WorkBuddy 会话后，直接说「把这篇 md 排版成公众号文章」即可触发该技能。"
