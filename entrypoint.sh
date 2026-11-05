#!/bin/sh
set -eu

DATA_DIR="${DATA_DIR:-/data}"
if ! mkdir -p "$DATA_DIR" 2>/dev/null || [ ! -w "$DATA_DIR" ]; then
    owner="$(stat -c '%u:%g' "$DATA_DIR" 2>/dev/null || echo 未知)"
    perms="$(stat -c '%a' "$DATA_DIR" 2>/dev/null || echo 未知)"
    echo "错误: 数据目录不可写: $DATA_DIR" >&2
    echo "  容器用户: uid=$(id -u) gid=$(id -g)；目录所有者: $owner，权限: $perms" >&2
    echo "提示: 使用宿主目录挂载（bind mount）时，可在 .env 中设置 PUID/PGID 为宿主机用户的 uid/gid，" >&2
    echo "  并在宿主机执行 sudo chown -R <uid>:<gid> <目录>；" >&2
    echo "  命名卷可执行 docker run --rm -u 0 -v <卷名>:/data <镜像> chown -R $(id -u):$(id -g) /data。" >&2
    echo "  也可以 chmod 0777 <目录> 并把 .env 的 DATA_DIR_MODE 设为 0777（不推荐，数据将对所有本地用户开放）。" >&2
    exit 1
fi

exec "$@"
