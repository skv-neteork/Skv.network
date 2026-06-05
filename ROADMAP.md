# SKV v4.0 Roadmap

## ✅ Сделано
- [x] TensorCube граф (1197 кубов, 3506 связей)
- [x] Spreading Activation (neural search)
- [x] Hebbian Learning (каждые 30 сек)
- [x] Decay (затухание, каждые 5 мин)
- [x] Contrastive Hebbian (+positive, -negative)
- [x] Auto-save графа (каждые 30 мин)
- [x] Кэш эмбеддингов
- [x] Защита конституционных кубов
- [x] /api/v1/info (1197 cubes)

## 🔥 Срочно
- [x] **Adaptive Decay** — умное забывание ✅ на основе usage_count
- [x] **Персональная память проектов** — /api/v4/sessions ✅
- [x] **Конституционные кубы** — 4 шт (00-03), иммунитет к decay ✅

## ⚡ Важно
- [x] **Создание кубов через API** — POST /api/v4/cubes ✅
- [x] **Формат анкет** — обновлён ✅
- [ ] **Trials + Evolver** — редизайн под v4

## 📦 Масштабирование (когда > 10 000 кубов)
- [x] **Hybrid Search** (Qdrant → TensorCube) ✅
- [x] **"Сон" графа** (consolidation cycle) ✅
- [ ] Hierarchical Topology (meta-узлы)
- [ ] Qdrant int8 (квантование)
- [ ] RocksDB (холодное хранение)
- [ ] Шардирование графа

## 🐛 Баги деплоя
- [ ] Volume mount отключить (перезаписывает файлы при рестарте)
- [ ] Контейнер в правильной сети Docker

## 🧠 R&D на будущее (от Google)

### 1. Иерархические абстракции (Microsoft GraphRAG style)
- Фоновый воркер раз в неделю собирает мета-данные из плотных подграфов
- Генерирует "суммари" для кластеров кубов
- Глобальные вопросы → готовый отчёт верхнего уровня вместо перебора тысяч кубов

### 2. Tool Calling SDK (Mem0/Letta style)
- Библиотека Python/TS: `agent.attach_memory(SKV_Client)`
- Агент автоматически внедряет инструкции TensorCube
- Стандарт Function Calling: `store()`, `recall()`, `update_relationship()`

### 3. Декларативная vs Процедурная память (ACT-R/SOAR)
- Факты (что) — обычный decay
- Инструкции (как) — медленный decay, "мышечная память" агента
- Разные правила затухания для разных типов кубов

### 4. Волновой резонанс (Spiking Neural Networks)
- Одновременная активация → мгновенный буст связи
- max_depth можно обойти через резонанс
- Эффект "чертога разума" для дальних ассоциаций

## 🎉 Сделано 05.06.2026
- [x] **Directed Edges (STDP)** — направленные связи ✅
- [x] **Contrastive Hebbian** — negative sampling ✅
- [x] **Массовый посев через Qdrant** — 5152 новых связей ✅
- [x] **hybrid_search** — 5 кубов (было 1) ✅
- [x] **Spreading Activation** — _top=5 ✅
- [x] **Данные в /data/skv/** — защищены от volume mount ✅
- [x] **API мониторинг** — /api/v4/graph/stats (7173 edges) ✅
- [x] **Hebbian создаёт новые связи** ✅
