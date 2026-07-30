"""
Configuration utilities for Prisma using Pydantic.
Load and validate TOML configuration files with robust type validation.
"""

import os
import tomllib
import logging
from pathlib import Path
from typing import Any, Dict, Optional, List
from pydantic import BaseModel, Field, field_validator, ConfigDict

logger = logging.getLogger(__name__)


class ZoteroConfig(BaseModel):
    """Zotero API configuration"""
    model_config = ConfigDict(arbitrary_types_allowed=True)
    
    enabled: bool = Field(False, description="Whether Zotero integration is enabled")
    api_key: Optional[str] = Field(None, description="Zotero API key — prefer api_key_env instead")
    api_key_env: Optional[str] = Field(
        None,
        description=(
            "Env var holding the API key — takes priority over api_key when set, "
            "same pattern as LLMConfig/ChatConfig's api_key_env. Lets the real "
            "secret live in an env var (e.g. a K8s Secret) instead of this file."
        ),
    )
    library_id: Optional[str] = Field(None, description="Zotero library ID — prefer library_id_env instead")
    library_id_env: Optional[str] = Field(
        None,
        description=(
            "Env var holding the library ID — takes priority over library_id "
            "when set, same api_key_env pattern. Not a secret, but keeping it "
            "alongside api_key_env avoids identifying info in a ConfigMap."
        ),
    )
    library_type: str = Field("user", description="Library type: 'user' or 'group'")
    default_collections: List[str] = Field(default_factory=list, description="Default collections to search")
    include_notes: bool = Field(False, description="Include notes in results")
    include_attachments: bool = Field(False, description="Include attachments in results")

    # Legacy local database support
    library_path: str = Field(
        default_factory=lambda: str(Path.home() / "Zotero" / "zotero.sqlite"),
        description="Path to local Zotero database"
    )
    data_directory: str = Field(
        default_factory=lambda: str(Path.home() / "Zotero"),
        description="Path to Zotero data directory"
    )

    @field_validator('library_type')
    @classmethod
    def validate_library_type(cls, v):
        if v not in ('user', 'group'):
            raise ValueError('library_type must be "user" or "group"')
        return v

    def resolve_api_key(self) -> Optional[str]:
        """Effective API key: api_key_env (if set) takes priority over the
        literal api_key field. Raises if api_key_env is set but the env var
        isn't — fail loud on a misconfigured indirection rather than silently
        falling back to a (possibly stale) literal value or None."""
        if self.api_key_env:
            key = os.environ.get(self.api_key_env)
            if not key:
                raise RuntimeError(
                    f"sources.zotero.api_key_env={self.api_key_env!r} is set but not present in the environment"
                )
            return key
        return self.api_key

    def resolve_library_id(self) -> Optional[str]:
        """Effective library ID: library_id_env (if set) takes priority over
        the literal library_id field. Same fail-loud contract as
        resolve_api_key() — a misconfigured indirection should be obvious,
        not silently fall through to None/offline mode."""
        if self.library_id_env:
            value = os.environ.get(self.library_id_env)
            if not value:
                raise RuntimeError(
                    f"sources.zotero.library_id_env={self.library_id_env!r} is set but not present in the environment"
                )
            return value
        return self.library_id


