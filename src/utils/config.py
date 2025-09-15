"""
Configuration utilities for Prisma.
Load and validate YAML configuration files.
"""

import os
import yaml
from pathlib import Path
from typing import Dict, Any, Optional


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
    
    def _load_config(self) -> Dict[str, Any]:
        """Load configuration from YAML file with defaults."""
        defaults = {
            'sources': {
                'zotero': {
                    'library_path': str(Path.home() / 'snap/zotero-snap/common/Zotero/zotero.sqlite'),
                    'data_directory': str(Path.home() / 'snap/zotero-snap/common/Zotero/')
                }
            },
            'llm': {
                'provider': 'ollama',
                'model': 'llama3.1:8b',
                'host': '172.29.32.1:11434'  # WSL default
            },
            'output': {
                'directory': './outputs',
                'format': 'markdown'
            },
            'search': {
                'default_limit': 10,
                'sources': ['arxiv']
            },
            'analysis': {
                'summary_length': 'medium'
            },
            'logging': {
                'level': 'INFO',
                'file': './logs/prisma.log'
            }
        }
        
        if not self.config_path:
            print("[WARNING] No config file found, using defaults")
            return defaults
        
        try:
            with open(self.config_path, 'r', encoding='utf-8') as f:
                user_config = yaml.safe_load(f)
            
            # Merge user config with defaults
            config = self._merge_configs(defaults, user_config)
            print(f"[INFO] Loaded config from {self.config_path}")
            return config
            
        except Exception as e:
            print(f"[ERROR] Failed to load config from {self.config_path}: {e}")
            print("[WARNING] Using default configuration")
            return defaults
    
    def _merge_configs(self, defaults: Dict[str, Any], user_config: Dict[str, Any]) -> Dict[str, Any]:
        """Recursively merge user configuration with defaults."""
        result = defaults.copy()
        
        for key, value in user_config.items():
            if key in result and isinstance(result[key], dict) and isinstance(value, dict):
                result[key] = self._merge_configs(result[key], value)
            else:
                result[key] = value
        
        return result
    
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
                value = value[key]
            return value
        except (KeyError, TypeError):
            return default
    
    def get_llm_config(self) -> Dict[str, Any]:
        """Get LLM configuration for Ollama integration."""
        return {
            'provider': self.get('llm.provider', 'ollama'),
            'model': self.get('llm.model', 'llama3.1:8b'),
            'host': self.get('llm.host', '172.29.32.1:11434'),
            'base_url': f"http://{self.get('llm.host', '172.29.32.1:11434')}"
        }
    
    def get_search_config(self) -> Dict[str, Any]:
        """Get search configuration."""
        return {
            'default_limit': self.get('search.default_limit', 10),
            'sources': self.get('search.sources', ['arxiv'])
        }
    
    def get_output_config(self) -> Dict[str, Any]:
        """Get output configuration."""
        return {
            'directory': self.get('output.directory', './outputs'),
            'format': self.get('output.format', 'markdown')
        }


# Global config instance
config = ConfigLoader()