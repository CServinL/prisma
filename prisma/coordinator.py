"""
Prisma Coordinator - Main orchestration logic for literature reviews.
MVP: Fast, simple, working

if relevance_result.is_relevant:
    relevant_papers.append(paper)
    if self.debug:
        level = relevance_result.relevance_level
        print(f"[DEBUG] Relevant paper: {paper.title[:50]}... ({level})")
else:
    discarded_papers += 1
    if self.debug:
        level = relevance_result.relevance_level
        print(f"[DEBUG] Discarded paper: {paper.title[:50]}... ({level})")tion.
"""

import json
from pathlib import Path
from typing import Dict, List, Any
import time

from .agents.search_agent import SearchAgent
from .agents.analysis_agent import AnalysisAgent  
from .agents.report_agent import ReportAgent
from .agents.zotero_agent import ZoteroAgent, ZoteroSearchCriteria
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
                    output_file=config.get('output_file', './failed_search.md'),
                    errors=["No papers found for the given query"],
                    total_duration=time.time() - start_time,
                    pipeline_metadata={}
                )
            
            if self.debug:
                print(f"[DEBUG] Found {len(search_results.papers)} papers")
            
            # Step 2: Relevance Assessment
            if self.debug:
                print("[DEBUG] Assessing document relevance...")
            
            relevance_start = time.time()
            relevant_papers = []
            discarded_papers = 0
            
            for paper in search_results.papers:
                try:
                    # Use LLM to quickly evaluate document relevance
                    relevance_result = self.analysis_agent.assess_relevance(
                        paper_title=paper.title,
                        paper_abstract=paper.abstract,  # abstract is required field
                        topic=config['topic']
                    )
                    
                    # Step 3: Filtering - Keep only relevant documents
                    if relevance_result.is_relevant:
                        relevant_papers.append(paper)
                        if self.debug:
                            level = relevance_result.relevance_level
                            print(f"[DEBUG] ✅ Relevant ({level}): {paper.title[:50]}...")
                    else:
                        discarded_papers += 1
                        if self.debug:
                            level = relevance_result.relevance_level
                            print(f"[DEBUG] ❌ Filtered ({level}): {paper.title[:50]}...")
                            
                except Exception as e:
                    # If relevance assessment fails, keep the paper for safety
                    relevant_papers.append(paper)
                    if self.debug:
                        print(f"[DEBUG] ⚠️ Relevance assessment failed for {paper.title[:50]}, keeping paper: {e}")
            
            relevance_time = time.time() - relevance_start
            
            if self.debug:
                print(f"[DEBUG] Relevance assessment complete: {len(relevant_papers)} relevant, {discarded_papers} discarded")
            
            if not relevant_papers:
                return CoordinatorResult(
                    success=False,
                    papers_analyzed=0,
                    authors_found=0,
                    output_file=config.get('output_file', './no_relevant_papers.md'),
                    errors=[f"No relevant papers found for topic '{config['topic']}' after relevance assessment"],
                    total_duration=time.time() - start_time,
                    pipeline_metadata={
                        'search_time': search_time,
                        'relevance_time': relevance_time,
                        'papers_found': len(search_results.papers),
                        'papers_discarded': discarded_papers,
                        'papers_relevant': len(relevant_papers)
                    }
                )
            
            # Step 4: Check Zotero Storage for duplicates (if available)
            if self.debug:
                print("[DEBUG] Checking for duplicates in Zotero...")
            
            duplicate_check_start = time.time()
            new_papers = []
            existing_papers = 0
            unsaved_papers = []
            
            # Simple duplicate checking using Zotero agent's search capabilities
            if self.zotero_agent is not None:
                try:
                    for paper in relevant_papers:
                        # Simple duplicate check: search by title
                        is_duplicate = self._check_zotero_duplicate_simple(paper)
                        if not is_duplicate:
                            new_papers.append(paper)
                        else:
                            existing_papers += 1
                            if self.debug:
                                print(f"[DEBUG] 📚 Duplicate found in Zotero: {paper.title[:50]}...")
                except Exception as e:
                    # If duplicate checking fails, treat all as new for safety
                    new_papers = relevant_papers
                    if self.debug:
                        print(f"[DEBUG] ⚠️ Duplicate checking failed, treating all as new: {e}")
                    warnings.append(f"Duplicate checking failed: {str(e)}")
            else:
                # No Zotero agent available, treat all relevant papers as new
                new_papers = relevant_papers
                if self.debug:
                    print("[DEBUG] No Zotero agent available, treating all papers as new")
            
            duplicate_check_time = time.time() - duplicate_check_start
            
            if self.debug:
                print(f"[DEBUG] Duplicate check complete: {len(new_papers)} new, {existing_papers} existing")
            
            # Step 5: Deep Analysis (only on relevant, non-duplicate documents)
            if self.debug:
                print(f"[DEBUG] Analyzing {len(new_papers)} relevant papers...")
            
            analysis_start = time.time()
            analysis_results = self.analysis_agent.analyze(new_papers)  # Use filtered papers
            analysis_time = time.time() - analysis_start
            
            # Step 4b: Save high-quality papers to Zotero (if enabled)
            saved_papers_count = 0
            if self.zotero_agent is not None:
                try:
                    saved_papers_count = self._save_papers_to_zotero(new_papers, analysis_results, config['topic'])
                    if self.debug and saved_papers_count > 0:
                        print(f"[DEBUG] Saved {saved_papers_count} high-quality papers to Zotero")
                except Exception as e:
                    warnings.append(f"Failed to save papers to Zotero: {str(e)}")
                    if self.debug:
                        print(f"[DEBUG] Zotero save error: {e}")
                    # Mark papers as unsaved
                    unsaved_papers.extend(new_papers)
            else:
                # Mark all papers as unsaved if Zotero agent not available
                unsaved_papers.extend(new_papers)
                if self.debug:
                    print(f"[DEBUG] Zotero agent not available, marking {len(new_papers)} papers as unsaved")
            
            # Step 6: Generate report
            if self.debug:
                print("[DEBUG] Generating report...")
            
            report_start = time.time()
            
            # Add timing information to config for report
            report_config = config.copy()
            report_config.update({
                'search_time': search_time,
                'relevance_time': relevance_time,
                'duplicate_check_time': duplicate_check_time,
                'analysis_time': analysis_time,
                'total_time': time.time() - start_time,
                'timestamp': time.strftime('%Y-%m-%d %H:%M:%S'),
                'papers_found': len(search_results.papers),
                'papers_discarded': discarded_papers,
                'papers_relevant': len(relevant_papers),
                'papers_existing': existing_papers,
                'papers_new': len(new_papers),
                'papers_unsaved': len(unsaved_papers)
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
                papers_analyzed=len(new_papers),  # Use actually analyzed papers
                authors_found=analysis_results.author_count,
                output_file=str(output_path),
                total_duration=total_duration,
                pipeline_metadata={
                    'search_time': search_time,
                    'relevance_time': relevance_time,
                    'duplicate_check_time': duplicate_check_time,
                    'analysis_time': analysis_time,
                    'report_time': report_time,
                    'search_results': search_results.total_found,
                    'sources_searched': search_results.sources_searched,
                    'papers_found': len(search_results.papers),
                    'papers_discarded': discarded_papers,
                    'papers_relevant': len(relevant_papers),
                    'papers_existing': existing_papers,
                    'papers_new': len(new_papers),
                    'papers_unsaved': len(unsaved_papers),
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
                output_file=config.get('output_file', './error_output.md'),
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
    
    def _check_zotero_duplicate_simple(self, paper) -> bool:
        """
        Simple check if a paper already exists in Zotero library.
        
        Args:
            paper: Paper metadata to check
            
        Returns:
            True if paper exists in Zotero, False otherwise
        """
        if not self.zotero_agent:
            return False
            
        try:
            # Use the search_papers method with title search
            if paper.title:  # title is required field, no need for hasattr
                # Search by title with a reasonable limit
                criteria = ZoteroSearchCriteria(
                    query=paper.title,
                    collections=[],
                    item_types=[],
                    tags=[],
                    date_range=None,
                    limit=10  # Small limit since we just need to check existence
                )
                results = self.zotero_agent.search_papers(criteria)
                
                # Check if any result has similar title
                if results:
                    paper_title_norm = paper.title.lower().strip()
                    for result in results:
                        if hasattr(result, 'title') and result.title:
                            result_title_norm = result.title.lower().strip()
                            # Simple title similarity check
                            if paper_title_norm == result_title_norm:
                                return True
                
            return False
            
        except Exception as e:
            # If search fails, assume no duplicate for safety
            if self.debug:
                print(f"[DEBUG] Error checking duplicate: {e}")
            return False

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
                    'DOI': paper.doi or '',  # doi is optional field in model
                    'publicationTitle': getattr(paper, 'venue', ''),  # venue not in model
                    'date': str(getattr(paper, 'year', '')),  # year not in model
                    'tags': [{'tag': f'Prisma-Discovery'}, 
                            {'tag': f'Confidence-{getattr(paper, "confidence_score", 0.0):.2f}'},
                            {'tag': f'Source-{paper.source}'},
                            {'tag': f'Topic-{topic}'}]
                }
                
                # Add summary as note if available
                if analysis_results.summaries:  # summaries is required field
                    for summary in analysis_results.summaries:
                        if summary.title == paper.title:
                            item['abstractNote'] += f"\n\n[Prisma Summary]\n{summary.summary}"
                            break
                
                zotero_items.append(item)
            
            # Save to Zotero using unified interface
            try:
                # Use the unified save method that all clients support
                if self.zotero_agent.client:
                    created_keys = self.zotero_agent.client.save_items(
                        items=zotero_items,
                        collection_key=None  # No specific collection for coordinator saves
                    )
                    if self.debug:
                        print(f"[DEBUG] Successfully saved {len(zotero_items)} items via unified interface")
                else:
                    if self.debug:
                        print(f"[DEBUG] No Zotero client available for saving")
                    return 0
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