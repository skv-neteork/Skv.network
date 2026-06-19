"""Memory Cube Chain — единая графовая модель памяти SKV v6.0"""
from dataclasses import dataclass, field
from typing import Optional, List
import math

@dataclass
class PIIItem:
    type: str         # "token", "password", "date", "email", "code", "ip", "url"
    value: str        # само значение
    context: str      # ±100 символов вокруг
    expires: Optional[str] = None

@dataclass
class SessionCube:
    cube_id: str
    user_id: str
    project: str
    vector: List[float]  # 384-dim embedding
    summary: str
    topics: List[str]
    timestamp: str
    pii: List[PIIItem] = field(default_factory=list)
    full_text: Optional[str] = None
    
    # Рёбра
    prev_session: Optional[str] = None
    next_session: Optional[str] = None
    related_topics: List[str] = field(default_factory=list)
    same_project: List[str] = field(default_factory=list)
    contains_pii: bool = False

    def cosine_similarity(self, other_vector: List[float]) -> float:
        if not self.vector or not other_vector:
            return 0.0
        dot_prod = sum(a * b for a, b in zip(self.vector, other_vector))
        mag_a = math.sqrt(sum(a * a for a in self.vector))
        mag_b = math.sqrt(sum(b * b for b in other_vector))
        if mag_a == 0 or mag_b == 0:
            return 0.0
        return dot_prod / (mag_a * mag_b)

# === Decay Factors ===
DECAY = {
    "PREV_SESSION":  {"weight": 0.9, "decay": 0.7},
    "NEXT_SESSION":  {"weight": 0.9, "decay": 0.7},
    "RELATED_TOPIC": {"weight": 0.6, "decay": 0.85},
    "SAME_PROJECT":  {"weight": 0.4, "decay": 0.9},
}

async def spreading_activation_v2(query_vector, user_id, 
                                   search_type="general",
                                   max_hops=3, threshold=0.15, max_results=20):
    """Spreading activation с жестким контролем типов через поля SessionCube"""
    from app.routers.v4_graph import _v4_graph
    
    activated = []
    visited = set()

    # Шаг 0: начальная активация по similarity
    for cid, cube in _v4_graph.items():
        if not isinstance(cube, SessionCube) or cube.vector is None:
            continue
        if cube.user_id != user_id:
            continue
        if search_type != "pii" and cube.contains_pii:
            continue

        sim = float(cube.cosine_similarity(query_vector))
        if sim > threshold:
            activated.append({
                "id": cid, "energy": sim, "hop": 0, "edge_type": "similarity"
            })
            visited.add(cid)

    # Шаги 1..N: распространение по рёбрам
    for hop in range(1, max_hops + 1):
        new_activated = []
        for item in activated:
            if item["hop"] != hop - 1:
                continue
            cube = _v4_graph.get(item["id"])
            if not cube:
                continue

            if search_type == "pii":
                edges_to_follow = ["PREV_SESSION", "NEXT_SESSION"]
            elif search_type == "topic":
                edges_to_follow = ["RELATED_TOPIC"]
            else:
                edges_to_follow = ["PREV_SESSION", "NEXT_SESSION", "RELATED_TOPIC", "SAME_PROJECT"]

            for edge_type in edges_to_follow:
                targets = []
                if edge_type == "PREV_SESSION" and cube.prev_session:
                    targets.append(cube.prev_session)
                elif edge_type == "NEXT_SESSION" and cube.next_session:
                    targets.append(cube.next_session)
                elif edge_type == "RELATED_TOPIC":
                    targets.extend(cube.related_topics)
                elif edge_type == "SAME_PROJECT":
                    targets.extend(cube.same_project)

                for tid in targets:
                    if tid in visited:
                        continue
                    tcube = _v4_graph.get(tid)
                    if not tcube:
                        continue

                    edge_cfg = DECAY.get(edge_type, {"weight": 0.5, "decay": 0.5})
                    energy = item["energy"] * edge_cfg["weight"] * edge_cfg["decay"]

                    if energy > threshold:
                        new_activated.append({
                            "id": tid, "energy": energy,
                            "hop": hop, "edge_type": edge_type
                        })
                        visited.add(tid)

        activated.extend(new_activated)

    activated.sort(key=lambda x: -x["energy"])
    return activated[:max_results]

print("[v4_cube_chain] Memory Cube Chain model loaded and fixed")
