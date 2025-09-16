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
        from coordinator import PrismaCoordinator
        from utils.config import ConfigLoader
        
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


if __name__ == '__main__':
    cli()