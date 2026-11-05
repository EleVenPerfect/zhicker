#!/bin/sh
set -eu

DATA_DIR="${DATA_DIR:-/data}"
if ! mkdir -p "$DATA_DIR" 2>/dev/null || [ ! -w "$DATA_DIR" ]; then
    echo "错误: 数据目录不可写: $DATA_DIR（容器用户 uid=$(id -u) gid=$(id -g)）" >&2
    echo "提示: 使用宿主目录挂载（bind mount）时，可在 .env 中设置 PUID/PGID 为宿主机用户的 uid/gid，" >&2
    echo "  或在宿主机执行 chmod 0777 <目录>，并把 .env 的 DATA_DIR_MODE 设为 0777。" >&2
    exit 1
fi

exec "$@"
