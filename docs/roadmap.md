# Roadmap

## Phase 0: Core MVP (Current Focus)
**Goal**: Basic literature review automation with all core components

**Features:**
- ✅ Simple pipeline architecture (4 core components)
- ✅ Zotero integration + Research Streams (Day 2) - **COMPLETED WITH ENHANCEMENTS**
- 🌐 Multi-Source Search (Day 3) 
- 🤖 AI Analysis (Day 4)
- 📊 Report Generation (Day 5)
- 👥 Author Analysis (Day 6)

**Timeline**: Q4 2024 - Q1 2025 (8-day intensive MVP)

## Phase 1: Enhanced Analysis (Next)
**Goal**: Improve analysis quality and user experience

**Features:**
- 📊 Better comparative analysis and trend detection
- 🎯 Improved deduplication and metadata handling
- 📄 Multiple output formats (HTML, PDF export)
- ⚡ Performance optimizations
- 🔧 Enhanced CLI with better error handling

**Timeline**: Q2-Q3 2025

## Phase 2: Collaborative Features (Future)
**Goal**: Multi-user workflows and advanced features

**Features:**
- 🌐 Optional web interface for report viewing
- 👥 Shared research projects and collaboration
- 🔄 Scheduled review updates
- 📈 Advanced analytics and visualizations
- 🔌 API endpoints for integration

**Timeline**: Q4 2025 - Q1 2026

## Development Principles
- **MVP First**: Get core functionality working before adding features
- **User-Driven**: Features based on real researcher needs
- **Simple by Default**: Complex features are optional, not required
- **Academic Integrity**: Maintain research quality and reproducibility standards

## Future Enhancements (Post-MVP)

**Priority: Get working MVP in 7 days, then iterate based on user feedback**

### 📅 **Week 2: Critical Improvements** 
- **Multiple APIs**: Add PubMed, Semantic Scholar integration
- **Book Support**: ISBN lookup, library catalogs, Google Books API
- **Document Processing**: PDF full-text extraction and analysis
- **LLM Analysis**: Local model integration for semantic analysis  
- **Better Export**: LaTeX and Word format support
- **Performance**: Concurrent processing and caching

### 📅 **Month 2: Advanced Features**
- **Reference Managers**: Mendeley, EndNote, RefWorks integration
- **Grey Literature**: Technical reports, theses, government publications
- **Team Collaboration**: Shared projects and multi-user support
- **Conference Proceedings**: Full conference database integration
- **Advanced Analytics**: Citation impact and trend analysis

### 🔍 **Expanded Search Scope**
- **Additional Databases**: Semantic Scholar, IEEE Xplore, JSTOR, Web of Science
- **Cross-domain Search**: Multi-disciplinary research support across all major databases
- **Advanced Filtering**: Institution-based, author-based, and citation-based filtering
- **Search Optimization**: Smarter query expansion and result ranking

### 📚 **Non-Open Access Support**
- **Institutional Access**: Integration with university library systems
- **Publisher APIs**: Direct integration with major academic publishers
- **Access Management**: Handle subscription-based and paywall content
- **Fair Use Compliance**: Automated compliance with academic use policies

### ⚡ **Parallel Processing & Performance**
- **Concurrent Search**: Search multiple databases simultaneously
- **Parallel Analysis**: Process multiple papers concurrently with LLM batching
- **Distributed Processing**: Scale across multiple machines for large reviews
- **Caching & Resume**: Smart caching and ability to resume interrupted reviews

### 🔄 **Automated Updates & Monitoring**
- **Scheduled Reviews**: Automatic updates to existing literature reviews
- **"What's New" Reports**: Highlight changes between report versions with visual diff
- **Delta Analysis**: Show new papers, updated citations, and emerging trends since last review
- **Change Notifications**: Alert system when new relevant papers are published
- **Trend Monitoring**: Track emerging topics and research directions over time
- **Version Control**: Maintain history of review updates and changes
- **Smart Incremental Updates**: Only re-analyze changed or new content to save time

### 🌐 **Advanced Integration**
- **Reference Managers**: Deep integration with Mendeley, EndNote, RefWorks
- **Citation Networks**: Analyze citation patterns and research impact
- **Collaboration Tools**: Team-based research projects and shared reviews
- **Export Formats**: LaTeX, Word, EndNote, and journal-specific formats

### 👥 **Author Intelligence & Research Mapping**
- **Comprehensive Author Profiles**: Detailed profiles of key researchers in the field
- **Research Trajectories**: Track how authors' research has evolved over time
- **Collaboration Networks**: Map co-authorship patterns and research partnerships
- **Institution Mapping**: Identify leading research institutions and departments
- **Contact Directory**: Academic "telephone guide" with affiliations and contact information
- **Expertise Classification**: Categorize authors by research specializations and methodologies
- **Publication Analytics**: Author productivity, citation impact, and influence metrics
- **Research Timeline**: Chronological view of each author's contributions to the field
- **Emerging Researchers**: Identify up-and-coming scholars and recent PhD graduates
- **Geographic Distribution**: Map research activity by country and region

### 📊 **Visual Analytics & Reference Mapping**
- **ConnectedPapers Integration**: Generate ConnectedPapers.com links for citation network visualization
- **One-click Network View**: Auto-generate ConnectedPapers URLs using DOIs or paper identifiers
- **Batch Link Generation**: Create ConnectedPapers links for multiple key papers simultaneously  
- **Report Embedding**: Include ConnectedPapers links directly in markdown literature review reports
- **Discovery Workflow**: Use ConnectedPapers to explore networks → Import relevant papers back to Prisma
- **Multi-origin Networks**: Leverage ConnectedPapers' multi-origin graphs for comprehensive field views
- **Prior/Derivative Works**: Link to ConnectedPapers' prior and derivative work views for temporal analysis

*Note: ConnectedPapers does not currently offer a public API, but we can generate direct links to their service using paper DOIs, arXiv IDs, or Semantic Scholar URLs for seamless integration.*

*Note: These features represent potential directions based on user feedback and academic research needs. The core philosophy remains simplicity and reliability first.*