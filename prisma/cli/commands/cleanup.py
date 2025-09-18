"""
Zotero Database Cleanup CLI Commands

This module provides CLI commands for cleaning up duplicates and managing
the local Zotero database through various maintenance operations.
"""

import logging
import click
from typing import Dict, List, Optional, Tuple, Set
from datetime import datetime
import json
from pathlib import Path

from ...integrations.zotero.local_api_client import ZoteroLocalAPIClient, ZoteroLocalAPIConfig
from ...integrations.zotero.client import ZoteroClient, ZoteroAPIConfig, ZoteroClientError
# from ...integrations.zotero.sqlite_client import ZoteroSQLiteClient, ZoteroSQLiteConfig, ZoteroSQLiteError
from ...storage.models.zotero_models import ZoteroItem
from ...utils.config import config

logger = logging.getLogger(__name__)


class DuplicateDetector:
    """Detects duplicate items in Zotero library using various matching strategies"""
    
    def __init__(self, client: ZoteroLocalAPIClient):
        self.client = client
        
    def _normalize_title(self, title: str) -> str:
        """Normalize title for comparison by removing common variations"""
        if not title:
            return ""
        
        # Convert to lowercase and strip whitespace
        normalized = title.lower().strip()
        
        # Remove common punctuation and extra spaces
        import re
        normalized = re.sub(r'[^\w\s]', ' ', normalized)
        normalized = re.sub(r'\s+', ' ', normalized)
        
        return normalized.strip()
    
    def _normalize_doi(self, doi: str) -> str:
        """Normalize DOI for comparison"""
        if not doi:
            return ""
        
        # Remove common prefixes and normalize
        doi = doi.lower().strip()
        if doi.startswith('doi:'):
            doi = doi[4:]
        if doi.startswith('http://dx.doi.org/'):
            doi = doi[18:]
        if doi.startswith('https://dx.doi.org/'):
            doi = doi[19:]
        if doi.startswith('https://doi.org/'):
            doi = doi[16:]
        
        return doi.strip()
    
    def _extract_authors_string(self, item: ZoteroItem) -> str:
        """Extract author information as a normalized string"""
        try:
            authors = []
            if hasattr(item, 'raw_data') and item.raw_data:
                data = item.raw_data.get('data', {})
                creators = data.get('creators', [])
                for creator in creators:
                    if creator.get('creatorType') == 'author':
                        last_name = creator.get('lastName', '').strip()
                        first_name = creator.get('firstName', '').strip()
                        if last_name:
                            authors.append(f"{last_name}, {first_name}".strip(', '))
            
            return ' | '.join(sorted(authors))
        except Exception:
            return ""
    
    def find_duplicates(self, items: List[ZoteroItem]) -> Dict[str, List[ZoteroItem]]:
        """
        Find duplicate items using multiple matching strategies
        
        Returns:
            Dict mapping duplicate group ID to list of duplicate items
        """
        duplicates = {}
        processed_items = set()
        
        click.echo(f"🔍 Analyzing {len(items)} items for duplicates...")
        
        for i, item in enumerate(items):
            if item.key in processed_items:
                continue
                
            # Find all potential duplicates for this item
            group = [item]
            processed_items.add(item.key)
            
            for j, other_item in enumerate(items[i+1:], i+1):
                if other_item.key in processed_items:
                    continue
                    
                if self._are_duplicates(item, other_item):
                    group.append(other_item)
                    processed_items.add(other_item.key)
            
            # Only consider it a duplicate group if we have more than one item
            if len(group) > 1:
                group_id = f"group_{len(duplicates) + 1}"
                duplicates[group_id] = group
                
        return duplicates
    
    def _are_duplicates(self, item1: ZoteroItem, item2: ZoteroItem) -> bool:
        """Check if two items are duplicates using various matching strategies"""
        
        # Strategy 1: DOI match (highest priority)
        doi1 = self._get_item_doi(item1)
        doi2 = self._get_item_doi(item2)
        
        if doi1 and doi2:
            normalized_doi1 = self._normalize_doi(doi1)
            normalized_doi2 = self._normalize_doi(doi2)
            if normalized_doi1 == normalized_doi2:
                return True
        
        # Strategy 2: Exact title match
        title1 = self._get_item_title(item1)
        title2 = self._get_item_title(item2)
        
        if title1 and title2:
            normalized_title1 = self._normalize_title(title1)
            normalized_title2 = self._normalize_title(title2)
            if normalized_title1 == normalized_title2 and len(normalized_title1) > 10:
                # Additional validation for title matches
                return self._validate_title_match(item1, item2)
        
        # Strategy 3: ISBN match for books
        isbn1 = self._get_item_isbn(item1)
        isbn2 = self._get_item_isbn(item2)
        
        if isbn1 and isbn2 and isbn1 == isbn2:
            return True
            
        return False
    
    def _validate_title_match(self, item1: ZoteroItem, item2: ZoteroItem) -> bool:
        """Additional validation for title-based matches"""
        # Check if publication years are similar (within 1 year)
        year1 = self._get_item_year(item1)
        year2 = self._get_item_year(item2)
        
        if year1 and year2:
            try:
                year_diff = abs(int(year1) - int(year2))
                if year_diff > 1:
                    return False
            except (ValueError, TypeError):
                pass
        
        # Check if authors overlap significantly
        authors1 = self._extract_authors_string(item1)
        authors2 = self._extract_authors_string(item2)
        
        if authors1 and authors2:
            # Simple overlap check - if any author matches
            authors1_set = set(authors1.lower().split(' | '))
            authors2_set = set(authors2.lower().split(' | '))
            overlap = authors1_set.intersection(authors2_set)
            
            # At least one author should match for title-based duplicates
            if not overlap:
                return False
        
        return True
    
    def _get_item_doi(self, item: ZoteroItem) -> Optional[str]:
        """Extract DOI from Zotero item"""
        try:
            if hasattr(item, 'doi') and item.doi:
                return item.doi
            
            if hasattr(item, 'raw_data') and item.raw_data:
                data = item.raw_data.get('data', {})
                return data.get('DOI') or data.get('doi')
                
        except Exception:
            pass
        return None
    
    def _get_item_title(self, item: ZoteroItem) -> Optional[str]:
        """Extract title from Zotero item"""
        try:
            if hasattr(item, 'title') and item.title:
                return item.title
                
            if hasattr(item, 'raw_data') and item.raw_data:
                data = item.raw_data.get('data', {})
                return data.get('title')
                
        except Exception:
            pass
        return None
    
    def _get_item_year(self, item: ZoteroItem) -> Optional[str]:
        """Extract publication year from Zotero item"""
        try:
            if hasattr(item, 'raw_data') and item.raw_data:
                data = item.raw_data.get('data', {})
                date_str = data.get('date', '') or data.get('year', '')
                
                # Extract year from various date formats
                import re
                year_match = re.search(r'(\d{4})', str(date_str))
                if year_match:
                    return year_match.group(1)
                    
        except Exception:
            pass
        return None
    
    def _get_item_isbn(self, item: ZoteroItem) -> Optional[str]:
        """Extract ISBN from Zotero item"""
        try:
            if hasattr(item, 'raw_data') and item.raw_data:
                data = item.raw_data.get('data', {})
                return data.get('ISBN') or data.get('isbn')
                
        except Exception:
            pass
        return None


