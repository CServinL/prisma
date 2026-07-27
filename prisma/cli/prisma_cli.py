#!/usr/bin/env python3
"""
Prisma CLI — Research Stream Management & Literature Review

Commands for managing research streams and generating literature reviews
using Zotero integration and multi-source academic search.
"""

import os
import sys
import click

from .commands.streams import streams_group
from .commands.zotero import zotero_group
from .commands.auth import auth_group


@click.group()
@click.version_option()
def cli():
    """
    Prisma - Intelligent Literature Review Tool

    Manage research streams and generate comprehensive literature reviews
    using smart Zotero integration and multi-source search capabilities.
    """
    pass


@cli.command()
@click.argument('topic', required=True)
@click.option('--output', '-o', help='Output file path')
@click.option('--sources', '-s', help='Data sources (arxiv,semanticscholar,...)')
@click.option('--limit', '-l', type=int, help='Maximum number of papers')
@click.option('--zotero-only', is_flag=True, help='Use only Zotero library')
@click.option('--include-authors', is_flag=True, help='Include author analysis')
@click.option('--refresh-cache', '-r', is_flag=True, help='Refresh cached metadata')
@click.option('--config', '-c', 'config_file', help='Path to configuration file')
def review(topic: str, output: str, sources: str, limit: int,
           zotero_only: bool, include_authors: bool, refresh_cache: bool, config_file: str):
    """
    Generate a literature review for a research topic.

    TOPIC: Research topic to search for (e.g., "mechanistic interpretability")
    """
    try:
        if config_file:
            os.environ['PRISMA_CONFIG'] = config_file

        from ..coordinator import PrismaCoordinator
        from ..connectivity import monitor as connectivity
        from ..utils.config import ConfigLoader
        cfg = ConfigLoader()

        if not zotero_only and not connectivity.is_online:
            click.echo("⚠️  Offline — literature review requires internet access.", err=True)
            raise click.ClickException("No internet connection")

        click.echo(f"🔍 Generating literature review for: {topic}")

        search_config = cfg.get_search_config()
        output_config = cfg.get_output_config()

        if not sources:
            sources = ','.join(search_config.sources)
        if not limit:
            limit = search_config.default_limit
        if not output:
            topic_safe = topic.replace(' ', '_').replace('/', '_')
            output = f"{output_config.directory}/literature_review_{topic_safe}.md"

        if zotero_only:
            sources = 'zotero'

        coordinator = PrismaCoordinator(debug=True)

        review_config = {
            'topic': topic,
            'sources': sources.split(','),
            'limit': limit,
            'output_file': output,
            'stream_name': None,
            'include_authors': include_authors,
            'zotero_collections': None,
            'zotero_recent_years': None,
        }

        click.echo("📝 Running literature review pipeline...")
        result = coordinator.run_review(review_config)

        if result.success:
            click.echo(f"✅ Review generated: {result.output_file}")
            click.echo(f"📊 Papers analyzed: {result.papers_analyzed}")
            click.echo(f"👥 Authors identified: {result.authors_found}")
        else:
            error_msg = "; ".join(result.errors) if result.errors else "Unknown error"
            click.echo(f"❌ Review failed: {error_msg}", err=True)
            raise click.ClickException(error_msg)

    except click.ClickException:
        raise
    except Exception as exc:
        click.echo(f"❌ Error: {exc}", err=True)
        raise click.ClickException(str(exc))


def _is_wsl() -> bool:
    try:
        with open('/proc/version') as f:
            return 'microsoft' in f.read().lower()
    except OSError:
        return False


def _wsl_windows_ip() -> str:
    """Best-effort: return the Windows host IP as seen from WSL."""
    import subprocess
    try:
        out = subprocess.check_output(
            ['ip', 'route', 'show'], text=True, stderr=subprocess.DEVNULL
        )
        for line in out.splitlines():
            if line.startswith('default'):
                return line.split()[2]
    except Exception:
        pass
    return '<windows-host-ip>'


