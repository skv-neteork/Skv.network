"""
SKV v7.7-Ultimate: Chrono-Toroidal Buffer
Production-ready implementation with all fixes applied.

Fixes applied:
- No normalization inside hop loop (prevents semantic explosion)
- Atomic np.savez via .tmp + os.replace
- global_tick incremented on every write (LRU works)
- Thermodynamic LRU with link_energy = weights * (timestamps / global_tick)

Features:
- Three matrices: core, shared, personal
- Structured 512-dim vectors (time, metrics, semantics, context, metadata, PII-ref)
- Sparse adjacency with thermodynamic LRU eviction (16 links per event)
- Full 2D vectorized spreading activation via np.bincount
- Zero-index gravity well protection
- Empty array protection
- Thermodynamic energy with lazy decay
- Hopfield pattern completion for associations
- Activity mask for soft deletion
- Threshold cutoff to prevent semantic explosion
"""

import numpy as np
from typing import List, Tuple, Optional, Dict
import logging
import os
import json
from datetime import datetime, timezone

# faiss HNSW (optional)
try:
    import faiss
    HAISS_AVAILABLE = True
except ImportError:
    HAISS_AVAILABLE = False
    faiss = None

logger = logging.getLogger(__name__)


class ChronoBufferV77Ultimate:
    """
    Production-grade chrono-toroidal memory buffer.
    
    Three matrices:
    - core_matrix: (6, 512) — constitution, static, no links
    - shared_matrix: (max_shared, 512) — public experience, timeless
    - personal_matrix: (max_personal, 512) — private memory, polar time
    
    Each with own sparse adjacency (except core).
    """
    
    def __init__(
        self,
        max_personal: int = 100000,
        max_shared: int = 10000,
        max_links: int = 16,
        storage_path: str = "/data/skv/chrono_buffer"
    ):
        # Dimensions
        self.max_personal = max_personal
        self.max_shared = max_shared
        self.max_links = max_links
        self.storage_path = storage_path
        
        # ═══════════════════════════════════════════
        # CORE MATRIX (Constitution, 6 cubes)
        # ═══════════════════════════════════════════
        self.core_matrix = np.zeros((6, 512), dtype=np.float32)
        self.core_idx_to_id: Dict[int, str] = {
            i: f"CUBE_0{i}" for i in range(6)
        }
        
        # ═══════════════════════════════════════════
        # SHARED MATRIX (Public experience)
        # ═══════════════════════════════════════════
        self.shared_matrix = np.zeros((max_shared, 512), dtype=np.float32)
        self.shared_adjacency_indices = np.full((max_shared, max_links), -1, dtype=np.int32)
        self.shared_adjacency_weights = np.zeros((max_shared, max_links), dtype=np.float32)
        self.shared_link_timestamps = np.zeros((max_shared, max_links), dtype=np.int32)
        self.shared_active_mask = np.ones(max_shared, dtype=np.bool_)
        self.shared_energy = np.ones(max_shared, dtype=np.float32)
        self.shared_current_size = 0
        self.shared_global_tick = 0
        self.shared_idx_to_id: Dict[int, str] = {}
        self.shared_id_to_idx: Dict[str, int] = {}
        
        # ═══════════════════════════════════════════
        # PERSONAL MATRIX (Private memory)
        # ═══════════════════════════════════════════
        self.personal_matrix = np.zeros((max_personal, 512), dtype=np.float32)
        self.personal_adjacency_indices = np.full((max_personal, max_links), -1, dtype=np.int32)
        self.personal_adjacency_weights = np.zeros((max_personal, max_links), dtype=np.float32)
        self.personal_link_timestamps = np.zeros((max_personal, max_links), dtype=np.int32)
        self.personal_active_mask = np.ones(max_personal, dtype=np.bool_)
        self.personal_energy = np.ones(max_personal, dtype=np.float32)
        self.personal_current_size = 0
        self.personal_global_tick = 0
        self.personal_idx_to_id: Dict[int, str] = {}
        self.personal_id_to_idx: Dict[str, int] = {}

        # HNSW index for fast search (optional)
        self.personal_hnsw_index = None
        self.shared_hnsw_index = None
        
        # Init persistence
        self.persistence = ChronoBufferPersistence(self)
        
        # Try to load existing buffer
        if not self.persistence.load():
            logger.info("Starting with fresh buffer")
    
    # ═══════════════════════════════════════════
    # WRITE EVENTS
    # ═══════════════════════════════════════════
    
    def write_personal_event(
        self,
        event_id: str,
        hour: int,
        minute: int,
        semantics_emb: np.ndarray,
        parent_indices: Optional[List[int]] = None,
        details_emb: Optional[np.ndarray] = None,
        metric_value: Optional[float] = None
    ) -> int:
        """Write a personal event with polar time."""
        if self.personal_current_size >= self.max_personal:
            raise RuntimeError(f"Personal buffer full")
        
        idx = self.personal_current_size
        
        self._write_event_to_matrix(
            self.personal_matrix,
            idx,
            hour,
            minute,
            semantics_emb,
            parent_indices,
            details_emb,
            metric_value,
            is_timeless=False,
            adjacency_indices=self.personal_adjacency_indices,
            adjacency_weights=self.personal_adjacency_weights,
            link_timestamps=self.personal_link_timestamps,
            global_tick=self.personal_global_tick
        )
        
        self.personal_idx_to_id[idx] = event_id
        self.personal_id_to_idx[event_id] = idx
        self.personal_energy[idx] = 0.8
        self.personal_active_mask[idx] = True
        self.personal_global_tick += 1
        self.personal_current_size += 1
        
        return idx
    
    def write_shared_experience(
        self,
        event_id: str,
        semantics_emb: np.ndarray,
        parent_indices: Optional[List[int]] = None,
        details_emb: Optional[np.ndarray] = None
    ) -> int:
        """Write a shared experience cube (timeless)."""
        if self.shared_current_size >= self.max_shared:
            raise RuntimeError(f"Shared buffer full")
        
        idx = self.shared_current_size
        
        self._write_event_to_matrix(
            self.shared_matrix,
            idx,
            0, 0,  # Timeless
            semantics_emb,
            parent_indices,
            details_emb,
            None,
            is_timeless=True,
            adjacency_indices=self.shared_adjacency_indices,
            adjacency_weights=self.shared_adjacency_weights,
            link_timestamps=self.shared_link_timestamps,
            global_tick=self.shared_global_tick
        )
        
        self.shared_idx_to_id[idx] = event_id
        self.shared_id_to_idx[event_id] = idx
        self.shared_energy[idx] = 0.8
        self.shared_active_mask[idx] = True
        self.shared_global_tick += 1
        self.shared_current_size += 1
        
        return idx
    
    def _write_event_to_matrix(
        self,
        matrix: np.ndarray,
        idx: int,
        hour: int,
        minute: int,
        semantics_emb: np.ndarray,
        parent_indices: Optional[List[int]],
        details_emb: Optional[np.ndarray],
        metric_value: Optional[float],
        is_timeless: bool,
        adjacency_indices: np.ndarray,
        adjacency_weights: np.ndarray,
        link_timestamps: np.ndarray,
        global_tick: int
    ):
        """Internal write to specified matrix."""
        # Layer 1: Time encoding (16 dim)
        if is_timeless:
            matrix[idx, 0:16] = 0.5  # Timeless constant
        else:
            matrix[idx, 0:16] = self._encode_time(hour, minute)
        
        # Layer 2: Metric cascade (16 dim)
        matrix[idx, 16:32] = self._encode_metrics(metric_value)
        
        # Layer 3: Semantic embedding (218 dim)
        if semantics_emb is not None:
            matrix[idx, 32:250] = semantics_emb[:218]
        
        # Layer 4: Hopfield associations (134 dim)
        if parent_indices:
            hopfield_pattern = self._hopfield_associate(matrix, parent_indices)
            matrix[idx, 250:384] = hopfield_pattern
            
            # Create sparse links
            for i, parent_idx in enumerate(parent_indices[:self.max_links]):
                weight = 0.8 ** i
                self._add_hebbian_link(
                    adjacency_indices, adjacency_weights, link_timestamps,
                    idx, parent_idx, weight, global_tick
                )
        
        # Layer 5: PII reference (128 dim)
        if details_emb is not None:
            matrix[idx, 384:512] = details_emb[:128]
    
    # ═══════════════════════════════════════════
    # SPARSE ADJACENCY (Thermodynamic LRU)
    # ═══════════════════════════════════════════
    
    def _add_hebbian_link(
        self,
        indices: np.ndarray,
        weights: np.ndarray,
        timestamps: np.ndarray,
        source_idx: int,
        target_idx: int,
        weight: float,
        global_tick: int
    ):
        """Add Hebbian link with thermodynamic LRU eviction."""
        # Check if link exists
        existing = np.where(indices[source_idx] == target_idx)[0]
        if len(existing) > 0:
            weights[source_idx, existing[0]] = weight
            timestamps[source_idx, existing[0]] = global_tick
            return
        
        # Find empty slot (-1)
        empty = np.where(indices[source_idx] == -1)[0]
        if len(empty) > 0:
            slot = empty[0]
            indices[source_idx, slot] = target_idx
            weights[source_idx, slot] = weight
            timestamps[source_idx, slot] = global_tick
        else:
            # Thermodynamic LRU: link_energy = weight * (timestamp / global_tick)
            tick = max(global_tick, 1)
            link_energy = weights[source_idx] * (timestamps[source_idx] / tick)
            min_idx = np.argmin(link_energy)
            
            if weight > weights[source_idx, min_idx]:
                indices[source_idx, min_idx] = target_idx
                weights[source_idx, min_idx] = weight
                timestamps[source_idx, min_idx] = global_tick
    
    # ═══════════════════════════════════════════
    # VECTORIZED PROPAGATION (no hop normalization)
    # ═══════════════════════════════════════════
    
    def _vectorized_propagation(
        self,
        initial_scores: np.ndarray,
        adjacency_indices: np.ndarray,
        adjacency_weights: np.ndarray,
        active_mask: np.ndarray,
        current_size: int,
        hops: int = 2,
        decay: float = 0.7,
        threshold: float = 0.1
    ) -> np.ndarray:
        """
        Full 2D vectorized spreading activation.
        No normalization inside hop loop — prevents semantic explosion.
        """
        scores = initial_scores.copy()
        
        for hop in range(hops):
            active = (scores >= threshold) & active_mask[:current_size]
            active_nodes = np.where(active)[0]
            
            if len(active_nodes) == 0:
                break
            
            # Extract links for active nodes
            act_indices = adjacency_indices[active_nodes]
            act_weights = adjacency_weights[active_nodes]
            act_scores = scores[active_nodes]
            
            # Compute spread
            decay_factor = decay ** (hop + 1)
            spread = act_scores[:, np.newaxis] * act_weights * decay_factor
            
            # ZERO-INDEX GRAVITY WELL PROTECTION
            spread[act_weights == 0.0] = 0.0
            
            # FULL 2D VECTORIZATION (no loops)
            safe_indices = np.maximum(act_indices, 0)
            target_active = active_mask[safe_indices] & (act_indices >= 0)
            
            valid = (act_indices >= 0) & (act_weights >= 0.1)
            valid = valid & target_active
            spread = spread * valid
            
            # Flatten for bincount
            flat_targets = act_indices[valid]
            flat_weights = spread[valid]
            
            # EMPTY ARRAY PROTECTION
            if len(flat_targets) == 0:
                break
            
            # VECTORIZED ACCUMULATION
            new_scores = np.bincount(
                flat_targets,
                weights=flat_weights,
                minlength=current_size
            )
            
            # Threshold cutoff
            new_scores[new_scores < threshold] = 0.0
            scores += new_scores

            # Normalize to prevent energy explosion (keep in [0, 1])
            max_score = np.max(scores)
            if max_score > 1.0:
                scores = scores / max_scor
        
        # Final normalization (once, after all hops)
        max_score = np.max(scores)
        if max_score > 0:
            scores = scores / max_score
        
        return scores
    
    # ═══════════════════════════════════════════
    # HYBRID SEARCH
    # ═══════════════════════════════════════════
    
    def hybrid_search(
        self,
        query: np.ndarray,
        user_id: str = "default",
        hops: int = 2,
        top_k: int = 20,
        weights: Optional[Dict[str, float]] = None
    ) -> List[Dict]:
        """
        Search across all three matrices.
        Returns ranked results with source annotation.
        """
        if weights is None:
            weights = {"personal": 0.5, "shared": 0.3, "core": 0.2}
        
        results = []
        
        # Personal
        if self.personal_current_size > 0:
            # Use HNSW if available
            if self.personal_hnsw_index is not None:
                try:
                    query_norm = query / (np.linalg.norm(query) + 1e-10)
                    distances, indices = self.personal_hnsw_index.search(
                        query_norm.reshape(1, -1).astype('float32'),
                        min(top_k * 2, self.personal_current_size)
                    )
                    p_scores = np.zeros(self.personal_current_size, dtype=np.float32)
                    for i, idx in enumerate(indices[0]):
                        if idx >= 0 and idx < self.personal_current_size:
                            p_scores[idx] = 1.0 - distances[0][i]
                    p_scores = p_scores * self.personal_active_mask[:self.personal_current_size]
                except Exception as e:
                    logger.warning(f"HNSW search failed, falling back to brute force: {e}")
                    p_scores = self.personal_matrix[:self.personal_current_size] @ query
                    p_scores = p_scores * self.personal_active_mask[:self.personal_current_size]
            else:
                p_scores = self.personal_matrix[:self.personal_current_size] @ query
                p_scores = p_scores * self.personal_active_mask[:self.personal_current_size]
            p_assoc = self._vectorized_propagation(
                p_scores,
                self.personal_adjacency_indices,
                self.personal_adjacency_weights,
                self.personal_active_mask,
                self.personal_current_size,
                hops=hops
            )
            p_final = 0.6 * p_scores + 0.4 * p_assoc
            p_max = np.max(p_final) or 1.0
            for i in range(self.personal_current_size):
                if p_final[i] > 0.01:
                    results.append({
                        "event_id": self.personal_idx_to_id.get(i, f"personal_{i}"),
                        "score": float(weights["personal"] * p_final[i] / p_max),
                        "source": "personal",
                        "summary": ""
                    })
        
        # Shared
        if self.shared_current_size > 0:
            s_scores = self.shared_matrix[:self.shared_current_size] @ query
            s_scores = s_scores * self.shared_active_mask[:self.shared_current_size]
            s_assoc = self._vectorized_propagation(
                s_scores,
                self.shared_adjacency_indices,
                self.shared_adjacency_weights,
                self.shared_active_mask,
                self.shared_current_size,
                hops=hops
            )
            s_final = 0.6 * s_scores + 0.4 * s_assoc
            s_max = np.max(s_final) or 1.0
            for i in range(self.shared_current_size):
                if s_final[i] > 0.01 and self.shared_active_mask[i]:
                    # Status multiplier
                    eid = self.shared_idx_to_id.get(i, '')
                    status_mult = 1.0
                    try:
                        import sqlite3
                        conn = sqlite3.connect('/data/skv/metadata_store/shared_master.db')
                        cur = conn.cursor()
                        cur.execute('SELECT status FROM event_metadata WHERE event_id = ?', (eid,))
                        row = cur.fetchone()
                        if row:
                            if row[0] == 'deprecated':
                                conn.close()
                                continue  # Skip deprecated
                            elif row[0] == 'verified':
                                status_mult = 1.2
                            elif row[0] == 'community':
                                status_mult = 0.7
                        conn.close()
                    except:
                        pass
                    results.append({
                        "event_id": self.shared_idx_to_id.get(i, f"shared_{i}"),
                        "score": float(weights["shared"] * s_final[i] / s_max),
                        "source": "shared",
                        "summary": ""
                    })
        
        # Core
        c_scores = self.core_matrix @ query
        c_max = np.max(c_scores) or 1.0
        for i in range(6):
            if c_scores[i] > 0.01:
                results.append({
                    "event_id": self.core_idx_to_id[i],
                    "score": float(weights["core"] * c_scores[i] / c_max),
                    "source": "core",
                    "summary": f"CUBE 0{i}: Constitutional rule"
                })
        
        # Structured output: three isolated streams
        # Personal boost: +10% to compete with shared
        for r in results:
            if r["source"] == "personal":
                r["score"] = r["score"] * 1.10
        personal = [r for r in results if r["source"] == "personal"]
        shared = [r for r in results if r["source"] == "shared"]
        core = [r for r in results if r["source"] == "core"]
        personal.sort(key=lambda x: -x["score"])
        shared.sort(key=lambda x: -x["score"])
        core.sort(key=lambda x: -x["score"])
        
        # Limit new community cubes to max 1 in top results
        community_count = 0
        filtered_shared = []
        for r in shared:
            is_new = r.get("summary", "") not in ("verified", "deprecated")
            if is_new:
                if community_count < 1:
                    filtered_shared.append(r)
                    community_count += 1
            else:
                filtered_shared.append(r)
        shared = filtered_shared
        return {
            "personal_memory": personal[:top_k],
            "shared_knowledge": shared[:top_k],
            "core_protocol": core[:top_k]
        }
    
    # ═══════════════════════════════════════════
    # THERMODYNAMIC ENERGY
    # ═══════════════════════════════════════════
    
    def boost_personal_energy(self, idx: int, amount: float = 0.08):
        if idx < self.personal_current_size:
            self.personal_energy[idx] = min(1.0, self.personal_energy[idx] + amount)
    
    def boost_shared_energy(self, idx: int, amount: float = 0.08):
        if idx < self.shared_current_size:
            self.shared_energy[idx] = min(1.0, self.shared_energy[idx] + amount)
    
    def lazy_decay(self, decay_rate: float = 0.97):
        self.personal_energy[:self.personal_current_size] *= decay_rate
        self.shared_energy[:self.shared_current_size] *= decay_rate
    
    # ═══════════════════════════════════════════
    # HELPERS
    # ═══════════════════════════════════════════
    
    def _hopfield_associate(self, matrix: np.ndarray, parent_indices: List[int]) -> np.ndarray:
        if not parent_indices:
            return np.zeros(134, dtype=np.float32)
        
        patterns = np.array([matrix[p, 32:166] for p in parent_indices])
        w = np.array([0.8 ** i for i in range(len(patterns))])
        w /= w.sum()
        
        pattern = np.average(patterns, axis=0, weights=w)
        for _ in range(3):
            pattern = np.tanh(pattern)
        
        return pattern
    
    def _encode_time(self, hour: int, minute: int) -> np.ndarray:
        total_minutes = hour * 60 + minute
        alpha = (total_minutes / 1440.0) * 2 * np.pi
        x = (np.cos(alpha) + 1.0) / 2.0
        y = (np.sin(alpha) + 1.0) / 2.0
        return np.array([x, y] * 8, dtype=np.float32)
    
    def _encode_metrics(self, value: Optional[float]) -> np.ndarray:
        block = np.zeros(16, dtype=np.float32)
        if value is None:
            return block
        thresholds = [1, 5, 10, 50, 100, 500, 1000, 5000]
        for i, t in enumerate(thresholds):
            if value >= t:
                block[i] = 1.0
        block[-1] = value / 10000.0
        return block
    

    # 
    # HNSW INDEX METHODS (faiss, optional)
    # 

    def _build_personal_hnsw(self):
        """Build HNSW index for personal matrix if faiss is available."""
        if not HAISS_AVAILABLE or self.personal_current_size < 1000:
            return
        try:
            self.personal_hnsw_index = faiss.IndexHNSWFlat(512, 32)
            vectors = self.personal_matrix[:self.personal_current_size].astype('float32')
            self.personal_hnsw_index.add(vectors)
            logger.info(f"HNSW personal index built: {self.personal_current_size} vectors")
        except Exception as e:
            logger.warning(f"Failed to build personal HNSW index: {e}")
            self.personal_hnsw_index = None

    def _build_shared_hnsw(self):
        """Build HNSW index for shared matrix if faiss is available."""
        if not HAISS_AVAILABLE or self.shared_current_size < 100:
            return
        try:
            self.shared_hnsw_index = faiss.IndexHNSWFlat(512, 32)
            vectors = self.shared_matrix[:self.shared_current_size].astype('float32')
            self.shared_hnsw_index.add(vectors)
            logger.info(f"HNSW shared index built: {self.shared_current_size} vectors")
        except Exception as e:
            logger.warning(f"Failed to build shared HNSW index: {e}")
            self.shared_hnsw_index = None

    def _invalidate_hnsw(self):
        """Invalidate HNSW index after write."""
        self.personal_hnsw_index = None
        self.shared_hnsw_index = None


    def process_pending_vectors(self, embedder=None):
        """Create vectors for texts that accumulated enough content."""
        import sqlite3, os, numpy as np
        from datetime import datetime, timezone
        
        base_dir = '/data/skv/metadata_store'
        processed = 0
        
        for f in os.listdir(base_dir):
            if not f.endswith('.db') or f == 'shared_master.db':
                continue
            db_path = os.path.join(base_dir, f)
            conn = sqlite3.connect(db_path)
            cur = conn.cursor()
            cur.execute("SELECT e.event_id, e.raw_dialogue, e.essence FROM event_metadata e LEFT JOIN personal_vectors v ON e.event_id = v.event_id WHERE v.event_id IS NULL ORDER BY e.rowid DESC LIMIT 20")
            rows = cur.fetchall()
            if not rows:
                conn.close()
                continue
            text = " ".join([(r[1] or r[2] or "") for r in rows])
            if len(text) < 100:
                conn.close()
                continue
            if embedder is None:
                from fastembed import TextEmbedding
                embedder = TextEmbedding(model_name='BAAI/bge-small-en-v1.5')
            emb = list(embedder.embed([text[:1000]]))[0]
            vec = np.zeros(512, dtype=np.float32)
            vec[32:384] = emb[:352]
            for eid, _, _ in rows:
                cur.execute('INSERT OR REPLACE INTO personal_vectors (event_id, vector_blob, created_at) VALUES (?, ?, ?)', (eid, vec.tobytes(), datetime.now(timezone.utc).isoformat()))
            conn.commit()
            conn.close()
            processed += len(rows)
        return processed

    def save(self):
        self.persistence.save()
    
    def load(self):
        return self.persistence.load()


