"""
Миграция experience cubes из SKV v6 в shared_matrix v7.7-Ultimate
"""
import requests
import numpy as np
import json
import logging
from typing import List, Dict

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class V6ToV7Migrator:
    def __init__(self, v6_api_url: str, v7_api_url: str):
        self.v6_url = v6_api_url
        self.v7_url = v7_api_url
        self.headers = {
            'Content-Type': 'application/json',
            'Authorization': 'Bearer migration_token'  # SEAL level >= 3
        }
    
    def fetch_v6_cubes(self, limit: int = 2000) -> List[Dict]:
        """Получает все experience cubes из v6"""
        try:
            r = requests.get(
                f"{self.v6_url}/api/v1/entries",
                params={"type": "experience", "limit": limit},
                timeout=30
            )
            if r.status_code == 200:
                data = r.json()
                cubes = data.get("cubes", [])
                logger.info(f"✅ Fetched {len(cubes)} cubes from v6")
                return cubes
        except Exception as e:
            logger.error(f"❌ Failed to fetch v6 cubes: {e}")
        return []
    
    def create_embedding_from_cube(self, cube: Dict) -> List[float]:
        """
        Создаёт 218-dim семантический эмбеддинг из куба.
        В продакшене здесь будет FastEmbed, но для MVP используем хэш.
        """
        # Простой хэш для MVP (в продакшене заменить на FastEmbed)
        text = f"{cube.get('title', '')} {' '.join(cube.get('rules', []))}"
        
        # Детерминированный вектор на основе хэша текста
        np.random.seed(hash(text) % (2**32))
        emb = np.random.randn(218).astype(float)
        
        # Нормализация
        emb = emb / np.linalg.norm(emb)
        
        return emb.tolist()
    
    def migrate_cube_to_v7(self, cube: Dict) -> bool:
        """Мигрирует один куб в v7 shared_matrix"""
        try:
            cube_id = cube.get("cube_id", f"exp_{cube.get('id', 'unknown')}")
            
            # Создаём эмбеддинг
            emb = self.create_embedding_from_cube(cube)
            
            # Отправляем в v7
            r = requests.post(
                f"{self.v7_url}/api/v7/experience/create",
                headers=self.headers,
                json={
                    'event_id': cube_id,
                    'semantics_emb': emb
                },
                timeout=10
            )
            
            if r.status_code == 201:
                logger.info(f"✅ Migrated: {cube.get('title', cube_id)}")
                return True
            else:
                logger.warning(f"⚠️ Failed: {cube_id} - {r.status_code} {r.text}")
                return False
        
        except Exception as e:
            logger.error(f"❌ Error migrating {cube.get('title', 'unknown')}: {e}")
            return False
    
    def run_migration(self, batch_size: int = 50):
        """Запускает полную миграцию"""
        logger.info("🚀 Starting migration v6 → v7...")
        
        # Получаем кубы
        cubes = self.fetch_v6_cubes()
        if not cubes:
            logger.error("❌ No cubes to migrate")
            return
        
        # Мигрируем
        success = 0
        failed = 0
        
        for i, cube in enumerate(cubes):
            if self.migrate_cube_to_v7(cube):
                success += 1
            else:
                failed += 1
            
            if (i + 1) % batch_size == 0:
                logger.info(f"📦 Progress: {i+1}/{len(cubes)} (success={success}, failed={failed})")
        
        logger.info(f"🎉 Migration complete: {success}/{len(cubes)} cubes migrated")


if __name__ == "__main__":
    migrator = V6ToV7Migrator(
        v6_api_url="https://skv.network",
        v7_api_url="http://localhost:8000"
    )
    migrator.run_migration()
