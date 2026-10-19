#!/bin/sh
# recreate skv_api (env in /root/skv_api.env)
docker run -d --restart unless-stopped --name skv_api --network skv-core_default --env-file /root/skv_api.env -v /data/skv:/data/skv -v /root/skv-core/src/app:/app/app -v /root/skv_vault:/run/skv_vault:ro -p 127.0.0.1:8000:8000 -w /app skv-network:v8.4 uvicorn app.main:app --host 0.0.0.0 --port 8000