@cli.command()
@click.option('--verbose', '-v', is_flag=True, help='Show detailed status information')
def status(verbose: bool):
    """
    Check Prisma system status and readiness.

    Verifies configuration, Zotero connection, dependencies, storage, and LLM.
    """
    import importlib.util
    import requests as _req
    from pathlib import Path

    click.echo("🔬 Prisma System Status Check")
    click.echo("=" * 40)

    all_good = True
    wsl = _is_wsl()

    # 0. Connectivity
    click.echo("\n🌐 Connectivity:")
    from ..connectivity import monitor as connectivity
    if connectivity.is_online:
        click.echo("  ✅ Internet: reachable")
    else:
        click.echo("  ⚠️  Internet: offline (stream updates and reviews unavailable)")

    # 1. Configuration
    config = None
    config_path = None
    click.echo("\n📋 Configuration:")

    default_config = Path.home() / '.config' / 'prisma' / 'config.yaml'
    env_config = os.getenv('PRISMA_CONFIG')

    if env_config:
        p = Path(env_config).expanduser()
        config_path = p if p.exists() else None
    elif default_config.exists():
        config_path = default_config

    if config_path is None:
        click.echo("  ❌ No config file found")
        click.echo(f"     Expected: {default_config}")
        click.echo("     Create it:")
        click.echo("       mkdir -p ~/.config/prisma")
        click.echo("       cp /path/to/repo/config.example.yaml ~/.config/prisma/config.yaml")
        all_good = False
    else:
        try:
            from ..utils.config import ConfigLoader
            config = ConfigLoader()
            click.echo(f"  ✅ Config loaded: {config_path}")
            if verbose:
                click.echo(f"     LLM:    {config.get('llm.provider', 'ollama')} / {config.get('llm.model', 'qwen2.5:7b-32k')}")
                click.echo(f"     Output: {config.get('output.directory', './outputs')}")
                click.echo(f"     Zotero: enabled={config.get('sources.zotero.enabled', False)}")
        except Exception as exc:
            click.echo(f"  ❌ Config error: {exc}")
            all_good = False

    # 2. Pending write queue
    click.echo("\n📬 Pending Write Queue:")
    try:
        from ..storage.pending_queue import PendingWriteQueue
        q = PendingWriteQueue()
        if q:
            click.echo(f"  ⏳ {q.pending_count} action(s) queued for Zotero sync")
        else:
            click.echo("  ✅ Queue empty")
    except Exception as exc:
        click.echo(f"  ❌ Queue error: {exc}")

    # 3. Zotero — prisma only talks to Zotero via its Web API (confirmed
    # 2026-07-27; there is no local Zotero Desktop integration anymore).
    click.echo("\n📚 Zotero Integration:")
    if config is None:
        click.echo("  ⚠️  Skipped — fix config first")
    else:
        api_key = config.get('sources.zotero.api_key', '')
        library_id = config.get('sources.zotero.library_id', '')

        if api_key and library_id:
            click.echo(f"  Web API: library_id={library_id} ✅ credentials configured")
            from ..services.zotero import check_web_api_reachable
            if check_web_api_reachable(api_key, library_id):
                click.echo("    ✅ Reachable")
            else:
                click.echo("    ❌ Unreachable — check credentials and internet connectivity")
                all_good = False
        else:
            missing = []
            if not api_key:
                missing.append('api_key')
            if not library_id:
                missing.append('library_id')
            click.echo(f"  Web API: ⚠️  missing {', '.join(missing)}")
            click.echo("    Get your key at: https://www.zotero.org/settings/keys/new")
            click.echo("    Get your user ID at: https://www.zotero.org/settings/keys")
            all_good = False

    # 4. Dependencies
    click.echo("\n📦 Dependencies:")
    for pkg in ['requests', 'pydantic', 'yaml', 'pyzotero', 'click']:
        spec = importlib.util.find_spec(pkg)
        mark = "✅" if spec else "❌"
        click.echo(f"  {mark} {pkg}")
        if not spec:
            all_good = False

    # 5. LLM
    click.echo("\n🤖 LLM (Ollama):")
    if config is None:
        click.echo("  ⚠️  Skipped — fix config first")
    else:
        llm_host = config.get('llm.host', 'localhost:11434')
        try:
            resp = _req.get(f"http://{llm_host}/api/tags", timeout=5)
            if resp.status_code == 200:
                click.echo(f"  ✅ Ollama: connected ({llm_host})")
                if verbose:
                    models = resp.json().get('models', [])
                    click.echo(f"     Models available: {len(models)}")
            else:
                click.echo(f"  ❌ Ollama: server error {resp.status_code}")
                all_good = False
        except Exception:
            click.echo(f"  ❌ Ollama: cannot connect to {llm_host}")
            if wsl:
                windows_ip = _wsl_windows_ip()
                click.echo("    In WSL, Ollama must run on Windows with OLLAMA_HOST=0.0.0.0:11434")
                click.echo(f"    Then set in config: host: \"{windows_ip}:11434\"")
                click.echo("    Or add to ~/.bashrc:")
                click.echo("      export OLLAMA_HOST=$(ip route show | grep default | awk '{print $3}'):11434")
            all_good = False

    click.echo("\n" + "=" * 40)
    if all_good:
        click.echo("🎉 Prisma is ready!")
        sys.exit(0)
    else:
        click.echo("⚠️  Some issues found — check details above")
        sys.exit(1)


