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
    - Internet connectivity
    - Web API credentials and access (the only backend prisma uses --
      see services/zotero.py; there is no local Zotero Desktop integration)
    """
    from ...connectivity import monitor as connectivity
    from ...services.zotero import check_web_api_reachable
    from ...utils.config import config

    click.echo("🔍 Checking Zotero integration status...\n")

    api_key = config.get('sources.zotero.api_key')
    library_id = config.get('sources.zotero.library_id')

    click.echo("🌐 Network Connectivity:")
    click.echo(f"   Internet: {'✅ Online' if connectivity.is_online else '❌ Offline'}")

    click.echo("\n🔗 Zotero Web API:")
    if api_key and library_id:
        click.echo("   Credentials: ✅ Configured")
        try:
            reachable = check_web_api_reachable(api_key, library_id)
            click.echo(f"   Access: {'✅ Available' if reachable else '❌ Unavailable'}")
        except Exception as e:
            click.echo(f"   Access: ❌ Error - {e}")
    else:
        click.echo("   Credentials: ⚠️  Not configured")
        click.echo("   Access: ❌ Unavailable")

    click.echo("\n✅ Zotero integration status check complete")


if __name__ == '__main__':
    zotero_group()