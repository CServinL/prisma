# Research Streams Complete Guide

Comprehensive guide to using Research Streams for persistent topic monitoring.

## Creating and Managing Streams

### 1. Create a New Research Stream
```bash
# Basic creation
prisma streams create "Stream Name" "search query keywords"

# With full options
prisma streams create "LLMs for Edge" "LLM edge computing quantization" \
  --description "Research on optimizing LLMs for resource-constrained devices" \
  --frequency weekly \
  --parent-collection "AI Research"
```

**Options:**
- `--description, -d`: Detailed description of the research stream
- `--frequency, -f`: Update frequency (`daily`, `weekly`, `monthly`, `manual`)
- `--parent-collection, -p`: Parent Zotero collection key
- `--config, -c`: Custom configuration file path

### 2. List and Monitor Streams
```bash
# List all streams
prisma streams list

# Filter by status
prisma streams list --status active
prisma streams list --status paused

# Get system overview
prisma streams summary
```

**Output includes:**
- Stream status (🟢 active, 🟡 paused, 🔴 archived)
- Paper count and last update time
- Collection name and search query
- Update frequency and next scheduled update

### 3. Get Detailed Stream Information
```bash
# View complete stream details
prisma streams info llms-for-edge

# With custom config
prisma streams info stream-id --config ./my-config.yaml
```

**Detailed info shows:**
- Complete search criteria and smart tags
- Paper discovery statistics
- Zotero collection details
- Update history and performance metrics
- Configuration and frequency settings

### 4. Update Streams to Find New Papers
```bash
# Update all active streams
prisma streams update --all

# Update specific stream
prisma streams update llms-for-edge

# Force update (ignore frequency settings)
prisma streams update --all --force

# Update with custom config
prisma streams update stream-id --config ./research-config.yaml
```

**Update process:**
1. **Search External Sources**: Query arXiv, PubMed, Semantic Scholar
2. **Deduplication**: Remove papers already in your library
3. **Zotero Integration**: Save new papers to designated collection
4. **Smart Tagging**: Apply automatic tags based on stream criteria
5. **Statistics**: Report papers found, saved, and any errors

## Stream Workflow Examples

### Complete Research Stream Setup
```bash
# 1. Create stream for ongoing research
prisma streams create "Neural Architecture Search" \
  "neural architecture search NAS AutoML" \
  --description "Automated neural network design and optimization" \
  --frequency weekly

# 2. Check what was created
prisma streams info neural-architecture-search

# 3. Populate with initial papers
prisma streams update neural-architecture-search

# 4. Monitor regularly
prisma streams summary
```

### Batch Stream Management
```bash
# Create multiple related streams
prisma streams create "Vision Transformers" "vision transformer ViT image" --frequency weekly
prisma streams create "Language Models" "large language model LLM GPT" --frequency weekly
prisma streams create "Multimodal AI" "multimodal AI vision language" --frequency monthly

# Update all at once
prisma streams update --all

# Check system status
prisma streams summary
```

## Understanding Stream Output

### Stream List Output
```
📋 Found 3 research stream(s):

🟢 LLMs for small low-power devices (llms-for-small-lowpower-devices)
   📁 Collection: Prisma: LLMs for small low-power devices
   🔍 Query: LLM small devices low power edge computing mobile AI quantization compression
   📊 Papers: 15
   🔄 Frequency: weekly
   📅 Last updated: 2025-09-16 14:30
```

### Stream Info Output
```
📋 Research Stream Details

🆔 ID: llms-for-small-lowpower-devices
📝 Name: LLMs for small low-power devices
📄 Description: Research on optimizing LLMs for resource-constrained devices
📁 Collection: Prisma: LLMs for small low-power devices (key: ABC123)
🔍 Search Query: LLM small devices low power edge computing mobile AI quantization compression
📊 Papers Found: 15
🔄 Frequency: weekly
📅 Created: 2025-09-16 06:04
📅 Last Updated: 2025-09-16 14:30
📅 Next Update: 2025-09-23 14:30

🏷️ Smart Tags:
   - prisma-llms-for-small-lowpower-devices (Prisma stream identifier)
   - recent (Papers from last 2 years)
   - edge-computing (Automatically detected topic)

📈 Update History:
   - 2025-09-16 14:30: Found 8 new papers (arXiv: 5, Semantic Scholar: 3)
   - 2025-09-16 06:04: Initial creation
```

### Stream Update Output
```
🔄 Updating research stream: LLMs for small low-power devices

🔍 Searching external sources...
   📚 arXiv: Found 12 papers
   🧬 PubMed: Found 0 papers  
   🧠 Semantic Scholar: Found 8 papers

🔧 Processing results...
   ✅ Deduplicated: 20 → 15 papers (5 duplicates removed)
   ✅ New papers: 7 papers not in library
   
💾 Saving to Zotero...
   ✅ Collection: "Prisma: LLMs for small low-power devices"
   ✅ Papers saved: 7/7 successful
   ✅ Tags applied: prisma-auto, recent, edge-computing

📊 Update complete!
   📈 Stream now contains: 22 papers (+7)
   ⏰ Next update: 2025-09-23 14:30
```

## Troubleshooting Common Issues

### Collection Creation Failed
```bash
# If you see: "Failed to create Zotero collection"
# 1. Check if Zotero is running
# 2. Verify Zotero Local API is accessible
curl http://localhost:23119/api/

# 3. Try updating the stream anyway (collection created on demand)
prisma streams update your-stream-id
```

### No Papers Found
```bash
# If update finds no papers:
# 1. Check your search query is not too specific
prisma streams info your-stream-id

# 2. Try broader keywords
prisma streams create "Broader Topic" "machine learning AI" --frequency weekly

# 3. Check external API availability
prisma status  # (if this command exists)
```

### Stream Not Updating
```bash
# Force an update regardless of frequency
prisma streams update your-stream-id --force

# Check stream configuration
prisma streams info your-stream-id

# Verify last update time and frequency settings
```

## Advanced Usage

### Custom Configuration
```bash
# Use custom config for specific research setup
prisma streams create "Domain Research" "topic keywords" \
  --config ./my-research.yaml

# All stream commands support custom configs
prisma streams update --all --config ./lab-config.yaml
```

### Integration with Traditional Reviews
```bash
# 1. Create and populate stream
prisma streams create "Research Topic" "keywords" --frequency monthly
prisma streams update research-topic

# 2. Generate literature review from stream
prisma review research-topic --output "topic-review.md"

# 3. Continue monitoring and update review periodically
prisma streams update research-topic
prisma review research-topic --output "updated-review.md"
```

## Smart Collections + Tags Strategy

**📁 Collections = Research Topics**
- Hierarchical organization by research area
- Examples: `Neural Networks/Transformers`, `AI Ethics`, `Quantum ML`
- Each stream creates a dedicated Zotero collection

**🏷️ Tags = Cross-cutting Metadata**
- **Prisma Tags**: `prisma-[stream-id]`, `prisma-auto`
- **Temporal Tags**: `year-2024`, `recent`, `foundational`  
- **Methodology Tags**: `survey`, `empirical`, `theoretical`
- **Status Tags**: `to-read`, `key-paper`, `cited-in-report`
- **Quality Tags**: `high-impact`, `peer-reviewed`

## Research Streams Workflow

1. **Create Stream**: Define research topic and search criteria
2. **Initial Population**: Search and save relevant papers to collection
3. **Continuous Monitoring**: Periodic searches for new papers
4. **Smart Tagging**: Automatic categorization and metadata assignment
5. **Report Generation**: Analyze stream contents for literature reviews