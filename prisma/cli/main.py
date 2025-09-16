#!/usr/bin/env python3
"""
Prisma CLI - Fast Literature Review Tool
MVP: Get working in 7 days
"""

import argparse
import sys
from pathlib import Path

# Add prisma package to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from ..coordinator import PrismaCoordinator
from ..utils.config import config


def main():
    """Main CLI entry point"""
    parser = argparse.ArgumentParser(
        description="Prisma - Automated Literature Review Tool",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  poetry run prisma --topic "machine learning" --output "ml_review.md"
  poetry run prisma --topic "climate change" --sources "arxiv" --limit 20
  poetry run prisma --topic "neural networks" --zotero --include-authors
  poetry run prisma --topic "deep learning" --zotero-only --zotero-collections "AI Papers,ML Research"
  poetry run prisma --topic "transformers" --zotero-recent 2 --limit 50
        """
    )
    
    parser.add_argument(
        "--topic", 
        required=True,
        help="Research topic to search for"
    )
    
    parser.add_argument(
        "--sources", 
        default=None,
        help="Data sources (default: from config). Options: arxiv,pubmed,scholar"
    )
    
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Maximum number of papers to analyze (default: from config)"
    )
    
    parser.add_argument(
        "--output",
        default=None,
        help="Output file path (default: from config output directory)"
    )
    
    parser.add_argument(
        "--stream",
        default=None,
        help="Research stream name (used for Zotero collection and tagging)"
    )
    
    parser.add_argument(
        "--include-authors",
        action="store_true",
        help="Include author analysis and research directory"
    )
    
    # Zotero integration options
    parser.add_argument(
        "--zotero",
        action="store_true",
        help="Include Zotero library search in addition to other sources"
    )
    
    parser.add_argument(
        "--zotero-only",
        action="store_true",
        help="Search only in Zotero library (ignores --sources)"
    )
    
    parser.add_argument(
        "--zotero-collections",
        default=None,
        help="Comma-separated list of Zotero collection names or keys to search"
    )
    
    parser.add_argument(
        "--zotero-recent",
        type=int,
        default=None,
        metavar="YEARS",
        help="Include papers from Zotero added in the last N years"
    )

    parser.add_argument(
        "--debug",
        action="store_true",
        help="Enable debug output"
    )

    args = parser.parse_args()
    
    # Get configuration defaults
    search_config = config.get_search_config()
    output_config = config.get_output_config()
    zotero_config = config.get_zotero_config()
    
    # Validate Zotero options
    if (args.zotero or args.zotero_only or args.zotero_collections or args.zotero_recent):
        if not config.has_zotero_credentials():
            print("❌ Error: Zotero integration requested but not configured.")
            print("Please set up Zotero API credentials in your config file.")
            print("Required: sources.zotero.api_key and sources.zotero.library_id")
            sys.exit(1)
    
    # Apply config defaults to args
    if args.sources is None:
        args.sources = ','.join(search_config['sources'])
    
    # Handle Zotero-only mode
    if args.zotero_only:
        args.sources = 'zotero'
    elif args.zotero:
        # Add zotero to existing sources
        sources_list = args.sources.split(',')
        if 'zotero' not in sources_list:
            sources_list.append('zotero')
        args.sources = ','.join(sources_list)
    
    if args.limit is None:
        args.limit = search_config['default_limit']
    
    if args.output is None:
        topic_safe = args.topic.replace(' ', '_').replace('/', '_')
        args.output = f"{output_config['directory']}/literature_review_{topic_safe}.md"
    
    # Ensure output goes to outputs directory
    output_path = Path(args.output)
    if not output_path.is_absolute() and not str(output_path).startswith('outputs/'):
        output_path = Path(output_config['directory']) / output_path.name
    
    # Create outputs directory if it doesn't exist
    output_path.parent.mkdir(exist_ok=True)
    
    # Print banner
    print("🔬 Prisma Literature Review Tool")
    print("=" * 40)
    print(f"Topic: {args.topic}")
    print(f"Sources: {args.sources}")
    print(f"Papers: {args.limit}")
    print(f"Output: {output_path}")
    print()
    
    # Initialize coordinator
    coordinator = PrismaCoordinator(debug=args.debug)
    
    # Run literature review
    try:
        print("🔍 Starting literature review...")
        
        review_config = {
            'topic': args.topic,
            'sources': args.sources.split(','),
            'limit': args.limit,
            'output_file': str(output_path),
            'stream_name': args.stream,
            'include_authors': args.include_authors,
            'zotero_collections': args.zotero_collections.split(',') if args.zotero_collections else None,
            'zotero_recent_years': args.zotero_recent
        }
        
        result = coordinator.run_review(review_config)
        
        if result.success:
            print(f"✅ Review completed successfully!")
            print(f"📄 Report saved to: {result.output_file}")
            print(f"📊 Papers analyzed: {result.papers_analyzed}")
            if args.include_authors:
                print(f"👥 Authors identified: {result.authors_found}")
        else:
            print(f"❌ Review failed")
            if result.errors:
                for error in result.errors:
                    print(f"   Error: {error}")
            sys.exit(1)
            
    except KeyboardInterrupt:
        print("\n⏹️  Review cancelled by user")
        sys.exit(1)
    except Exception as e:
        print(f"💥 Unexpected error: {e}")
        if args.debug:
            import traceback
            traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()