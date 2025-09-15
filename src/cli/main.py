#!/usr/bin/env python3
"""
Prisma CLI - Fast Literature Review Tool
MVP: Get working in 7 days
"""

import argparse
import sys
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from coordinator import PrismaCoordinator
from utils.config import config


def main():
    """Main CLI entry point"""
    parser = argparse.ArgumentParser(
        description="Prisma - Automated Literature Review Tool",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python -m src.cli.main --topic "machine learning" --output "ml_review.md"
  python -m src.cli.main --topic "climate change" --sources "arxiv" --limit 20
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
        "--include-authors",
        action="store_true",
        help="Include author analysis and research directory"
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
    
    # Apply config defaults to args
    if args.sources is None:
        args.sources = ','.join(search_config['sources'])
    
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
            'include_authors': args.include_authors
        }
        
        result = coordinator.run_review(review_config)
        
        if result['success']:
            print(f"✅ Review completed successfully!")
            print(f"📄 Report saved to: {output_path}")
            print(f"📊 Papers analyzed: {result['papers_analyzed']}")
            if args.include_authors:
                print(f"👥 Authors identified: {result.get('authors_found', 0)}")
        else:
            print(f"❌ Review failed: {result['error']}")
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