class LLMConfig(BaseModel):
    """LLM configuration — used for KG extraction (see kg_app.py). Cloud
    routing (openrouter) mirrors ChatConfig's own pattern (ADR-014): api_key
    comes from an env var, never this file, and there's no local endpoint to
    live-query for context window, so it's an explicit config value instead."""
    provider: str = Field("ollama", description="ollama | llama_cpp | openrouter")
    model: str = Field("qwen2.5:7b-32k", description="Model name")
    host: str = Field("localhost:11434", description="Host and port — ignored for openrouter")
    max_concurrent_inferences: int = Field(1, ge=1, le=16, description="Max simultaneous requests")
    api_key_env: Optional[str] = Field(
        None, description="Env var holding the API key — only used/required when provider=openrouter"
    )
    base_url_override: Optional[str] = Field(
        None, description="Override the provider's default base_url; None derives it from provider"
    )
    context_window: Optional[int] = Field(
        None,
        description=(
            "Static context window for providers with no live-queryable endpoint "
            "(openrouter) — ollama/llama_cpp instead resolve this live per-call "
            "(see KnowledgeGraphService._resolve_context_window) and ignore this field."
        ),
    )
    pool: Optional[str] = Field(
        None,
        description=(
            "compute_pools entry this backend's calls lease from — must match a name "
            "in compute_pools. None lets the lease land on whichever pool has free "
            "capacity, which is fine for local providers (ollama/llama_cpp) but risks "
            "misattribution for provider=openrouter: without a dedicated pool, a cloud "
            "call can be auto-routed onto a model_affinity'd local-GPU pool and start "
            "denying real local calls for no hardware reason (see resource_lock.lease's "
            "docstring). Set this explicitly when provider=openrouter."
        ),
    )

    @field_validator('provider')
    @classmethod
    def validate_provider(cls, v):
        if v not in ('ollama', 'llama_cpp', 'openrouter'):
            raise ValueError('provider must be "ollama", "llama_cpp", or "openrouter"')
        return v

    @property
    def base_url(self) -> str:
        """Generate base URL for API calls"""
        if self.base_url_override:
            return self.base_url_override
        if self.provider == "openrouter":
            return "https://openrouter.ai/api/v1"
        return f"http://{self.host}"

    def resolve_api_key(self) -> str:
        """Effective API key for this LLM backend. Only meaningful for
        provider="openrouter" -- ollama/llama_cpp's local OpenAI-compat
        servers don't check the key at all, so those get the placeholder
        "ollama" (kept non-empty for the openai SDK's requirement) without
        even looking at api_key_env. For openrouter, raises if
        api_key_env isn't set or the named env var is empty -- fail loud
        on a misconfigured indirection, same contract as
        ZoteroConfig.resolve_api_key/SourceQuotaConfig.resolve_api_key.
        Callers that need to degrade instead of crash (kg_app.py, which
        must still start with a partially-broken LLM config) catch this
        themselves."""
        if self.provider != "openrouter":
            return "ollama"
        if not self.api_key_env:
            raise RuntimeError("llm.provider is 'openrouter' but llm.api_key_env is not set")
        key = os.environ.get(self.api_key_env)
        if not key:
            raise RuntimeError(f"llm.api_key_env={self.api_key_env!r} is not set in the environment")
        return key


class ChatConfig(BaseModel):
    """Chat module LLM backend configuration (ADR-014: openai SDK, multi-base_url)."""
    provider: str = Field("ollama", description="ollama | openrouter | anthropic")
    model: str = Field("qwen2.5:7b-32k", description="Model name for the chosen provider")
    base_url: Optional[str] = Field(
        None, description="Override the provider's default base_url; None derives it from provider"
    )
    api_key_env: Optional[str] = Field(
        None, description="Name of the environment variable holding the API key (None for local Ollama)"
    )
    pool: str = Field(
        "local-ollama",
        description="compute_pools entry this backend's calls lease from — must match a name in compute_pools",
    )
    context_window: int = Field(
        32768,
        description=(
            "This backend's real usable context window (verified via /api/ps's context_length "
            "for Ollama, not a claimed/configured value — see ADR-013's follow-up section on why "
            "that distinction matters). Drives ADR-015's compressed-vs-verbatim Excerpt mode: a "
            "small window (today's local qwen2.5:7b-32k) needs pinned turns compressed into a "
            "Summary; a large one (a future cloud backend) can afford to keep them verbatim."
        ),
    )
    max_tokens: int = Field(
        2000,
        description=(
            "Hard cap on generated tokens per chat completion. Without this, a rambling or "
            "confused generation has nothing to stop it (found live: the same gap in kg's "
            "extraction calls let a single section's call run for minutes — see "
            "knowledge_graph_service.py's _call_ollama_extract num_predict comment)."
        ),
    )

    @field_validator('provider')
    @classmethod
    def validate_provider(cls, v):
        if v not in ('ollama', 'llama_cpp', 'openrouter', 'anthropic'):
            raise ValueError('provider must be "ollama", "llama_cpp", "openrouter", or "anthropic"')
        return v


class OutputConfig(BaseModel):
    """Output configuration"""
    directory: str = Field("./outputs", description="Output directory")
    format: str = Field("markdown", description="Output format")
    
    @field_validator('format')
    @classmethod
    def validate_format(cls, v):
        valid_formats = ['markdown', 'json', 'yaml', 'txt']
        if v not in valid_formats:
            raise ValueError(f'format must be one of {valid_formats}')
        return v


