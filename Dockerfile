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
# 키 파일이 존재하는 경우에만 복사 (GitHub Actions 빌드 시 시크릿 파일 연동 대응)
COPY gdrive_credentials*.json* ./

# 디렉터리 구조 준비 및 로컬 완본 텍스트 번들(wiki_text_bundle.zip) 내장
RUN mkdir -p /app/WikiDB/docs /app/WikiDB/reports /app/WikiDB/assets /app/Source
COPY WikiDB/wiki_text_bundle.zip* ./WikiDB/
RUN chmod -R 777 /app

EXPOSE 8080

CMD ["sh", "-c", "uvicorn run_cloud:app --host 0.0.0.0 --port ${PORT:-8080}"]

