# Quick Start Guide

Get up and running with Prisma in minutes.

## Prerequisites

1. **Python 3.12+** with Poetry 
2. **Ollama** installed with llama3.1:8b model
3. **Zotero** with research library (optional for basic testing)

## Installation

```bash
# Clone the repository
git clone https://github.com/CServinL/prisma.git
cd prisma

# Set up Python environment with Poetry
poetry install
poetry shell

# Test the CLI
poetry run prisma --help
```

## Your First Research Stream

```bash
# Create a research stream for continuous monitoring
poetry run prisma streams create "Neural Networks 2024" "neural networks transformer attention" --frequency weekly

# List your research streams
poetry run prisma streams list

# Update all streams to find new papers
poetry run prisma streams update --all

# Generate a literature review (classic approach)
poetry run prisma review "machine learning" --output "ml_review.md"
```

## Research Streams in Action

```bash
# Create focused research streams
prisma streams create "AI Ethics" "artificial intelligence ethics bias fairness" --frequency weekly
prisma streams create "Quantum ML" "quantum machine learning" --frequency monthly

# Monitor and update
prisma streams summary              # Overview of all streams
prisma streams update --all         # Find new papers in all streams
prisma streams info ai-ethics      # Detailed stream information
```

## What You Get

- **Executive Summary**: Key findings and trends
- **Paper Summaries**: Structured analysis of each paper
- **Comparative Analysis**: Trends, gaps, and conflicts
- **Recommendations**: Future research directions
- **Raw Data**: CSV/JSON exports for further analysis

## Next Steps

- 📖 [Complete Research Streams Guide](research-streams-guide.md)
- 🔧 [Development Setup](development-setup.md)
- ⚙️ [Configuration Guide](configuration.md)
- 🏗️ [Architecture Overview](architecture.md)