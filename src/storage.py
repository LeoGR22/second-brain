"""Camada de persistência do Second Brain.

Dois backends com o mesmo comportamento:
- SQLiteStorage: desenvolvimento e testes locais.
- FirestoreStorage: produção no GCP.

Regras comuns (implementadas na BaseStorage):
- tags são normalizadas (minúsculas, sem espaços extras, sem duplicatas);
- o filtro de projeto ignora maiúsculas/minúsculas (campo auxiliar `projeto_key`);
- remover uma memória a move para a lixeira (soft delete), sem apagar de vez.
"""

from __future__ import annotations

import json
import os
import sqlite3
import uuid
from abc import ABC, abstractmethod
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Iterable, List, Optional

from src.config import settings

HIGHLIGHT_CATEGORIES = {"portfolio", "arquitetura", "trabalho"}
UPDATABLE_FIELDS = {"titulo", "conteudo", "categoria", "tags", "projeto", "url_referencia"}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def normalize_tags(tags: Optional[Iterable[str]]) -> List[str]:
    seen: List[str] = []
    for tag in tags or []:
        clean = " ".join(str(tag).split()).lower()
        if clean and clean not in seen:
            seen.append(clean)
    return seen


def project_key(projeto: Optional[str]) -> Optional[str]:
    return projeto.strip().lower() if projeto and projeto.strip() else None


def _clean_optional(value: Optional[str]) -> Optional[str]:
    return value.strip() if value and value.strip() else None


def _matches_text(memory: Dict[str, Any], query: str) -> bool:
    q = query.strip().lower()
    return q in memory.get("titulo", "").lower() or q in memory.get("conteudo", "").lower()


class BaseStorage(ABC):
    # ---- operações específicas de cada backend -------------------------------------------------
    @abstractmethod
    def _insert(self, doc: Dict[str, Any]) -> None: ...

    @abstractmethod
    def _replace(self, doc: Dict[str, Any]) -> None: ...

    @abstractmethod
    def get_memory(self, memory_id: str) -> Optional[Dict[str, Any]]: ...

    @abstractmethod
    def search_memories(
        self,
        query: Optional[str] = None,
        categoria: Optional[str] = None,
        tag: Optional[str] = None,
        projeto: Optional[str] = None,
        limit: int = 10,
    ) -> List[Dict[str, Any]]: ...

    @abstractmethod
    def list_recent(self, days: int = 7, limit: int = 15) -> List[Dict[str, Any]]: ...

    @abstractmethod
    def delete_memory(self, memory_id: str) -> bool:
        """Move a memória para a lixeira. Retorna False se não existir."""

    # ---- regras comuns --------------------------------------------------------------------------
    def save_memory(
        self,
        titulo: str,
        conteudo: str,
        categoria: str = "geral",
        tags: Optional[List[str]] = None,
        projeto: Optional[str] = None,
        url_referencia: Optional[str] = None,
    ) -> Dict[str, Any]:
        now = _now()
        doc = {
            "id": str(uuid.uuid4()),
            "titulo": titulo.strip(),
            "conteudo": conteudo.strip(),
            "categoria": (categoria or "geral").strip().lower(),
            "tags": normalize_tags(tags),
            "projeto": _clean_optional(projeto),
            "projeto_key": project_key(projeto),
            "url_referencia": _clean_optional(url_referencia),
            "created_at": now,
            "updated_at": now,
        }
        self._insert(doc)
        return doc

    def update_memory(self, memory_id: str, **changes: Any) -> Optional[Dict[str, Any]]:
        """Atualiza só os campos informados (valores None são ignorados)."""
        doc = self.get_memory(memory_id)
        if doc is None:
            return None

        for field, value in changes.items():
            if field not in UPDATABLE_FIELDS or value is None:
                continue
            if field == "tags":
                doc["tags"] = normalize_tags(value)
            elif field == "categoria":
                doc["categoria"] = value.strip().lower()
            elif field == "projeto":
                doc["projeto"] = _clean_optional(value)
                doc["projeto_key"] = project_key(value)
            elif field == "url_referencia":
                doc["url_referencia"] = _clean_optional(value)
            else:
                doc[field] = value.strip()

        doc["updated_at"] = _now()
        self._replace(doc)
        return doc

    def portfolio_summary(self, focus: Optional[str] = None, limit: int = 20) -> Dict[str, Any]:
        memories = self.search_memories(query=focus, limit=limit)
        tags_count: Dict[str, int] = {}
        projects_count: Dict[str, int] = {}
        highlights = []

        for m in memories:
            for t in m.get("tags", []):
                tags_count[t] = tags_count.get(t, 0) + 1
            if m.get("projeto"):
                projects_count[m["projeto"]] = projects_count.get(m["projeto"], 0) + 1
            if m.get("categoria") in HIGHLIGHT_CATEGORIES:
                conteudo = m.get("conteudo", "")
                highlights.append({
                    "id": m["id"],
                    "titulo": m["titulo"],
                    "projeto": m.get("projeto"),
                    "tags": m.get("tags"),
                    "data": m.get("created_at", "")[:10],
                    "resumo": conteudo[:200] + ("..." if len(conteudo) > 200 else ""),
                })

        return {
            "total_analisado": len(memories),
            "principais_skills_e_tags": sorted(tags_count.items(), key=lambda x: x[1], reverse=True)[:10],
            "projetos_envolvidos": sorted(projects_count.items(), key=lambda x: x[1], reverse=True),
            "destaques_para_curriculo": highlights[:10],
        }


