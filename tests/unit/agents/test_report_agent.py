"""Unit tests for ReportAgent's author analysis / research directory
(docs/wiki/roadmap.md's Phase 5 MVP: analyze_authors + create_research_directory,
map_collaboration_networks stays a separate, unbuilt increment)."""
from prisma.agents.report_agent import ReportAgent
from prisma.storage.models.agent_models import AnalysisResult, PaperSummary


def _summary(title: str, authors: list[str], key_findings: list[str] | None = None,
             confidence: float | None = None, url: str | None = None) -> PaperSummary:
    return PaperSummary(
        title=title, authors=authors, abstract="an abstract", summary="a summary",
        key_findings=key_findings or [], url=url or f"https://example.com/{title}",
        analysis_confidence=confidence,
    )


def test_analyze_authors_groups_papers_by_author():
    summaries = [
        _summary("Attention Is All You Need", ["Vaswani", "Shazeer"]),
        _summary("Scaling Transformers", ["Vaswani"]),
    ]
    analysis = ReportAgent().analyze_authors(summaries)

    by_name = {p.name: p for p in analysis.authors}
    assert analysis.total_unique_authors == 2
    assert by_name["Vaswani"].paper_count == 2
    assert by_name["Shazeer"].paper_count == 1


def test_analyze_authors_sorts_by_paper_count_descending():
    summaries = [
        _summary("Paper A", ["Prolific"]),
        _summary("Paper B", ["Prolific"]),
        _summary("Paper C", ["Prolific", "OneOff"]),
    ]
    analysis = ReportAgent().analyze_authors(summaries)

    assert [a.name for a in analysis.authors] == ["Prolific", "OneOff"]


def test_analyze_authors_key_publications_ranked_by_confidence_and_capped():
    summaries = [_summary(f"Paper {i}", ["Author"], confidence=i / 10) for i in range(10)]
    analysis = ReportAgent().analyze_authors(summaries)

    profile = analysis.authors[0]
    assert profile.paper_count == 10
    assert len(profile.key_publications) == 5  # capped, not all 10
    assert profile.key_publications[0].title == "Paper 9"  # highest confidence first
    assert profile.key_publications[-1].title == "Paper 5"


def test_analyze_authors_specializations_reflect_frequent_title_words():
    summaries = [
        _summary("Quantization for Neural Networks", ["Author"], key_findings=["Quantization reduces memory"]),
        _summary("Advances in Quantization", ["Author"], key_findings=["Quantization improves speed"]),
    ]
    analysis = ReportAgent().analyze_authors(summaries)

    assert "quantization" in analysis.authors[0].specializations


def test_analyze_authors_no_institutional_affiliation_field():
    # Regression guard for the deliberate MVP scope cut -- AuthorProfile
    # must not grow an affiliation field until real data backs it (see its
    # docstring). Catches an accidental re-introduction.
    analysis = ReportAgent().analyze_authors([_summary("P", ["A"])])
    assert not hasattr(analysis.authors[0], "affiliation")
    assert not hasattr(analysis.authors[0], "institution")


def test_analyze_authors_empty_corpus_returns_empty_analysis():
    analysis = ReportAgent().analyze_authors([])
    assert analysis.authors == []
    assert analysis.total_unique_authors == 0


def test_create_research_directory_lists_each_author_with_publications():
    summaries = [_summary("Attention Is All You Need", ["Vaswani"], confidence=0.9)]
    analysis = ReportAgent().analyze_authors(summaries)

    directory = ReportAgent().create_research_directory(analysis)

    assert "## Research Directory" in directory
    assert "### Vaswani" in directory
    assert "[Attention Is All You Need](https://example.com/Attention Is All You Need)" in directory


def test_create_research_directory_does_not_mention_affiliation_as_available():
    directory = ReportAgent().create_research_directory(
        ReportAgent().analyze_authors([_summary("P", ["A"])])
    )
    assert "affiliation isn't shown" in directory.lower()


def test_generate_omits_author_directory_by_default():
    result = AnalysisResult(
        summaries=[_summary("Paper", ["Author"], confidence=0.9)], author_count=1, total_papers=1,
        avg_processing_time=0.0,
    )
    report = ReportAgent().generate(result, {"topic": "test"})

    assert "Research Directory" not in report.content


def test_generate_includes_author_directory_when_requested():
    result = AnalysisResult(
        summaries=[_summary("Paper", ["Author"], confidence=0.9)], author_count=1, total_papers=1,
        avg_processing_time=0.0,
    )
    report = ReportAgent().generate(result, {"topic": "test", "include_authors": True})

    assert "## Research Directory" in report.content
    assert "### Author" in report.content
