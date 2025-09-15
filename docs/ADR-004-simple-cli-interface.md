# ADR-004: Simple CLI Interface

**Date:** 2025-09-14  
**Author:** CServinL

## Context

The Prisma literature review system needs a command-line interface for researchers to:
- Configure and start literature reviews using YAML files
- Check progress and retrieve results
- Use simple commands without complex setup

## Decision

Use **Typer** for a simple CLI that directly calls our 4-component pipeline.

### Why Typer:
- ✅ **Easy to use**: Simple commands with good help text
- ✅ **Type safety**: Validates inputs automatically
- ✅ **Research-friendly**: Good for academic workflows
- ✅ **Python native**: Works well with our existing code

### Simple Architecture:
```bash
# Start literature review
prisma start my_config.yaml

# Check status  
prisma status my_job_123

# Get results
prisma results my_job_123
```

## Implementation

### Basic CLI Structure
```python
import typer
from pathlib import Path

app = typer.Typer()

@app.command()
def start(config_file: Path):
    """Start a literature review from YAML config."""
    # Load config, create job, run pipeline
    pass

@app.command() 
def status(job_id: str):
    """Check job status from database."""
    # Query SQLite for job status
    pass

@app.command()
def results(job_id: str):
    """Get job results."""
    # Return final report from job
    pass
```

### Configuration Format
```yaml
topic: "machine learning healthcare"
sources: ["pubmed", "arxiv"] 
max_papers: 100
output_format: "markdown"
```

### Simple Workflow
1. CLI loads YAML config
2. Creates job record in SQLite
3. Calls Coordinator directly (no messaging)
4. Coordinator runs pipeline sequentially
5. Results saved to database
6. CLI retrieves and displays results

## Benefits
- **Simple**: Easy to understand and maintain
- **Direct**: No complex messaging or async coordination
- **Reliable**: Fewer moving parts mean fewer failure points
- **Fast**: No overhead from complex architecture

## When to Enhance
- If we need web interface
- If jobs take more than 15 minutes
- If we need to run multiple jobs simultaneously
- If we add user authentication

---

**Related ADRs**: 
- [ADR-001: Simple Pipeline Architecture](./ADR-001-simple-pipeline-architecture.md)
- [ADR-005: Sequential Processing](./ADR-005-sequential-processing.md)
