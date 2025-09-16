"""
Research Stream CLI Commands

This module provides CLI commands for managing Research Streams - persistent
research topics that use Zotero Collections and smart tagging.
"""

import logging
import click
from typing import Optional
from datetime import datetime

from ...services.research_stream_manager import ResearchStreamManager, ResearchStreamError
from ...storage.models.research_stream_models import RefreshFrequency, StreamStatus

logger = logging.getLogger(__name__)


@click.group(name='streams')
def streams_group():
    """Manage research streams for continuous literature monitoring"""
    pass


@streams_group.command('create')
@click.argument('name', required=True)
@click.argument('query', required=True)
@click.option('--description', '-d', help='Description of the research stream')
@click.option('--frequency', '-f', 
              type=click.Choice(['daily', 'weekly', 'monthly', 'manual']),
              default='weekly',
              help='How often to refresh the stream')
@click.option('--parent-collection', '-p', help='Parent collection key')
@click.option('--config', '-c', help='Path to configuration file')
def create_stream(name: str, query: str, description: Optional[str], 
                 frequency: str, parent_collection: Optional[str], 
                 config: Optional[str]):
    """
    Create a new research stream
    
    NAME: Human-readable name for the stream (e.g., "Neural Networks 2024")
    QUERY: Search query for finding papers (e.g., "neural networks transformer")
    """
    try:
        click.echo(f"🚀 Creating research stream: {name}")
        
        # Initialize manager
        manager = ResearchStreamManager(config)
        
        # Convert frequency
        refresh_freq = RefreshFrequency(frequency)
        
        # Create the stream
        stream = manager.create_stream(
            name=name,
            search_query=query,
            description=description,
            refresh_frequency=refresh_freq,
            parent_collection=parent_collection
        )
        
        click.echo("✅ Research stream created successfully!")
        click.echo(f"   📋 ID: {stream.id}")
        click.echo(f"   📁 Collection: {stream.collection_name}")
        if stream.collection_key:
            click.echo(f"   🔑 Collection Key: {stream.collection_key}")
        click.echo(f"   🔍 Query: {stream.search_criteria.query}")
        click.echo(f"   🔄 Frequency: {stream.refresh_frequency.value}")
        click.echo(f"   📅 Created: {stream.created_at.strftime('%Y-%m-%d %H:%M')}")
        
        # Ask if user wants to run initial update
        if click.confirm("Run initial update to populate the stream?"):
            click.echo("🔍 Running initial update...")
            result = manager.update_stream(stream.id, force=True)
            
            if result.success:
                click.echo(f"✅ Found {result.new_papers_found} papers")
            else:
                click.echo(f"⚠️  Update completed with issues: {result.errors}")
        
    except ResearchStreamError as e:
        click.echo(f"❌ Error creating stream: {e}", err=True)
        raise click.ClickException(str(e))
    except Exception as e:
        click.echo(f"❌ Unexpected error: {e}", err=True)
        raise click.ClickException(str(e))


@streams_group.command('list')
@click.option('--status', '-s', 
              type=click.Choice(['active', 'paused', 'archived']),
              help='Filter by status')
@click.option('--config', '-c', help='Path to configuration file')
def list_streams(status: Optional[str], config: Optional[str]):
    """List all research streams"""
    try:
        manager = ResearchStreamManager(config)
        
        # Filter by status if provided
        stream_status = StreamStatus(status) if status else None
        streams = manager.list_streams(stream_status)
        
        if not streams:
            click.echo("📭 No research streams found")
            return
        
        click.echo(f"📋 Found {len(streams)} research stream(s):")
        click.echo()
        
        for stream in streams:
            # Status emoji
            status_emoji = {
                StreamStatus.ACTIVE: "🟢",
                StreamStatus.PAUSED: "🟡", 
                StreamStatus.ARCHIVED: "🔴"
            }.get(stream.status, "❓")
            
            click.echo(f"{status_emoji} {stream.name} ({stream.id})")
            click.echo(f"   📁 Collection: {stream.collection_name}")
            click.echo(f"   🔍 Query: {stream.search_criteria.query}")
            click.echo(f"   📊 Papers: {stream.total_papers}")
            click.echo(f"   🔄 Frequency: {stream.refresh_frequency.value}")
            
            if stream.last_updated:
                click.echo(f"   📅 Last updated: {stream.last_updated.strftime('%Y-%m-%d %H:%M')}")
                
                if stream.is_due_for_update():
                    click.echo("   ⏰ Due for update")
            else:
                click.echo("   📅 Never updated")
            
            click.echo()
        
    except Exception as e:
        click.echo(f"❌ Error listing streams: {e}", err=True)
        raise click.ClickException(str(e))


