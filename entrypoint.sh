#!/bin/sh
set -eu

DATA_DIR="${DATA_DIR:-/data}"
PUID="${PUID:-10001}"
PGID="${PGID:-10001}"
export DATA_DIR

print_error() {
    owner="$(stat -c '%u:%g' "$DATA_DIR" 2>/dev/null || echo 未知)"
    perms="$(stat -c '%a' "$DATA_DIR" 2>/dev/null || echo 未知)"
    echo "错误: 数据目录不可写: $DATA_DIR" >&2
    echo "  运行用户: uid=$PUID gid=$PGID；目录所有者: $owner，权限: $perms" >&2
    echo "提示: 检查 .env 的 PUID/PGID 是否与宿主机目录所有者一致，以及挂载是否只读；" >&2
    echo "  bind mount 可在宿主机执行 sudo chown -R $PUID:$PGID <目录>。" >&2
}

case "$PUID" in
    ''|*[!0-9]*) echo "错误: PUID 必须是数字: $PUID" >&2; exit 1 ;;
esac
case "$PGID" in
    ''|*[!0-9]*) echo "错误: PGID 必须是数字: $PGID" >&2; exit 1 ;;
esac

if [ "$(id -u)" = "0" ]; then
    if ! mkdir -p "$DATA_DIR"; then
        echo "错误: 无法创建数据目录: $DATA_DIR" >&2
        exit 1
    fi
    if [ "$(stat -c '%u:%g' "$DATA_DIR")" != "$PUID:$PGID" ]; then
        chown -R "$PUID:$PGID" "$DATA_DIR" 2>/dev/null || true
    fi
    if ! setpriv --reuid="$PUID" --regid="$PGID" --clear-groups \
        sh -c 'test -w "$DATA_DIR"'; then
        print_error
        exit 1
    fi
    exec setpriv --reuid="$PUID" --regid="$PGID" --clear-groups "$@"
fi

if ! mkdir -p "$DATA_DIR" 2>/dev/null || [ ! -w "$DATA_DIR" ]; then
    print_error
    exit 1
fi

exec "$@"
