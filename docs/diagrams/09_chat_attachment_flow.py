"""prisma — chat attachment upload/promote flow (sequence diagram).

Run: .venv/bin/python docs/diagrams/09_chat_attachment_flow.py

Shows the v3 attachment lifecycle: ephemeral upload (L1/L2, scoped to one
chat's own session graph) versus deliberate promotion to a real vault Note
(L3, indexed and searchable) -- see docs/concepts/chat-session-graph.md's
Attachments and Memory tiers sections. The pdf branch shown here is the
one kind with a real conversion path (PDF->MD, closing the gap tracked in
TODO.md since 2026-08-11); svg/latex/drawio skip the upload step entirely
(built client-side, sent as plain text) and jpg has no conversion step at
promote time -- both omitted here for focus, see the concept doc for the
full per-kind picture. Has one self-message (api -> api, the magic-byte
sniff) -- a normal, well-supported sequence-diagram construct (a short
loop-back arrow on one lifeline), not the same thing as an ER self-loop;
this diagram doesn't hit 08_chat_session_graph.py's sysatlas issue.
"""
from pathlib import Path
from sysatlas import SequenceMap

OUT = Path(__file__).with_suffix(".html")

m = SequenceMap(title="prisma — chat attachment upload -> promote flow")

m.actor("user",   kind="actor",    label="User")
m.actor("ui",     kind="boundary", label="+page.svelte")
m.actor("api",    kind="boundary", label="FastAPI :8765")
m.actor("vault",  kind="system",   label="VaultService")
m.actor("docu",   kind="system",   label="docu_craft.pdf_md")
m.actor("kg",     kind="system",   label="KnowledgeGraphClient")

m.send("user",  "ui",    label="attach paper.pdf",                                   order=1)
m.send("ui",    "api",   label="POST /chats/{slug}/attachments/upload (multipart)",  order=2)
m.send("api",   "api",   label="sniff magic bytes -> kind=pdf",                      order=3)
m.send("api",   "vault", label="write <chats_dir>/{slug}-attachments/{uuid}.pdf",    order=4)
m.send("api",   "ui",    label="201 AssetMediaNode{kind: pdf, asset_path}",          order=5, kind="reply")
m.send("ui",    "user",  label="shows pending attachment chip",                      order=6, kind="reply")

m.send("user",  "ui",   label="send message (attachment still pending)",             order=7)
m.send("ui",    "api",  label="POST /chat {message, attachments: [AssetMediaNode]}", order=8)
m.send("api",   "vault", label="append_messages: user TurnNode.attachments = [...]", order=9)
m.send("api",   "ui",   label="200 ChatResponse",                                     order=10, kind="reply")

m.send("user",  "ui",   label="click \"save to vault\" on the attachment",            order=11)
m.send("ui",    "api",  label="POST /chats/{slug}/attachments/promote {attachment}", order=12)
m.send("api",   "vault", label="create_note(title) -> new Note + .pdf companion",    order=13)
m.send("api",   "vault", label="ensure_md_format(companion) -- .pdf branch",         order=14)
m.send("vault", "docu",  label="pdf_bytes_to_md(companion.read_bytes())",            order=15)
m.send("docu",  "vault", label="extracted markdown text",                            order=16, kind="reply")
m.send("api",   "kg",    label="mark_stale() -- new Note now indexable",             order=17)
m.send("api",   "ui",    label="201 {slug: <new-note-slug>}",                        order=18, kind="reply")
m.send("ui",    "user",  label="attachment now a real, searchable vault Note",       order=19, kind="reply")

m.save(str(OUT))
print(f"[sysatlas] wrote {OUT}")
