# Prisma CLI Documentation

Complete command-line interface reference for Prisma literature review system.

## Overview

Prisma provides a comprehensive CLI for managing research streams, generating literature reviews, and integrating with Zotero. All commands follow the pattern:

```bash
prisma [COMMAND] [SUBCOMMAND] [OPTIONS] [ARGUMENTS]
```

## Global Options

```bash
--help, -h          Show help message and exit
--version           Show version information
--config, -c        Path to custom configuration file
```

## Command Groups

### 1. Research Streams (`streams`)

Persistent topic monitoring with automatic paper discovery.

#### Create a Stream
```bash
prisma streams create NAME QUERY [OPTIONS]
```

**Arguments:**
- `NAME`: Human-readable stream name (e.g., "Neural Networks 2024")
- `QUERY`: Search query keywords (e.g., "neural networks transformer")

**Options:**
- `--description, -d TEXT`: Detailed description of the research stream
- `--frequency, -f [daily|weekly|monthly|manual]`: Update frequency (default: weekly)
- `--parent-collection, -p TEXT`: Parent Zotero collection key
- `--config, -c PATH`: Path to configuration file

**Examples:**
```bash
# Basic stream creation
prisma streams create "LLMs for Edge" "LLM edge computing quantization"

# With full options
prisma streams create "AI Ethics" "artificial intelligence ethics bias" \
  --description "Research on ethical implications of AI systems" \
  --frequency daily \
  --parent-collection "AI Research"
```

#### List Streams
```bash
prisma streams list [OPTIONS]
```

**Options:**
- `--status, -s [active|paused|archived]`: Filter by stream status
- `--config, -c PATH`: Path to configuration file

**Examples:**
```bash
# List all streams
prisma streams list

# Filter active streams only
prisma streams list --status active
```

#### Update Streams
```bash
prisma streams update [STREAM_ID] [OPTIONS]
```

**Arguments:**
- `STREAM_ID`: Optional stream ID to update (if not provided, use --all)

**Options:**
- `--all, -a`: Update all active streams
- `--force, -f`: Force update even if not due
- `--refresh-cache, -r`: Refresh cached metadata instead of using cache
- `--config, -c PATH`: Path to configuration file

**Examples:**
```bash
# Update all active streams
prisma streams update --all

# Update specific stream
prisma streams update neural-networks-2024

# Force update with cache refresh
prisma streams update --all --force --refresh-cache
```

#### Stream Information
```bash
prisma streams info STREAM_ID [OPTIONS]
```

**Arguments:**
- `STREAM_ID`: Stream identifier

**Options:**
- `--config, -c PATH`: Path to configuration file

**Examples:**
```bash
# Get detailed stream information
prisma streams info ai-ethics
```

#### Stream Summary
```bash
prisma streams summary [OPTIONS]
```

**Options:**
- `--config, -c PATH`: Path to configuration file

**Examples:**
```bash
# Overview of all streams
prisma streams summary
```

### 2. Literature Reviews (`review`)

Generate comprehensive literature reviews for research topics.

#### Generate Review
```bash
prisma review TOPIC [OPTIONS]
```

**Arguments:**
- `TOPIC`: Research topic to search for (e.g., "neural networks")

**Options:**
- `--output, -o PATH`: Output file path
- `--sources, -s TEXT`: Data sources (arxiv,pubmed,scholar)
- `--limit, -l INTEGER`: Maximum number of papers
- `--zotero-only`: Use only Zotero library
- `--include-authors`: Include author analysis
- `--refresh-cache, -r`: Refresh cached metadata
- `--config, -c PATH`: Path to configuration file

**Examples:**
```bash
# Basic literature review
prisma review "neural networks" --output nn_review.md

# Use specific sources with limit
prisma review "AI ethics" --sources arxiv,scholar --limit 50

# Zotero-only mode
prisma review "machine learning" --zotero-only

# Include author analysis
prisma review "transformers" --include-authors --limit 30
```

### 3. System Management (`status`)

Check system status and configuration.

#### System Status
```bash
prisma status [OPTIONS]
```

**Options:**
- `--verbose, -v`: Show detailed status information

**Examples:**
```bash
# Basic status check
prisma status

# Detailed system information
prisma status --verbose
```

