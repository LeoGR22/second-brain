"""Firestore em memória, com o subconjunto da API usado pelo FirestoreStorage.

Permite testar a lógica do backend Firestore sem emulador nem credenciais.
"""

from __future__ import annotations

import copy
from typing import Any, Dict, List, Optional

OPS = {
    "==": lambda a, b: a == b,
    ">=": lambda a, b: a is not None and a >= b,
    "array_contains": lambda a, b: isinstance(a, list) and b in a,
}


class FakeSnapshot:
    def __init__(self, data: Optional[Dict[str, Any]]):
        self._data = data

    @property
    def exists(self) -> bool:
        return self._data is not None

    def to_dict(self) -> Optional[Dict[str, Any]]:
        return copy.deepcopy(self._data)


class FakeDocRef:
    def __init__(self, store: Dict[str, Dict[str, Any]], doc_id: str):
        self._store, self.id = store, doc_id

    def get(self) -> FakeSnapshot:
        return FakeSnapshot(self._store.get(self.id))

    def set(self, data: Dict[str, Any]) -> None:
        self._store[self.id] = copy.deepcopy(data)

    def delete(self) -> None:
        self._store.pop(self.id, None)


class FakeQuery:
    def __init__(self, store: Dict[str, Dict[str, Any]], filters=None, order=None, limit_n=None):
        self._store = store
        self._filters: List[tuple] = filters or []
        self._order = order
        self._limit = limit_n

    def where(self, *, filter) -> "FakeQuery":  # noqa: A002 - mesma assinatura do SDK
        return FakeQuery(self._store, self._filters + [(filter.field_path, filter.op_string, filter.value)],
                         self._order, self._limit)

    def order_by(self, field: str, direction: str = "ASCENDING") -> "FakeQuery":
        return FakeQuery(self._store, self._filters, (field, direction), self._limit)

    def limit(self, n: int) -> "FakeQuery":
        return FakeQuery(self._store, self._filters, self._order, n)

    def stream(self):
        docs = [d for d in self._store.values()
                if all(OPS[op](d.get(field), value) for field, op, value in self._filters)]
        if self._order:
            field, direction = self._order
            docs.sort(key=lambda d: d.get(field, ""), reverse=direction == "DESCENDING")
        if self._limit is not None:
            docs = docs[: self._limit]
        return [FakeSnapshot(d) for d in docs]


class FakeCollection(FakeQuery):
    def __init__(self, store: Dict[str, Dict[str, Any]]):
        super().__init__(store)

    def document(self, doc_id: str) -> FakeDocRef:
        return FakeDocRef(self._store, doc_id)


class FakeBatch:
    def __init__(self):
        self._ops: List[tuple] = []

    def set(self, ref: FakeDocRef, data: Dict[str, Any]) -> None:
        self._ops.append(("set", ref, data))

    def delete(self, ref: FakeDocRef) -> None:
        self._ops.append(("delete", ref, None))

    def commit(self) -> None:
        for op, ref, data in self._ops:
            ref.set(data) if op == "set" else ref.delete()


class FakeFirestoreClient:
    def __init__(self):
        self.collections: Dict[str, Dict[str, Dict[str, Any]]] = {}

    def collection(self, name: str) -> FakeCollection:
        return FakeCollection(self.collections.setdefault(name, {}))

    def batch(self) -> FakeBatch:
        return FakeBatch()
