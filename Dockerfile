FROM python:3.12-slim
ENV PYTHONUNBUFFERED=1 TZ=Europe/Madrid
WORKDIR /srv
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY app ./app
RUN useradd -m appuser && mkdir -p /data && chown appuser /data
USER appuser
EXPOSE 8085
CMD ["sh","-c","exec uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8085} --proxy-headers --forwarded-allow-ips=172.16.0.0/12,127.0.0.1"]
