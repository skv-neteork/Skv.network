"""Constitution Guard — защита конституционных кубов от потери правил."""
import json, os

ORIGINALS_DIR = "/app/knowledge_library/cubes/constitutional"

def load_original_rules():
    """Загрузить оригинальные правила из knowledge_library."""
    rules = {}
    if not os.path.exists(ORIGINALS_DIR):
        return rules
    
    for fname in os.listdir(ORIGINALS_DIR):
        if fname.endswith('.json'):
            with open(os.path.join(ORIGINALS_DIR, fname)) as f:
                d = json.load(f)
                title = d.get('title', '')
                rules[title] = d.get('rules', [])
    return rules

def validate_and_repair(graph: dict) -> int:
    """Проверить конституционные кубы и восстановить правила если потеряны."""
    originals = load_original_rules()
    repaired = 0
    
    for cid, c in graph.items():
        if not c.get('metadata', {}).get('is_constitutional'):
            continue
        
        current_rules = c['metadata'].get('rules', [])
        if len(current_rules) == 0:
            # Правила потеряны — ищем оригинал
            title = c['metadata'].get('title', '')
            for orig_title, orig_rules in originals.items():
                if any(word in title for word in orig_title.split(' — ')[0].split()):
                    c['metadata']['rules'] = orig_rules
                    repaired += 1
                    print(f"[GUARD] Repaired: {title[:50]} ({len(orig_rules)} rules)")
                    break
    
    return repaired
