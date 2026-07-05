"""
Configuration utilities for Prisma using Pydantic.
Load and validate YAML configuration files with robust type validation.
"""

import os
import yaml
import logging
from pathlib import Path
from typing import Dict, Any, Optional, List
from pydantic import BaseModel, Field, field_validator, ConfigDict

logger = logging.getLogger(__name__)


class ZoteroConfig(BaseModel):
    """Zotero API configuration"""
    model_config = ConfigDict(arbitrary_types_allowed=True)
    
    enabled: bool = Field(False, description="Whether Zotero integration is enabled")
    mode: str = Field("hybrid", description="Zotero client mode: 'hybrid', 'local_api', 'sqlite', 'web'")
    api_key: Optional[str] = Field(None, description="Zotero API key")
    library_id: Optional[str] = Field(None, description="Zotero library ID")
    library_type: str = Field("user", description="Library type: 'user' or 'group'")
    default_collections: List[str] = Field(default_factory=list, description="Default collections to search")
    include_notes: bool = Field(False, description="Include notes in results")
    include_attachments: bool = Field(False, description="Include attachments in results")
    
    # Local API configuration
    local_api_url: str = Field("http://localhost:23119", description="Zotero Local HTTP API URL")
    
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


class LLMConfig(BaseModel):
    """LLM configuration"""
    provider: str = Field("ollama", description="LLM provider")
    model: str = Field("prisma-llm:7b", description="Model name")
    host: str = Field("localhost:11434", description="Host and port")
    max_concurrent_inferences: int = Field(1, ge=1, le=16, description="Max simultaneous Ollama requests")

    @property
    def base_url(self) -> str:
        """Generate base URL for API calls"""
        return f"http://{self.host}"


class ChatConfig(BaseModel):
    """Chat module LLM backend configuration (ADR-014: openai SDK, multi-base_url)."""
    provider: str = Field("ollama", description="ollama | openrouter | anthropic")
    model: str = Field("prisma-llm:7b", description="Model name for the chosen provider")
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
            "small window (today's local prisma-llm:7b) needs pinned turns compressed into a "
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
        if v not in ('ollama', 'openrouter', 'anthropic'):
            raise ValueError('provider must be "ollama", "openrouter", or "anthropic"')
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

    @field_validator('sources')
    @classmethod
    def validate_sources(cls, v):
        valid_sources = ['arxiv', 'zotero', 'pubmed', 'google_scholar', 'semanticscholar', 'openlibrary', 'googlebooks', 'academia']
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
    embedding_model: str = Field("nomic-embed-text", description="Ollama embedding model for ChromaDB semantic search")
    ollama_base_url: str = Field("http://localhost:11434", description="Ollama base URL for embeddings")
    chroma_port: int = Field(8767, description="Port of the supervised ChromaDB server process (see ADR-012)")


class PrismaConfig(BaseModel):
    """Complete Prisma configuration with validation"""
    model_config = ConfigDict(arbitrary_types_allowed=True)

    sources: SourcesConfig = Field(default_factory=lambda: SourcesConfig())
    llm: LLMConfig = Field(default_factory=lambda: LLMConfig())
    chat: ChatConfig = Field(default_factory=lambda: ChatConfig())
    output: OutputConfig = Field(default_factory=lambda: OutputConfig())
    search: SearchConfig = Field(default_factory=lambda: SearchConfig())
    analysis: AnalysisConfig = Field(default_factory=lambda: AnalysisConfig())
    logging: LoggingConfig = Field(default_factory=lambda: LoggingConfig())
    retrieval: RetrievalConfig = Field(default_factory=lambda: RetrievalConfig())


class ConfigLoader:
    """Load and validate configuration from YAML files and environment variables."""
    
    def __init__(self):
        self.config_path = self._get_config_path()
        self.config = self._load_config()
    
    def _get_config_path(self) -> Optional[Path]:
        """Get configuration file path from environment or default location."""
        # Check environment variable first
        env_config = os.getenv('PRISMA_CONFIG')
        if env_config:
            config_path = Path(env_config).expanduser()
            if config_path.exists():
                return config_path
        
        # Check default locations
        default_locations = [
            Path.home() / '.config' / 'prisma' / 'config.yaml',
            Path('./config.yaml'),
            Path('./prisma-config.yaml')
        ]
        
        for path in default_locations:
            if path.exists():
                return path
        
        return None
    
    def _load_config(self) -> PrismaConfig:
        """Load configuration from YAML file with defaults and validation."""
        user_data = {}
        
        if self.config_path:
            try:
                with open(self.config_path, 'r', encoding='utf-8') as f:
                    user_data = yaml.safe_load(f) or {}
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

    def has_zotero_credentials(self) -> bool:
        """Check if Zotero API credentials are configured."""
        zotero_config = self.config.sources.zotero
        return (
            zotero_config.enabled and
            zotero_config.api_key is not None and
            zotero_config.library_id is not None
        )


# Global config instance
config = ConfigLoader()