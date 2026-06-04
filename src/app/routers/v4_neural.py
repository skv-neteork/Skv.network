"""V4 Neural Search + Hebbian Learning — вызывается из consult.py одной строкой."""
from app.routers.v4_graph import get_graph
from app.routers.tensor_cube import hebbian_update

def run_decay_cycle():
    """Ослабляет неиспользуемые связи."""
    try:
        _graph = get_graph()
        if _graph:
            for _cube in _graph.values():
                if hasattr(_cube, 'decay_connections') and not _cube.metadata.get('constitutional'):
                    _cube.decay_connections()
            print(f"[V4] Decay applied to {len(_graph)} cubes", flush=True)
    except Exception as e:
        print(f"[V4] Decay error: {e}", flush=True)

def run_neural_cycle() -> str:
    """Запускает spreading activation и Hebbian update. Возвращает контекст для LLM."""
    try:
        _graph = get_graph()
        if not _graph:
            return ""
        
        print(f"[V4] Neural cycle on {len(_graph)} cubes", flush=True)
        
        # Hebbian update на активных кубах
        # Не трогаем конституционные кубы
        non_const = [cid for cid, cb in _graph.items() if not cb.metadata.get('constitutional')]
        active_ids = (non_const or list(_graph.keys()))[:5]
        hebbian_update(_graph, active_ids)
        print(f"[V4] Hebbian updated {len(active_ids)} cubes", flush=True)
        
        # TODO: spreading activation когда починим связи
        return ""
    except Exception as e:
        print(f"[V4] Neural error: {e}", flush=True)
        return ""

# Alias для lifespan
def run_hebbian_cycle():
    """Вызов Hebbian learning — используется в lifespan main.py."""
    run_neural_cycle()
