"""Shared injection-defense helpers — mechanically defang prompt-injection
attempts hiding in untrusted content (a downloaded paper, a web page, a
vault note) before it enters any LLM's context.

Shared between `knowledge_graph_service.py`'s extraction pipeline and the
chat module's tool results — same threat model, same mitigation, one place
to fix it.
"""
from __future__ import annotations

import hashlib
import re

_INJECTION_SENTINELS = re.compile(
    r"</?untrusted_source\b[^>]*>"
    r"|<\|(?:im_start|im_end|system|user|assistant|endoftext)\|>"
    r"|<<SYS>>|<</SYS>>"
    r"|\[/?INST\]"
    r"|^\s*###?\s*(?:system|instruction)s?\s*:?\s*$",
    re.IGNORECASE | re.MULTILINE,
)


def neutralise_injection_sentinels(text: str) -> str:
    return _INJECTION_SENTINELS.sub(lambda m: m.group(0)[0] + "​" + m.group(0)[1:], text)


def wrap_untrusted(rel: str, content: str) -> str:
    sha = hashlib.sha256(content.encode("utf-8", errors="replace")).hexdigest()
    safe = neutralise_injection_sentinels(content)
    return f'<untrusted_source path="{rel}" sha256="{sha}">\n{safe}\n</untrusted_source>'
