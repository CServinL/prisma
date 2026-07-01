"""Shared static-file serving helper — used by both the API process (which no
longer mounts the UI, kept only for local/dev convenience) and the Web
process (prisma.server.web_app), which is the sole owner of UI serving in
the supervised, multi-process layout. See ADR-012."""
from __future__ import annotations


class CleanUrlStaticFiles:
    """StaticFiles that resolves extension-less clean URLs (SvelteKit prerendered
    routes, e.g. /foo) to their built file (foo.html), like a real static host does.
    Without this, prerendered pages 404 since adapter-static writes them as flat
    .html files but the browser/service worker requests the clean path."""

    def __new__(cls, *args, **kwargs):
        from fastapi.staticfiles import StaticFiles

        class _Impl(StaticFiles):
            def lookup_path(self, path: str):
                full_path, stat_result = super().lookup_path(path)
                if stat_result is None and path and "." not in path.rsplit("/", 1)[-1]:
                    full_path, stat_result = super().lookup_path(f"{path}.html")
                return full_path, stat_result

        return _Impl(*args, **kwargs)