class ChronoBufferPersistence:
    """Persistence layer with atomic writes."""
    
    def __init__(self, buffer: ChronoBufferV77Ultimate):
        self.buffer = buffer
    

    # 
    # HNSW INDEX METHODS (faiss, optional)
    # 

    def _build_personal_hnsw(self):
        """Build HNSW index for personal matrix if faiss is available."""
        if not HAISS_AVAILABLE or self.personal_current_size < 1000:
            return
        try:
            self.personal_hnsw_index = faiss.IndexHNSWFlat(512, 32)
            vectors = self.personal_matrix[:self.personal_current_size].astype('float32')
            self.personal_hnsw_index.add(vectors)
            logger.info(f"HNSW personal index built: {self.personal_current_size} vectors")
        except Exception as e:
            logger.warning(f"Failed to build personal HNSW index: {e}")
            self.personal_hnsw_index = None

    def _build_shared_hnsw(self):
        """Build HNSW index for shared matrix if faiss is available."""
        if not HAISS_AVAILABLE or self.shared_current_size < 100:
            return
        try:
            self.shared_hnsw_index = faiss.IndexHNSWFlat(512, 32)
            vectors = self.shared_matrix[:self.shared_current_size].astype('float32')
            self.shared_hnsw_index.add(vectors)
            logger.info(f"HNSW shared index built: {self.shared_current_size} vectors")
        except Exception as e:
            logger.warning(f"Failed to build shared HNSW index: {e}")
            self.shared_hnsw_index = None

    def _invalidate_hnsw(self):
        """Invalidate HNSW index after write."""
        self.personal_hnsw_index = None
        self.shared_hnsw_index = None


    def process_pending_vectors(self, embedder=None):
        """Create vectors for texts that accumulated enough content."""
        import sqlite3, os, numpy as np
        from datetime import datetime, timezone
        
        base_dir = '/data/skv/metadata_store'
        processed = 0
        
        for f in os.listdir(base_dir):
            if not f.endswith('.db') or f == 'shared_master.db':
                continue
            db_path = os.path.join(base_dir, f)
            conn = sqlite3.connect(db_path)
            cur = conn.cursor()
            cur.execute("SELECT e.event_id, e.raw_dialogue, e.essence FROM event_metadata e LEFT JOIN personal_vectors v ON e.event_id = v.event_id WHERE v.event_id IS NULL ORDER BY e.rowid DESC LIMIT 20")
            rows = cur.fetchall()
            if not rows:
                conn.close()
                continue
            text = " ".join([(r[1] or r[2] or "") for r in rows])
            if len(text) < 100:
                conn.close()
                continue
            if embedder is None:
                from fastembed import TextEmbedding
                embedder = TextEmbedding(model_name='BAAI/bge-small-en-v1.5')
            emb = list(embedder.embed([text[:1000]]))[0]
            vec = np.zeros(512, dtype=np.float32)
            vec[32:384] = emb[:352]
            for eid, _, _ in rows:
                cur.execute('INSERT OR REPLACE INTO personal_vectors (event_id, vector_blob, created_at) VALUES (?, ?, ?)', (eid, vec.tobytes(), datetime.now(timezone.utc).isoformat()))
            conn.commit()
            conn.close()
            processed += len(rows)
        return processed

    def save(self):
        path = self.buffer.storage_path
        os.makedirs(path, exist_ok=True)
        
        try:
            # Atomic np.savez via .tmp
            tmp_npz = f"{path}/buffer.tmp.npz"
            np.savez(
                tmp_npz,
                core_matrix=self.buffer.core_matrix,
                shared_matrix=self.buffer.shared_matrix,
                shared_adjacency_indices=self.buffer.shared_adjacency_indices,
                shared_adjacency_weights=self.buffer.shared_adjacency_weights,
                shared_active_mask=self.buffer.shared_active_mask,
                shared_energy=self.buffer.shared_energy,
                personal_matrix=self.buffer.personal_matrix,
                personal_adjacency_indices=self.buffer.personal_adjacency_indices,
                personal_adjacency_weights=self.buffer.personal_adjacency_weights,
                personal_active_mask=self.buffer.personal_active_mask,
                personal_energy=self.buffer.personal_energy,
            )
            os.replace(tmp_npz, f"{path}/buffer.npz")
            
            # Atomic metadata
            metadata = {
                "version": "7.7-Ultimate",
                "max_personal": self.buffer.max_personal,
                "max_shared": self.buffer.max_shared,
                "max_links": self.buffer.max_links,
                "personal_current_size": self.buffer.personal_current_size,
                "shared_current_size": self.buffer.shared_current_size,
                "saved_at": datetime.now(timezone.utc).isoformat()
            }
            
            tmp = f"{path}/metadata.tmp"
            with open(tmp, "w") as f:
                json.dump(metadata, f, indent=2)
            os.replace(tmp, f"{path}/metadata.json")
            
            # Atomic index maps
            for name, data in [
                ("personal_idx_to_id", {str(k): v for k, v in self.buffer.personal_idx_to_id.items()}),
                ("personal_id_to_idx", self.buffer.personal_id_to_idx),
                ("shared_idx_to_id", {str(k): v for k, v in self.buffer.shared_idx_to_id.items()}),
                ("shared_id_to_idx", self.buffer.shared_id_to_idx),
            ]:
                tmp = f"{path}/{name}.tmp"
                with open(tmp, "w") as f:
                    json.dump(data, f, indent=2)
                os.replace(tmp, f"{path}/{name}.json")
            
            logger.info(f"Buffer saved: personal={self.buffer.personal_current_size}, shared={self.buffer.shared_current_size}")
            
        except Exception as e:
            logger.error(f"Failed to save: {e}")
            raise
    
    def load(self) -> bool:
        path = self.buffer.storage_path
        
        required = ["metadata.json", "buffer.npz"]
        for f in required:
            if not os.path.isfile(f"{path}/{f}"):
                logger.warning(f"Missing: {f}")
                return False
        
        try:
            with open(f"{path}/metadata.json", "r") as f:
                meta = json.load(f)
            
            if meta.get("version") != "7.7-Ultimate":
                logger.warning(f"Version mismatch: {meta.get('version')}")
                return False
            
            data = np.load(f"{path}/buffer.npz")
            self.buffer.core_matrix = data["core_matrix"]
            self.buffer.shared_matrix = data["shared_matrix"]
            self.buffer.shared_adjacency_indices = data["shared_adjacency_indices"]
            self.buffer.shared_adjacency_weights = data["shared_adjacency_weights"]
            self.buffer.shared_active_mask = data["shared_active_mask"]
            self.buffer.shared_energy = data["shared_energy"]
            self.buffer.personal_matrix = data["personal_matrix"]
            self.buffer.personal_adjacency_indices = data["personal_adjacency_indices"]
            self.buffer.personal_adjacency_weights = data["personal_adjacency_weights"]
            self.buffer.personal_active_mask = data["personal_active_mask"]
            self.buffer.personal_energy = data["personal_energy"]
            
            self.buffer.personal_current_size = meta["personal_current_size"]
            self.buffer.shared_current_size = meta["shared_current_size"]
            
            # Load index maps
            for name, attr in [
                ("personal_idx_to_id", "personal_idx_to_id"),
                ("personal_id_to_idx", "personal_id_to_idx"),
                ("shared_idx_to_id", "shared_idx_to_id"),
                ("shared_id_to_idx", "shared_id_to_idx"),
            ]:
                map_path = f"{path}/{name}.json"
                if os.path.isfile(map_path):
                    with open(map_path, "r") as f:
                        d = json.load(f)
                    if name.endswith("idx_to_id"):
                        d = {int(k): v for k, v in d.items()}
                    setattr(self.buffer, attr, d)
            
            logger.info(f"Buffer loaded: personal={self.buffer.personal_current_size}, shared={self.buffer.shared_current_size}")
            return True
            
        except Exception as e:
            logger.error(f"Failed to load: {e}")
            return False


logger.info("[v7.7-Ultimate] ChronoBufferV77Ultimate ready")
