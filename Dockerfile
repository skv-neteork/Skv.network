FROM python:3.11-slim
RUN apt-get update && apt-get install -y --no-install-recommends g++ && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY src/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt || pip install --no-cache-dir --only-binary=:all: -r requirements.txt || echo "Some packages skipped"

COPY src/app/ /app/app/

RUN mkdir -p /data/skv /app/app/runtime/memory

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
# Force rebuild 1783065274
# Force rebuild 1783167167
