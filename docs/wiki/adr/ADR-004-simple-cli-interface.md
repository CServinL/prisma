# ADR-004: Enhanced CLI Interface with Research Streams

**Date:** 2025-09-14 (Updated: 2025-09-15)
**Author:** CServinL
**Status:** Superseded (2026-07-27) — see "Follow-up" at the end. `prisma
review`/`streams`/`zotero` (this ADR's core additions) were removed; the CLI
is now API-only, HTTP-only surfaces excepted.

## Context

The Prisma literature review system needs a command-line interface for researchers to:
- Configure and start literature reviews using YAML files
- Manage Research Streams for persistent topic monitoring
- Check progress and retrieve results  
- Use simple commands without complex setup

## Decision

Use **Click** for a comprehensive CLI that supports both traditional literature reviews and the new Research Streams architecture.

### Why Click (Updated from Typer):
- ✅ **Industry Standard**: Widely adopted for complex CLI applications
- ✅ **Command Groups**: Perfect for organizing streams commands
- ✅ **Rich Features**: Advanced options, help formatting, command chaining
- ✅ **Extensible**: Easy to add new command groups as system grows
- ✅ **Research-friendly**: Supports complex academic workflows

### Enhanced Architecture:
```bash
# Traditional literature review
prisma review "machine learning" --output "ml_review.md"

# Research Streams management
prisma streams create "Neural Networks 2024" "neural networks transformer"
prisma streams list --status active
prisma streams update --all
prisma streams info neural-networks-2024
prisma streams summary
```

## Implementation

### CLI Structure
```python
import click
from .commands.streams import streams_group

@click.group()
@click.version_option()
def cli():
    """Prisma - Intelligent Literature Review Tool"""
    pass

@cli.command()
@click.argument('topic', required=True)
@click.option('--output', '-o', help='Output file path')
def review(topic: str, output: str):
    """Generate a literature review for a research topic"""
    pass

# Add command groups
cli.add_command(streams_group)
```

### Research Streams Commands
```python
@click.group(name='streams')
def streams_group():
    """Manage research streams for continuous literature monitoring"""
    pass

@streams_group.command('create')
@click.argument('name', required=True)
@click.argument('query', required=True) 
@click.option('--frequency', '-f', type=click.Choice(['daily', 'weekly', 'monthly', 'manual']))
def create_stream(name: str, query: str, frequency: str):
    """Create a new research stream"""
    pass
```

## Enhanced Features (Day 2 Update)

### Research Streams Integration
- **Stream Management**: Complete CRUD operations for research streams
- **Batch Operations**: Update multiple streams simultaneously
- **Rich Status Display**: Detailed information about stream status and statistics
- **Flexible Filtering**: Filter streams by status, update schedule, etc.

### User Experience Enhancements
- **Progress Indicators**: Visual feedback for long-running operations
- **Error Handling**: Clear error messages with suggested solutions
- **Help System**: Comprehensive help text and examples
- **Configuration**: Support for config files and environment variables

## Commands Implemented

### Core Literature Review
- `prisma review <topic>` - Generate traditional literature review
- Options: `--output`, `--sources`, `--limit`, `--zotero-only`, `--include-authors`

### Research Streams
- `prisma streams create <name> <query>` - Create new research stream
- `prisma streams list [--status]` - List all or filtered streams  
- `prisma streams update [<stream_id>|--all]` - Update streams
- `prisma streams info <stream_id>` - Detailed stream information
- `prisma streams summary` - System-wide statistics

## Benefits Realized

### For Researchers
- **Intuitive Commands**: Natural language-like command structure
- **Flexible Workflows**: Support for both one-time and persistent research
- **Rich Feedback**: Detailed status and progress information
- **Error Recovery**: Clear guidance when operations fail

### For System Development  
- **Modular Design**: Command groups enable easy feature addition
- **Consistent Interface**: Uniform option patterns across commands
- **Extensible Architecture**: Easy to add new command groups
- **Professional UX**: Industry-standard CLI patterns

## Status

**Accepted** - Successfully implemented with full Research Streams support in Day 2 development.

## Related ADRs
- ADR-001: Simple Pipeline Architecture (CLI integrates with pipeline)
- ADR-007: Research Streams Architecture (CLI provides streams interface)

## Follow-up (2026-07-27): CLI minimized to what can't be an API call

Prompted by a direct request to reduce the CLI "to a minimum, only to manage
the core." By the time this ADR's commands existed, the FastAPI server
(`app.py`) had grown its own equivalent route for nearly everything they did:
`POST /review`, `GET/POST/PATCH/DELETE /streams`, `POST /streams/{slug}/run`,
`GET /zotero/status`, `POST /maintenance/deduplicate`. Two gaps were closed
rather than left as excuses to keep the CLI: `GET /zotero/stats` (new route,
replacing `prisma zotero stats`) and `POST /zotero/sync-pending` (new route,
replacing `prisma sync` — flushes `data/pending_writes.json`, the queue
`coordinator.py`'s review pipeline writes to when a Zotero write fails
offline).

**Removed:** `prisma review`, the entire `prisma streams` group, the entire
`prisma zotero` group, and `cli/commands/cleanup.py` (639 lines) wholesale —
it turned out to hold a second, independent, CLI-only duplicate-detection
implementation (`DuplicateDetector`) that nothing but the deleted `zotero
duplicates` command ever called; `services/dedup.py`'s `find_all_duplicates`
(backing `/maintenance/deduplicate`) was already the live implementation.

**Kept, because each is structurally incapable of being an API call:**
`prisma serve` (starts the thing you'd otherwise call), `prisma status`
(pre-flight check — runs before/without a live server), `prisma auth
hash-password` (bootstraps the password before one exists), and `prisma
reload-resources` (a thin wrapper over the supervisor's own control port —
see the next follow-up entry in this file for where that one is headed).

See TODO.md's "CLI minimization" entry and `docs/wiki/cli.md`'s "Moved to
the API" table for the full command→route mapping.
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
