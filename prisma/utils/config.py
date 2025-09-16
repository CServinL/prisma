"""
Configuration utilities for Prisma using Pydantic.
Load and validate YAML configuration files with robust type validation.
"""

import os
import yaml
from pathlib import Path
from typing import Dict, Any, Optional, List
from pydantic import BaseModel, Field, field_validator, ConfigDict


class ZoteroConfig(BaseModel):
    """Zotero API configuration"""
    model_config = ConfigDict(arbitrary_types_allowed=True)
    
    enabled: bool = Field(False, description="Whether Zotero integration is enabled")
    api_key: Optional[str] = Field(None, description="Zotero API key")
    library_id: Optional[str] = Field(None, description="Zotero library ID")
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


class LLMConfig(BaseModel):
    """LLM configuration"""
    provider: str = Field("ollama", description="LLM provider")
    model: str = Field("llama3.1:8b", description="Model name")
    host: str = Field("localhost:11434", description="Host and port")
    
    @property
    def base_url(self) -> str:
        """Generate base URL for API calls"""
        return f"http://{self.host}"


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
    default_limit: int = Field(10, ge=1, le=1000, description="Default search limit")
    sources: List[str] = Field(default_factory=lambda: ['arxiv'], description="Search sources")
    
    @field_validator('sources')
    @classmethod
    def validate_sources(cls, v):
        valid_sources = ['arxiv', 'zotero', 'pubmed', 'google_scholar']
        for source in v:
            if source not in valid_sources:
                raise ValueError(f'source "{source}" not in valid sources: {valid_sources}')
        return v


class AnalysisConfig(BaseModel):
    """Analysis configuration"""
    summary_length: str = Field("medium", description="Summary length")
    
    @field_validator('summary_length')
    @classmethod
    def validate_summary_length(cls, v):
        valid_lengths = ['short', 'medium', 'long', 'detailed']
        if v not in valid_lengths:
            raise ValueError(f'summary_length must be one of {valid_lengths}')
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
    zotero: ZoteroConfig = Field(default_factory=ZoteroConfig)


class PrismaConfig(BaseModel):
    """Complete Prisma configuration with validation"""
    model_config = ConfigDict(arbitrary_types_allowed=True)
    
    sources: SourcesConfig = Field(default_factory=SourcesConfig)
    llm: LLMConfig = Field(default_factory=LLMConfig)
    output: OutputConfig = Field(default_factory=OutputConfig)
    search: SearchConfig = Field(default_factory=SearchConfig)
    analysis: AnalysisConfig = Field(default_factory=AnalysisConfig)
    logging: LoggingConfig = Field(default_factory=LoggingConfig)


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
                print(f"[INFO] Loaded config from {self.config_path}")
            except Exception as e:
                print(f"[ERROR] Failed to load config from {self.config_path}: {e}")
                print("[WARNING] Using default configuration")
        else:
            print("[WARNING] No config file found, using defaults")
        
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
    
    def get_llm_config(self) -> Dict[str, Any]:
        """Get LLM configuration for Ollama integration."""
        llm_config = self.config.llm
        return {
            'provider': llm_config.provider,
            'model': llm_config.model,
            'host': llm_config.host,
            'base_url': llm_config.base_url
        }
    
    def get_search_config(self) -> Dict[str, Any]:
        """Get search configuration."""
        search_config = self.config.search
        return {
            'default_limit': search_config.default_limit,
            'sources': search_config.sources
        }
    
    def get_output_config(self) -> Dict[str, Any]:
        """Get output configuration."""
        output_config = self.config.output
        return {
            'directory': output_config.directory,
            'format': output_config.format
        }
    
    def get_zotero_config(self) -> Dict[str, Any]:
        """Get Zotero configuration for API integration."""
        zotero_config = self.config.sources.zotero
        return {
            'enabled': zotero_config.enabled,
            'api_key': zotero_config.api_key,
            'library_id': zotero_config.library_id,
            'library_type': zotero_config.library_type,
            'default_collections': zotero_config.default_collections,
            'include_notes': zotero_config.include_notes,
            'include_attachments': zotero_config.include_attachments
        }
    
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