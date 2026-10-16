FROM python:3.11-slim

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    STORAGE_MODE=gdrive \
    PORT=8080

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app
COPY run_cloud.py sync_gdrive.py ./
# 디렉터리 구조 준비 (기동 시 Google Drive에서 최신 텍스트 번들 자동 다운로드 및 마운트)
RUN mkdir -p /app/WikiDB/docs /app/WikiDB/reports /app/WikiDB/assets /app/Source
RUN chmod -R 777 /app

EXPOSE 8080

CMD ["sh", "-c", "uvicorn run_cloud:app --host 0.0.0.0 --port ${PORT:-8080}"]

