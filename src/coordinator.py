"""
Prisma Coordinator - Main orchestration logic for literature reviews.
MVP: Fast, simple, working implementation.
"""

import json
from pathlib import Path
from typing import Dict, List, Any

from agents.search_agent import SearchAgent
from agents.analysis_agent import AnalysisAgent  
from agents.report_agent import ReportAgent


class PrismaCoordinator:
    """Main coordinator for orchestrating literature review pipeline."""
    
    def __init__(self, debug: bool = False):
        self.debug = debug
        self.search_agent = SearchAgent()
        self.analysis_agent = AnalysisAgent()
        self.report_agent = ReportAgent()
        
        if debug:
            print("[DEBUG] Coordinator initialized")
    
    def run_review(self, config: Dict[str, Any]) -> Dict[str, Any]:
        """
        Run complete literature review pipeline.
        
        Args:
            config: Review configuration with topic, sources, limits, etc.
            
        Returns:
            Review results with success status and metadata
        """
        try:
            # Step 1: Search for papers
            if self.debug:
                print(f"[DEBUG] Searching for papers on: {config['topic']}")
            
            search_results = self.search_agent.search(
                query=config['topic'],
                sources=config['sources'],
                limit=config['limit']
            )
            
            if not search_results['papers']:
                return {
                    'success': False,
                    'error': 'No papers found for the given topic',
                    'papers_analyzed': 0
                }
            
            if self.debug:
                print(f"[DEBUG] Found {len(search_results['papers'])} papers")
            
            # Step 2: Analyze papers
            if self.debug:
                print("[DEBUG] Analyzing papers...")
            
            analysis_results = self.analysis_agent.analyze(
                papers=search_results['papers']
            )
            
            # Step 3: Generate report
            if self.debug:
                print("[DEBUG] Generating report...")
            
            report = self.report_agent.generate(
                summaries=analysis_results['summaries'],
                config=config
            )
            
            # Step 4: Save to file
            output_path = Path(config['output_file'])
            with open(output_path, 'w', encoding='utf-8') as f:
                f.write(report['content'])
            
            return {
                'success': True,
                'papers_analyzed': len(search_results['papers']),
                'authors_found': analysis_results.get('author_count', 0),
                'output_file': str(output_path),
                'metadata': report['metadata']
            }
            
        except Exception as e:
            if self.debug:
                import traceback
                traceback.print_exc()
            
            return {
                'success': False,
                'error': str(e),
                'papers_analyzed': 0
            }
    
    def get_status(self) -> Dict[str, str]:
        """Get current system status."""
        return {
            'version': '0.1.0-mvp',
            'status': 'ready',
            'agents': {
                'search': 'initialized',
                'analysis': 'initialized', 
                'report': 'initialized'
            }
        }


# Legacy class alias for backward compatibility
Coordinator = PrismaCoordinator