#!/usr/bin/env bash
# 把本仓库安装为 DeepSeek Harness filesystem skill，并做一次健康检查。
#
# 用法：
#   ./install-dsh.sh
#   DSH_HOME=/tmp/dsh-home ./install-dsh.sh
#   PYTHON=python3.11 ./install-dsh.sh --force
set -euo pipefail

# 用脚本自身位置定位仓库，不假设 CWD。
REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
MANAGER="$REPO/scripts/dsh_manager.py"
PYTHON="${PYTHON:-python3}"

if [ ! -f "$MANAGER" ]; then
    echo "找不到 $MANAGER。请在仓库根目录运行本脚本。" >&2
    exit 1
fi

if ! command -v "$PYTHON" >/dev/null 2>&1; then
    echo "未找到 Python（$PYTHON）。本打包工具需要 Python 3.10+，可用 PYTHON=... 指定解释器。" >&2
    exit 1
fi

# 前置依赖只做提示，不中断：doctor 才是唯一的判定入口。
for command in node npm npx; do
    command -v "$command" >/dev/null 2>&1 || \
        echo "警告：未在 PATH 中找到 $command。安装会继续，最终结论以 doctor 输出为准。" >&2
done

"$PYTHON" "$MANAGER" install "$@"
"$PYTHON" "$MANAGER" doctor
