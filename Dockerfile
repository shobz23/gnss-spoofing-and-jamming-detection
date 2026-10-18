FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 SENTINEL_DATA_DIR=/data
WORKDIR /app
COPY pyproject.toml README.md ./
COPY src ./src
RUN pip install --no-cache-dir . && useradd --create-home sentinel && mkdir /data && chown sentinel:sentinel /data
USER sentinel
EXPOSE 8765
HEALTHCHECK --interval=30s --timeout=5s CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8765/health', timeout=3)"
CMD ["gnss-sentinel", "serve", "--host", "0.0.0.0", "--port", "8765"]