class SQLiteStorage(BaseStorage):
    COLUMNS = ("id", "titulo", "conteudo", "categoria", "tags", "projeto", "projeto_key",
               "url_referencia", "created_at", "updated_at")

    def __init__(self, db_path: str):
        self.db_path = db_path
        os.makedirs(os.path.dirname(os.path.abspath(db_path)), exist_ok=True)
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        schema = """
            id TEXT PRIMARY KEY,
            titulo TEXT NOT NULL,
            conteudo TEXT NOT NULL,
            categoria TEXT NOT NULL,
            tags TEXT NOT NULL,
            projeto TEXT,
            projeto_key TEXT,
            url_referencia TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        """
        with self._connect() as conn:
            conn.execute(f"CREATE TABLE IF NOT EXISTS memories ({schema})")
            conn.execute(f"CREATE TABLE IF NOT EXISTS memories_trash ({schema}, deleted_at TEXT NOT NULL)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_memories_created ON memories (created_at)")

    @staticmethod
    def _row_to_dict(row: sqlite3.Row) -> Dict[str, Any]:
        data = dict(row)
        data["tags"] = json.loads(data["tags"])
        return data

    def _to_row(self, doc: Dict[str, Any]) -> tuple:
        return tuple(json.dumps(doc[c], ensure_ascii=False) if c == "tags" else doc.get(c) for c in self.COLUMNS)

    def _insert(self, doc: Dict[str, Any]) -> None:
        placeholders = ", ".join("?" for _ in self.COLUMNS)
        with self._connect() as conn:
            conn.execute(f"INSERT INTO memories ({', '.join(self.COLUMNS)}) VALUES ({placeholders})", self._to_row(doc))

    def _replace(self, doc: Dict[str, Any]) -> None:
        assignments = ", ".join(f"{c} = ?" for c in self.COLUMNS if c != "id")
        values = self._to_row(doc)[1:] + (doc["id"],)
        with self._connect() as conn:
            conn.execute(f"UPDATE memories SET {assignments} WHERE id = ?", values)

    def get_memory(self, memory_id: str) -> Optional[Dict[str, Any]]:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM memories WHERE id = ?", (memory_id,)).fetchone()
        return self._row_to_dict(row) if row else None

    def search_memories(
        self,
        query: Optional[str] = None,
        categoria: Optional[str] = None,
        tag: Optional[str] = None,
        projeto: Optional[str] = None,
        limit: int = 10,
    ) -> List[Dict[str, Any]]:
        conditions: List[str] = []
        params: List[Any] = []

        if categoria:
            conditions.append("categoria = ?")
            params.append(categoria.strip().lower())
        if projeto:
            conditions.append("projeto_key = ?")
            params.append(project_key(projeto))
        if tag:
            # correspondência exata da tag dentro do array JSON
            conditions.append("EXISTS (SELECT 1 FROM json_each(memories.tags) WHERE json_each.value = ?)")
            params.append(normalize_tags([tag])[0])
        if query:
            conditions.append("(LOWER(titulo) LIKE ? OR LOWER(conteudo) LIKE ?)")
            q = f"%{query.strip().lower()}%"
            params.extend([q, q])

        where = f"WHERE {' AND '.join(conditions)}" if conditions else ""
        params.append(limit)
        with self._connect() as conn:
            rows = conn.execute(f"SELECT * FROM memories {where} ORDER BY created_at DESC LIMIT ?", params).fetchall()
        return [self._row_to_dict(r) for r in rows]

    def list_recent(self, days: int = 7, limit: int = 15) -> List[Dict[str, Any]]:
        since = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM memories WHERE created_at >= ? ORDER BY created_at DESC LIMIT ?", (since, limit)
            ).fetchall()
        return [self._row_to_dict(r) for r in rows]

    def delete_memory(self, memory_id: str) -> bool:
        cols = ", ".join(self.COLUMNS)
        with self._connect() as conn:
            moved = conn.execute(
                f"INSERT INTO memories_trash ({cols}, deleted_at) SELECT {cols}, ? FROM memories WHERE id = ?",
                (_now(), memory_id),
            ).rowcount
            if not moved:
                return False
            conn.execute("DELETE FROM memories WHERE id = ?", (memory_id,))
        return True


