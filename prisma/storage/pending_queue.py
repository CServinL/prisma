"""
Pending write queue — buffers Zotero write actions when offline.

When Prisma cannot reach the Zotero API it logs the intended write here.
When `flush()` is called (on start or via `prisma sync`) it replays the
actions against the live client, removing each one on success.

Conflict rule: if an action matches an item already in Zotero (same DOI or
normalised title) the action is silently dropped — Zotero wins.

Storage: data/pending_writes.json (created automatically).
"""

import json
import logging
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger(__name__)

_DEFAULT_FILE = Path("./data/pending_writes.json")
_MAX_ATTEMPTS = 3
_VERSION = 1


class PendingWriteQueue:
    def __init__(self, queue_file: Optional[Path] = None):
        self._file = queue_file or _DEFAULT_FILE
        self._actions: list[dict] = []
        self._load()

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def _load(self):
        try:
            if self._file.exists():
                data = json.loads(self._file.read_text(encoding="utf-8"))
                self._actions = data.get("actions", [])
                logger.debug("Loaded %d pending actions from %s", len(self._actions), self._file)
        except Exception as exc:
            logger.error("Failed to load pending queue: %s", exc)
            self._actions = []

    def _save(self):
        try:
            self._file.parent.mkdir(parents=True, exist_ok=True)
            payload = {"version": _VERSION, "actions": self._actions}
            self._file.write_text(
                json.dumps(payload, indent=2, default=str),
                encoding="utf-8",
            )
        except Exception as exc:
            logger.error("Failed to save pending queue: %s", exc)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def enqueue(
        self,
        action_type: str,
        data: dict[str, Any],
        collection_key: Optional[str] = None,
    ) -> str:
        """
        Add an action to the queue.

        action_type values:
            save_paper         — data is a Zotero item dict
            create_collection  — data is a collection creation dict
            add_to_collection  — data must contain 'item_key' and 'collection_key'
        """
        action_id = str(uuid.uuid4())
        self._actions.append(
            {
                "id": action_id,
                "type": action_type,
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "data": data,
                "collection_key": collection_key,
                "attempts": 0,
                "last_error": None,
            }
        )
        self._save()
        logger.info("Queued %s action %s (total pending: %d)", action_type, action_id, len(self._actions))
        return action_id

    def flush(self, zotero_client) -> tuple[int, int]:
        """
        Replay all pending actions against zotero_client.

        Returns (success_count, failed_count).
        Actions that succeed are removed; actions that fail keep their slot
        and increment their attempt counter.  Actions that exceed MAX_ATTEMPTS
        are dropped with a warning.
        """
        if not self._actions:
            return 0, 0

        success = 0
        failed = 0
        remaining = []

        for action in self._actions:
            if action["attempts"] >= _MAX_ATTEMPTS:
                logger.warning(
                    "Dropping action %s (%s) after %d failed attempts: %s",
                    action["id"], action["type"], action["attempts"], action.get("last_error"),
                )
                continue

            action["attempts"] += 1
            try:
                self._dispatch(action, zotero_client)
                success += 1
                logger.info("Flushed %s action %s", action["type"], action["id"])
            except Exception as exc:
                action["last_error"] = str(exc)
                remaining.append(action)
                failed += 1
                logger.warning("Failed to flush %s action %s: %s", action["type"], action["id"], exc)

        self._actions = remaining
        self._save()
        return success, failed

    def _dispatch(self, action: dict, zotero_client):
        t = action["type"]

        if t == "save_paper":
            result = zotero_client.save_items(
                items=[action["data"]],
                collection_key=action.get("collection_key"),
            )
            if not result:
                raise RuntimeError("save_items returned empty result")

        elif t == "create_collection":
            result = zotero_client.create_collection(action["data"])
            if not result:
                raise RuntimeError("create_collection returned empty result")

        elif t == "add_to_collection":
            result = zotero_client.add_item_to_collection(
                action["data"]["item_key"],
                action["data"]["collection_key"],
            )
            if not result:
                raise RuntimeError("add_item_to_collection failed")

        else:
            raise ValueError(f"Unknown action type: {t!r}")

    # ------------------------------------------------------------------
    # Inspection
    # ------------------------------------------------------------------

    @property
    def pending_count(self) -> int:
        return len(self._actions)

    def __len__(self) -> int:
        return len(self._actions)

    def __bool__(self) -> bool:
        return bool(self._actions)