@click.group(name='cleanup')
def cleanup_group():
    """Database cleanup and maintenance operations"""
    pass


@cleanup_group.command('duplicates')
@click.option('--collection', '-c', help='Specific collection to clean (by name or key)')
@click.option('--dry-run', '-n', is_flag=True, help='Show what would be deleted without deleting')
@click.option('--auto-select', '-a', is_flag=True, help='Automatically select which duplicates to keep (keep oldest)')
@click.option('--export-report', '-e', help='Export duplicate analysis to JSON file')
@click.option('--verbose', '-v', is_flag=True, help='Show detailed information about each duplicate')
def cleanup_duplicates(collection: Optional[str], dry_run: bool, auto_select: bool, 
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
    try:
        # Initialize Zotero clients
        # Use local API for reading (faster, more reliable)
        local_config = ZoteroLocalAPIConfig(
            server_url=config.get('sources.zotero.server_url', 'http://127.0.0.1:23119'),
            timeout=30.0,
            user_id="0"
        )
        local_client = ZoteroLocalAPIClient(local_config)
        
        # Initialize web API client for deletion
        web_client = None
        
        try:
            api_key = config.get('sources.zotero.api_key')
            library_id = config.get('sources.zotero.library_id')
            library_type = config.get('sources.zotero.library_type', 'user')
            
            if api_key and library_id:
                web_config = ZoteroAPIConfig(
                    api_key=api_key,
                    library_id=library_id,
                    library_type=library_type,
                    api_version=3
                )
                web_client = ZoteroClient(web_config)
                click.echo("✅ Web API available for deletion operations")
            else:
                click.echo("⚠️  Web API credentials not found - deletion will be disabled")
        except Exception as e:
            click.echo(f"⚠️  Web API not available: {e}")
        
        deletion_enabled = web_client is not None
        if deletion_enabled:
            click.echo("ℹ️  Duplicate detection and deletion enabled")
        else:
            click.echo("ℹ️  Duplicate detection enabled, automatic deletion disabled")
        
        click.echo("🧹 Starting duplicate cleanup process...")
        
        # Get all items (or from specific collection)
        if collection:
            click.echo(f"📁 Analyzing collection: {collection}")
            # TODO: Add collection-specific search
            search_result = local_client.search_items("")
        else:
            click.echo("📚 Analyzing entire library...")
            search_result = local_client.search_items("")
        
        if not search_result.items:
            click.echo("ℹ️  No items found to analyze")
            return
        
        # Initialize duplicate detector
        detector = DuplicateDetector(local_client)
        
        # Find duplicates
        duplicates = detector.find_duplicates(search_result.items)
        
        if not duplicates:
            click.echo("✅ No duplicates found! Your library is clean.")
            return
        
        # Report findings
        total_duplicates = sum(len(group) for group in duplicates.values())
        total_groups = len(duplicates)
        items_to_remove = total_duplicates - total_groups  # Keep one from each group
        
        click.echo(f"\n📊 Duplicate Analysis Results:")
        click.echo(f"   Found {total_groups} duplicate groups")
        click.echo(f"   Total duplicate items: {total_duplicates}")
        click.echo(f"   Items that can be removed: {items_to_remove}")
        
        # Export report if requested
        if export_report:
            _export_duplicate_report(duplicates, export_report)
            click.echo(f"📄 Report exported to: {export_report}")
        
        # Show duplicates and handle selection
        items_to_delete = []
        
        for group_id, group in duplicates.items():
            click.echo(f"\n🔍 {group_id.upper()} - {len(group)} duplicates:")
            
            for i, item in enumerate(group):
                title = detector._get_item_title(item) or "No Title"
                doi = detector._get_item_doi(item)
                year = detector._get_item_year(item)
                
                click.echo(f"  {i+1}. {title[:60]}{'...' if len(title) > 60 else ''}")
                if verbose:
                    click.echo(f"     Key: {item.key}")
                    if doi:
                        click.echo(f"     DOI: {doi}")
                    if year:
                        click.echo(f"     Year: {year}")
                    if hasattr(item, 'date_added'):
                        click.echo(f"     Added: {item.date_added}")
            
            # Select which items to delete
            if auto_select:
                # Keep the first (oldest) item, delete the rest - oldest is likely the original
                to_delete = group[1:]  # Delete all but the first one
                keep_item = group[0]
                keep_title = detector._get_item_title(keep_item) or "No Title"
                click.echo(f"  ✅ Auto-selected to keep oldest: {keep_title[:50]}...")
            elif not dry_run:
                # Interactive selection
                click.echo("  Which item should be KEPT? (others will be deleted)")
                while True:
                    try:
                        choice = click.prompt("  Enter number (1-{})".format(len(group)), type=int)
                        if 1 <= choice <= len(group):
                            keep_index = choice - 1
                            to_delete = group[:keep_index] + group[keep_index+1:]
                            break
                        else:
                            click.echo("  Invalid choice. Please try again.")
                    except click.Abort:
                        click.echo("\n🚫 Cleanup cancelled by user")
                        return
            else:
                # Dry run - just show what would be deleted
                to_delete = group[:-1]  # Would delete all but the last one
            
            items_to_delete.extend(to_delete)
        
        # Show summary
        click.echo(f"\n📋 Summary:")
        click.echo(f"   Items to delete: {len(items_to_delete)}")
        click.echo(f"   Items to keep: {total_groups}")
        
        if dry_run:
            click.echo("\n🔍 DRY RUN - No items were actually deleted")
            if verbose:
                click.echo("\nItems that WOULD be deleted:")
                for item in items_to_delete:
                    title = detector._get_item_title(item) or "No Title"
                    click.echo(f"  - {title} (Key: {item.key})")
        else:
            # Confirm deletion
            if items_to_delete:
                click.echo(f"\n⚠️  This will permanently delete {len(items_to_delete)} items!")
                if not click.confirm("Do you want to proceed?"):
                    click.echo("🚫 Cleanup cancelled")
                    return
                
                # Perform deletion
                success_count = 0
                
                if web_client:
                    click.echo(f"\n🗑️  Deleting {len(items_to_delete)} duplicate items...")
                    
                    for item in items_to_delete:
                        title = detector._get_item_title(item) or "No title"
                        try:
                            if web_client.delete_item(item.key):
                                success_count += 1
                                click.echo(f"   ✅ Deleted: {title}")
                            else:
                                click.echo(f"   ❌ Failed to delete: {title} (Key: {item.key})")
                        except Exception as e:
                            click.echo(f"   ❌ Error deleting {title}: {e}")
                    
                    click.echo(f"\n✅ Successfully deleted {success_count}/{len(items_to_delete)} duplicate items")
                else:
                    click.echo(f"\n⚠️  Web API not available - manual deletion required")
                    click.echo(f"   Items identified for manual deletion:")
                    
                    for item in items_to_delete:
                        title = detector._get_item_title(item) or "No title"
                        click.echo(f"   🗑️  {title} (Key: {item.key})")
                    
                    click.echo(f"\n💡 Please delete these {len(items_to_delete)} duplicate items manually in Zotero desktop")
            else:
                click.echo("\n✅ No items to delete")
    
    except Exception as e:
        click.echo(f"❌ Error during cleanup: {e}", err=True)
        raise click.ClickException(str(e))


def _export_duplicate_report(duplicates: Dict[str, List], export_file: str):
    """Export duplicate analysis to JSON file"""
    report_data = {
        'analysis_date': datetime.now().isoformat(),
        'total_groups': len(duplicates),
        'total_duplicates': sum(len(group) for group in duplicates.values()),
        'groups': {}
    }
    
    for group_id, group in duplicates.items():
        group_data = []
        for item in group:
            # Use static methods for data extraction without requiring client
            item_data = {
                'key': item.key,
                'title': _get_item_title_safe(item),
                'doi': _get_item_doi_safe(item),
                'year': _get_item_year_safe(item),
                'authors': _extract_authors_string_safe(item)
            }
            group_data.append(item_data)
        
        report_data['groups'][group_id] = group_data
    
    with open(export_file, 'w', encoding='utf-8') as f:
        json.dump(report_data, f, indent=2, ensure_ascii=False)


@cleanup_group.command('stats')
@click.option('--collection', '-c', help='Specific collection to analyze')
def library_stats(collection: Optional[str]):
    """
    Show detailed statistics about your Zotero library
    
    Provides insights into:
    - Total item counts by type
    - Items without DOI
    - Items without abstracts
    - Potential quality issues
    """
    try:
        # Initialize Zotero client
        zotero_config = ZoteroLocalAPIConfig(
            server_url=config.get('sources.zotero.server_url', 'http://127.0.0.1:23119'),
            timeout=30.0,
            user_id="0"
        )
        client = ZoteroLocalAPIClient(zotero_config)
        
        click.echo("📊 Analyzing library statistics...")
        
        # Get all items
        search_result = client.search_items("")
        
        if not search_result.items:
            click.echo("ℹ️  No items found in library")
            return
        
        items = search_result.items
        total_items = len(items)
        
        # Analyze by item type
        item_types = {}
        items_without_doi = 0
        items_without_abstract = 0
        items_without_authors = 0
        
        for item in items:
            # Count by type
            item_type = getattr(item, 'item_type', 'unknown')
            item_types[item_type] = item_types.get(item_type, 0) + 1
            
            # Check for missing metadata
            if not _has_doi(item):
                items_without_doi += 1
            
            if not _has_abstract(item):
                items_without_abstract += 1
                
            if not _has_authors(item):
                items_without_authors += 1
        
        # Display statistics
        click.echo(f"\n📚 Library Overview:")
        click.echo(f"   Total items: {total_items}")
        
        click.echo(f"\n📄 Item Types:")
        for item_type, count in sorted(item_types.items(), key=lambda x: x[1], reverse=True):
            percentage = (count / total_items) * 100
            click.echo(f"   {item_type}: {count} ({percentage:.1f}%)")
        
        click.echo(f"\n🔍 Metadata Quality:")
        click.echo(f"   Items without DOI: {items_without_doi} ({(items_without_doi/total_items)*100:.1f}%)")
        click.echo(f"   Items without abstract: {items_without_abstract} ({(items_without_abstract/total_items)*100:.1f}%)")
        click.echo(f"   Items without authors: {items_without_authors} ({(items_without_authors/total_items)*100:.1f}%)")
        
        # Quality score
        quality_score = 100 - ((items_without_doi + items_without_abstract + items_without_authors) / (total_items * 3) * 100)
        click.echo(f"\n⭐ Overall Quality Score: {quality_score:.1f}%")
        
        if quality_score < 70:
            click.echo("💡 Consider using 'prisma cleanup missing-metadata' to improve quality")
        
    except Exception as e:
        click.echo(f"❌ Error analyzing library: {e}", err=True)
        raise click.ClickException(str(e))


def _has_doi(item) -> bool:
    """Check if item has a DOI"""
    try:
        if hasattr(item, 'doi') and item.doi:
            return True
        if hasattr(item, 'raw_data') and item.raw_data:
            data = item.raw_data.get('data', {})
            return bool(data.get('DOI') or data.get('doi'))
    except Exception:
        pass
    return False


def _has_abstract(item) -> bool:
    """Check if item has an abstract"""
    try:
        if hasattr(item, 'raw_data') and item.raw_data:
            data = item.raw_data.get('data', {})
            abstract = data.get('abstractNote', '') or data.get('abstract', '')
            return bool(abstract and len(abstract.strip()) > 50)
    except Exception:
        pass
    return False


def _has_authors(item) -> bool:
    """Check if item has authors"""
    try:
        if hasattr(item, 'raw_data') and item.raw_data:
            data = item.raw_data.get('data', {})
            creators = data.get('creators', [])
            authors = [c for c in creators if c.get('creatorType') == 'author']
            return len(authors) > 0
    except Exception:
        pass
    return False


def _get_item_title_safe(item) -> Optional[str]:
    """Safe title extraction for export"""
    try:
        if hasattr(item, 'title') and item.title:
            return item.title
        if hasattr(item, 'raw_data') and item.raw_data:
            data = item.raw_data.get('data', {})
            return data.get('title')
    except Exception:
        pass
    return None


def _get_item_doi_safe(item) -> Optional[str]:
    """Safe DOI extraction for export"""
    try:
        if hasattr(item, 'doi') and item.doi:
            return item.doi
        if hasattr(item, 'raw_data') and item.raw_data:
            data = item.raw_data.get('data', {})
            return data.get('DOI') or data.get('doi')
    except Exception:
        pass
    return None


def _get_item_year_safe(item) -> Optional[str]:
    """Safe year extraction for export"""
    try:
        if hasattr(item, 'raw_data') and item.raw_data:
            data = item.raw_data.get('data', {})
            date_str = data.get('date', '') or data.get('year', '')
            
            import re
            year_match = re.search(r'(\d{4})', str(date_str))
            if year_match:
                return year_match.group(1)
    except Exception:
        pass
    return None


def _extract_authors_string_safe(item) -> str:
    """Safe author extraction for export"""
    try:
        authors = []
        if hasattr(item, 'raw_data') and item.raw_data:
            data = item.raw_data.get('data', {})
            creators = data.get('creators', [])
            for creator in creators:
                if creator.get('creatorType') == 'author':
                    last_name = creator.get('lastName', '').strip()
                    first_name = creator.get('firstName', '').strip()
                    if last_name:
                        authors.append(f"{last_name}, {first_name}".strip(', '))
        
        return ' | '.join(sorted(authors))
    except Exception:
        return ""


if __name__ == '__main__':
    cleanup_group()