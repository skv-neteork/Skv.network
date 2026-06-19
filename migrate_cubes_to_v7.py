"""
Миграция 1200 experience cubes из PostgreSQL в shared_matrix v7.7-Ultimate
"""
import psycopg2
import requests
import numpy as np
import json
import logging
from typing import List, Dict, Optional
from fastembed import TextEmbedding
from tqdm import tqdm

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class CubeMigrator:
    def __init__(
        self,
        pg_host: str = "localhost",
        pg_port: int = 5432,
        pg_db: str = "skv",
        pg_user: str = "skv_user",
        pg_password: str = "skv_password",
        v7_api_url: str = "http://localhost:8000",
        auth_token: str = "Bearer test_token"
    ):
        self.pg_config = {
            "host": pg_host,
            "port": pg_port,
            "dbname": pg_db,
            "user": pg_user,
            "password": pg_password
        }
        self.v7_url = v7_api_url
        self.auth_token = auth_token
        self.headers = {
            "Content-Type": "application/json",
            "Authorization": auth_token
        }
        
        # Инициализируем FastEmbed
        logger.info("🔄 Инициализация FastEmbed (BAAI/bge-small-en-v1.5)...")
        self.embedder = TextEmbedding(model_name="BAAI/bge-small-en-v1.5")
        logger.info("✅ FastEmbed готов")
    
    def fetch_cubes_from_db(self) -> List[Dict]:
        """Загружает все experience кубы из PostgreSQL"""
        logger.info("📊 Подключение к PostgreSQL...")
        
        try:
            conn = psycopg2.connect(**self.pg_config)
            cursor = conn.cursor()
            
            query = """
                SELECT cube_id, title, rules, trigger_intent
                FROM cubes
                WHERE type = 'experience' OR is_constitutional = false
                ORDER BY created_at
            """
            
            cursor.execute(query)
            rows = cursor.fetchall()
            
            cubes = []
            for row in rows:
                cube_id, title, rules, trigger_intent = row
                cubes.append({
                    "cube_id": cube_id,
                    "title": title or "",
                    "rules": rules if isinstance(rules, list) else [],
                    "trigger_intent": trigger_intent if isinstance(trigger_intent, list) else []
                })
            
            cursor.close()
            conn.close()
            
            logger.info(f"✅ Загружено {len(cubes)} experience кубов из PostgreSQL")
            return cubes
            
        except Exception as e:
            logger.error(f"❌ Ошибка подключения к PostgreSQL: {e}")
            return []
    
    def create_embedding(self, cube: Dict) -> List[float]:
        """
        Создаёт 218-dim семантический эмбеддинг из title + rules.
        FastEmbed BAAI/bge-small-en-v1.5 даёт 384-dim, обрезаем до 218.
        """
        # Формируем текст для эмбеддинга
        text_parts = [cube.get("title", "")]
        text_parts.extend(cube.get("rules", []))
        text = " ".join(text_parts).strip()
        
        if not text:
            # Если текст пустой, возвращаем нулевой вектор
            return [0.0] * 218
        
        # Создаём эмбеддинг через FastEmbed
        embeddings = list(self.embedder.embed([text]))
        emb_384 = embeddings[0]
        
        # Обрезаем до 218-dim (слой 3: семантика)
        emb_218 = emb_384[:218]
        
        # Нормализация
        norm = np.linalg.norm(emb_218)
        if norm > 0:
            emb_218 = emb_218 / norm
        
        return emb_218.tolist()
    
    def migrate_cube(self, cube: Dict, max_retries: int = 3) -> bool:
        """Мигрирует один куб в v7 shared_matrix"""
        cube_id = cube["cube_id"]
        
        for attempt in range(max_retries):
            try:
                # Создаём эмбеддинг
                emb = self.create_embedding(cube)
                
                # Отправляем в v7 API
                response = requests.post(
                    f"{self.v7_url}/api/v7/experience/create",
                    headers=self.headers,
                    json={
                        "event_id": cube_id,
                        "semantics_emb": emb
                    },
                    timeout=10
                )
                
                if response.status_code == 201:
                    return True
                elif response.status_code == 409:
                    # Куб уже существует, пропускаем
                    logger.debug(f"⏭️  Куб {cube_id} уже существует")
                    return True
                else:
                    logger.warning(
                        f"⚠️  Попытка {attempt+1}/{max_retries} для {cube_id}: "
                        f"{response.status_code} - {response.text}"
                    )
                    
            except Exception as e:
                logger.warning(
                    f"⚠️  Попытка {attempt+1}/{max_retries} для {cube_id}: {e}"
                )
        
        logger.error(f"❌ Не удалось мигрировать куб {cube_id} после {max_retries} попыток")
        return False
    
    def save_backup(self, cubes: List[Dict], filename: str = "migration_backup.json"):
        """Сохраняет список cube_id в файл для бэкапа"""
        backup_data = {
            "total_cubes": len(cubes),
            "cube_ids": [cube["cube_id"] for cube in cubes],
            "timestamp": __import__("datetime").datetime.now().isoformat()
        }
        
        with open(filename, "w", encoding="utf-8") as f:
            json.dump(backup_data, f, indent=2, ensure_ascii=False)
        
        logger.info(f"💾 Бэкап сохранён: {filename}")
    
    def verify_migration(self) -> bool:
        """Проверяет результат миграции через health endpoint"""
        try:
            response = requests.get(f"{self.v7_url}/api/v7/health", timeout=5)
            if response.status_code == 200:
                health = response.json()
                shared_size = health.get("shared_size", 0)
                logger.info(f"✅ Проверка миграции: shared_size = {shared_size}")
                return shared_size > 0
        except Exception as e:
            logger.error(f"❌ Ошибка проверки миграции: {e}")
        
        return False
    
    def test_search(self, query_text: str = "docker kubernetes deployment"):
        """Тестирует поиск по shared_matrix"""
        logger.info(f"🔍 Тестирование поиска: '{query_text}'")
        
        # Создаём эмбеддинг для запроса
        emb_384 = list(self.embedder.embed([query_text]))[0]
        emb_218 = emb_384[:218]
        query_vec = emb_218.tolist() + [0.0] * 294  # Добиваем до 512
        
        try:
            response = requests.post(
                f"{self.v7_url}/api/v7/search",
                headers={"Content-Type": "application/json"},
                json={
                    "query_vector": query_vec,
                    "user_id": "test_user",
                    "hops": 2,
                    "top_k": 5
                },
                timeout=10
            )
            
            if response.status_code == 200:
                results = response.json().get("results", [])
                logger.info(f"✅ Найдено результатов: {len(results)}")
                for i, result in enumerate(results[:3], 1):
                    logger.info(
                        f"  {i}. {result['event_id']} "
                        f"(score: {result['score']:.3f}, source: {result['source']})"
                    )
        except Exception as e:
            logger.error(f"❌ Ошибка тестирования поиска: {e}")
    
    def run_migration(self):
        """Основной цикл миграции"""
        logger.info("🚀 Начало миграции v6.0 → v7.7-Ultimate")
        logger.info("=" * 60)
        
        # 1. Загружаем кубы из PostgreSQL
        cubes = self.fetch_cubes_from_db()
        if not cubes:
            logger.error("❌ Нет кубов для миграции")
            return
        
        # 2. Сохраняем бэкап
        self.save_backup(cubes)
        
        # 3. Мигрируем кубы
        success_count = 0
        fail_count = 0
        failed_cubes = []
        
        logger.info(f"📦 Начинаем миграцию {len(cubes)} кубов...")
        
        for cube in tqdm(cubes, desc="Миграция кубов"):
            if self.migrate_cube(cube):
                success_count += 1
            else:
                fail_count += 1
                failed_cubes.append(cube["cube_id"])
        
        # 4. Логируем результат
        logger.info("=" * 60)
        logger.info(f"✅ Успешно мигрировано: {success_count}/{len(cubes)}")
        logger.info(f"❌ Ошибок: {fail_count}")
        
        if failed_cubes:
            logger.warning(f"⚠️  Неудачные кубы: {failed_cubes[:10]}...")
        
        # 5. Проверяем миграцию
        if self.verify_migration():
            logger.info("✅ Миграция завершена успешно!")
            
            # 6. Тестируем поиск
            self.test_search()
        else:
            logger.error("❌ Миграция завершена с ошибками")


if __name__ == "__main__":
    migrator = CubeMigrator(
        pg_host="skv_postgres",
        pg_port=5432,
        pg_db="skv_db",
        pg_user="skv_user",
        pg_password="skv_secret_2026",
        v7_api_url="http://localhost:8000",
        auth_token="Bearer test_token"
    )
    migrator.run_migration()
