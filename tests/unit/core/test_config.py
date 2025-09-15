"""
Unit tests for Pydantic-based configuration system.
"""

import unittest
import tempfile
import os
from pathlib import Path
import sys

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent / 'src'))

from src.utils.config import ConfigLoader, PrismaConfig, ZoteroConfig, LLMConfig
from pydantic import ValidationError


class TestConfigLoader(unittest.TestCase):
    """Test configuration loading and merging with Pydantic validation."""
    
    def setUp(self):
        """Set up test fixtures."""
        self.test_config_content = """
llm:
  model: "test-model"
  host: "localhost:11434"

search:
  default_limit: 5
  sources: ["arxiv"]

sources:
  zotero:
    enabled: true
    api_key: "test_key"
    library_id: "12345"
"""
    
    def test_default_config_loading(self):
        """Test that default configuration loads when no config file exists."""
        # Create ConfigLoader without any config file
        with tempfile.TemporaryDirectory() as temp_dir:
            old_env = os.environ.get('PRISMA_CONFIG')
            os.environ['PRISMA_CONFIG'] = str(Path(temp_dir) / 'nonexistent.yaml')
            
            config_loader = ConfigLoader()
            
            # Should have defaults and be Pydantic model
            self.assertIsInstance(config_loader.config, PrismaConfig)
            self.assertEqual(config_loader.config.llm.provider, 'ollama')
            self.assertEqual(config_loader.config.llm.model, 'llama3.1:8b')
            self.assertEqual(config_loader.config.search.default_limit, 10)
            
            # Restore environment
            if old_env:
                os.environ['PRISMA_CONFIG'] = old_env
            elif 'PRISMA_CONFIG' in os.environ:
                del os.environ['PRISMA_CONFIG']
    
    def test_config_file_loading(self):
        """Test loading configuration from YAML file."""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.yaml', delete=False) as f:
            f.write(self.test_config_content)
            config_path = f.name
        
        try:
            old_env = os.environ.get('PRISMA_CONFIG')
            os.environ['PRISMA_CONFIG'] = config_path
            
            config_loader = ConfigLoader()
            
            # Should have merged config with Pydantic validation
            self.assertIsInstance(config_loader.config, PrismaConfig)
            self.assertEqual(config_loader.config.llm.model, 'test-model')
            self.assertEqual(config_loader.config.llm.host, 'localhost:11434')
            self.assertEqual(config_loader.config.search.default_limit, 5)
            
            # Should still have defaults for missing keys
            self.assertEqual(config_loader.config.llm.provider, 'ollama')
            
            # Test Zotero config
            self.assertTrue(config_loader.config.sources.zotero.enabled)
            self.assertEqual(config_loader.config.sources.zotero.api_key, 'test_key')
            
        finally:
            os.unlink(config_path)
            if old_env:
                os.environ['PRISMA_CONFIG'] = old_env
            elif 'PRISMA_CONFIG' in os.environ:
                del os.environ['PRISMA_CONFIG']
    
    def test_get_method_with_dot_notation(self):
        """Test the get method with dot notation for backward compatibility."""
        config_loader = ConfigLoader()
        
        # Test existing key
        result = config_loader.get('llm.provider')
        self.assertEqual(result, 'ollama')
        
        # Test non-existing key with default
        result = config_loader.get('nonexistent.key', 'default_value')
        self.assertEqual(result, 'default_value')
    
    def test_llm_config_helper(self):
        """Test LLM configuration helper method."""
        config_loader = ConfigLoader()
        llm_config = config_loader.get_llm_config()
        
        self.assertIn('provider', llm_config)
        self.assertIn('model', llm_config)
        self.assertIn('base_url', llm_config)
        self.assertEqual(llm_config['provider'], 'ollama')
    
    def test_validation_errors(self):
        """Test that Pydantic validation catches invalid configurations."""
        # Test invalid output format
        with self.assertRaises(ValidationError):
            PrismaConfig(output={'format': 'invalid_format'})
        
        # Test invalid library type
        with self.assertRaises(ValidationError):
            PrismaConfig(sources={'zotero': {'library_type': 'invalid'}})
        
        # Test invalid search limit
        with self.assertRaises(ValidationError):
            PrismaConfig(search={'default_limit': -1})
    
    def test_zotero_credentials_check(self):
        """Test Zotero credentials validation."""
        config_loader = ConfigLoader()
        
        # Default config should not have credentials
        self.assertFalse(config_loader.has_zotero_credentials())
        
        # Mock config with credentials
        config_loader.config.sources.zotero.enabled = True
        config_loader.config.sources.zotero.api_key = 'test_key'
        config_loader.config.sources.zotero.library_id = '12345'
        
        self.assertTrue(config_loader.has_zotero_credentials())


if __name__ == '__main__':
    unittest.main()