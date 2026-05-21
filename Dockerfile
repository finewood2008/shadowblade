FROM python:3.11-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    fonts-noto-cjk \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY config/ config/
COPY tools/ tools/
COPY app/ app/

RUN mkdir -p app/work app/final

EXPOSE 8000

CMD ["uvicorn", "app.worker:app", "--host", "0.0.0.0", "--port", "8000"]
