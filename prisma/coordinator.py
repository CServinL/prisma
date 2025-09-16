"""
Prisma Coordinator - Main orchestration logic for literature reviews.
MVP: Fast, simple, working implementation.
"""

import json
from pathlib import Path
from typing import Dict, List, Any
import time

from .agents.search_agent import SearchAgent
from .agents.analysis_agent import AnalysisAgent  
from .agents.report_agent import ReportAgent
from .storage.models.agent_models import CoordinatorResult


class PrismaCoordinator:
    """Main coordinator for orchestrating literature review pipeline."""
    
    def __init__(self, debug: bool = False):
        self.debug = debug
        self.search_agent = SearchAgent()
        self.analysis_agent = AnalysisAgent()
        self.report_agent = ReportAgent()
        
        if debug:
            print("[DEBUG] Coordinator initialized")
    
    def run_review(self, config: Dict[str, Any]) -> CoordinatorResult:
        """
        Run complete literature review pipeline.
        
        Args:
            config: Review configuration with topic, sources, limits, etc.
            
        Returns:
            CoordinatorResult with success status and metadata
        """
        start_time = time.time()
        errors = []
        warnings = []
        
        try:
            # Step 1: Search for papers
            if self.debug:
                print(f"[DEBUG] Searching for papers on: {config['topic']}")
            
            search_start = time.time()
            search_results = self.search_agent.search(
                query=config['topic'],
                sources=config['sources'],
                limit=config['limit']
            )
            search_time = time.time() - search_start
            
            if not search_results.papers:
                return CoordinatorResult(
                    success=False,
                    papers_analyzed=0,
                    authors_found=0,
                    output_file="",
                    errors=["No papers found for the given query"],
                    total_duration=time.time() - start_time
                )
            
            if self.debug:
                print(f"[DEBUG] Found {len(search_results.papers)} papers")
            
            # Step 2: Analyze papers
            if self.debug:
                print("[DEBUG] Analyzing papers...")
            
            analysis_start = time.time()
            analysis_results = self.analysis_agent.analyze(search_results.papers)
            analysis_time = time.time() - analysis_start
            
            # Step 3: Generate report
            if self.debug:
                print("[DEBUG] Generating report...")
            
            report_start = time.time()
            
            # Add timing information to config for report
            report_config = config.copy()
            report_config.update({
                'search_time': search_time,
                'analysis_time': analysis_time,
                'total_time': time.time() - start_time,
                'timestamp': time.strftime('%Y-%m-%d %H:%M:%S')
            })
            
            report = self.report_agent.generate(analysis_results, report_config)
            report_time = time.time() - report_start
            
            # Step 4: Save to file
            output_path = Path(config['output_file'])
            with open(output_path, 'w', encoding='utf-8') as f:
                f.write(report.content)
            
            total_duration = time.time() - start_time
            
            return CoordinatorResult(
                success=True,
                papers_analyzed=len(search_results.papers),
                authors_found=analysis_results.author_count,
                output_file=str(output_path),
                total_duration=total_duration,
                pipeline_metadata={
                    'search_time': search_time,
                    'analysis_time': analysis_time,
                    'report_time': report_time,
                    'search_results': search_results.total_found,
                    'sources_searched': search_results.sources_searched
                },
                errors=errors,
                warnings=warnings
            )
            
        except Exception as e:
            if self.debug:
                import traceback
                traceback.print_exc()
            
            errors.append(str(e))
            return CoordinatorResult(
                success=False,
                papers_analyzed=0,
                authors_found=0,
                output_file="",
                errors=errors,
                total_duration=time.time() - start_time
            )
    
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