class SourceQuotaConfig(BaseModel):
    """Per-source quota/API-key override for one entry in
    SearchConfig.source_overrides. Any field left unset falls back to that
    source module's own hardcoded, web-verified default (see
    prisma/integrations/sources/) -- so zero config is required for any
    source to work out of the box; this only matters once you have a real
    API key (raises a source's rate limit) or want to tune a limit
    yourself. Same api_key/api_key_env resolver pattern as ZoteroConfig
    above -- api_key_env takes priority, keeps the real secret out of this
    file."""
    model_config = ConfigDict(extra="ignore")

    requests_per_second: Optional[float] = Field(
        None, gt=0, description="Override this source's rate limit (requests/second)"
    )
    daily_cap: Optional[int] = Field(
        None, ge=1, description="Override this source's hard daily request cap"
    )
    api_key: Optional[str] = Field(None, description="API key -- prefer api_key_env instead")
    api_key_env: Optional[str] = Field(
        None,
        description="Env var holding the API key -- takes priority over api_key when set, same pattern as ZoteroConfig.api_key_env",
    )

    def resolve_api_key(self, source_name: str = "") -> Optional[str]:
        """Same fail-loud contract as ZoteroConfig.resolve_api_key(): if
        api_key_env is set but the env var isn't, raise rather than
        silently falling back to None/an unauthenticated request.
        `source_name` is only used to make the error message point at the
        right [sources.*] block."""
        if self.api_key_env:
            key = os.environ.get(self.api_key_env)
            if not key:
                label = f"sources.{source_name}" if source_name else "a source"
                raise RuntimeError(
                    f"{label}.api_key_env={self.api_key_env!r} is set but not present in the environment"
                )
            return key
        return self.api_key


class SearchConfig(BaseModel):
    """Search configuration"""
    model_config = ConfigDict(extra="ignore")

    default_limit: int = Field(10, ge=1, le=1000, description="Default search limit")
    sources: List[str] = Field(
        default_factory=lambda: ['semanticscholar', 'arxiv'],
        description="Search sources",
    )
    min_confidence_score: float = Field(0.5, ge=0.0, le=1.0)
    prefer_high_quality: bool = Field(True)
    require_academic_validation: bool = Field(True)
    source_overrides: Dict[str, SourceQuotaConfig] = Field(
        default_factory=dict,
        description=(
            "Per-source quota/API-key overrides, keyed by source name "
            "(e.g. 'pubmed', 'ieee_xplore', 'semanticscholar', 'googlebooks'). "
            "Sources not listed here use their module's built-in defaults."
        ),
    )

    @field_validator('sources')
    @classmethod
    def validate_sources(cls, v):
        valid_sources = ['arxiv', 'zotero', 'pubmed', 'google_scholar', 'semanticscholar', 'openlibrary', 'googlebooks', 'ieee_xplore']
        for source in v:
            if source not in valid_sources:
                raise ValueError(f'source "{source}" not in valid sources: {valid_sources}')
        return v


class AnalysisConfig(BaseModel):
    """Analysis configuration"""
    summary_length: str = Field("medium", description="Summary length")
    nltk_dedup_sensitivity: str = Field(
        "medium",
        description=(
            "Controls NLTK stem-overlap thresholds used at dedup levels 4-5. "
            "low: certain=13 ambiguous=10 | medium: certain=10 ambiguous=7 | high: certain=7 ambiguous=5"
        ),
    )

    @field_validator('summary_length')
    @classmethod
    def validate_summary_length(cls, v):
        valid_lengths = ['short', 'medium', 'long', 'detailed']
        if v not in valid_lengths:
            raise ValueError(f'summary_length must be one of {valid_lengths}')
        return v

    @field_validator('nltk_dedup_sensitivity')
    @classmethod
    def validate_nltk_dedup_sensitivity(cls, v):
        valid = ['low', 'medium', 'high']
        if v not in valid:
            raise ValueError(f'nltk_dedup_sensitivity must be one of {valid}')
        return v


class LoggingConfig(BaseModel):
    """Logging configuration"""
    level: str = Field("INFO", description="Log level")
    file: str = Field("./logs/prisma.log", description="Log file path")
    
    @field_validator('level')
    @classmethod
    def validate_level(cls, v):
        valid_levels = ['DEBUG', 'INFO', 'WARNING', 'ERROR', 'CRITICAL']
        if v.upper() not in valid_levels:
            raise ValueError(f'level must be one of {valid_levels}')
        return v.upper()


class SourcesConfig(BaseModel):
    """Sources configuration"""
    zotero: ZoteroConfig = Field(default_factory=lambda: ZoteroConfig())


