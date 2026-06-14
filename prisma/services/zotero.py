from __future__ import annotations

import re
import sqlite3
from enum import Enum
from pathlib import Path
from typing import Iterator

from pydantic import BaseModel


class ZoteroMode(str, Enum):
    offline = "offline"
    desktop = "desktop"
    web_api = "web-api"


class ZoteroCollection(BaseModel):
    key: str
    name: str
    parent_key: str | None = None


class ZoteroItem(BaseModel):
    key: str
    title: str
    item_type: str
    authors: list[str]
    year: int | None
    abstract: str | None
    doi: str | None
    url: str | None
    publication: str | None
    tags: list[str]
    collection_keys: list[str]
    pdf_path: Path | None = None


def _detect_db_path() -> Path | None:
    candidates = [
        Path.home() / "Zotero" / "zotero.sqlite",
    ]
    # WSL2: scan Windows user profiles under /mnt/c/Users/
    mnt = Path("/mnt/c/Users")
    if mnt.exists():
        for user_dir in mnt.iterdir():
            candidate = user_dir / "Zotero" / "zotero.sqlite"
            if candidate.exists():
                candidates.append(candidate)
    for p in candidates:
        if p.exists():
            return p
    return None


def _extract_year(date_str: str | None) -> int | None:
    if not date_str:
        return None
    m = re.search(r"\b(19|20)\d{2}\b", date_str)
    return int(m.group(0)) if m else None


def _make_citekey(authors: list[str], year: int | None, title: str | None = None) -> str:
    names = [a for a in authors if a.strip()]
    if not names:
        first_word = ""
        if title:
            first_word = re.sub(r"[^a-z]", "", title.split()[0].lower())
        return f"{first_word or 'unknown'}{year or ''}"
    last = names[0].split()[-1].lower()
    last = re.sub(r"[^a-z]", "", last)
    return f"{last}{year or ''}"


