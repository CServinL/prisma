#!/usr/bin/env python3
"""
Prisma CLI — minimal, local-machine-only surface.

Only commands that inherently can't be an HTTP API call live here: `serve`
(starts the API this CLI can't yet call), `status` (pre-flight diagnostic —
runs before/without a live server), `reload-config` (diffs config on disk
against what's loaded and reloads only the affected subsystems), and `auth
hash-password` (bootstraps server.auth.password_hash before any server/
password exists).
Everything else — literature review, research streams, Zotero duplicates/
stats/status, syncing the offline pending-write queue — is API-only now
(see docs/wiki/cli.md's "Moved to the API" section for the exact routes).
"""

import os
import sys
import click

from .commands.auth import auth_group


@click.group()
@click.version_option()
def cli():
    """
    Prisma - Intelligent Literature Review Tool

    Local-machine management: start the server, check its readiness,
    bootstrap auth. Content and research operations go through the API.
    """
    pass


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

    default_config = Path.home() / '.config' / 'prisma' / 'config.toml'
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
        click.echo("       cp /path/to/repo/config.example.toml ~/.config/prisma/config.toml")
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
        zconf = config.config.sources.zotero
        env_errors = []
        try:
            api_key = zconf.resolve_api_key() or ''
        except RuntimeError as exc:
            api_key = ''
            env_errors.append(str(exc))
        try:
            library_id = zconf.resolve_library_id() or ''
        except RuntimeError as exc:
            library_id = ''
            env_errors.append(str(exc))

        if env_errors:
            for err in env_errors:
                click.echo(f"  Web API: ❌ {err}")
            all_good = False
        elif api_key and library_id:
            click.echo(f"  Web API: library_id={library_id} ✅ credentials configured")
            from ..integrations.zotero.client import check_web_api_reachable
            if check_web_api_reachable(api_key, library_id, library_type=getattr(zconf, "library_type", "user")):
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


@cli.command("reload-config")
@click.option("--port", default=8765, show_default=True, help="API port")
def reload_config(port: int):
    """Diff the config on disk against what's currently loaded, and reload
    only the subsystems that actually changed (vault, Zotero, retrieval/
    Chroma, chat) plus the supervisor's compute_pools — no restart, no lost
    in-flight leases or connections for anything that didn't change."""
    import requests as _req
    try:
        r = _req.post(f"http://127.0.0.1:{port}/reload", timeout=15)
        r.raise_for_status()
    except _req.RequestException as exc:
        raise click.ClickException(f"could not reach the API at port {port}: {exc}")

    body = r.json()
    changed = body.get("changed", [])
    reloaded = body.get("reloaded", [])
    pools_reloaded = body.get("compute_pools_reloaded", False)

    if changed:
        click.echo(f"Changed: {', '.join(changed)}")
        click.echo(f"Reloaded: {', '.join(reloaded)}")
    else:
        click.echo("No config sections changed.")
    click.echo(f"Compute pools: {'reloaded' if pools_reloaded else 'supervisor unreachable — not reloaded'}")


cli.add_command(auth_group)


if __name__ == '__main__':
    cli()
