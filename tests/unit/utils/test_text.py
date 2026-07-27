"""Unit tests for prisma.utils.text.content_hash — the single source of
truth for the SHA256-content-hash algorithm on the Python side, mirrored by
prisma-desktop's Rust content_hash() (sync/mod.rs)."""
from prisma.utils.text import content_hash


def test_content_hash_matches_known_digest():
    # Same pinned digest prisma-desktop's Rust content_hash() test asserts
    # (sync/mod.rs's content_hash_is_deterministic_and_content_sensitive) —
    # keeping both languages' tests pinned to the same known value is what
    # actually verifies they stay in lockstep.
    assert content_hash("hello") == "2cf24dba5fb0a30e26e83b2ac5b9e29e1b161e5c1fa7425e73043362938b9824"


def test_content_hash_is_deterministic():
    assert content_hash("some content") == content_hash("some content")


def test_content_hash_is_content_sensitive():
    assert content_hash("a") != content_hash("b")


def test_content_hash_handles_non_ascii():
    # UTF-8 can represent any Unicode code point, so this never raises
    # regardless of the errors= policy — just confirms it doesn't crash and
    # is still deterministic for non-ASCII input.
    assert content_hash("café ☕") == content_hash("café ☕")
