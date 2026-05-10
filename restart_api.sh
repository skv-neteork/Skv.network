#!/bin/bash
# Очищаем Python-кэш (volume mount пробрасывает его в контейнер)
find /root/skv-core/src -name "__pycache__" -exec rm -rf {} + 2>/dev/null
find /root/skv-core/src -name "*.pyc" -delete 2>/dev/null
# Перезапускаем контейнер
docker restart skv_api
sleep 3
echo "✅ skv_api перезапущен с очищенным кэшем"
