FROM python:3.12-slim
RUN pip install --no-cache-dir pytest && apt-get update && apt-get install -y --no-install-recommends nodejs && rm -rf /var/lib/apt/lists/* && useradd -u 10001 -m sb
USER 10001
WORKDIR /work
