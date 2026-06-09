FROM python:3.11-slim

WORKDIR /app

# Зависимости
COPY src/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Код приложения
COPY src/app/ /app/app/
COPY src/config.py /app/config.py 2>/dev/null || true

# Данные
RUN mkdir -p /data/skv /app/app/runtime/memory

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