class RetrievalConfig(BaseModel):
    provider: str = Field("ollama", description="ollama | llama_cpp — embedding backend for ChromaDB")
    embedding_model: str = Field("nomic-embed-text", description="Embedding model name for ChromaDB semantic search")
    ollama_base_url: str = Field(
        "http://localhost:11434",
        description="Embedding backend base URL — name kept for backward compat, used regardless of provider",
    )
    chroma_port: int = Field(8767, description="Port of the supervised ChromaDB server process (see ADR-012)")

    @field_validator('provider')
    @classmethod
    def validate_provider(cls, v):
        if v not in ('ollama', 'llama_cpp'):
            raise ValueError('provider must be "ollama" or "llama_cpp"')
        return v


class AuthConfig(BaseModel):
    """Server auth (ADR-011) — password mode only; oidc is reserved for a
    future WAN-facing implementation and rejected at load time if set."""
    mode: str = Field("none", description="none | password | oidc")
    password_hash: str = Field("", description="bcrypt hash — generate with: prisma auth hash-password")
    session_ttl_hours: int = Field(720, description="JWT session lifetime (default 30 days)")

    @field_validator('mode')
    @classmethod
    def validate_mode(cls, v):
        if v not in ('none', 'password', 'oidc'):
            raise ValueError('mode must be "none", "password", or "oidc"')
        return v


class ServerConfig(BaseModel):
    """Zone-based auth gating (ADR-011 / deployment-models.md). host/port
    here are for schema parity with the documented YAML — the actual bind
    address/port are still CLI flags on `prisma serve`, unrelated to auth."""
    host: str = Field("127.0.0.1", description="Documented for parity; --host on `prisma serve` is authoritative")
    port: int = Field(8765, description="Documented for parity; --port on `prisma serve` is authoritative")
    trusted_proxies: List[str] = Field(
        default_factory=lambda: ["127.0.0.1", "::1"],
        description="IPs allowed to set X-Forwarded-For — trusted only when the direct connection is loopback",
    )
    auth: AuthConfig = Field(default_factory=lambda: AuthConfig())


class KGConfig(BaseModel):
    """Knowledge graph indexer tuning (`[kg]` in config.toml), read only by
    the kg worker process (kg_app.py). Per-deployment, not shared constants —
    a cloud-routed extraction model (cheap per-token cost, no local-hardware
    speed concern) can afford a much higher cap than a local model
    (cservinl, 2026-07-25)."""
    max_output_fraction: float = Field(0.25, description="Fraction of the model's context window reserved for output tokens")
    max_entities: int = Field(15, description="Max entities extracted per chunk")
    max_relationships: int = Field(20, description="Max relationships extracted per chunk")
    index_extensions: List[str] = Field(
        default_factory=list,
        description="File extensions to index, with or without a leading dot (both '.md' and 'md' work). Empty = caller's own default.",
    )
    extraction_concurrency: int = Field(3, description="Concurrent extraction calls to the LLM backend")
    # See docs/kg-extraction-context-length.md — a controlled test on real
    # paper content found the old 8000 default produced ~10x fewer unique
    # entities and ~4x fewer relationships than chunking at ~2000
    # tokens/section, not just marginally worse. Lowered further to 1000
    # (2026-07-05, per cservinl) after a dense chunk's JSON output exceeded
    # max_tokens and got dropped — smaller input chunks mean proportionally
    # smaller (and less likely to truncate) output.
    token_budget: int = Field(1000, description="Max tokens per extraction chunk")


class PrismaConfig(BaseModel):
    """Complete Prisma configuration with validation"""
    model_config = ConfigDict(arbitrary_types_allowed=True)

    vault_root: str = Field("", description="Vault directory path. Empty = ~/prisma-vault")
    sources: SourcesConfig = Field(default_factory=lambda: SourcesConfig())
    llm: LLMConfig = Field(default_factory=lambda: LLMConfig())
    kg: KGConfig = Field(default_factory=lambda: KGConfig())
    chat: ChatConfig = Field(default_factory=lambda: ChatConfig())
    output: OutputConfig = Field(default_factory=lambda: OutputConfig())
    search: SearchConfig = Field(default_factory=lambda: SearchConfig())
    analysis: AnalysisConfig = Field(default_factory=lambda: AnalysisConfig())
    logging: LoggingConfig = Field(default_factory=lambda: LoggingConfig())
    retrieval: RetrievalConfig = Field(default_factory=lambda: RetrievalConfig())
    server: ServerConfig = Field(default_factory=lambda: ServerConfig())

    @field_validator('server')
    @classmethod
    def validate_server_auth_mode(cls, v):
        if v.auth.mode == 'oidc':
            raise ValueError(
                'server.auth.mode "oidc" is not implemented yet (ADR-011 WAN tier) — '
                'use "none" or "password"'
            )
        return v


