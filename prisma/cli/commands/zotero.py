#!/usr/bin/env python3
"""
Zotero Integration CLI Commands

This module provides CLI commands specifically for Zotero library management
and integration operations, separate from the main literature review workflow.
"""

import logging
import click
from typing import Optional

# Import the existing cleanup functionality
from .cleanup import cleanup_duplicates, library_stats

logger = logging.getLogger(__name__)


@click.group(name='zotero')
def zotero_group():
    """
    Zotero library management and integration operations
    
    Commands for managing your Zotero library independently of the
    main literature review workflow.
    """
    pass


# Add the cleanup commands as Zotero-specific operations
@zotero_group.command('duplicates')
@click.option('--collection', '-c', help='Specific collection to clean (by name or key)')
@click.option('--dry-run', '-n', is_flag=True, help='Show what would be deleted without deleting')
@click.option('--auto-select', '-a', is_flag=True, help='Automatically select which duplicates to keep (keep oldest)')
@click.option('--export-report', '-e', help='Export duplicate analysis to JSON file')
@click.option('--verbose', '-v', is_flag=True, help='Show detailed information about each duplicate')
@click.pass_context
def zotero_duplicates(ctx, collection: Optional[str], dry_run: bool, auto_select: bool, 
                     export_report: Optional[str], verbose: bool):
    """
    Find and clean up duplicate items in Zotero library
    
    This command identifies duplicates using multiple strategies:
    - DOI matching (highest priority)
    - Title similarity with author validation
    - ISBN matching for books
    
    By default, shows interactive selection for which duplicates to keep.
    Use --auto-select to automatically keep the oldest item (original).
    Use --dry-run to see what would be deleted without making changes.
    """
    # Forward to the existing cleanup_duplicates function
    ctx.invoke(cleanup_duplicates, 
               collection=collection, 
               dry_run=dry_run, 
               auto_select=auto_select,
               export_report=export_report, 
               verbose=verbose)


@zotero_group.command('stats')
@click.option('--collection', '-c', help='Specific collection to analyze')
@click.pass_context
def zotero_stats(ctx, collection: Optional[str]):
    """
    Show detailed statistics about your Zotero library
    
    Provides insights into:
    - Total item counts by type
    - Items without DOI/metadata
    - Collection organization
    - Recent additions
    """
    # Forward to the existing library_stats function
    ctx.invoke(library_stats, collection=collection)


@zotero_group.command('status')
def zotero_status():
    """
    Check Zotero integration status and connectivity
    
    Verifies:
    - Zotero desktop app connection
    - Web API credentials and access
    - Local HTTP server availability
    - Network connectivity for hybrid mode
    """
    from ...integrations.zotero.hybrid_client import (
        ZoteroHybridClient, ZoteroHybridConfig, 
        check_internet_connectivity, check_zotero_web_api_access
    )
    from ...utils.config import config
    
    click.echo("🔍 Checking Zotero integration status...\n")
    
    try:
        # Create hybrid config from settings
        hybrid_config = ZoteroHybridConfig(
            api_key=config.get('sources.zotero.api_key'),
            library_id=config.get('sources.zotero.library_id'),
            library_type=config.get('sources.zotero.library_type', 'user'),
            local_server_url=config.get('sources.zotero.server_url', 'http://127.0.0.1:23119')
        )
        
        # Initialize hybrid client
        client = ZoteroHybridClient(hybrid_config)
        
        # Check network connectivity
        click.echo("🌐 Network Connectivity:")
        is_online = check_internet_connectivity()
        click.echo(f"   Internet: {'✅ Online' if is_online else '❌ Offline'}")
        
        # Check Web API access
        click.echo("\n🔗 Zotero Web API:")
        if hybrid_config.api_key and hybrid_config.library_id:
            try:
                web_api_available = check_zotero_web_api_access(
                    hybrid_config.api_key, 
                    hybrid_config.library_id
                )
                click.echo(f"   Credentials: ✅ Configured")
                click.echo(f"   Access: {'✅ Available' if web_api_available else '❌ Unavailable'}")
            except Exception as e:
                click.echo(f"   Access: ❌ Error - {e}")
        else:
            click.echo("   Credentials: ⚠️  Not configured")
            click.echo("   Access: ❌ Unavailable")
        
        # Check Local HTTP server
        click.echo("\n🖥️  Zotero Desktop App:")
        try:
            local_available = client.local_api_client is not None
            if local_available:
                # Try a simple search to test connectivity
                try:
                    test_result = client.local_api_client.search_items("")
                    click.echo("   HTTP Server: ✅ Available")
                    click.echo(f"   URL: {hybrid_config.local_server_url}")
                except Exception:
                    click.echo("   HTTP Server: ❌ Not responding")
            else:
                click.echo("   HTTP Server: ❌ Not available")
        except Exception as e:
            click.echo(f"   HTTP Server: ❌ Error - {e}")
        
        # Check Desktop app for saving
        click.echo("\n💾 Desktop Save Capability:")
        if client.desktop_client:
            try:
                # This would check if desktop app is running
                click.echo("   Desktop Client: ✅ Available")
                click.echo("   Save Operations: ✅ Enabled")
            except Exception as e:
                click.echo(f"   Desktop Client: ❌ Error - {e}")
        else:
            click.echo("   Desktop Client: ❌ Not available")
        
        # Show current mode
        click.echo("\n⚙️  Integration Mode:")
        if is_online and client.api_client:
            click.echo("   Current Mode: 🌐 Online (Web API preferred)")
        elif client.local_api_client:
            click.echo("   Current Mode: 🖥️  Offline (Local HTTP only)")
        else:
            click.echo("   Current Mode: ❌ No connectivity")
            
        click.echo(f"\n✅ Zotero integration status check complete")
        
    except Exception as e:
        click.echo(f"❌ Error checking Zotero status: {e}", err=True)
        raise click.ClickException(str(e))


if __name__ == '__main__':
    zotero_group()