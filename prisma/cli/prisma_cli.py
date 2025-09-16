#!/usr/bin/env python3
"""
Prisma CLI - Research Stream Management & Literature Review

This CLI provides commands for managing research streams and generating
literature reviews using Zotero integration.
"""

import sys
import click
from pathlib import Path

# Add src to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

# Import command groups
from .commands.streams import streams_group


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
@click.option('--config', '-c', help='Path to configuration file')
def review(topic: str, output: str, sources: str, limit: int, 
          zotero_only: bool, include_authors: bool, config: str):
    """
    Generate a literature review for a research topic
    
    TOPIC: Research topic to search for (e.g., "neural networks")
    """
    try:
        click.echo(f"🔍 Generating literature review for: {topic}")
        
        # Import here to avoid circular imports
        from ..coordinator import PrismaCoordinator
        from ..utils.config import ConfigLoader
        
        # Load configuration
        config_loader = ConfigLoader(config)
        prisma_config = config_loader.load()
        
        # Initialize coordinator
        coordinator = PrismaCoordinator(prisma_config)
        
        # Set up parameters
        params = {
            'topic': topic,
            'output_file': output or f"{topic.replace(' ', '_')}_review.md"
        }
        
        if sources:
            params['sources'] = sources.split(',')
        if limit:
            params['limit'] = limit
        if zotero_only:
            params['zotero_only'] = True
        if include_authors:
            params['include_authors'] = True
        
        # Generate review
        click.echo("📝 Running literature review pipeline...")
        result = coordinator.run_literature_review(**params)
        
        if result.get('success', False):
            output_path = result.get('output_file', params['output_file'])
            click.echo(f"✅ Review generated successfully: {output_path}")
            
            # Show summary
            if 'papers_analyzed' in result:
                click.echo(f"📊 Papers analyzed: {result['papers_analyzed']}")
            if 'sources_used' in result:
                click.echo(f"🔍 Sources used: {', '.join(result['sources_used'])}")
        else:
            error = result.get('error', 'Unknown error')
            click.echo(f"❌ Review generation failed: {error}", err=True)
            raise click.ClickException(error)
        
    except Exception as e:
        click.echo(f"❌ Error generating review: {e}", err=True)
        raise click.ClickException(str(e))


# Add command groups
cli.add_command(streams_group)


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
        from ..utils.config import ConfigLoader
        config_loader = ConfigLoader()
        config = config_loader.config
        
        if config_loader.config_path:
            click.echo(f"  ✅ Config file: {config_loader.config_path}")
        else:
            click.echo("  ⚠️  Using default configuration (no config file found)")
            if verbose:
                click.echo("     Consider creating a config.yaml file")
        
        if verbose:
            click.echo(f"     LLM: {config.llm.provider} ({config.llm.model})")
            click.echo(f"     Output: {config.output.directory}")
            
    except Exception as e:
        click.echo(f"  ❌ Configuration error: {e}")
        all_good = False
    
    # 2. Check Zotero Connection
    click.echo("\n📚 Zotero Integration:")
    try:
        from ..integrations.zotero.hybrid_client import ZoteroHybridClient
        zotero_client = ZoteroHybridClient(config)
        
        # Test desktop connection
        try:
            desktop_status = zotero_client._test_desktop_connection()
            if desktop_status:
                click.echo("  ✅ Zotero desktop app: Connected")
            else:
                click.echo("  ❌ Zotero desktop app: Not connected")
                all_good = False
        except Exception as e:
            click.echo("  ❌ Zotero desktop app: Not connected")
            if verbose:
                click.echo(f"     Error: {e}")
            all_good = False
        
        # Check API credentials
        if config.sources.zotero.api_key and config.sources.zotero.library_id:
            click.echo("  ✅ Zotero API: Credentials configured")
        else:
            click.echo("  ⚠️  Zotero API: No credentials configured")
            if verbose:
                click.echo("     API access requires api_key and library_id in config")
                
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
        output_dir = Path(config.output.directory)
        if output_dir.exists():
            click.echo(f"  ✅ Output directory: {output_dir}")
        else:
            click.echo(f"  ⚠️  Output directory: {output_dir} (will be created)")
            
        data_dir = Path("./data")
        if data_dir.exists():
            click.echo(f"  ✅ Data directory: {data_dir}")
        else:
            click.echo(f"  ⚠️  Data directory: {data_dir} (will be created)")
            
    except Exception as e:
        click.echo(f"  ❌ Storage error: {e}")
        all_good = False
    
    # 5. Check LLM Connection (if configured)
    click.echo("\n🤖 LLM Integration:")
    try:
        if config.llm.provider == "ollama":
            import requests
            try:
                response = requests.get(f"{config.llm.base_url}/api/tags", timeout=5)
                if response.status_code == 200:
                    click.echo(f"  ✅ Ollama: Connected to {config.llm.base_url}")
                    if verbose:
                        models = response.json().get('models', [])
                        click.echo(f"     Available models: {len(models)}")
                else:
                    click.echo(f"  ❌ Ollama: Server responded with {response.status_code}")
                    all_good = False
            except requests.exceptions.RequestException as e:
                click.echo(f"  ❌ Ollama: Cannot connect to {config.llm.base_url}")
                if verbose:
                    click.echo(f"     Error: {e}")
                all_good = False
        else:
            click.echo(f"  ⚠️  LLM provider '{config.llm.provider}' not tested")
            
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