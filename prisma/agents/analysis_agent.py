"""
Analysis Agent - Analyzes and summarizes academic papers using LLM.
"""

import logging
import requests
import json
import threading
from typing import Dict, List, Any
from pathlib import Path
from datetime import datetime
import time

from ..utils.config import config
from ..storage.models.agent_models import PaperMetadata, PaperSummary, AnalysisResult, ReportMetadata, LiteratureReviewReport
from ..storage.models.api_response_models import OllamaGenerateResponse, LLMRelevanceResult, LLMIdentityResult
from ..services import resource_lock

_ollama_log = logging.getLogger("prisma.ollama")

_RESOURCE_HOLDER = "api"  # must match the worker name supervisor.py restarts, so a crash releases our leases


class AnalysisAgent:
    """Analyze papers and generate summaries using Ollama."""

    def __init__(self, supervisor_host: str = "127.0.0.1", supervisor_port: int | None = None):
        self.llm_config = config.get_llm_config()
        self.base_url = self.llm_config.base_url
        self.model = self.llm_config.model
        self._inference_sem = threading.Semaphore(self.llm_config.max_concurrent_inferences)
        self._supervisor_host = supervisor_host
        self._supervisor_port = supervisor_port if supervisor_port is not None else resource_lock.default_port()

    def _call_ollama_generate(self, prompt: str, options: dict, timeout: float) -> requests.Response | None:
        """Single choke point for every Ollama /api/generate call in this agent.

        Wraps the supervisor's compute-pool lease (ADR-012) around the existing
        process-local concurrency semaphore, so this agent can't run concurrently
        against the same GPU/LLM backend as Graphify or ChromaDB indexing.
        Returns None if no compute pool is free right now — callers should
        treat that the same as any other LLM failure.
        """
        with resource_lock.lease(
            self._supervisor_host, self._supervisor_port, holder=_RESOURCE_HOLDER, model=self.model,
        ) as granted:
            if not granted:
                return None
            with self._inference_sem:
                return requests.post(
                    f"{self.base_url}/api/generate",
                    json={"model": self.model, "prompt": prompt, "stream": False, "options": options},
                    timeout=timeout,
                )
    
    def analyze(self, papers: List[PaperMetadata]) -> AnalysisResult:
        """
        Analyze papers and generate summaries.
        
        Args:
            papers: List of paper metadata from SearchAgent
            
        Returns:
            AnalysisResult with summaries and metadata
        """
        summaries = []
        processing_times = []
        
        for paper in papers:
            start_time = time.time()
            summary = self._summarize_paper(paper)
            processing_time = time.time() - start_time
            
            processing_times.append(processing_time)
            summaries.append(summary)
        
        # Extract unique authors
        all_authors = []
        for paper in papers:
            all_authors.extend(paper.authors)
        unique_authors = list(set(all_authors))
        
        # Calculate average processing time
        avg_processing_time = sum(processing_times) / len(processing_times) if processing_times else 0
        
        # Generate top authors (most frequent)
        author_counts = {}
        for author in all_authors:
            author_counts[author] = author_counts.get(author, 0) + 1
        top_authors = sorted(author_counts.keys(), key=lambda x: author_counts[x], reverse=True)[:10]
        
        return AnalysisResult(
            summaries=summaries,
            author_count=len(unique_authors),
            total_papers=len(papers),
            avg_processing_time=avg_processing_time,
            analysis_timestamp=datetime.now(),
            top_authors=top_authors,
            common_themes=[]  # TODO: Implement theme extraction
        )
    
    def _summarize_paper(self, paper: PaperMetadata) -> PaperSummary:
        """
        Summarize a single paper using Ollama.
        
        Args:
            paper: Paper metadata from SearchAgent
            
        Returns:
            PaperSummary with key findings, methodology, results
        """
        start_time = time.time()
        
        # Try to get enhanced summary from Ollama
        enhanced_summary = self._get_ollama_summary(paper.title, paper.abstract)
        
        # Extract key findings and methodology
        summary_text = enhanced_summary or paper.abstract
        key_findings = self._extract_key_findings(summary_text)
        methodology = self._extract_methodology(summary_text)
        
        processing_time = time.time() - start_time
        
        return PaperSummary(
            title=paper.title,
            authors=paper.authors,
            abstract=paper.abstract,
            summary=enhanced_summary or (paper.abstract[:500] + '...' if len(paper.abstract) > 500 else paper.abstract),
            key_findings=key_findings,
            methodology=methodology,
            url=paper.url,
            connected_papers_url=paper.connected_papers_url or f"https://www.connectedpapers.com/search?q={paper.title.replace(' ', '%20')}",
            analysis_confidence=0.8 if enhanced_summary else 0.5,
            processing_time=processing_time
        )
    
    def _log_ollama(self, op: str, elapsed_ms: float, data: dict | None, error: str | None = None, **kw) -> None:
        if error:
            _ollama_log.warning("op=%s model=%s elapsed_ms=%.0f error=%s", op, self.model, elapsed_ms, error)
            return
        prompt_tokens = data.get("prompt_eval_count") if data else None
        gen_tokens = data.get("eval_count") if data else None
        extra = " ".join(f"{k}={v}" for k, v in kw.items())
        _ollama_log.info(
            "op=%s model=%s elapsed_ms=%.0f prompt_tokens=%s gen_tokens=%s%s",
            op, self.model, elapsed_ms, prompt_tokens if prompt_tokens is not None else "?",
            gen_tokens if gen_tokens is not None else "?",
            f" {extra}" if extra else "",
        )

    def _get_ollama_summary(self, title: str, abstract: str) -> str:
        prompt = f"""Analyze this research paper and provide a concise summary in 2-3 sentences:

Title: {title}

Abstract: {abstract}

Provide a clear, academic summary focusing on the main contribution and significance."""

        t0 = time.monotonic()
        try:
            response = self._call_ollama_generate(
                prompt, options={"temperature": 0.3, "num_predict": 200}, timeout=30,
            )
            elapsed_ms = (time.monotonic() - t0) * 1000
            if response is not None and response.status_code == 200:
                data = response.json()
                self._log_ollama("summarize", elapsed_ms, data)
                ollama_response = OllamaGenerateResponse.model_validate(data)
                return ollama_response.response.strip()
            else:
                error = f"status={response.status_code}" if response is not None else "no compute lease available"
                self._log_ollama("summarize", elapsed_ms, None, error=error)
                return ""
        except Exception as e:
            elapsed_ms = (time.monotonic() - t0) * 1000
            self._log_ollama("summarize", elapsed_ms, None, error=str(e))
            return ""
    
    def _extract_key_findings(self, text: str) -> List[str]:
        """Extract key findings from summary text."""
        # Simple extraction for MVP - could be enhanced with NLP
        if "findings" in text.lower() or "results" in text.lower():
            return [text.split('.')[0] + '.']
        return ['Key findings extracted from analysis']
    
    def _extract_methodology(self, text: str) -> str:
        """Extract methodology information from summary text."""
        # Simple extraction for MVP - could be enhanced with NLP
        if "method" in text.lower() or "approach" in text.lower():
            return "Methodology identified in analysis"
        return "Methodology analysis from abstract"
    
    def assess_relevance(self, paper_title: str, paper_abstract: str, topic: str) -> LLMRelevanceResult:
        """
        Assess if a paper is relevant to a topic using semantic understanding via LLM.
        
        Args:
            paper_title: Title of the paper
            paper_abstract: Abstract of the paper
            topic: Research topic to assess relevance against
            
        Returns:
            Dict with relevance assessment results
        """
        t0 = time.monotonic()
        try:
            prompt = f"""Analyze whether this research paper is semantically relevant to the research topic.

Research Topic: {topic}

Paper Title: {paper_title}

Paper Abstract: {paper_abstract}

Please evaluate:
1. Does this paper contribute knowledge to the research topic?
2. Are the methods, findings, or applications related to the topic?
3. Would this paper be valuable for someone researching this topic?

Consider semantic relationships, not just keyword matches. For example, a paper about "neural networks for image recognition" would be relevant to "computer vision" even without exact word matches.

Respond with:
RELEVANCE: [HIGHLY_RELEVANT/RELEVANT/SOMEWHAT_RELEVANT/NOT_RELEVANT]
CONFIDENCE: [HIGH/MEDIUM/LOW]
REASONING: [2-3 sentences explaining the semantic connection or lack thereof]"""

            response = self._call_ollama_generate(
                prompt, options={"temperature": 0.3, "num_predict": 250}, timeout=45,
            )
            elapsed_ms = (time.monotonic() - t0) * 1000

            if response is not None and response.status_code == 200:
                data = response.json()
                self._log_ollama("assess_relevance", elapsed_ms, data)
                result = data.get('response', '').strip()
                return self._parse_semantic_relevance(result)
            else:
                status = response.status_code if response is not None else "no compute lease available"
                self._log_ollama("assess_relevance", elapsed_ms, None, error=str(status))
                return LLMRelevanceResult(
                    is_relevant=False,
                    relevance_level="UNKNOWN",
                    confidence=0.0,
                    reasoning=f"LLM request failed with status {status}",
                    semantic_score=0.0
                )

        except Exception as e:
            elapsed_ms = (time.monotonic() - t0) * 1000
            self._log_ollama("assess_relevance", elapsed_ms, None, error=str(e))
            return LLMRelevanceResult(
                is_relevant=False,
                relevance_level="UNKNOWN",
                confidence=0.0,
                reasoning=f"Assessment failed due to error: {e}",
                semantic_score=0.0
            )
    
    def _parse_semantic_relevance(self, response: str) -> LLMRelevanceResult:
        """Parse LLM response for semantic relevance assessment."""
        try:
            lines = response.split('\n')
            relevance_level = "NOT_RELEVANT"
            confidence = "LOW"
            reasoning = "Unable to parse reasoning"
            
            for line in lines:
                if line.startswith("RELEVANCE:"):
                    relevance_level = line.split(":", 1)[1].strip()
                elif line.startswith("CONFIDENCE:"):
                    confidence = line.split(":", 1)[1].strip()
                elif line.startswith("REASONING:"):
                    reasoning = line.split(":", 1)[1].strip()
            
            # Convert to boolean and numeric score
            is_relevant = relevance_level in ["HIGHLY_RELEVANT", "RELEVANT", "SOMEWHAT_RELEVANT"]
            
            # Semantic score based on relevance level
            score_map = {
                "HIGHLY_RELEVANT": 0.9,
                "RELEVANT": 0.7,
                "SOMEWHAT_RELEVANT": 0.5,
                "NOT_RELEVANT": 0.1
            }
            semantic_score = score_map.get(relevance_level, 0.0)
            
            # Convert confidence to float
            confidence_value = 0.5  # Default
            if confidence.upper() in ["LOW", "MEDIUM", "HIGH"]:
                confidence_map = {"LOW": 0.3, "MEDIUM": 0.6, "HIGH": 0.9}
                confidence_value = confidence_map[confidence.upper()]
            
            return LLMRelevanceResult(
                is_relevant=is_relevant,
                relevance_level=relevance_level,
                confidence=confidence_value,
                reasoning=reasoning,
                semantic_score=semantic_score
            )
            
        except Exception as e:
            return LLMRelevanceResult(
                is_relevant=False,
                relevance_level="NOT_RELEVANT",
                confidence=0.3, 
                reasoning=f"Failed to parse LLM response: {e}",
                semantic_score=0.0
            )
    
    _RELEVANCE_BATCH_SIZE = 50  # items per LLM call — stays within 7B context window

    def batch_relevance_check(
        self,
        query: str,
        candidates: list[tuple[str, str, str | None]],  # (key, title, abstract)
    ) -> list[bool]:
        """
        Check which candidates are relevant to query.

        Chunks candidates into groups of _RELEVANCE_BATCH_SIZE and makes one
        LLM call per chunk so the prompt never exceeds the model's context window.

        candidates: list of (key, title, abstract) — abstract may be None.
        Returns: list of bool in the same order as candidates.
        On LLM failure for a chunk, returns True for that chunk (fail open).
        """
        if not candidates:
            return []

        results: list[bool] = []
        for i in range(0, len(candidates), self._RELEVANCE_BATCH_SIZE):
            chunk = candidates[i : i + self._RELEVANCE_BATCH_SIZE]
            results.extend(self._relevance_chunk(query, chunk))
        return results

    def _relevance_chunk(
        self,
        query: str,
        candidates: list[tuple[str, str, str | None]],
    ) -> list[bool]:
        def _entry(i: int, title: str, abstract: str | None) -> str:
            if abstract:
                return f"{i}. {title}\n{abstract}"
            return f"{i}. {title}"

        items_block = "\n\n".join(
            _entry(i + 1, title, abstract)
            for i, (_, title, abstract) in enumerate(candidates)
        )
        prompt = (
            f'Topic: "{query}"\n\n'
            f"Which items are relevant to this topic? "
            f"Reply with only the numbers of relevant items, comma-separated. "
            f"Example: 1, 4, 7\n"
            f"If none are relevant, reply: none\n\n"
            f"{items_block}"
        )

        t0 = time.monotonic()
        try:
            response = self._call_ollama_generate(
                prompt, options={"temperature": 0.1, "num_predict": 60}, timeout=30,
            )
            elapsed_ms = (time.monotonic() - t0) * 1000
            if response is None or response.status_code != 200:
                error = f"status={response.status_code}" if response is not None else "no compute lease available"
                self._log_ollama("batch_relevance", elapsed_ms, None, error=error, n=len(candidates))
                return [True] * len(candidates)
            data = response.json()
            self._log_ollama("batch_relevance", elapsed_ms, data, n=len(candidates))
            text = data.get("response", "").strip().lower()
            if "none" in text and not any(ch.isdigit() for ch in text):
                return [False] * len(candidates)
            import re
            selected = {int(n) for n in re.findall(r"\d+", text) if 1 <= int(n) <= len(candidates)}
            return [i + 1 in selected for i in range(len(candidates))]
        except Exception as exc:
            elapsed_ms = (time.monotonic() - t0) * 1000
            self._log_ollama("batch_relevance", elapsed_ms, None, error=str(exc), n=len(candidates))
            return [True] * len(candidates)

    _IDENTITY_THRESHOLD = 8  # candidates per incoming paper; above this, switch to parallel

    def check_identity_batch(
        self,
        incoming_title: str,
        incoming_abstract: str,
        candidates: list[tuple[str, str]],  # list of (title, abstract)
    ) -> list[LLMIdentityResult]:
        """
        Check whether the incoming paper is the same work as any of the candidates.

        Sends all candidates in a single prompt when len(candidates) <= _IDENTITY_THRESHOLD.
        Falls back to parallel single-pair requests for larger sets.

        Returns one LLMIdentityResult per candidate, in the same order.
        If LLM is unavailable, returns all are_same=False (assume different).
        """
        if not candidates:
            return []
        if len(candidates) <= self._IDENTITY_THRESHOLD:
            return self._batch_prompt(incoming_title, incoming_abstract, candidates)
        return self._parallel_checks(incoming_title, incoming_abstract, candidates)

    def _batch_prompt(
        self,
        incoming_title: str,
        incoming_abstract: str,
        candidates: list[tuple[str, str]],
    ) -> list[LLMIdentityResult]:
        """Single LLM call comparing incoming paper against N candidates."""
        candidate_block = "\n\n".join(
            f"CANDIDATE {i + 1}\nTitle: {t}\nAbstract: {a or '(no abstract)'}"
            for i, (t, a) in enumerate(candidates)
        )
        expected_lines = "\n".join(
            f"CANDIDATE {i + 1}: [YES/NO] | CONFIDENCE: [HIGH/MEDIUM/LOW] | REASON: [one sentence]"
            for i in range(len(candidates))
        )
        prompt = f"""You are checking whether an incoming academic paper is the same work as each candidate.

Papers are the SAME WORK when they share the same core contribution and authors, even if the title
was reworded (e.g. arXiv preprint vs published journal version).
Papers are DIFFERENT when they merely share a topic or keyword.

INCOMING PAPER
Title: {incoming_title}
Abstract: {incoming_abstract or "(no abstract)"}

CANDIDATES
{candidate_block}

Respond with exactly one line per candidate:
{expected_lines}"""

        t0 = time.monotonic()
        try:
            response = self._call_ollama_generate(
                prompt, options={"temperature": 0.1, "num_predict": 30 * len(candidates)}, timeout=10 + 15 * len(candidates),
            )
            elapsed_ms = (time.monotonic() - t0) * 1000
            if response is None or response.status_code != 200:
                error = f"status={response.status_code}" if response is not None else "no compute lease available"
                self._log_ollama("check_identity_batch", elapsed_ms, None, error=error, n=len(candidates))
                return [LLMIdentityResult(are_same=False, confidence=0.0, reason="LLM unavailable")] * len(candidates)
            data = response.json()
            self._log_ollama("check_identity_batch", elapsed_ms, data, n=len(candidates))
            return self._parse_batch_response(data.get("response", "").strip(), len(candidates))
        except Exception as exc:
            elapsed_ms = (time.monotonic() - t0) * 1000
            self._log_ollama("check_identity_batch", elapsed_ms, None, error=str(exc), n=len(candidates))
            return [LLMIdentityResult(are_same=False, confidence=0.0, reason=f"error: {exc}")] * len(candidates)

    def _parse_batch_response(self, text: str, n: int) -> list[LLMIdentityResult]:
        results: list[LLMIdentityResult] = []
        lines_by_candidate: dict[int, str] = {}
        for line in text.splitlines():
            for i in range(1, n + 1):
                if line.upper().startswith(f"CANDIDATE {i}:"):
                    lines_by_candidate[i] = line
                    break
        for i in range(1, n + 1):
            line = lines_by_candidate.get(i, "")
            results.append(self._parse_inline_identity(line))
        return results

    def _parse_inline_identity(self, line: str) -> LLMIdentityResult:
        # Expected: "CANDIDATE N: YES | CONFIDENCE: HIGH | REASON: ..."
        are_same = False
        confidence = 0.5
        reason = ""
        if not line:
            return LLMIdentityResult(are_same=False, confidence=0.0, reason="no response")
        upper = line.upper()
        # Check for YES/NO after the colon
        after_colon = line.split(":", 1)[-1] if ":" in line else line
        are_same = "YES" in after_colon.upper().split("|")[0]
        parts = [p.strip() for p in after_colon.split("|")]
        for part in parts:
            pupper = part.upper()
            if pupper.startswith("CONFIDENCE:"):
                val = part.split(":", 1)[1].strip().upper()
                confidence = {"HIGH": 0.9, "MEDIUM": 0.6, "LOW": 0.3}.get(val, 0.5)
            elif pupper.startswith("REASON:"):
                reason = part.split(":", 1)[1].strip()
        return LLMIdentityResult(are_same=are_same, confidence=confidence, reason=reason)

    def _parallel_checks(
        self,
        incoming_title: str,
        incoming_abstract: str,
        candidates: list[tuple[str, str]],
    ) -> list[LLMIdentityResult]:
        """Fire one LLM request per candidate in parallel threads."""
        from concurrent.futures import ThreadPoolExecutor, as_completed

        def _check_one(args):
            idx, title_b, abstract_b = args
            result = self._single_pair_check(incoming_title, incoming_abstract, title_b, abstract_b)
            return idx, result

        results: list[LLMIdentityResult] = [
            LLMIdentityResult(are_same=False, confidence=0.0, reason="pending")
        ] * len(candidates)

        with ThreadPoolExecutor(max_workers=self.llm_config.max_concurrent_inferences) as pool:
            futures = {
                pool.submit(_check_one, (i, t, a)): i
                for i, (t, a) in enumerate(candidates)
            }
            for future in as_completed(futures):
                try:
                    idx, result = future.result()
                    results[idx] = result
                except Exception as exc:
                    results[futures[future]] = LLMIdentityResult(
                        are_same=False, confidence=0.0, reason=f"error: {exc}"
                    )
        return results

    def _single_pair_check(
        self, title_a: str, abstract_a: str, title_b: str, abstract_b: str
    ) -> LLMIdentityResult:
        prompt = f"""Are these two academic papers the same work? (Same paper may have different titles: preprint vs journal version, reordered words.)

Paper A — Title: {title_a}
Abstract: {abstract_a or "(no abstract)"}

Paper B — Title: {title_b}
Abstract: {abstract_b or "(no abstract)"}

SAME: [YES/NO]
CONFIDENCE: [HIGH/MEDIUM/LOW]
REASON: [one sentence]"""
        t0 = time.monotonic()
        try:
            response = self._call_ollama_generate(
                prompt, options={"temperature": 0.1, "num_predict": 60}, timeout=20,
            )
            elapsed_ms = (time.monotonic() - t0) * 1000
            if response is None or response.status_code != 200:
                error = f"status={response.status_code}" if response is not None else "no compute lease available"
                self._log_ollama("check_identity_single", elapsed_ms, None, error=error)
                return LLMIdentityResult(are_same=False, confidence=0.0, reason="LLM unavailable")
            data = response.json()
            self._log_ollama("check_identity_single", elapsed_ms, data)
            text = data.get("response", "").strip()
            are_same = False
            confidence = 0.5
            reason = ""
            for line in text.splitlines():
                upper = line.upper()
                if upper.startswith("SAME:"):
                    are_same = "YES" in upper
                elif upper.startswith("CONFIDENCE:"):
                    val = line.split(":", 1)[1].strip().upper()
                    confidence = {"HIGH": 0.9, "MEDIUM": 0.6, "LOW": 0.3}.get(val, 0.5)
                elif upper.startswith("REASON:"):
                    reason = line.split(":", 1)[1].strip()
            return LLMIdentityResult(are_same=are_same, confidence=confidence, reason=reason)
        except Exception as exc:
            elapsed_ms = (time.monotonic() - t0) * 1000
            self._log_ollama("check_identity_single", elapsed_ms, None, error=str(exc))
            return LLMIdentityResult(are_same=False, confidence=0.0, reason=f"error: {exc}")

    def _simple_relevance_check(self, title: str, abstract: str, topic: str) -> Dict[str, Any]:
        """This method is deprecated - semantic evaluation should be used instead."""
        return {
            "is_relevant": False,
            "relevance_level": "NOT_RELEVANT",
            "confidence": "LOW",
            "reasoning": "Fallback method - semantic evaluation unavailable",
            "semantic_score": 0.0
        }
    
    def _fetch_full_text(self, paper: dict) -> str:
        """Fetch full text of paper if available."""
        # TODO: Implement paper fetching from various sources
        return ""