class ZoteroService:
    def __init__(self, mode: ZoteroMode, db_path: Path | None = None,
                 api_key: str | None = None, user_id: str | None = None) -> None:
        self.mode = mode
        self._db_path = db_path
        self._api_key = api_key
        self._user_id = user_id

    # ── Status ────────────────────────────────────────────────────────────────

    def status(self) -> dict:
        if self.mode == ZoteroMode.offline:
            p = self._db_path or _detect_db_path()
            ok = p is not None and p.exists()
            return {"mode": self.mode, "available": ok, "db_path": str(p) if p else None}
        if self.mode == ZoteroMode.desktop:
            ok = self._desktop_ping()
            return {"mode": self.mode, "available": ok}
        if self.mode == ZoteroMode.web_api:
            ok = bool(self._api_key and self._user_id)
            return {"mode": self.mode, "available": ok}
        return {"mode": self.mode, "available": False}

    # ── Collections ───────────────────────────────────────────────────────────

    def list_collections(self) -> list[ZoteroCollection]:
        if self.mode == ZoteroMode.offline:
            return self._sqlite_collections()
        if self.mode == ZoteroMode.desktop:
            return self._desktop_collections()
        if self.mode == ZoteroMode.web_api:
            return self._webapi_collections()
        return []

    # ── Items ─────────────────────────────────────────────────────────────────

    def list_items(self, collection_key: str | None = None,
                   q: str | None = None) -> list[ZoteroItem]:
        if self.mode == ZoteroMode.offline:
            return self._sqlite_items(collection_key, q)
        if self.mode == ZoteroMode.desktop:
            return self._desktop_items(collection_key, q)
        if self.mode == ZoteroMode.web_api:
            return self._webapi_items(collection_key, q)
        return []

    def get_item(self, key: str) -> ZoteroItem | None:
        items = self.list_items()
        for item in items:
            if item.key == key:
                return item
        return None

    def get_pdf_bytes(self, key: str) -> bytes | None:
        if self.mode == ZoteroMode.web_api:
            return self._webapi_pdf(key)
        if self.mode == ZoteroMode.offline:
            return self._sqlite_pdf(key)
        return None

    # ── SQLite (offline) ──────────────────────────────────────────────────────

    def _db(self) -> sqlite3.Connection:
        path = self._db_path or _detect_db_path()
        if path is None:
            raise FileNotFoundError("Zotero database not found")
        return sqlite3.connect(f"file:{path}?mode=ro", uri=True)

    def _sqlite_collections(self) -> list[ZoteroCollection]:
        with self._db() as con:
            cur = con.execute(
                "SELECT key, collectionName, parentCollectionID FROM collections ORDER BY collectionName"
            )
            rows = cur.fetchall()
            # Build key lookup for parent resolution
            id_to_key: dict[int, str] = {}
            raw = []
            cur2 = con.execute("SELECT collectionID, key FROM collections")
            for cid, ckey in cur2.fetchall():
                id_to_key[cid] = ckey
            for key, name, parent_id in rows:
                raw.append(ZoteroCollection(
                    key=key,
                    name=name,
                    parent_key=id_to_key.get(parent_id) if parent_id else None,
                ))
        return raw

    def _sqlite_items(self, collection_key: str | None, q: str | None) -> list[ZoteroItem]:
        with self._db() as con:
            # Resolve collection → item IDs
            collection_item_ids: set[int] | None = None
            if collection_key:
                cur = con.execute(
                    "SELECT ci.itemID FROM collectionItems ci "
                    "JOIN collections c ON ci.collectionID=c.collectionID "
                    "WHERE c.key=?",
                    (collection_key,),
                )
                collection_item_ids = {r[0] for r in cur.fetchall()}

            # Top-level items (not attachments/notes)
            cur = con.execute(
                "SELECT i.itemID, i.key, it.typeName FROM items i "
                "JOIN itemTypes it ON i.itemTypeID=it.itemTypeID "
                "WHERE it.typeName NOT IN ('attachment','note','annotation') "
                "AND i.itemID NOT IN (SELECT itemID FROM deletedItems)"
            )
            item_rows = cur.fetchall()

            # Bulk-load field values
            cur = con.execute(
                "SELECT id.itemID, f.fieldName, idv.value "
                "FROM itemData id "
                "JOIN fields f ON id.fieldID=f.fieldID "
                "JOIN itemDataValues idv ON id.valueID=idv.valueID"
            )
            fields: dict[int, dict[str, str]] = {}
            for item_id, fname, val in cur.fetchall():
                fields.setdefault(item_id, {})[fname] = val

            # Bulk-load creators
            cur = con.execute(
                "SELECT ic.itemID, c.firstName, c.lastName "
                "FROM itemCreators ic "
                "JOIN creators c ON ic.creatorID=c.creatorID "
                "JOIN creatorTypes ct ON ic.creatorTypeID=ct.creatorTypeID "
                "WHERE ct.creatorType='author' "
                "ORDER BY ic.itemID, ic.orderIndex"
            )
            authors_map: dict[int, list[str]] = {}
            for item_id, first, last in cur.fetchall():
                name = f"{first} {last}".strip() if first else last
                authors_map.setdefault(item_id, []).append(name)

            # Bulk-load tags
            cur = con.execute(
                "SELECT it.itemID, t.name FROM itemTags it JOIN tags t ON it.tagID=t.tagID"
            )
            tags_map: dict[int, list[str]] = {}
            for item_id, tag in cur.fetchall():
                tags_map.setdefault(item_id, []).append(tag)

            # Bulk-load collection membership
            cur = con.execute(
                "SELECT ci.itemID, c.key FROM collectionItems ci "
                "JOIN collections c ON ci.collectionID=c.collectionID"
            )
            coll_map: dict[int, list[str]] = {}
            for item_id, ckey in cur.fetchall():
                coll_map.setdefault(item_id, []).append(ckey)

        result: list[ZoteroItem] = []
        for item_id, key, type_name in item_rows:
            if collection_item_ids is not None and item_id not in collection_item_ids:
                continue
            f = fields.get(item_id, {})
            title = f.get("title", "(no title)")
            if q and q.lower() not in title.lower() and q.lower() not in f.get("abstractNote", "").lower():
                continue
            result.append(ZoteroItem(
                key=key,
                title=title,
                item_type=type_name,
                authors=authors_map.get(item_id, []),
                year=_extract_year(f.get("date")),
                abstract=f.get("abstractNote"),
                doi=f.get("DOI"),
                url=f.get("url"),
                publication=f.get("publicationTitle") or f.get("conferenceName"),
                tags=tags_map.get(item_id, []),
                collection_keys=coll_map.get(item_id, []),
            ))
        result.sort(key=lambda x: x.title.lower())
        return result

    def _sqlite_pdf(self, key: str) -> bytes | None:
        try:
            with self._db() as con:
                row = con.execute(
                    "SELECT ia.path FROM items i "
                    "JOIN itemAttachments ia ON ia.itemID=i.itemID "
                    "JOIN items parent ON ia.parentItemID=parent.itemID "
                    "WHERE parent.key=? AND ia.contentType='application/pdf' "
                    "LIMIT 1",
                    (key,),
                ).fetchone()
            if not row or not row[0]:
                return None
            storage = (self._db_path or _detect_db_path()).parent / "storage"
            # Zotero path format: "storage:filename.pdf" or absolute
            rel = row[0].replace("storage:", "")
            # Find the file under storage/{attachmentKey}/
            for candidate in storage.rglob(rel.lstrip("/")):
                return candidate.read_bytes()
        except Exception:
            return None
        return None

    # ── Desktop API (port 23119) ──────────────────────────────────────────────

    def _desktop_ping(self) -> bool:
        import urllib.request
        try:
            urllib.request.urlopen("http://127.0.0.1:23119/connector/ping", timeout=2)
            return True
        except Exception:
            return False

    def _desktop_collections(self) -> list[ZoteroCollection]:
        raise NotImplementedError("desktop mode not yet implemented")

    def _desktop_items(self, collection_key: str | None, q: str | None) -> list[ZoteroItem]:
        raise NotImplementedError("desktop mode not yet implemented")

    # ── Web API ───────────────────────────────────────────────────────────────

    def _webapi_get(self, path: str, params: dict | None = None) -> list[dict]:
        import json
        import urllib.parse
        import urllib.request

        base = f"https://api.zotero.org{path}"
        headers = {
            "Zotero-API-Key": self._api_key or "",
            "Zotero-API-Version": "3",
        }
        results: list[dict] = []
        start = 0
        limit = 100
        while True:
            p = {**(params or {}), "format": "json", "limit": limit, "start": start}
            url = f"{base}?{urllib.parse.urlencode(p)}"
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=15) as resp:
                total = int(resp.headers.get("Total-Results", "0"))
                batch = json.loads(resp.read())
            results.extend(batch)
            start += len(batch)
            if not batch or start >= total:
                break
        return results

    def _webapi_collections(self) -> list[ZoteroCollection]:
        rows = self._webapi_get(f"/users/{self._user_id}/collections")
        out: list[ZoteroCollection] = []
        for r in rows:
            d = r.get("data", {})
            parent = d.get("parentCollection")
            out.append(ZoteroCollection(
                key=d["key"],
                name=d.get("name", "(no name)"),
                parent_key=parent if isinstance(parent, str) else None,
            ))
        return sorted(out, key=lambda c: c.name.lower())

    def _webapi_items(self, collection_key: str | None, q: str | None) -> list[ZoteroItem]:
        _EXCLUDED = {"attachment", "note", "annotation"}
        if collection_key:
            path = f"/users/{self._user_id}/collections/{collection_key}/items"
        else:
            path = f"/users/{self._user_id}/items"
        params: dict = {}
        if q:
            params["q"] = q
        rows = self._webapi_get(path, params)
        out: list[ZoteroItem] = []
        for r in rows:
            d = r.get("data", {})
            if d.get("itemType") in _EXCLUDED:
                continue
            authors = [
                name for c in d.get("creators", [])
                if c.get("creatorType") == "author"
                for name in [
                    c.get("name") or
                    f"{c.get('firstName', '')} {c.get('lastName', '')}".strip()
                ]
                if name
            ]
            out.append(ZoteroItem(
                key=d["key"],
                title=d.get("title", "(no title)"),
                item_type=d.get("itemType", ""),
                authors=authors,
                year=_extract_year(d.get("date")),
                abstract=d.get("abstractNote") or None,
                doi=d.get("DOI") or None,
                url=d.get("url") or None,
                publication=d.get("publicationTitle") or d.get("conferenceName") or None,
                tags=[t["tag"] for t in d.get("tags", [])],
                collection_keys=d.get("collections", []),
            ))
        return sorted(out, key=lambda x: x.title.lower())

    def _webapi_pdf(self, key: str) -> bytes | None:
        import json
        import urllib.parse
        import urllib.request

        headers = {
            "Zotero-API-Key": self._api_key or "",
            "Zotero-API-Version": "3",
        }
        # Get child attachments
        url = (f"https://api.zotero.org/users/{self._user_id}/items/{key}/children"
               f"?{urllib.parse.urlencode({'format': 'json', 'itemType': 'attachment'})}")
        try:
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=15) as resp:
                children = json.loads(resp.read())
        except Exception:
            return None

        pdf_key = None
        for child in children:
            d = child.get("data", {})
            if d.get("contentType") == "application/pdf":
                pdf_key = d.get("key")
                break
        if not pdf_key:
            return None

        file_url = f"https://api.zotero.org/users/{self._user_id}/items/{pdf_key}/file"
        try:
            req = urllib.request.Request(file_url, headers=headers)
            with urllib.request.urlopen(req, timeout=60) as resp:
                return resp.read()
        except Exception:
            return None
