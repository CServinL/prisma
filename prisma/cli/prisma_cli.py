#!/usr/bin/env python3
"""
Prisma CLI — Research Stream Management & Literature Review

Commands for managing research streams and generating literature reviews
using Zotero integration and multi-source academic search.
"""

import sys
import click
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from .commands.streams import streams_group
from .commands.zotero import zotero_group


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
        from ..coordinator import PrismaCoordinator
        from ..connectivity import monitor as connectivity
        from ..utils.config import config

        if not connectivity.is_online:
            click.echo("⚠️  Offline — literature review requires internet access.", err=True)
            raise click.ClickException("No internet connection")

        click.echo(f"🔍 Generating literature review for: {topic}")

        search_config = config.get_search_config()
        output_config = config.get_output_config()

        if not sources:
            sources = ','.join(search_config.sources)
        if not limit:
            limit = search_config.default_limit
        if not output:
            topic_safe = topic.replace(' ', '_').replace('/', '_')
            output = f"{output_config.directory}/literature_review_{topic_safe}.md"

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


@cli.command()
@click.option('--verbose', '-v', is_flag=True, help='Show detailed status information')
def status(verbose: bool):
    """
    Check Prisma system status and readiness.

    Verifies configuration, Zotero connection, dependencies, storage, and LLM.
    """
    import importlib.util

    click.echo("🔬 Prisma System Status Check")
    click.echo("=" * 40)

    all_good = True

    # 0. Connectivity
    click.echo("\n🌐 Connectivity:")
    from ..connectivity import monitor as connectivity
    if connectivity.is_online:
        click.echo("  ✅ Internet: reachable")
    else:
        click.echo("  ⚠️  Internet: offline (stream updates and reviews unavailable)")

    # 1. Configuration
    click.echo("\n📋 Configuration:")
    try:
        from ..utils.config import config
        click.echo("  ✅ Config loaded")
        if verbose:
            click.echo(f"     LLM: {config.get('llm.provider', 'ollama')} ({config.get('llm.model', 'llama3.1:8b')})")
            click.echo(f"     Output: {config.get('output.directory', './outputs')}")
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

    # 3. Zotero
    click.echo("\n📚 Zotero Integration:")
    try:
        zotero_mode = config.get('sources.zotero.mode', 'hybrid')
        if zotero_mode == 'local_api':
            import requests as _req
            server_url = config.get('sources.zotero.server_url', 'http://127.0.0.1:23119')
            try:
                resp = _req.get(f"{server_url}/connector/ping", timeout=2)
                if resp.status_code == 200:
                    click.echo("  ✅ Zotero Local API: connected")
                    if verbose:
                        click.echo(f"     Server: {server_url}")
                else:
                    click.echo("  ❌ Zotero Local API: not responding")
                    all_good = False
            except Exception:
                click.echo("  ❌ Zotero Local API: not connected (start Zotero desktop)")
                all_good = False
        else:
            api_key = config.get('sources.zotero.api_key', '')
            library_id = config.get('sources.zotero.library_id', '')
            if api_key and library_id:
                click.echo("  ✅ Zotero API: credentials configured")
            else:
                click.echo("  ⚠️  Zotero API: no credentials (set api_key + library_id)")
    except Exception as exc:
        click.echo(f"  ❌ Zotero error: {exc}")
        all_good = False

    # 4. Dependencies
    click.echo("\n📦 Dependencies:")
    for pkg, desc in [
        ('requests', 'HTTP requests'),
        ('pydantic', 'Data validation'),
        ('yaml', 'Config parsing'),
        ('pyzotero', 'Zotero API client'),
        ('click', 'CLI framework'),
    ]:
        spec = importlib.util.find_spec(pkg)
        mark = "✅" if spec else "❌"
        click.echo(f"  {mark} {pkg}")
        if not spec:
            all_good = False

    # 5. LLM
    click.echo("\n🤖 LLM (Ollama):")
    try:
        import requests as _req
        llm_host = config.get('llm.host', 'localhost:11434')
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
        click.echo(f"  ❌ Ollama: cannot connect to {llm_host} (start Ollama)")
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


cli.add_command(streams_group)
cli.add_command(zotero_group)


if __name__ == '__main__':
    cli()