class ConfigLoader:
    """Load and validate configuration from TOML files and environment variables."""

    def __init__(self, config_path: str | Path | None = None):
        # Explicit param takes priority over PRISMA_CONFIG/default-location
        # discovery — for callers (e.g. the CLI's --config flag) that
        # already have a specific path in hand, rather than needing to set
        # an env var as a side effect just to point this at it.
        self.config_path = Path(config_path).expanduser() if config_path else self._get_config_path()
        self.config = self._load_config()

    def get_vault_root(self) -> Path:
        root = self.config.vault_root.strip()
        if root:
            return Path(root).expanduser().resolve()
        return Path.home() / "prisma-vault"

    def get_kg_config(self) -> KGConfig:
        return self.config.kg

    def _get_config_path(self) -> Optional[Path]:
        """Get configuration file path from environment or default location.

        This exact precedence is duplicated in prisma/server/supervisor.py's
        _read_raw_config() -- that module can't import this class (stdlib-only,
        see its module docstring) but must resolve the same file the workers
        it spawns will read. If either side's precedence changes, change the
        other to match, or the supervisor and the api/kg workers it starts
        can silently disagree about vault_root/compute_pools."""
        # Check environment variable first
        env_config = os.getenv('PRISMA_CONFIG')
        if env_config:
            config_path = Path(env_config).expanduser()
            if config_path.exists():
                return config_path
        
        # Check default locations
        default_locations = [
            Path.home() / '.config' / 'prisma' / 'config.toml',
            Path('./config.toml'),
            Path('./prisma-config.toml')
        ]
        
        for path in default_locations:
            if path.exists():
                return path
        
        return None
    
    def _load_config(self) -> PrismaConfig:
        """Load configuration from TOML file with defaults and validation."""
        user_data = {}

        if self.config_path:
            try:
                with open(self.config_path, 'rb') as f:
                    user_data = tomllib.load(f) or {}
                logger.debug(f"Loaded config from {self.config_path}")
            except Exception as e:
                logger.error(f"Failed to load config from {self.config_path}: {e}")
                logger.warning("Using default configuration")
        else:
            logger.debug("No config file found, using defaults")
        
        try:
            # Create Pydantic config with validation
            config = PrismaConfig(**user_data)
            return config
        except Exception as e:
            print(f"[ERROR] Configuration validation failed: {e}")
            print("[WARNING] Using default configuration")
            return PrismaConfig()
    
    def get(self, key_path: str, default: Any = None) -> Any:
        """
        Get configuration value using dot notation.
        
        Args:
            key_path: Dot-separated path like 'llm.model' or 'sources.zotero.library_path'
            default: Default value if key not found
            
        Returns:
            Configuration value or default
        """
        keys = key_path.split('.')
        value = self.config
        
        try:
            for key in keys:
                value = getattr(value, key)
            return value
        except (AttributeError, TypeError):
            return default
    
    def get_llm_config(self) -> LLMConfig:
        """Get LLM configuration for Ollama integration."""
        return self.config.llm
    
    def get_search_config(self) -> SearchConfig:
        """Get search configuration."""
        return self.config.search
    
    def get_output_config(self) -> OutputConfig:
        """Get output configuration."""
        return self.config.output
    
    def get_zotero_config(self) -> ZoteroConfig:
        """Get Zotero configuration for API integration."""
        return self.config.sources.zotero
    
    def get_retrieval_config(self) -> RetrievalConfig:
        return self.config.retrieval

    def get_chat_config(self) -> ChatConfig:
        return self.config.chat

    def get_server_config(self) -> ServerConfig:
        return self.config.server

    def has_zotero_credentials(self) -> bool:
        """Check if Zotero API credentials are configured."""
        zotero_config = self.config.sources.zotero
        try:
            api_key = zotero_config.resolve_api_key()
            library_id = zotero_config.resolve_library_id()
        except RuntimeError:
            return False
        return (
            zotero_config.enabled and
            api_key is not None and
            library_id is not None
        )


# Global config instance
config = ConfigLoader()