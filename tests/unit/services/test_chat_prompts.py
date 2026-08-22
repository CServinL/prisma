"""Unit tests for chat_prompts.py -- the user prompt persistence behind the
Settings page's "Chat instructions" panel (PUT /chat/user-prompt), and
build_system_prompt()'s layering of that on top of the fixed, code-owned
CHAT_SYSTEM_PROMPT.
"""
from prisma.services import chat_prompts


def test_load_user_prompt_returns_empty_when_never_saved(tmp_path, monkeypatch):
    monkeypatch.setattr(chat_prompts, "_user_prompt_path", lambda: tmp_path / "chat_user_prompt.md")

    assert chat_prompts.load_user_prompt() == ""


def test_save_user_prompt_writes_stripped_content(tmp_path, monkeypatch):
    path = tmp_path / "chat_user_prompt.md"
    monkeypatch.setattr(chat_prompts, "_user_prompt_path", lambda: path)

    chat_prompts.save_user_prompt("  Always cite page numbers when quoting a PDF.  \n\n")

    assert path.read_text(encoding="utf-8") == "Always cite page numbers when quoting a PDF.\n"


def test_save_user_prompt_creates_parent_dir(tmp_path, monkeypatch):
    path = tmp_path / "nested" / "chat_user_prompt.md"
    monkeypatch.setattr(chat_prompts, "_user_prompt_path", lambda: path)

    chat_prompts.save_user_prompt("hi")

    assert path.exists()


def test_save_then_load_round_trips(tmp_path, monkeypatch):
    path = tmp_path / "chat_user_prompt.md"
    monkeypatch.setattr(chat_prompts, "_user_prompt_path", lambda: path)

    chat_prompts.save_user_prompt("Custom instructions.")

    assert chat_prompts.load_user_prompt() == "Custom instructions."


def test_save_empty_user_prompt_clears_back_to_blank(tmp_path, monkeypatch):
    path = tmp_path / "chat_user_prompt.md"
    monkeypatch.setattr(chat_prompts, "_user_prompt_path", lambda: path)
    chat_prompts.save_user_prompt("Something.")

    chat_prompts.save_user_prompt("   ")

    assert chat_prompts.load_user_prompt() == ""


def test_build_system_prompt_is_just_the_base_when_user_prompt_blank(tmp_path, monkeypatch):
    monkeypatch.setattr(chat_prompts, "_user_prompt_path", lambda: tmp_path / "chat_user_prompt.md")

    assert chat_prompts.build_system_prompt() == chat_prompts.CHAT_SYSTEM_PROMPT.strip()


def test_build_system_prompt_layers_user_instructions_on_top(tmp_path, monkeypatch):
    path = tmp_path / "chat_user_prompt.md"
    monkeypatch.setattr(chat_prompts, "_user_prompt_path", lambda: path)
    chat_prompts.save_user_prompt("Always cite page numbers when quoting a PDF.")

    result = chat_prompts.build_system_prompt()

    assert result.startswith(chat_prompts.CHAT_SYSTEM_PROMPT.strip())
    assert "Always cite page numbers when quoting a PDF." in result