class FirestoreStorage(BaseStorage):
    """Backend Firestore.

    As consultas usam apenas filtros de igualdade/array_contains (sem order_by combinado),
    então não exigem índices compostos. A ordenação por data e a busca textual são feitas
    em memória sobre no máximo `max_scan` documentos, o que é adequado para uso pessoal.
    """

    def __init__(self, project_id: Optional[str] = None, collection_name: str = "second_brain_memories",
                 max_scan: int = 2000, client: Any = None, emulator_host: Optional[str] = None):
        if client is None:
            from google.cloud import firestore

            if emulator_host:
                # O SDK só enxerga o emulador por variável de ambiente; o .env é lido pelo
                # pydantic-settings e não chega ao os.environ sozinho.
                os.environ["FIRESTORE_EMULATOR_HOST"] = emulator_host

            client = firestore.Client(project=project_id)
        self.db = client
        self.collection = self.db.collection(collection_name)
        self.trash = self.db.collection(f"{collection_name}_trash")
        self.max_scan = max_scan

    @staticmethod
    def _filter(field: str, op: str, value: Any):
        from google.cloud.firestore_v1.base_query import FieldFilter

        return FieldFilter(field, op, value)

    def _insert(self, doc: Dict[str, Any]) -> None:
        self.collection.document(doc["id"]).set(doc)

    def _replace(self, doc: Dict[str, Any]) -> None:
        self.collection.document(doc["id"]).set(doc)

    def get_memory(self, memory_id: str) -> Optional[Dict[str, Any]]:
        snap = self.collection.document(memory_id).get()
        return snap.to_dict() if snap.exists else None

    def search_memories(
        self,
        query: Optional[str] = None,
        categoria: Optional[str] = None,
        tag: Optional[str] = None,
        projeto: Optional[str] = None,
        limit: int = 10,
    ) -> List[Dict[str, Any]]:
        ref = self.collection
        has_filter = False
        if categoria:
            ref = ref.where(filter=self._filter("categoria", "==", categoria.strip().lower()))
            has_filter = True
        if projeto:
            ref = ref.where(filter=self._filter("projeto_key", "==", project_key(projeto)))
            has_filter = True
        if tag:
            ref = ref.where(filter=self._filter("tags", "array_contains", normalize_tags([tag])[0]))
            has_filter = True

        if not has_filter:
            # Sem filtros: índice simples de created_at (criado automaticamente pelo Firestore)
            ref = ref.order_by("created_at", direction="DESCENDING")

        docs = [d.to_dict() for d in ref.limit(self.max_scan).stream()]
        if query:
            docs = [d for d in docs if _matches_text(d, query)]
        docs.sort(key=lambda d: d.get("created_at", ""), reverse=True)
        return docs[:limit]

    def list_recent(self, days: int = 7, limit: int = 15) -> List[Dict[str, Any]]:
        since = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
        docs = (
            self.collection
            .where(filter=self._filter("created_at", ">=", since))
            .order_by("created_at", direction="DESCENDING")
            .limit(limit)
            .stream()
        )
        return [d.to_dict() for d in docs]

    def delete_memory(self, memory_id: str) -> bool:
        doc_ref = self.collection.document(memory_id)
        snap = doc_ref.get()
        if not snap.exists:
            return False
        data = snap.to_dict()
        data["deleted_at"] = _now()
        # batch: copiar para a lixeira e apagar acontecem juntos ou não acontecem
        batch = self.db.batch()
        batch.set(self.trash.document(memory_id), data)
        batch.delete(doc_ref)
        batch.commit()
        return True


def get_storage() -> BaseStorage:
    if settings.storage_backend == "firestore":
        return FirestoreStorage(
            project_id=settings.gcp_project_id,
            collection_name=settings.firestore_collection,
            max_scan=settings.firestore_max_scan,
            emulator_host=settings.firestore_emulator_host,
        )
    return SQLiteStorage(db_path=settings.sqlite_db_path)
