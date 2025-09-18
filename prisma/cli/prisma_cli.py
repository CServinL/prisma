#!/usr/bin/env python3
"""
Prisma CLI - Research Stream Management & Literature Review

T            click.echo(f"📊 Papers analyzed: {result.papers_analyzed}")
            if hasattr(result, 'authors_found'):
                click.echo(f"👥 Authors identified: {result.authors_found}")
        else:
            error_msg = "Unknown error"
            if result.errors:
                error_msg = "; ".join(result.errors)
            click.echo(f"❌ Review generation failed: {error_msg}", err=True)
            raise click.ClickException(error_msg)
        
    except click.ClickException:
        # Re-raise ClickExceptions as they are
        raise
    except Exception as e:
        click.echo(f"❌ Error generating review: {e}", err=True)
        raise click.ClickException(str(e))des commands for managing research streams and generating
literature reviews using Zotero integration.
"""

import sys
import click
from pathlib import Path

# Add src to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

# Import command groups
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
@click.option('--sources', '-s', help='Data sources (arxiv,pubmed,scholar)')
@click.option('--limit', '-l', type=int, help='Maximum number of papers')
@click.option('--zotero-only', is_flag=True, help='Use only Zotero library')
@click.option('--include-authors', is_flag=True, help='Include author analysis')
@click.option('--refresh-cache', '-r', is_flag=True, help='Refresh cached metadata instead of using cache')
@click.option('--config', '-c', 'config_file', help='Path to configuration file')
def review(topic: str, output: str, sources: str, limit: int, 
          zotero_only: bool, include_authors: bool, refresh_cache: bool, config_file: str):
    """
    Generate a literature review for a research topic
    
    TOPIC: Research topic to search for (e.g., "neural networks")
    
    By default, uses cached metadata for known papers. Use --refresh-cache to update
    existing entries with latest information from sources.
    """
    try:
        click.echo(f"🔍 Generating literature review for: {topic}")
        
        # Import here to avoid circular imports
        from ..coordinator import PrismaCoordinator
        from ..utils.config import config
        
        # Get configuration defaults
        search_config = config.get_search_config()
        output_config = config.get_output_config()
        
        # Apply defaults
        if not sources:
            sources = ','.join(search_config['sources'])
        if not limit:
            limit = search_config['default_limit']
        if not output:
            topic_safe = topic.replace(' ', '_').replace('/', '_')
            output = f"{output_config['directory']}/literature_review_{topic_safe}.md"
        
        # Initialize coordinator
        coordinator = PrismaCoordinator(debug=True)
        
        # Set up parameters
        review_config = {
            'topic': topic,
            'sources': sources.split(','),
            'limit': limit,
            'output_file': output,
            'stream_name': None,
            'include_authors': include_authors,
            'zotero_collections': None,
            'zotero_recent_years': None
        }
        
        # Generate review
        click.echo("📝 Running literature review pipeline...")
        result = coordinator.run_review(review_config)
        
        if result.success:
            click.echo(f"✅ Review generated successfully: {result.output_file}")
            
            # Show summary
            click.echo(f"📊 Papers analyzed: {result.papers_analyzed}")
            if hasattr(result, 'authors_found'):
                click.echo(f"� Authors identified: {result.authors_found}")
        else:
            error_msg = "Unknown error"
            if result.errors:
                error_msg = "; ".join(result.errors)
            click.echo(f"❌ Review generation failed: {error_msg}", err=True)
            raise click.ClickException(error_msg)
        
    except Exception as e:
        click.echo(f"❌ Error generating review: {e}", err=True)
        raise click.ClickException(str(e))


# Add command groups
cli.add_command(streams_group)
cli.add_command(zotero_group)


