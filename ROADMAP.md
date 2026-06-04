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
- [ ] **Adaptive Decay** — умное забывание на основе usage_count
- [ ] **Персональная память проектов** — user_id + project, бесконечный контекст
- [ ] **Обновить конституционные кубы** — тексты под v4 TensorCube

## ⚡ Важно
- [ ] **Создание кубов через API** — POST /api/v4/cubes
- [ ] **Обновить формат анкет** — под v4
- [ ] **Восстановить Trials + Evolver**

## 📦 Масштабирование (когда > 10 000 кубов)
- [ ] Hierarchical Topology (meta-узлы)
- [ ] Qdrant int8 (квантование)
- [ ] RocksDB (холодное хранение)
- [ ] Шардирование графа

## 🐛 Баги деплоя
- [ ] Volume mount отключить (перезаписывает файлы при рестарте)
- [ ] Контейнер в правильной сети Docker
