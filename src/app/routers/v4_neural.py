"""V4 Neural Search + Hebbian Learning — вызывается из consult.py одной строкой."""
from app.routers.v4_graph import get_graph
from app.routers.tensor_cube import hebbian_update

def run_neural_cycle() -> str:
    """Запускает spreading activation и Hebbian update. Возвращает контекст для LLM."""
    try:
        _graph = get_graph()
        if not _graph:
            return ""
        
        print(f"[V4] Neural cycle on {len(_graph)} cubes", flush=True)
        
        # Hebbian update на активных кубах
        active_ids = list(_graph.keys())[:5]
        hebbian_update(_graph, active_ids)
        print(f"[V4] Hebbian updated {len(active_ids)} cubes", flush=True)
        
        # TODO: spreading activation когда починим связи
        return ""
    except Exception as e:
        print(f"[V4] Neural error: {e}", flush=True)
        return ""
