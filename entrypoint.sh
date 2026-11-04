#!/bin/sh
set -eu

DATA_DIR="${DATA_DIR:-/data}"
if ! mkdir -p "$DATA_DIR" 2>/dev/null || [ ! -w "$DATA_DIR" ]; then
    echo "错误: 数据目录不可写: $DATA_DIR" >&2
    echo "提示: 使用宿主目录挂载时，请确保容器内 uid 10001 有写权限，例如：" >&2
    echo "  sudo chown -R 10001:10001 <宿主机目录>" >&2
    exit 1
fi

exec "$@"