@streams_group.command('update')
@click.argument('stream_id', required=False)
@click.option('--all', '-a', is_flag=True, help='Update all active streams')
@click.option('--force', '-f', is_flag=True, help='Force update even if not due')
@click.option('--refresh-cache', '-r', is_flag=True, help='Refresh cached entries with new metadata instead of using cache')
@click.option('--config', '-c', help='Path to configuration file')
def update_streams(stream_id: Optional[str], all: bool, force: bool, refresh_cache: bool, config: Optional[str]):
    """
    Update research streams to find new papers
    
    By default, uses cached metadata for known papers. Use --refresh-cache to update
    existing entries with latest information from sources.
    """
    try:
        manager = ResearchStreamManager(config)
        
        if all:
            # Update all active streams
            streams = manager.list_streams(StreamStatus.ACTIVE)
            
            if not streams:
                click.echo("📭 No active streams to update")
                return
            
            click.echo(f"🔄 Updating {len(streams)} active stream(s)...")
            
            total_new_papers = 0
            for stream in streams:
                if force or stream.is_due_for_update():
                    click.echo(f"   🔍 Updating {stream.name}...")
                    if refresh_cache:
                        click.echo(f"     🔄 Refreshing cached metadata...")
                    result = manager.update_stream(stream.id, force=force, refresh_cache=refresh_cache)
                    
                    if result.success:
                        total_new_papers += result.new_papers_found
                        click.echo(f"     ✅ Found {result.new_papers_found} new papers")
                    else:
                        click.echo(f"     ⚠️  Issues: {', '.join(result.errors)}")
                else:
                    click.echo(f"   ⏭️  Skipping {stream.name} (not due)")
            
            click.echo(f"🎉 Update complete! Found {total_new_papers} new papers total")
            
        elif stream_id:
            # Update specific stream
            stream = manager.get_stream(stream_id)
            if not stream:
                click.echo(f"❌ Stream not found: {stream_id}", err=True)
                raise click.ClickException("Stream not found")
            
            click.echo(f"🔄 Updating stream: {stream.name}")
            if refresh_cache:
                click.echo(f"🔄 Refreshing cached metadata...")
            result = manager.update_stream(stream_id, force=force, refresh_cache=refresh_cache)
            
            if result.success:
                click.echo(f"✅ Found {result.new_papers_found} new papers")
                click.echo(f"⏱️  Duration: {result.duration_seconds:.1f} seconds")
            else:
                click.echo(f"⚠️  Update issues:")
                for error in result.errors:
                    click.echo(f"   • {error}")
        else:
            click.echo("❌ Please specify a stream ID or use --all", err=True)
            raise click.ClickException("No stream specified")
        
    except Exception as e:
        click.echo(f"❌ Error updating streams: {e}", err=True)
        raise click.ClickException(str(e))


@streams_group.command('info')
@click.argument('stream_id', required=True)
@click.option('--config', '-c', help='Path to configuration file')
def stream_info(stream_id: str, config: Optional[str]):
    """Show detailed information about a research stream"""
    try:
        manager = ResearchStreamManager(config)
        stream = manager.get_stream(stream_id)
        
        if not stream:
            click.echo(f"❌ Stream not found: {stream_id}", err=True)
            raise click.ClickException("Stream not found")
        
        # Status emoji
        status_emoji = {
            StreamStatus.ACTIVE: "🟢",
            StreamStatus.PAUSED: "🟡",
            StreamStatus.ARCHIVED: "🔴"
        }.get(stream.status, "❓")
        
        click.echo(f"📋 Research Stream: {stream.name}")
        click.echo("=" * 50)
        click.echo(f"🆔 ID: {stream.id}")
        click.echo(f"{status_emoji} Status: {stream.status.value}")
        click.echo(f"📁 Collection: {stream.collection_name}")
        if stream.collection_key:
            click.echo(f"🔑 Collection Key: {stream.collection_key}")
        click.echo()
        
        click.echo("🔍 Search Configuration:")
        click.echo(f"   Query: {stream.search_criteria.query}")
        click.echo(f"   Max Results: {stream.search_criteria.max_results}")
        if stream.search_criteria.tags:
            click.echo(f"   Required Tags: {', '.join(stream.search_criteria.tags)}")
        if stream.search_criteria.exclude_tags:
            click.echo(f"   Excluded Tags: {', '.join(stream.search_criteria.exclude_tags)}")
        click.echo()
        
        click.echo("📊 Statistics:")
        click.echo(f"   Total Papers: {stream.total_papers}")
        click.echo(f"   New in Last Update: {stream.new_papers_last_update}")
        click.echo(f"   Refresh Frequency: {stream.refresh_frequency.value}")
        click.echo()
        
        click.echo("📅 Timeline:")
        click.echo(f"   Created: {stream.created_at.strftime('%Y-%m-%d %H:%M:%S')}")
        if stream.last_updated:
            click.echo(f"   Last Updated: {stream.last_updated.strftime('%Y-%m-%d %H:%M:%S')}")
            click.echo(f"   Next Update: {stream.next_update.strftime('%Y-%m-%d %H:%M:%S')}")
            
            if stream.is_due_for_update():
                click.echo("   ⏰ Due for update now!")
        else:
            click.echo("   Last Updated: Never")
        
        if stream.description:
            click.echo()
            click.echo(f"📝 Description: {stream.description}")
        
        click.echo()
        click.echo("🏷️  Smart Tags:")
        for tag in stream.smart_tags:
            click.echo(f"   • {tag.name} ({tag.category.value})")
        
    except Exception as e:
        click.echo(f"❌ Error getting stream info: {e}", err=True)
        raise click.ClickException(str(e))


@streams_group.command('summary')
@click.option('--config', '-c', help='Path to configuration file')
def streams_summary(config: Optional[str]):
    """Show summary of all research streams"""
    try:
        manager = ResearchStreamManager(config)
        summary = manager.get_summary()
        
        click.echo("📊 Research Streams Summary")
        click.echo("=" * 30)
        click.echo(f"📋 Total Streams: {summary.total_streams}")
        click.echo(f"🟢 Active Streams: {summary.active_streams}")
        click.echo(f"📄 Total Papers: {summary.total_papers}")
        click.echo(f"⏰ Streams Due for Update: {summary.streams_due_update}")
        
        if summary.last_global_update:
            click.echo(f"📅 Last Global Update: {summary.last_global_update.strftime('%Y-%m-%d %H:%M')}")
        else:
            click.echo("📅 Last Global Update: Never")
        
        if summary.streams_due_update > 0:
            click.echo()
            click.echo("💡 Tip: Run 'prisma streams update --all' to update all due streams")
        
    except Exception as e:
        click.echo(f"❌ Error getting summary: {e}", err=True)
        raise click.ClickException(str(e))


# Add the streams group to the main CLI when imported
__all__ = ['streams_group']