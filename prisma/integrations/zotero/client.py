"""
Zotero Web API Client

The single Zotero client used throughout Prisma (2026-07-28) -- wraps
pyzotero, a maintained third-party library built specifically for this API,
so pagination/rate-limiting/retry correctness lives there instead of being
hand-rolled and duplicated across this codebase. Previously there were two
independent implementations (this one, and services/zotero.py's
hand-rolled urllib.request client, which also carried a genuine
local-Zotero-Desktop-SQLite-reading fallback path that contradicted the
project's "Web API only, everywhere" architecture) -- consolidated onto
this one for its richer, more Zotero-API-faithful data model
(storage/models/zotero_models.py) and because pyzotero's retry/pagination
handling is more robust than 3 copies of a hand-rolled loop.

Public method names/signatures are kept stable for existing callers
(ResearchStreamManager, PendingWriteQueue) -- this used to be split across
this file (pyzotero calls, raw dicts) and unified_client.py (a facade
converting to typed models via hasattr-based capability dispatch). That
dispatch was already ceremonial before this merge -- there was only ever
one concrete backend since the Local-API/Desktop/Hybrid clients were
removed -- so it's gone now, not carried forward.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator

try:
    from pyzotero import zotero
except ImportError:
    zotero = None

from ...storage.models.zotero_models import ZoteroCollection, ZoteroItem
from ...utils.config import PrismaConfig

logger = logging.getLogger(__name__)


def check_web_api_reachable(api_key: Optional[str], library_id: Optional[str], timeout: float = 2.0) -> bool:
    """Live reachability check: validates the configured library is
    actually reachable with these credentials, not just that a key is
    present. Backs ZoteroClient.status()'s `reachable` field, `prisma
    status`, and the UI status panel. Deliberately uses urllib directly
    rather than pyzotero -- this is a short-timeout probe, not a real
    library operation, and doesn't need pyzotero's pagination/retry
    machinery."""
    if not api_key or not library_id:
        return False
    import urllib.error
    import urllib.request

    req = urllib.request.Request(
        f"https://api.zotero.org/users/{library_id}/collections?limit=1",
        headers={"Zotero-API-Key": api_key, "Zotero-API-Version": "3"},
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status == 200
    except Exception:
        return False


class ZoteroAPIConfig(BaseModel):
    """Configuration for Zotero API client with validation"""
    api_key: str = Field(..., description="Zotero API key")
    library_id: str = Field(..., description="Zotero library ID")
    library_type: str = Field("user", description="Library type: 'user' or 'group'")
    api_version: int = Field(3, description="Zotero API version")

    @field_validator('library_type')
    @classmethod
    def validate_library_type(cls, v):
        if v not in ('user', 'group'):
            raise ValueError('library_type must be "user" or "group"')
        return v

    @field_validator('api_version')
    @classmethod
    def validate_api_version(cls, v):
        if v != 3:
            raise ValueError('Only API version 3 is supported')
        return v


class ZoteroClientError(Exception):
    """Base exception for Zotero client errors"""
    pass


class ZoteroStatus(BaseModel):
    """`{mode, available, reachable}` -- mirrors the shape /status,
    `prisma status`, and the UI panel already expect."""
    mode: str
    available: bool
    reachable: bool


class ZoteroClientInfo(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    available: bool
    class_name: Optional[str] = Field(None, alias="class")


class ZoteroLibraryStats(BaseModel):
    total_items: int
    total_collections: int
    api_available: bool
    error: Optional[str] = None


class ZoteroClient:
    """
    Zotero Web API client wrapping pyzotero -- reads/writes typed
    ZoteroItem/ZoteroCollection models (storage/models/zotero_models.py),
    not raw dicts.
    """

    def __init__(self, config: ZoteroAPIConfig):
        """
        Initialize Zotero client

        Args:
            config: ZoteroAPIConfig with API credentials and settings

        Raises:
            ZoteroClientError: If pyzotero is not installed or config is invalid
        """
        if zotero is None:
            raise ZoteroClientError(
                "pyzotero is required for Zotero integration. "
                "Install with: pip install pyzotero"
            )

        self.config = config
        self._client = None
        self._initialize_client()

    @classmethod
    def from_config(cls, config: PrismaConfig) -> "ZoteroClient":
        """Build a client from the app's PrismaConfig, resolving
        api_key/library_id through ZoteroConfig.resolve_api_key()/
        resolve_library_id() (env-var indirection takes priority over the
        literal config fields when set)."""
        zconf = config.sources.zotero
        return cls(ZoteroAPIConfig(
            api_key=zconf.resolve_api_key() or "",
            library_id=zconf.resolve_library_id() or "",
            library_type=getattr(zconf, "library_type", "user"),
        ))

    def _initialize_client(self):
        """Initialize the pyzotero client"""
        try:
            self._client = zotero.Zotero(
                library_id=self.config.library_id,
                library_type=self.config.library_type,
                api_key=self.config.api_key
            )
            logger.info(f"Initialized Zotero client for {self.config.library_type} library {self.config.library_id}")
        except Exception as e:
            raise ZoteroClientError(f"Failed to initialize Zotero client: {e}")

    # ── Status ────────────────────────────────────────────────────────────────

    def test_connection(self) -> bool:
        """Test the Zotero API connection."""
        try:
            info = self._client.key_info()
            logger.info(f"Zotero connection successful: {info}")
            return True
        except Exception as e:
            logger.error(f"Zotero connection failed: {e}")
            return False

    def is_available(self) -> bool:
        return self.test_connection()

    def status(self) -> ZoteroStatus:
        """`available` keeps its existing meaning (credentials configured);
        `reachable` is the live check (mirrors the same short-timeout
        pattern already used for Ollama)."""
        configured = bool(self.config.api_key and self.config.library_id)
        return ZoteroStatus(
            mode="web-api",
            available=configured,
            reachable=check_web_api_reachable(self.config.api_key, self.config.library_id) if configured else False,
        )

    # ── Collections ───────────────────────────────────────────────────────────

    def get_collections(self, limit: int = 100) -> List[ZoteroCollection]:
        try:
            raw = self._client.collections(limit=limit)
            logger.info(f"Retrieved {len(raw)} collections")
            return [ZoteroCollection.from_zotero_data(c) for c in raw]
        except Exception as e:
            logger.error(f"Failed to retrieve collections: {e}")
            raise ZoteroClientError(f"Failed to retrieve collections: {e}")

    def create_collection(self, collection_data: Dict[str, Any]) -> Optional[ZoteroCollection]:
        """
        Create a new collection.

        Args:
            collection_data: dict with 'name' and optional 'parentCollection'
        """
        try:
            template = [collection_data]
            created = self._client.create_collections(template)

            if created and 'successful' in created and created['successful']:
                first_key = list(created['successful'].keys())[0]
                collection = created['successful'][first_key]

                collection_name = collection.get('data', {}).get('name', 'Unknown')
                collection_key = collection.get('key', 'Unknown')
                logger.info(f"Created collection: {collection_name} with key {collection_key}")
                return ZoteroCollection.from_zotero_data(collection)
            else:
                logger.error(f"Failed to create collection: {created}")
                return None
        except Exception as e:
            logger.error(f"Failed to create collection: {e}")
            return None

    def ensure_collection(self, name: str, parent_key: Optional[str] = None) -> Optional[ZoteroCollection]:
        """Return the existing collection with this name, or create it."""
        for c in self.get_collections():
            if c.name == name:
                return c
        data: Dict[str, Any] = {"name": name}
        if parent_key:
            data["parentCollection"] = parent_key
        return self.create_collection(data)

    def delete_collection(self, collection_key: str) -> bool:
        """Delete a collection."""
        try:
            try:
                collection = self._client.collection(collection_key)
                if not collection:
                    logger.error(f"Collection {collection_key} not found")
                    return False
            except Exception as e:
                logger.error(f"Failed to fetch collection {collection_key} for deletion: {e}")
                return False

            self._client.delete_collection(collection)
            logger.info(f"Successfully deleted collection: {collection_key}")
            return True
        except Exception as e:
            logger.error(f"Failed to delete collection {collection_key}: {e}")
            return False

    # ── Items ─────────────────────────────────────────────────────────────────

    def get_items(self, limit: int = 100, item_type: Optional[str] = None) -> List[ZoteroItem]:
        try:
            params: Dict[str, Any] = {"limit": limit}
            if item_type:
                params["itemType"] = item_type
            raw = self._client.items(**params)
            logger.info(f"Retrieved {len(raw)} items")
            return [ZoteroItem.from_zotero_data(i) for i in raw]
        except Exception as e:
            logger.error(f"Failed to retrieve items: {e}")
            raise ZoteroClientError(f"Failed to retrieve items: {e}")

    def get_all_items(self, item_type: Optional[str] = None) -> List[ZoteroItem]:
        """Retrieve every item in the library, paginating past pyzotero's
        default per-request limit -- for whole-library operations
        (duplicate detection, library stats) that need everything, not a
        capped page."""
        try:
            params: Dict[str, Any] = {}
            if item_type:
                params["itemType"] = item_type
            raw = self._client.everything(self._client.items(**params))
            logger.info(f"Retrieved {len(raw)} items (full library)")
            return [ZoteroItem.from_zotero_data(i) for i in raw]
        except Exception as e:
            logger.error(f"Failed to retrieve all items: {e}")
            raise ZoteroClientError(f"Failed to retrieve all items: {e}")

    def get_collection_items(self, collection_key: str, limit: int = 100) -> List[ZoteroItem]:
        try:
            raw = self._client.collection_items(collection_key, limit=limit)
            logger.info(f"Retrieved {len(raw)} items from collection {collection_key}")
            return [ZoteroItem.from_zotero_data(i) for i in raw]
        except Exception as e:
            logger.error(f"Failed to retrieve collection items: {e}")
            raise ZoteroClientError(f"Failed to retrieve collection items: {e}")

    def search_items(self, query: str, limit: int = 100) -> List[ZoteroItem]:
        try:
            raw = self._client.items(q=query, limit=limit)
            logger.info(f"Found {len(raw)} items matching '{query}'")
            return [ZoteroItem.from_zotero_data(i) for i in raw]
        except Exception as e:
            logger.error(f"Failed to search items: {e}")
            raise ZoteroClientError(f"Failed to search items: {e}")

    def get_item(self, item_key: str) -> Optional[ZoteroItem]:
        """Fetch a single item. Returns None (not a raised error) if it
        can't be found -- callers (dedup checks, Zotero import) treat a
        missing item as a normal, expected outcome."""
        try:
            raw = self._client.item(item_key)
            return ZoteroItem.from_zotero_data(raw) if raw else None
        except Exception as e:
            logger.debug(f"Failed to retrieve item {item_key}: {e}")
            return None

    def find_by_identifier(
        self,
        doi: Optional[str] = None,
        title: Optional[str] = None,
        collection_key: Optional[str] = None,
    ) -> Optional[ZoteroItem]:
        """
        Ask Zotero's own search index whether an item already exists.

        Tries DOI first (strongest identity signal), falls back to an
        exact case-insensitive title match. Pass collection_key to scope
        the check to one collection; omit it to search the whole library.
        Returns None if nothing matches -- callers fall through to their
        own NLTK stem-overlap/LLM checks.
        """
        def _in_collection(item: ZoteroItem) -> bool:
            return collection_key is None or collection_key in item.collections

        if doi:
            doi_norm = doi.lower().strip()
            for item in self.search_items(doi):
                if item.doi and item.doi.lower().strip() == doi_norm and _in_collection(item):
                    return item

        if title:
            title_norm = title.lower().strip()
            for item in self.search_items(title):
                if item.title and item.title.lower().strip() == title_norm and _in_collection(item):
                    return item

        return None

    def get_pdf_bytes(self, key: str) -> Optional[bytes]:
        """Find `key`'s child PDF attachment (if any) and return its raw
        file bytes."""
        try:
            children = self._client.children(key)
        except Exception as e:
            logger.debug(f"Failed to get children for {key}: {e}")
            return None

        pdf_key = None
        for child in children:
            d = child.get("data", {})
            if d.get("contentType") == "application/pdf":
                pdf_key = d.get("key")
                break
        if not pdf_key:
            return None

        try:
            return self._client.file(pdf_key)
        except Exception as e:
            logger.debug(f"Failed to fetch PDF bytes for {pdf_key}: {e}")
            return None

    def create_item(self, item_data: Dict[str, Any]) -> Optional[str]:
        """Create an item from a raw Zotero-format dict. Returns the
        created item's key, or None if creation failed."""
        try:
            if 'itemType' not in item_data:
                logger.error("Item data must include 'itemType'")
                return None

            result = self._client.create_items([item_data])

            if result and isinstance(result, dict):
                successful = result.get('successful', {})
                success = result.get('success', {})

                if successful and '0' in successful:
                    item_key = successful['0']['key']
                    logger.info(f"Successfully created item: {item_key}")
                    return item_key
                elif success and '0' in success:
                    item_key = success['0']
                    logger.info(f"Successfully created item: {item_key}")
                    return item_key
                else:
                    logger.error(f"No successful items in result: {result}")
                    return None
            else:
                logger.error(f"Failed to create item: {result}")
                return None
        except Exception as e:
            logger.error(f"Failed to create item: {e}")
            return None

    def add_paper(self, paper: Any, collection_key: Optional[str] = None) -> ZoteroItem:
        """Add a domain paper/analyzed-result object (duck-typed via
        getattr -- title/authors/abstract/url/doi/published_date/arxiv_id)
        to the library. Distinct from create_item(), which takes an
        already-Zotero-shaped dict; this does the paper -> Zotero item
        conversion."""
        authors = getattr(paper, "authors", []) or []
        arxiv_id = getattr(paper, "arxiv_id", None)
        item_type = "preprint" if arxiv_id else "journalArticle"
        item_data = {
            "itemType": item_type,
            "title": getattr(paper, "title", ""),
            "creators": [{"creatorType": "author", "name": a} for a in authors],
            "abstractNote": getattr(paper, "abstract", "") or "",
            "url": getattr(paper, "url", "") or "",
            "DOI": getattr(paper, "doi", "") or "",
            "date": getattr(paper, "published_date", "") or "",
            "collections": [collection_key] if collection_key else [],
            "tags": [],
        }
        try:
            result = self._client.create_items([item_data])
        except Exception as e:
            raise ZoteroClientError(f"Failed to add paper: {e}")

        successful = result.get("successful", {}) if isinstance(result, dict) else {}
        if not successful:
            raise ZoteroClientError(f"Zotero add_item failed: {result}")
        entry = next(iter(successful.values()))
        return ZoteroItem.from_zotero_data(entry)

    def delete_item(self, item_key: str) -> bool:
        """Delete an item."""
        try:
            item = self._client.item(item_key)
            if not item:
                logger.error(f"Item {item_key} not found")
                return False

            result = self._client.delete_item(item)
            if result:
                logger.info(f"Successfully deleted item {item_key}")
                return True
            else:
                logger.error(f"Failed to delete item {item_key}")
                return False
        except Exception as e:
            logger.error(f"Failed to delete item {item_key}: {e}")
            return False

    def add_item_to_collection(self, item_key: str, collection_key: str) -> bool:
        """Add an existing item to a collection."""
        try:
            if hasattr(self._client, 'addto_collection'):
                try:
                    item = self._client.item(item_key)
                    if 'collections' not in item['data']:
                        item['data']['collections'] = []

                    if collection_key not in item['data']['collections']:
                        self._client.addto_collection(collection_key, item)
                        logger.info(f"Successfully added item {item_key} to collection {collection_key} using addto_collection")
                        return True
                    else:
                        logger.info(f"Item {item_key} already in collection {collection_key}")
                        return True
                except Exception as e:
                    logger.warning(f"addto_collection failed: {e}")

            try:
                item = self._client.item(item_key)
                if 'collections' not in item['data']:
                    item['data']['collections'] = []

                if collection_key not in item['data']['collections']:
                    item['data']['collections'].append(collection_key)
                    self._client.update_item(item)
                    logger.info(f"Successfully added item {item_key} to collection {collection_key} using update_item")
                    return True
                else:
                    logger.info(f"Item {item_key} already in collection {collection_key}")
                    return True
            except Exception as e:
                logger.error(f"update_item approach failed: {e}")

            logger.error(f"No available method to add item {item_key} to collection {collection_key}")
            return False
        except Exception as e:
            logger.error(f"Failed to add item {item_key} to collection {collection_key}: {e}")
            return False

    def save_items(self, items: List[Dict[str, Any]],
                   collection_key: Optional[str] = None) -> List[str]:
        """Save a batch of already-Zotero-shaped item dicts, optionally
        assigning each to a collection. Returns the created item keys;
        per-item failures are logged and skipped rather than failing the
        whole batch."""
        created_keys: List[str] = []
        for item_data in items:
            try:
                item_key = self.create_item(item_data)
                if item_key:
                    created_keys.append(item_key)
                    logger.info(f"Successfully saved item: {item_key}")
                    if collection_key:
                        try:
                            self.add_item_to_collection(item_key, collection_key)
                            logger.info(f"Added item to collection {collection_key}: {item_key}")
                        except Exception as e:
                            logger.warning(f"Failed to add item to collection {collection_key}: {e}")
                else:
                    logger.error(f"Failed to save item '{item_data.get('title', 'Unknown')}'")
            except Exception as e:
                logger.error(f"Failed to save item '{item_data.get('title', 'Unknown')}': {e}")
                continue

        logger.info(f"Save operation complete: {len(created_keys)}/{len(items)} items saved successfully")
        return created_keys

    # ── Client information ────────────────────────────────────────────────────

    @property
    def client_info(self) -> ZoteroClientInfo:
        return ZoteroClientInfo(
            available=self.is_available(),
            class_name=self._client.__class__.__name__ if self._client else None,
        )

    def get_library_stats(self) -> ZoteroLibraryStats:
        try:
            items = self.get_all_items()
            collections = self.get_collections()
            return ZoteroLibraryStats(
                total_items=len(items),
                total_collections=len(collections),
                api_available=True,
            )
        except Exception as e:
            logger.error(f"Failed to get library stats: {e}")
            return ZoteroLibraryStats(
                total_items=0,
                total_collections=0,
                api_available=False,
                error=str(e),
            )

    def __repr__(self) -> str:
        return f"ZoteroClient(available={self.is_available()})"
