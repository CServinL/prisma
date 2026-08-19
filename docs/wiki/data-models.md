# Data Models

Prisma uses **Pydantic v2** for all internal data models. Every API response, search result, and Zotero object is validated at runtime.

## Model Files

| File | Models |
|------|--------|
| `storage/models/agent_models.py` | `PaperMetadata`, `BookMetadata`, `SearchResult`, `CoordinatorResult` |
| `storage/models/zotero_models.py` | `ZoteroItem`, `ZoteroCreator`, `ZoteroTag`, `ZoteroCollection`, `ZoteroSearchQuery` |
| `storage/models/vault_models.py` | Vault nodes (`Note`, `Source`, `Stream`, `StreamStatus`, `RefreshFrequency`) and the chat session graph (`Chat`, `TurnNode`, `ToolCallNode`, `ThinkingNode`, `CitedClaimNode`/`InferenceNode`, `MediaNode`) — see [Chat Session Graph](#chat-session-graph) below and `docs/concepts/chat-session-graph.md` for the full design |
| `storage/models/api_response_models.py` | `OpenLibraryResponse`, `SemanticScholarResponse`, `GoogleBooksResponse`, `ArXivEntry`, `LLMRelevanceResult` |
| `storage/models/source_quality.py` | `SourceQuality`, `SourceMetadata`, `AcademicValidationCriteria`, `SOURCE_REGISTRY` |
| `storage/models/chroma_models.py` | `ChromaStatus` |
| `storage/models/kg_models.py` | `KGStatus`, `GraphQueryResult` |

---

## Zotero Models

### `ZoteroCreator`

Supports both Python-style and Zotero API field names via aliases:

```python
# Python style
creator = ZoteroCreator(creator_type="author", first_name="Jane", last_name="Doe")

# Zotero API style (also accepted)
creator = ZoteroCreator(creator_type="author", firstName="Jane", lastName="Doe")
```

### `ZoteroItem`

```python
item = ZoteroItem(
    key="ITEM123",
    item_type="journalArticle",
    title="Machine Learning Applications",
    creators=[creator],
    tags=[ZoteroTag(tag="ML")],
    date="2024-01-15"
)

# Computed properties
item.year              # 2024
item.citation_key      # "Doe2024MachineLearningApplications"
item.is_academic_paper # True
```

Supports `itemType` / `item_type` field aliases for direct Zotero API round-trips.

### `ZoteroCollection`

```python
collection = ZoteroCollection(
    key="COLL123",
    name="AI Research",
    parent_collection="PARENT456"
)
```

---

## Search / Pipeline Models

### `PaperMetadata`

Required fields: `title`, `authors`, `abstract`, `source`, `url`  
Optional: `doi`, `arxiv_id`, `journal`, `volume`, `issue`, `pages`, `published_date`, `pdf_url`, `connected_papers_url`, `confidence_score`

### `BookMetadata`

Required: `title`, `authors`, `source`, `url`  
Optional: `isbn_10`, `isbn_13`, `publisher`, `published_date`, `page_count`, `subjects`, `language`, `preview_url`, `cover_url`

### `SearchResult`

```python
SearchResult(
    papers=[...],        # List[PaperMetadata]
    books=[...],         # List[BookMetadata]
    total_found=23,
    sources_searched=["arxiv", "semanticscholar"],
    query="neural networks",
    timestamp=datetime.now()
)
```

### `CoordinatorResult`

Returned by `PrismaCoordinator.run_review()`:

```python
CoordinatorResult(
    success=True,
    papers_analyzed=12,
    authors_found=8,
    output_file="./outputs/review.md",
    total_duration=142.3,
    pipeline_metadata={
        "papers_found": 20,
        "papers_discarded": 5,
        "papers_relevant": 15,
        "papers_existing": 3,
        "papers_new": 12,
        "saved_to_zotero": 10,
        ...
    },
    errors=[],
    warnings=[]
)
```

---

## Chat Session Graph

A `Chat` is stored as pure JSON (`.sess` files, `CHAT_SCHEMA_VERSION`, versioned via
`schema_gov.VersionedModel` with a migration chain), not `.md` — full design in
`docs/concepts/chat-session-graph.md`. **`thoughts`/`ThinkingNode`, `relation="paraphrase"`,
and `CHAT_SCHEMA_VERSION=4` below are not yet merged to `main`** (branch
`chat-schema-v3-toulmin-media-attachments`) — everything else on this page is. `Chat.messages` is a main line of `TurnNode`s; everything
else (tool calls, reasoning, claims, media) is a typed branch off the turn that produced it,
built with `SessionOrchestrator`/`session_graph.py` into an in-memory `networkx.MultiDiGraph` per
active session, not stored as explicit edge objects on disk:

```python
TurnNode(
    role=ChatRole.assistant,
    content=RichContent(format=ContentFormat.markdown, value="..."),
    tool_calls=[ToolCallNode(tool="search_vault", args={"query": "..."}, result="...", status="ok")],
    thoughts=[ThinkingNode(thought="...", thought_number=1)],       # THINK: tool, gated by has_native_reasoning
    claims=[CitedClaimNode(index=1, claim_text="...", sources=["some-slug"], relation="citation")],
    recalls=[RecallRef(node_id="...", node_kind="turn")],           # RECALL tool hits
    alternates=[...],                                                # prior regeneration attempts
)
```

`relation` on `CitedClaimNode` is one of `citation` (verbatim quote), `paraphrase` (close
restatement), `attribution` (paraphrased/synthesized), or `relational` (connects 2+ sources);
content the model can't trace to any source becomes an `InferenceNode` instead (no `relation`
field — the `kind` discriminator already says so).

---

## Serialization

All models use standard Pydantic v2:

```python
# To dict
data = item.model_dump()

# To JSON
json_str = item.model_dump_json(indent=2)

# From dict (with validation)
item = ZoteroItem.model_validate(data)
```

---

## Running Model Tests

```bash
source ~/prisma/bin/activate
pytest tests/unit/integrations/zotero/test_models.py -v
```