@cli.command()
def sync():
    """
    Flush the pending write queue to Zotero.

    Prisma queues Zotero write actions (save paper, create collection) when
    offline or when Zotero is unavailable.  Run this command once connectivity
    is restored to push all queued actions.
    """
    from ..connectivity import monitor as connectivity
    from ..storage.pending_queue import PendingWriteQueue

    q = PendingWriteQueue()
    if not q:
        click.echo("✅ No pending actions to sync.")
        return

    click.echo(f"📬 {q.pending_count} action(s) pending.")

    if not connectivity.is_online:
        click.echo("⚠️  Offline — cannot sync right now. Try again when connected.", err=True)
        raise click.ClickException("No internet connection")

    click.echo("🔄 Syncing with Zotero...")
    try:
        from ..services.research_stream_manager import ResearchStreamManager
        manager = ResearchStreamManager()
        ok, fail = manager.sync_pending()
        click.echo(f"✅ Synced: {ok} succeeded, {fail} failed")
        if fail:
            click.echo("⚠️  Failed actions remain in queue — check logs for details")
    except Exception as exc:
        click.echo(f"❌ Sync error: {exc}", err=True)
        raise click.ClickException(str(exc))


@cli.command()
@click.option("--host", default="127.0.0.1", show_default=True, help="Bind address")
@click.option("--port", default=8765, show_default=True, help="API port")
@click.option("--web-port", default=8766, show_default=True, help="Web (UI) port")
@click.option("--chroma-port", default=8767, show_default=True, help="ChromaDB server port")
@click.option("--kg-port", default=8768, show_default=True, help="Knowledge graph server port")
@click.option("--supervisor-port", default=8760, show_default=True, help="Supervisor control port (loopback only)")
@click.option("--reload", is_flag=True, help="Auto-reload the API on code changes (dev only)")
def serve(host: str, port: int, web_port: int, chroma_port: int, kg_port: int, supervisor_port: int, reload: bool):
    """Start Prisma: a supervisor process managing the API, Web, ChromaDB, and
    knowledge graph server processes independently (see ADR-012). A crash in
    any one of them no longer takes down the others."""
    try:
        import uvicorn  # noqa: F401 — validated here for a clearer error message
    except ImportError:
        raise click.ClickException("uvicorn not installed — run: pip install 'prisma[server]'")
    from ..server.supervisor import main as supervisor_main
    click.echo(f"Starting Prisma — API http://{host}:{port}  Web http://{host}:{web_port}")
    supervisor_main(
        host=host, api_port=port, web_port=web_port,
        chroma_port=chroma_port, kg_port=kg_port, supervisor_port=supervisor_port, reload=reload,
    )


@cli.command("reload-resources")
@click.option("--supervisor-port", default=8760, show_default=True, help="Supervisor control port")
def reload_resources(supervisor_port: int):
    """Re-read compute_pools from config.yaml into an already-running
    supervisor — no restart, no lost in-flight leases. For tuning
    max_concurrent/per-model overrides against observed GPU utilization
    without killing every worker just to pick up one changed number."""
    import requests as _req
    try:
        r = _req.post(f"http://127.0.0.1:{supervisor_port}/supervisor/resources/reload", timeout=5)
        r.raise_for_status()
        click.echo(f"Reloaded pools: {', '.join(r.json().get('pools', []))}")
    except _req.RequestException as exc:
        raise click.ClickException(f"could not reach supervisor at port {supervisor_port}: {exc}")


cli.add_command(streams_group)
cli.add_command(zotero_group)
cli.add_command(auth_group)


if __name__ == '__main__':
    cli()
