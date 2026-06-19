"""
SKV v7.7-HPC-Stable: Cognitive Text Decoder (Final)
Клиентский декодер метаданных в когнитивную карту для ИИ.

Исправления:
1. Null-Safety: жесткая проверка типов через isinstance
2. Attention Drift: убраны пустые скобки [нет]
3. Dead Code: убран metadata_store (клиент получает готовый JSON)
"""
from typing import Dict, Any, List


class ChronoCognitiveDecoder:
    """
    Декодирует метаданные событий в когнитивную карту для ИИ.
    Работает на стороне клиента (Guardian SDK).
    """
    
    @staticmethod
    def decode_event_metadata(
        event_id: str,
        metadata: Dict[str, Any],
        score: float,
        source: str
    ) -> str:
        """
        Декодирует метаданные события в карточку памяти.
        
        Защита от грязных типов данных:
        - isinstance(links, list) перед .join()
        - Чистый вывод без пустых скобок
        """
        metadata = metadata or {}
        
        time_str = metadata.get("time") or "Вневременной куб"
        metric_val = metadata.get("metric_value") or "нет"
        
        # ФИКС #1: Жесткая проверка типов для links
        raw_links = metadata.get("links")
        if isinstance(raw_links, list):
            links_str = ", ".join(str(l) for l in raw_links) if raw_links else "нет"
        else:
            links_str = str(raw_links) if raw_links else "нет"
        
        # ФИКС #2: Чистый вывод без пустых скобок
        links_display = f"[{links_str}]" if links_str != "нет" else "нет"
        
        essence = metadata.get("essence") or "Суть не извлечена"
        
        # Жесткая проверка типов для topics
        raw_topics = metadata.get("topics")
        if isinstance(raw_topics, list):
            topics_str = ", ".join(str(t) for t in raw_topics) if raw_topics else "нет"
        else:
            topics_str = str(raw_topics) if raw_topics else "нет"
        
        msg_count = metadata.get("messages_count") or 0
        
        card = f"""[МАРКЕР ПАМЯТИ SKV] ID: {event_id} | Источник: {source} | Релевантность: {score:.2f} | Метрика: {metric_val} | Связи: {links_display}
  
  ◆ ХРОНО-ДИСК:
    Время события: {time_str}
    
  ◆ СЮЖЕТНАЯ СУТЬ:
    {essence}
  
  ◆ МЕТА-ДЕТАЛИ:
    Ключевые темы: {topics_str}
    Объем контекста: {msg_count} реплик.
  ========================================================================"""
        return card

    @classmethod
    def decode_search_results(cls, results: List[Dict[str, Any]]) -> str:
        """
        Декодирует результаты поиска в монолитный блок контекста.
        
        ФИКС #3: Убран metadata_store — клиент получает готовый JSON
        от роутера с метаданными внутри каждого item.
        """
        if not results:
            return "=== В ДОЛГОВРЕМЕННОЙ ПАМЯТИ SKV СОВПАДЕНИЙ НЕ НАЙДЕНО ===\n"
        
        manifest = [
            "=== КОНЦЕНТРАТ ИЗВЛЕЧЕННОЙ ПАМЯТИ АГЕНТА (SKV v7.7-HPC-Stable) ===",
            "ИНСТРУКЦИЯ: Сканируй заголовки и суть. Если критически необходим",
            "исходный Raw-текст диалога, вызови инструмент `get_event_detail(event_id)`.\n"
        ]
        
        for item in results:
            event_id = item.get("event_id", "unknown")
            score = item.get("score", 0.0)
            source = item.get("source", "unknown")
            
            # Метаданные уже внутри item (пакетная отдача от роутера)
            metadata = item.get("metadata") or {}
            
            card_text = cls.decode_event_metadata(event_id, metadata, score, source)
            manifest.append(card_text)
        
        return "\n".join(manifest)