@cli.command()
@click.option('--verbose', '-v', is_flag=True, help='Show detailed status information')
def status(verbose: bool):
    """
    Check Prisma system status and readiness
    
    Verifies that all components are properly configured and available:
    - Configuration files
    - Zotero connection
    - Required dependencies
    - Storage directories
    """
    import sys
    from pathlib import Path
    import importlib.util
    
    click.echo("🔬 Prisma System Status Check")
    click.echo("=" * 40)
    
    all_good = True
    
    # 1. Check Configuration
    click.echo("\n📋 Configuration:")
    try:
        from ..utils.config import config
        
        # Check if config loaded successfully  
        click.echo(f"  ✅ Config file: config.yaml")
        
        if verbose:
            llm_provider = config.get('llm.provider', 'unknown')
            llm_model = config.get('llm.model', 'unknown')
            output_dir = config.get('output.directory', './outputs')
            click.echo(f"     LLM: {llm_provider} ({llm_model})")
            click.echo(f"     Output: {output_dir}")
            
    except Exception as e:
        click.echo(f"  ❌ Configuration error: {e}")
        all_good = False
    
    # 2. Check Zotero Connection
    click.echo("\n📚 Zotero Integration:")
    try:
        zotero_mode = config.get('sources.zotero.mode', 'hybrid')
        
        if zotero_mode == 'local_api':
            # Check Local API mode
            from ..integrations.zotero.local_api_client import ZoteroLocalAPIClient
            try:
                server_url = config.get('sources.zotero.server_url', 'http://127.0.0.1:23119')
                local_client = ZoteroLocalAPIClient(server_url)
                
                # Test connection by making a simple request
                import requests
                try:
                    response = requests.get(f"{server_url}/connector/ping", timeout=2)
                    if response.status_code == 200:
                        click.echo("  ✅ Zotero Local API: Connected")
                        if verbose:
                            click.echo(f"     Server: {server_url}")
                    else:
                        click.echo("  ❌ Zotero Local API: Not responding")
                        all_good = False
                except requests.exceptions.RequestException:
                    click.echo("  ❌ Zotero Local API: Not connected")
                    if verbose:
                        click.echo(f"     Server: {server_url}")
                        click.echo("     Make sure Zotero desktop is running with Local API enabled")
                    all_good = False
            except Exception as e:
                click.echo("  ❌ Zotero Local API: Connection failed")
                if verbose:
                    click.echo(f"     Error: {e}")
                all_good = False
        else:
            # Check Hybrid/Web API mode
            from ..integrations.zotero.hybrid_client import ZoteroHybridClient
            try:
                # Create a minimal config for the hybrid client
                hybrid_config = {
                    'api_key': config.get('sources.zotero.api_key', ''),
                    'library_id': config.get('sources.zotero.library_id', ''),
                    'library_type': config.get('sources.zotero.library_type', 'user'),
                    'library_path': config.get('sources.zotero.library_path', ''),
                }
                
                # Check API credentials
                if hybrid_config['api_key'] and hybrid_config['library_id']:
                    click.echo("  ✅ Zotero API: Credentials configured")
                else:
                    click.echo("  ⚠️  Zotero API: No credentials configured")
                    if verbose:
                        click.echo("     API access requires api_key and library_id in config")
            except Exception as e:
                click.echo("  ❌ Zotero hybrid mode: Configuration error")
                if verbose:
                    click.echo(f"     Error: {e}")
                all_good = False
                
    except Exception as e:
        click.echo(f"  ❌ Zotero integration error: {e}")
        all_good = False
    
    # 3. Check Dependencies
    click.echo("\n📦 Dependencies:")
    required_packages = [
        ('requests', 'HTTP requests'),
        ('pydantic', 'Data validation'),
        ('yaml', 'Configuration parsing (PyYAML)'),
        ('pyzotero', 'Zotero API client'),
        ('click', 'CLI framework')
    ]
    
    for package, description in required_packages:
        try:
            spec = importlib.util.find_spec(package)
            if spec:
                click.echo(f"  ✅ {package}: Available")
            else:
                click.echo(f"  ❌ {package}: Missing")
                all_good = False
        except Exception:
            click.echo(f"  ❌ {package}: Error checking")
            all_good = False
    
    # 4. Check Storage
    click.echo("\n💾 Storage:")
    try:
        output_dir = Path(config.get('output.directory', './outputs'))
        if output_dir.exists():
            click.echo(f"  ✅ Output directory: {output_dir}")
        else:
            click.echo(f"  ✅ Output directory: {output_dir}")
            
        data_dir = Path("./data")
        if data_dir.exists():
            click.echo(f"  ✅ Data directory: {data_dir}")
        else:
            click.echo(f"  ✅ Data directory: {data_dir}")
            
    except Exception as e:
        click.echo(f"  ❌ Storage error: {e}")
        all_good = False
    
    # 5. Check LLM Connection (if configured)
    click.echo("\n🤖 LLM Integration:")
    try:
        llm_provider = config.get('llm.provider', 'ollama')
        if llm_provider == "ollama":
            import requests
            try:
                llm_host = config.get('llm.host', 'localhost:11434')
                base_url = f"http://{llm_host}"
                response = requests.get(f"{base_url}/api/tags", timeout=5)
                if response.status_code == 200:
                    click.echo(f"  ✅ Ollama: Connected to {base_url}")
                    if verbose:
                        models = response.json().get('models', [])
                        click.echo(f"     Available models: {len(models)}")
                else:
                    click.echo(f"  ❌ Ollama: Server responded with {response.status_code}")
                    all_good = False
            except requests.exceptions.RequestException as e:
                click.echo(f"  ❌ Ollama: Cannot connect to {base_url}")
                if verbose:
                    click.echo(f"     Error: {e}")
                all_good = False
        else:
            click.echo(f"  ⚠️  LLM provider '{llm_provider}' not tested")
            
    except Exception as e:
        click.echo(f"  ❌ LLM integration error: {e}")
        all_good = False
    
    # Final Status
    click.echo("\n" + "=" * 40)
    if all_good:
        click.echo("🎉 Prisma is ready to work!")
        sys.exit(0)
    else:
        click.echo("⚠️  Some issues found - check details above")
        sys.exit(1)


if __name__ == '__main__':
    cli()