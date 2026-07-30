"""
Unit tests for Pydantic-based configuration system.
"""

import unittest
import tempfile
import os
from pathlib import Path
import sys
from unittest.mock import patch

# Add prisma to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from prisma.utils.config import ConfigLoader, PrismaConfig, ZoteroConfig, LLMConfig
from pydantic import ValidationError


class TestConfigLoader(unittest.TestCase):
    """Test configuration loading and merging with Pydantic validation."""
    
    def setUp(self):
        """Set up test fixtures."""
        self.test_config_content = """
[llm]
model = "test-model"
host = "localhost:11434"

[search]
default_limit = 5
sources = ["arxiv"]

[sources.zotero]
enabled = true
api_key = "test_key"
library_id = "12345"
"""
    
    def test_default_config_loading(self):
        """Test that default configuration loads when no config file exists."""
        # Create ConfigLoader without any config file. Also patches Path.exists
        # to False (not just PRISMA_CONFIG to a nonexistent path) — otherwise
        # _get_config_path()'s fallback to default_locations (which includes
        # the real ~/.config/prisma/config.toml) would pick up whatever real
        # config the machine running this test happens to have, defeating the
        # "no config file" isolation this test is actually after. Same
        # pattern as test_zotero_credentials_check below.
        with tempfile.TemporaryDirectory() as temp_dir, \
                patch('prisma.utils.config.Path.exists', return_value=False):
            old_env = os.environ.get('PRISMA_CONFIG')
            os.environ['PRISMA_CONFIG'] = str(Path(temp_dir) / 'nonexistent.toml')

            config_loader = ConfigLoader()

            # Should have defaults and be Pydantic model
            self.assertIsInstance(config_loader.config, PrismaConfig)
            self.assertEqual(config_loader.config.llm.provider, 'ollama')
            self.assertIsInstance(config_loader.config.llm.model, str)
            self.assertTrue(len(config_loader.config.llm.model) > 0)
            self.assertEqual(config_loader.config.search.default_limit, 10)

            # Restore environment
            if old_env:
                os.environ['PRISMA_CONFIG'] = old_env
            elif 'PRISMA_CONFIG' in os.environ:
                del os.environ['PRISMA_CONFIG']
    
    def test_config_file_loading(self):
        """Test loading configuration from TOML file."""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.toml', delete=False) as f:
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

    def test_get_vault_root_defaults_to_home_prisma_vault(self):
        with tempfile.TemporaryDirectory() as temp_dir, \
             patch('prisma.utils.config.Path.exists', return_value=False):
            old_env = os.environ.get('PRISMA_CONFIG')
            os.environ['PRISMA_CONFIG'] = str(Path(temp_dir) / 'nonexistent.toml')
            try:
                loader = ConfigLoader()
                self.assertEqual(loader.get_vault_root(), Path.home() / "prisma-vault")
            finally:
                if old_env:
                    os.environ['PRISMA_CONFIG'] = old_env
                elif 'PRISMA_CONFIG' in os.environ:
                    del os.environ['PRISMA_CONFIG']

    def test_get_vault_root_and_kg_config_from_file(self):
        # vault_root and kg: previously had no Pydantic model at all --
        # every call site (app.py, kg_app.py, cli/commands/streams.py)
        # independently re-parsed the raw config file for these two values. This test
        # pins the consolidated ConfigLoader.get_vault_root()/get_kg_config()
        # behavior those call sites now share.
        with tempfile.NamedTemporaryFile(mode='w', suffix='.toml', delete=False) as f:
            f.write("""
vault_root = "~/custom-vault"

[kg]
max_entities = 42
token_budget = 750
index_extensions = ["md", ".yaml"]
""")
            config_path = f.name
        try:
            old_env = os.environ.get('PRISMA_CONFIG')
            os.environ['PRISMA_CONFIG'] = config_path
            loader = ConfigLoader()
            self.assertEqual(loader.get_vault_root(), (Path.home() / "custom-vault").resolve())
            kg = loader.get_kg_config()
            self.assertEqual(kg.max_entities, 42)
            self.assertEqual(kg.token_budget, 750)
            self.assertEqual(kg.index_extensions, ["md", ".yaml"])
            # untouched settings still default
            self.assertEqual(kg.max_relationships, 20)
        finally:
            os.unlink(config_path)
            if old_env:
                os.environ['PRISMA_CONFIG'] = old_env
            elif 'PRISMA_CONFIG' in os.environ:
                del os.environ['PRISMA_CONFIG']

    def test_config_path_constructor_arg_overrides_env_var(self):
        # The CLI's --config flag needs to point ConfigLoader at a specific
        # file without the side effect of mutating PRISMA_CONFIG globally.
        with tempfile.NamedTemporaryFile(mode='w', suffix='.toml', delete=False) as f:
            f.write('vault_root = "/explicit-path-vault"\n')
            explicit_path = f.name
        try:
            old_env = os.environ.get('PRISMA_CONFIG')
            os.environ['PRISMA_CONFIG'] = "/should-be-ignored.toml"
            loader = ConfigLoader(config_path=explicit_path)
            self.assertEqual(loader.get_vault_root(), Path("/explicit-path-vault"))
        finally:
            os.unlink(explicit_path)
            if old_env:
                os.environ['PRISMA_CONFIG'] = old_env
            elif 'PRISMA_CONFIG' in os.environ:
                del os.environ['PRISMA_CONFIG']

    def test_get_method_with_dot_notation(self):
        """Test the get method with dot notation for backward compatibility."""
        # Isolated from whatever real ~/.config/prisma/config.toml exists on
        # the machine running this test — see test_default_config_loading.
        with patch('prisma.utils.config.Path.exists', return_value=False):
            config_loader = ConfigLoader()

            # Test existing key
            result = config_loader.get('llm.provider')
            self.assertEqual(result, 'ollama')

            # Test non-existing key with default
            result = config_loader.get('nonexistent.key', 'default_value')
            self.assertEqual(result, 'default_value')

    def test_llm_config_helper(self):
        """Test LLM configuration helper method."""
        # Isolated from whatever real ~/.config/prisma/config.toml exists on
        # the machine running this test — see test_default_config_loading.
        with patch('prisma.utils.config.Path.exists', return_value=False):
            config_loader = ConfigLoader()
            llm_config = config_loader.get_llm_config()

            # Test that we get a Pydantic model with proper attributes
            self.assertTrue(hasattr(llm_config, 'provider'))
            self.assertTrue(hasattr(llm_config, 'model'))
            self.assertTrue(hasattr(llm_config, 'host'))
            self.assertEqual(llm_config.provider, 'ollama')
    
    def test_llm_config_openrouter_provider_accepted(self):
        cfg = LLMConfig(provider='openrouter', model='openai/gpt-4o-mini', api_key_env='OPENROUTER_API_KEY')
        self.assertEqual(cfg.provider, 'openrouter')

    def test_llm_config_openrouter_base_url(self):
        cfg = LLMConfig(provider='openrouter')
        self.assertEqual(cfg.base_url, 'https://openrouter.ai/api/v1')

    def test_llm_config_base_url_override_wins(self):
        cfg = LLMConfig(provider='openrouter', base_url_override='https://custom.example/v1')
        self.assertEqual(cfg.base_url, 'https://custom.example/v1')

    def test_llm_config_ollama_base_url_unchanged(self):
        cfg = LLMConfig(provider='ollama', host='localhost:11434')
        self.assertEqual(cfg.base_url, 'http://localhost:11434')

    def test_llm_config_invalid_provider_still_rejected(self):
        with self.assertRaises(ValidationError):
            LLMConfig(provider='anthropic')

    def test_llm_resolve_api_key_ollama_returns_placeholder_ignoring_api_key_env(self):
        # Local OpenAI-compat servers don't check the key at all -- must not
        # even look at api_key_env (or raise if it's unset) for this provider.
        cfg = LLMConfig(provider='ollama')
        self.assertEqual(cfg.resolve_api_key(), 'ollama')

    def test_llm_resolve_api_key_llama_cpp_returns_placeholder(self):
        cfg = LLMConfig(provider='llama_cpp')
        self.assertEqual(cfg.resolve_api_key(), 'ollama')

    def test_llm_resolve_api_key_openrouter_reads_named_env_var(self):
        cfg = LLMConfig(provider='openrouter', api_key_env='LLM_TEST_KEY_VAR')
        with patch.dict(os.environ, {'LLM_TEST_KEY_VAR': 'from-env'}):
            self.assertEqual(cfg.resolve_api_key(), 'from-env')

    def test_llm_resolve_api_key_openrouter_raises_when_api_key_env_unset(self):
        cfg = LLMConfig(provider='openrouter')
        with self.assertRaises(RuntimeError):
            cfg.resolve_api_key()

    def test_llm_resolve_api_key_openrouter_raises_when_env_var_missing(self):
        cfg = LLMConfig(provider='openrouter', api_key_env='LLM_TEST_KEY_VAR_UNSET')
        os.environ.pop('LLM_TEST_KEY_VAR_UNSET', None)
        with self.assertRaises(RuntimeError):
            cfg.resolve_api_key()

    def test_validation_errors(self):
        """Test that Pydantic validation catches invalid configurations."""
        # Test invalid output format
        with self.assertRaises(ValidationError):
            from prisma.utils.config import OutputConfig
            OutputConfig(format='invalid_format', directory='outputs')
        
        # Test invalid library type  
        with self.assertRaises(ValidationError):
            from prisma.utils.config import ZoteroConfig
            ZoteroConfig(
                enabled=True,
                api_key="test",
                library_id="123",
                library_type='invalid',
                include_notes=False,
                include_attachments=False,
            )
        
        # Test invalid search limit
        with self.assertRaises(ValidationError):
            from prisma.utils.config import SearchConfig
            SearchConfig(default_limit=-1)
    
    def test_zotero_credentials_check(self):
        """Test Zotero credentials validation."""
        # Test with a clean config loader (no config file)
        with patch('prisma.utils.config.Path.exists', return_value=False):
            config_loader = ConfigLoader()
            
            # Default config should not have credentials
            self.assertFalse(config_loader.has_zotero_credentials())
        
        # Test with credentials
        config_loader = ConfigLoader()
        config_loader.config.sources.zotero.enabled = True
        config_loader.config.sources.zotero.api_key = 'test_key'
        config_loader.config.sources.zotero.library_id = '12345'

        self.assertTrue(config_loader.has_zotero_credentials())

    def test_zotero_resolve_api_key_falls_back_to_literal(self):
        cfg = ZoteroConfig(api_key='literal-key')
        self.assertEqual(cfg.resolve_api_key(), 'literal-key')

    def test_zotero_resolve_api_key_env_takes_priority(self):
        cfg = ZoteroConfig(api_key='literal-key', api_key_env='ZOTERO_TEST_KEY_VAR')
        with patch.dict(os.environ, {'ZOTERO_TEST_KEY_VAR': 'from-env'}):
            self.assertEqual(cfg.resolve_api_key(), 'from-env')

    def test_zotero_resolve_api_key_env_missing_raises(self):
        cfg = ZoteroConfig(api_key='literal-key', api_key_env='ZOTERO_TEST_KEY_VAR_UNSET')
        os.environ.pop('ZOTERO_TEST_KEY_VAR_UNSET', None)
        with self.assertRaises(RuntimeError):
            cfg.resolve_api_key()

    def test_has_zotero_credentials_false_when_api_key_env_missing(self):
        # A misconfigured api_key_env must degrade to "no credentials",
        # not crash the caller -- has_zotero_credentials() is a plain bool
        # check used in several places with no exception handling of its own.
        with patch('prisma.utils.config.Path.exists', return_value=False):
            config_loader = ConfigLoader()
        config_loader.config.sources.zotero.enabled = True
        config_loader.config.sources.zotero.library_id = '12345'
        config_loader.config.sources.zotero.api_key_env = 'ZOTERO_TEST_KEY_VAR_UNSET'
        os.environ.pop('ZOTERO_TEST_KEY_VAR_UNSET', None)

        self.assertFalse(config_loader.has_zotero_credentials())

    def test_zotero_resolve_library_id_falls_back_to_literal(self):
        cfg = ZoteroConfig(library_id='12345')
        self.assertEqual(cfg.resolve_library_id(), '12345')

    def test_zotero_resolve_library_id_env_takes_priority(self):
        cfg = ZoteroConfig(library_id='12345', library_id_env='ZOTERO_TEST_LIBID_VAR')
        with patch.dict(os.environ, {'ZOTERO_TEST_LIBID_VAR': '99999'}):
            self.assertEqual(cfg.resolve_library_id(), '99999')

    def test_zotero_resolve_library_id_env_missing_raises(self):
        cfg = ZoteroConfig(library_id='12345', library_id_env='ZOTERO_TEST_LIBID_VAR_UNSET')
        os.environ.pop('ZOTERO_TEST_LIBID_VAR_UNSET', None)
        with self.assertRaises(RuntimeError):
            cfg.resolve_library_id()

    def test_has_zotero_credentials_false_when_library_id_env_missing(self):
        with patch('prisma.utils.config.Path.exists', return_value=False):
            config_loader = ConfigLoader()
        config_loader.config.sources.zotero.enabled = True
        config_loader.config.sources.zotero.api_key = 'test_key'
        config_loader.config.sources.zotero.library_id_env = 'ZOTERO_TEST_LIBID_VAR_UNSET'
        os.environ.pop('ZOTERO_TEST_LIBID_VAR_UNSET', None)

        self.assertFalse(config_loader.has_zotero_credentials())


if __name__ == '__main__':
    unittest.main()