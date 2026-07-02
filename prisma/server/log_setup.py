import logging
import logging.handlers
import sys
from pathlib import Path

from pydantic import BaseModel


class LogPaths(BaseModel):
    log_dir: Path
    server: Path
    access: Path
    maintenance: Path
    ollama: Path
    activity: Path
    chroma: Path
    kg: Path
    supervisor: Path
    streams_dir: Path

    model_config = {"arbitrary_types_allowed": True}


_paths: LogPaths | None = None


def paths() -> LogPaths:
    if _paths is None:
        raise RuntimeError("call configure() first")
    return _paths


def configure(level: int = logging.INFO) -> LogPaths:
    global _paths

    base = Path.home() / ".local" / "share" / "prisma" / "logs"
    streams_dir = base / "streams"
    base.mkdir(parents=True, exist_ok=True)
    streams_dir.mkdir(exist_ok=True)

    fmt = logging.Formatter("%(asctime)s [%(name)s] %(levelname)s %(message)s")

    def _rotating(path: Path, max_bytes: int = 5 * 1024 * 1024, backups: int = 3) -> logging.handlers.RotatingFileHandler:
        h = logging.handlers.RotatingFileHandler(
            path, maxBytes=max_bytes, backupCount=backups, encoding="utf-8"
        )
        h.setFormatter(fmt)
        return h

    root = logging.getLogger()
    root.setLevel(level)
    if not root.handlers:
        console = logging.StreamHandler(sys.stdout)
        console.setFormatter(fmt)
        root.addHandler(console)
        root.addHandler(_rotating(base / "server.log"))

    for name, filename in [
        ("prisma.maintenance", "maintenance.log"),
        ("prisma.ollama", "ollama.log"),
        ("prisma.activity", "activity.log"),
        ("prisma.chroma", "chroma.log"),
        ("prisma.knowledge_graph", "kg.log"),
    ]:
        lgr = logging.getLogger(name)
        lgr.propagate = True
        if not lgr.handlers:
            lgr.addHandler(_rotating(base / filename))

    # Access: file only — too chatty for stdout
    access = logging.getLogger("prisma.access")
    access.propagate = False
    if not access.handlers:
        access.addHandler(_rotating(base / "access.log"))

    _paths = LogPaths(
        log_dir=base,
        server=base / "server.log",
        access=base / "access.log",
        maintenance=base / "maintenance.log",
        ollama=base / "ollama.log",
        activity=base / "activity.log",
        chroma=base / "chroma.log",
        kg=base / "kg.log",
        # Written by the supervisor process itself (prisma.server.supervisor),
        # not by this configure() — that process deliberately doesn't import
        # this module (which pulls in pydantic) to stay stdlib + yaml only.
        # Same base dir and filename convention, so this is just the path the
        # api process's /logs viewer reads from, not a handler this owns.
        supervisor=base / "supervisor.log",
        streams_dir=streams_dir,
    )
    return _paths


def get_stream_logger(slug: str) -> logging.Logger:
    lgr = logging.getLogger(f"prisma.stream.{slug}")
    if _paths is not None and not lgr.handlers:
        fmt = logging.Formatter("%(asctime)s [%(levelname)s] %(message)s")
        h = logging.handlers.RotatingFileHandler(
            _paths.streams_dir / f"{slug}.log",
            maxBytes=2 * 1024 * 1024,
            backupCount=5,
            encoding="utf-8",
        )
        h.setFormatter(fmt)
        lgr.addHandler(h)
        lgr.propagate = True
    return lgr
