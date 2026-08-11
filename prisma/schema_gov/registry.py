"""Generic type registry -- maps an arbitrary key (an enum, a string,
whatever a caller uses to tag its persisted types) to the Pydantic class
backing it. Not hardcoded to any one domain's type-tag enum, so prisma
keys it by its own NodeType while a future project could key it by
anything."""
from __future__ import annotations

from typing import Generic, Iterator, TypeVar

from pydantic import BaseModel

K = TypeVar("K")

__all__ = ["TypeRegistry"]


class TypeRegistry(Generic[K]):
    def __init__(self) -> None:
        self._classes: dict[K, type[BaseModel]] = {}

    def register(self, key: K, cls: type[BaseModel]) -> None:
        self._classes[key] = cls

    def get(self, key: K) -> type[BaseModel]:
        return self._classes[key]

    def schema_for(self, key: K) -> dict:
        return self.get(key).model_json_schema()

    def all_schemas(self) -> dict[str, dict]:
        return {str(key): cls.model_json_schema() for key, cls in self._classes.items()}

    def __contains__(self, key: K) -> bool:
        return key in self._classes

    def __iter__(self) -> Iterator[K]:
        return iter(self._classes)