**Status Checks:**
- ✅ Configuration files loaded
- ✅ Zotero connection (Local API/Web API)
- ✅ Required dependencies installed
- ✅ Storage directories available
- ✅ LLM integration (Ollama)

### 4. Zotero Integration (`zotero`)

Manage Zotero connections and operations.

#### Test Connection
```bash
prisma zotero test-connection [OPTIONS]
```

**Options:**
- `--config, -c PATH`: Path to configuration file

**Examples:**
```bash
# Test Zotero connectivity
prisma zotero test-connection
```

#### List Collections
```bash
prisma zotero list-collections [OPTIONS]
```

**Options:**
- `--config, -c PATH`: Path to configuration file

**Examples:**
```bash
# Show all Zotero collections
prisma zotero list-collections
```

#### Sync Status
```bash
prisma zotero sync-status [OPTIONS]
```

**Options:**
- `--config, -c PATH`: Path to configuration file

**Examples:**
```bash
# Check Zotero sync status
prisma zotero sync-status
```

## Configuration

Prisma uses YAML configuration files for settings:

```bash
# Use custom config file
prisma --config ./my-config.yaml streams list

# Environment-specific configs
prisma --config ./configs/research.yaml review "topic"
```

## Common Workflows

### Setting Up Research Monitoring
```bash
# 1. Check system status
prisma status --verbose

# 2. Create research streams
prisma streams create "AI Safety" "AI safety alignment" --frequency weekly
prisma streams create "Quantum ML" "quantum machine learning" --frequency monthly

# 3. Initial population
prisma streams update --all --force

# 4. Monitor progress
prisma streams summary
```

### Generating Literature Reviews
```bash
# 1. Quick review from internet sources
prisma review "neural architecture search" --sources arxiv,scholar --limit 25

# 2. Comprehensive review with Zotero
prisma review "federated learning" --include-authors --limit 50

# 3. Zotero-only review for existing library
prisma review "computer vision" --zotero-only
```

### Troubleshooting
```bash
# Check system status
prisma status --verbose

# Test Zotero connection
prisma zotero test-connection

# Force update with fresh data
prisma streams update stream-id --force --refresh-cache
```

## Exit Codes

- `0`: Success
- `1`: General error
- `2`: Configuration error
- `3`: Zotero connection error
- `4`: LLM integration error

## Environment Variables

```bash
export PRISMA_CONFIG_PATH="/path/to/config.yaml"
export PRISMA_DEBUG=1                    # Enable debug output
export ZOTERO_API_KEY="your-api-key"     # Override config API key
export OLLAMA_HOST="localhost:11434"     # Override LLM host
```

## Advanced Usage

### Batch Operations
```bash
# Update multiple streams with specific criteria
for stream in ai-ethics quantum-ml neural-nets; do
  prisma streams update $stream --force
done

# Generate multiple reviews
for topic in "AI safety" "quantum computing" "federated learning"; do
  prisma review "$topic" --output "${topic// /_}_review.md"
done
```

### Automation Scripts
```bash
#!/bin/bash
# Daily research monitoring script

echo "🔍 Daily Research Update"
prisma streams update --all
echo "📊 Research Summary"
prisma streams summary
```

### Custom Configuration
```yaml
# research-config.yaml
search:
  sources: ["arxiv", "semanticscholar"]
  default_limit: 50

llm:
  provider: "ollama"
  model: "llama3.1:8b"
  host: "localhost:11434"

zotero:
  mode: "hybrid"
  api_key: "${ZOTERO_API_KEY}"
  library_id: "12345"
```

## Error Handling

Prisma provides detailed error messages and suggestions:

```bash
❌ Error: Zotero connection failed
   Suggestion: Ensure Zotero Desktop is running with Local API enabled
   
❌ Error: No papers found for query
   Suggestion: Try broader search terms or different sources

⚠️  Warning: LLM analysis failed for 2 papers
   Info: Papers were saved but analysis incomplete
```

## See Also

- [Configuration Guide](configuration.md) - Complete configuration reference
- [Research Streams Guide](research-streams-guide.md) - Detailed streams documentation
- [Zotero Integration](zotero-integration.md) - Zotero setup and usage
- [Development Setup](development-setup.md) - Developer installation guide