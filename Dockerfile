ARG BASE_IMAGE=python:3.12-slim
FROM ${BASE_IMAGE}

ARG PIP_INDEX_URL=https://pypi.tuna.tsinghua.edu.cn/simple

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    DATA_DIR=/data \
    TZ=Asia/Shanghai

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt -i ${PIP_INDEX_URL}

COPY . .

RUN useradd --uid 10001 --user-group --create-home --shell /usr/sbin/nologin appuser \
    && chmod +x /app/entrypoint.sh \
    && mkdir -p /data \
    && chown -R appuser:appuser /app /data

ENV HOME=/home/appuser

# entrypoint 以 root 启动修正数据目录归属，再用 setpriv 降权到 PUID/PGID（默认 appuser）
VOLUME ["/data"]
EXPOSE 8080

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD python -c "import os, urllib.request; urllib.request.urlopen('http://127.0.0.1:' + os.environ.get('PORT', '8080') + '/healthz', timeout=3)"

ENTRYPOINT ["/app/entrypoint.sh"]
CMD ["python", "run.py"]
