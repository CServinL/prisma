"""Unit tests for VaultRef (ADR-021) -- parsing the vault:/dir/name
interchange form, the dir--name compound-slug form, and a bare slug into
one consistent (dir, name) shape, and reconstructing either representation
back out."""
from prisma.storage.models.vault_models import VaultRef


def test_parses_vault_uri_with_nested_dirs():
    ref = VaultRef.parse("vault:/sources/2024/paper")
    assert ref.dir == "sources/2024"
    assert ref.name == "paper"


def test_parses_compound_slug():
    ref = VaultRef.parse("sources--paper")
    assert ref.dir == "sources"
    assert ref.name == "paper"


def test_parses_bare_slug():
    ref = VaultRef.parse("paper")
    assert ref.dir == ""
    assert ref.name == "paper"


def test_compound_slug_roundtrips_through_multiple_dir_levels():
    ref = VaultRef.parse("vault:/papers/bricken2003/index")
    assert ref.compound_slug == "papers--bricken2003--index"
    assert VaultRef.parse(ref.compound_slug).dir == "papers/bricken2003"


def test_uri_roundtrips_from_compound_slug():
    ref = VaultRef.parse("sources--paper")
    assert ref.uri == "vault:/sources/paper"


def test_bare_slug_has_no_dir_in_either_representation():
    ref = VaultRef.parse("paper")
    assert ref.compound_slug == "paper"
    assert ref.uri == "vault:/paper"
