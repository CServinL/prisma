import logging
from pathlib import Path
from typing import Optional

import click

from prisma.services.vault import VaultService
from prisma.services.zotero import ZoteroMode, ZoteroService
from prisma.storage.models.vault_models import RefreshFrequency, StreamStatus

logger = logging.getLogger(__name__)


def _make_vault(config: Optional[str]) -> VaultService:
    import yaml
    cfg_path = Path(config).expanduser() if config else Path.home() / ".config" / "prisma" / "config.yaml"
    try:
        cfg = yaml.safe_load(cfg_path.read_text()) or {}
        root = cfg.get("vault_root", "").strip()
        vault_root = Path(root).expanduser().resolve() if root else Path.home() / "prisma-vault"
    except Exception:
        vault_root = Path.home() / "prisma-vault"
    return VaultService(vault_root=vault_root)


def _make_zotero(config: Optional[str]) -> ZoteroService:
    import yaml
    cfg_path = Path(config).expanduser() if config else Path.home() / ".config" / "prisma" / "config.yaml"
    try:
        cfg = yaml.safe_load(cfg_path.read_text()) or {}
        zconf = cfg.get("sources", {}).get("zotero", {})
        api_key = zconf.get("api_key") or None
        user_id = zconf.get("library_id") or None
        mode = ZoteroMode.web_api if api_key else ZoteroMode.offline
        return ZoteroService(mode=mode, api_key=api_key, user_id=user_id)
    except Exception:
        return ZoteroService(mode=ZoteroMode.offline)


@click.group(name="streams")
def streams_group():
    """Manage research streams for continuous literature monitoring"""
    pass


@streams_group.command("create")
@click.argument("name", required=True)
@click.argument("query", required=True)
@click.option("--description", "-d", help="Description of the research stream")
@click.option(
    "--frequency", "-f",
    type=click.Choice(["daily", "weekly", "monthly", "manual"]),
    default="weekly",
    help="How often to refresh the stream",
)
@click.option("--config", "-c", help="Path to configuration file")
def create_stream(name: str, query: str, description: Optional[str], frequency: str, config: Optional[str]):
    """Create a new research stream.

    NAME: Human-readable name for the stream
    QUERY: Search query for finding papers
    """
    vault = _make_vault(config)
    stream = vault.create_stream(
        title=name,
        query=query,
        description=description,
        refresh_frequency=frequency,
    )
    click.echo(f"Created: {stream.slug}")
    click.echo(f"  Title: {stream.title}")
    click.echo(f"  Query: {stream.query}")
    click.echo(f"  Frequency: {stream.refresh_frequency.value}")
    click.echo(f"  Status: {stream.status.value}")


@streams_group.command("list")
@click.option("--status", "-s", type=click.Choice(["active", "paused", "archived"]), help="Filter by status")
@click.option("--config", "-c", help="Path to configuration file")
def list_streams(status: Optional[str], config: Optional[str]):
    """List all research streams"""
    vault = _make_vault(config)
    streams = vault.list_streams()
    if status:
        streams = [s for s in streams if s.status.value == status]
    if not streams:
        click.echo("No streams found.")
        return
    for s in streams:
        due = s.next_update is None or (s.next_update and s.next_update.timestamp() < __import__("time").time())
        due_marker = " [DUE]" if s.status == StreamStatus.active and due else ""
        click.echo(f"{s.slug}  {s.title}  ({s.status.value}){due_marker}")
        click.echo(f"  query={s.query}  papers={s.total_papers}  freq={s.refresh_frequency.value}")
        if s.last_updated:
            click.echo(f"  last_updated={s.last_updated.strftime('%Y-%m-%d %H:%M')}")


@streams_group.command("info")
@click.argument("slug", required=True)
@click.option("--config", "-c", help="Path to configuration file")
def stream_info(slug: str, config: Optional[str]):
    """Show detailed information about a stream"""
    vault = _make_vault(config)
    try:
        s = vault.get_stream(slug)
    except FileNotFoundError:
        raise click.ClickException(f"stream not found: {slug!r}")
    click.echo(f"Slug:       {s.slug}")
    click.echo(f"Title:      {s.title}")
    click.echo(f"Status:     {s.status.value}")
    click.echo(f"Query:      {s.query}")
    click.echo(f"Frequency:  {s.refresh_frequency.value}")
    click.echo(f"Papers:     {s.total_papers}")
    if s.collection_key:
        click.echo(f"Collection: {s.collection_key}")
    if s.description:
        click.echo(f"Desc:       {s.description}")
    if s.last_updated:
        click.echo(f"Updated:    {s.last_updated.strftime('%Y-%m-%d %H:%M')}")
    if s.next_update:
        click.echo(f"Next:       {s.next_update.strftime('%Y-%m-%d %H:%M')}")


@streams_group.command("update")
@click.argument("slug", required=False)
@click.option("--all", "-a", "all_streams", is_flag=True, help="Update all active streams")
@click.option("--force", "-f", is_flag=True, help="Force update even if not due")
@click.option("--config", "-c", help="Path to configuration file")
def update_streams(slug: Optional[str], all_streams: bool, force: bool, config: Optional[str]):
    """Update research streams to find new papers"""
    from prisma.services.stream_runner import run_stream

    if not slug and not all_streams:
        raise click.ClickException("Specify a slug or use --all")

    vault = _make_vault(config)
    zotero = _make_zotero(config)

    targets: list[str]
    if all_streams:
        targets = [s.slug for s in vault.list_streams() if s.status == StreamStatus.active]
        if not targets:
            click.echo("No active streams.")
            return
    else:
        targets = [slug]

    for target_slug in targets:
        click.echo(f"Running {target_slug}...")
        try:
            result = run_stream(target_slug, vault, zotero, force=force)
            click.echo(
                f"  found={result.papers_found} saved={result.papers_saved}"
                f" skipped_llm={result.papers_skipped_llm}"
            )
            if result.errors:
                for err in result.errors:
                    click.echo(f"  warning: {err}")
        except FileNotFoundError:
            click.echo(f"  stream not found: {target_slug!r}", err=True)
        except Exception as exc:
            click.echo(f"  error: {exc}", err=True)


@streams_group.command("summary")
@click.option("--config", "-c", help="Path to configuration file")
def streams_summary(config: Optional[str]):
    """Show summary of all streams"""
    import time as _time
    vault = _make_vault(config)
    streams = vault.list_streams()
    active = [s for s in streams if s.status == StreamStatus.active]
    due = [s for s in active if s.next_update is None or s.next_update.timestamp() < _time.time()]
    total_papers = sum(s.total_papers for s in streams)
    click.echo(f"Total:   {len(streams)}")
    click.echo(f"Active:  {len(active)}")
    click.echo(f"Due:     {len(due)}")
    click.echo(f"Papers:  {total_papers}")


__all__ = ["streams_group"]
