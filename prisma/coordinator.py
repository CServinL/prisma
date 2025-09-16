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
from .agents.zotero_agent import ZoteroAgent
from .storage.models.agent_models import CoordinatorResult
from .utils.config import config


class PrismaCoordinator:
    """Main coordinator for orchestrating literature review pipeline."""
    
    def __init__(self, debug: bool = False):
        self.debug = debug
        self.search_agent = SearchAgent()
        self.analysis_agent = AnalysisAgent()
        self.report_agent = ReportAgent()
        
        # Initialize Zotero agent for saving papers
        self.zotero_agent = None
        if config.get('sources.zotero.enabled', False) and config.get('sources.zotero.auto_save_papers', False):
            try:
                zotero_config = config.get('sources.zotero', {})
                self.zotero_agent = ZoteroAgent(zotero_config)
                if debug:
                    print("[DEBUG] Zotero agent initialized for auto-saving")
            except Exception as e:
                if debug:
                    print(f"[DEBUG] Failed to initialize Zotero agent: {e}")
        
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
                    total_duration=time.time() - start_time,
                    pipeline_metadata={}
                )
            
            if self.debug:
                print(f"[DEBUG] Found {len(search_results.papers)} papers")
            
            # Step 2: Analyze papers
            if self.debug:
                print("[DEBUG] Analyzing papers...")
            
            analysis_start = time.time()
            analysis_results = self.analysis_agent.analyze(search_results.papers)
            analysis_time = time.time() - analysis_start
            
            # Step 2.5: Save high-quality papers to Zotero (if enabled)
            saved_papers_count = 0
            if self.zotero_agent is not None:
                try:
                    saved_papers_count = self._save_papers_to_zotero(search_results.papers, analysis_results, config['topic'])
                    if self.debug and saved_papers_count > 0:
                        print(f"[DEBUG] Saved {saved_papers_count} high-quality papers to Zotero")
                except Exception as e:
                    warnings.append(f"Failed to save papers to Zotero: {str(e)}")
                    if self.debug:
                        print(f"[DEBUG] Zotero save error: {e}")
            
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
                    'sources_searched': search_results.sources_searched,
                    'saved_to_zotero': saved_papers_count
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
                total_duration=time.time() - start_time,
                pipeline_metadata={}
            )
    
    def get_status(self) -> Dict[str, Any]:
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
    
    def _save_papers_to_zotero(self, papers: List[Any], analysis_results: Any, topic: str) -> int:
        """
        Save high-quality papers to Zotero using the topic as collection name.
        
        Args:
            papers: List of papers from search results
            analysis_results: Analysis results containing paper summaries
            topic: Research topic (used as collection name)
            
        Returns:
            Number of papers successfully saved
        """
        if not self.zotero_agent or not papers:
            return 0
        
        min_confidence = config.get('sources.zotero.min_confidence_for_save', 0.5)
        # Use topic as collection name, with fallback
        collection_name = topic or config.get('sources.zotero.auto_save_collection', 'Prisma Discoveries')
        
        # Filter papers by confidence score
        high_quality_papers = []
        for paper in papers:
            confidence = getattr(paper, 'confidence_score', 0.0)
            if confidence >= min_confidence:
                high_quality_papers.append(paper)
        
        if not high_quality_papers:
            if self.debug:
                print(f"[DEBUG] No papers meet minimum confidence threshold ({min_confidence})")
            return 0
        
        try:
            # Convert papers to Zotero format and save
            zotero_items = []
            for paper in high_quality_papers:
                item = {
                    'itemType': 'journalArticle',
                    'title': paper.title,
                    'creators': [{'creatorType': 'author', 'firstName': '', 'lastName': author} 
                               for author in paper.authors],
                    'abstractNote': paper.abstract,
                    'url': paper.url,
                    'DOI': getattr(paper, 'doi', ''),
                    'publicationTitle': getattr(paper, 'venue', ''),
                    'date': str(getattr(paper, 'year', '')),
                    'tags': [{'tag': f'Prisma-Discovery'}, 
                            {'tag': f'Confidence-{paper.confidence_score:.2f}'},
                            {'tag': f'Source-{paper.source}'},
                            {'tag': f'Topic-{topic}'}]
                }
                
                # Add summary as note if available
                if hasattr(analysis_results, 'summaries'):
                    for summary in analysis_results.summaries:
                        if summary.title == paper.title:
                            item['abstractNote'] += f"\n\n[Prisma Summary]\n{summary.summary}"
                            break
                
                zotero_items.append(item)
            
            # Save to Zotero using unified interface
            try:
                # Use the unified save method that all clients support
                created_keys = self.zotero_agent.client.save_items(
                    items=zotero_items,
                    collection_key=None  # No specific collection for coordinator saves
                )
                if self.debug:
                    print(f"[DEBUG] Successfully saved {len(zotero_items)} items via unified interface")
            except Exception as e:
                if self.debug:
                    print(f"[DEBUG] Failed to save items to Zotero: {e}")
                return 0
            
            return len(zotero_items)
            
        except Exception as e:
            if self.debug:
                print(f"[DEBUG] Error saving to Zotero: {e}")
            raise


# Legacy class alias for backward compatibility
Coordinator = PrismaCoordinator