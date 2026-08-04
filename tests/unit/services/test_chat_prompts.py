"""Unit tests for chat_prompts.py's save_system_prompt() -- the write path
behind the Settings page's "Chat instructions" panel (PUT /chat/system-prompt).
load_system_prompt() already has implicit coverage via every test that builds
a ChatAgent; this is the first test for writing the file."""
from prisma.services import chat_prompts


def test_save_system_prompt_writes_stripped_content(tmp_path, monkeypatch):
    path = tmp_path / "chat_system_prompt.md"
    monkeypatch.setattr(chat_prompts, "_prompt_path", lambda: path)

    chat_prompts.save_system_prompt("  Always answer in Spanish.  \n\n")

    assert path.read_text(encoding="utf-8") == "Always answer in Spanish.\n"


def test_save_system_prompt_creates_parent_dir(tmp_path, monkeypatch):
    path = tmp_path / "nested" / "chat_system_prompt.md"
    monkeypatch.setattr(chat_prompts, "_prompt_path", lambda: path)

    chat_prompts.save_system_prompt("hi")

    assert path.exists()


def test_save_then_load_round_trips(tmp_path, monkeypatch):
    path = tmp_path / "chat_system_prompt.md"
    monkeypatch.setattr(chat_prompts, "_prompt_path", lambda: path)

    chat_prompts.save_system_prompt("Custom instructions.")

    assert chat_prompts.load_system_prompt() == "Custom instructions."
