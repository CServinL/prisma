# Software Engineering Quality Aspects

Reference rubric for modularization/refactoring work — what to actually evaluate
against, rather than proxies like file size or line count. Kept identical in
this repo and the sibling `prisma-desktop` repo; update both together.

## Structure / boundaries

1. **Separation of concerns** — distinct responsibilities live in distinct
   places. Includes *hierarchy of concerns* (layering: presentation →
   business logic → data access) and *interception of concerns*
   (cross-cutting behavior — logging, auth, error handling — handled at one
   seam, not scattered inline everywhere it happens to apply).
2. **Cohesion** — everything inside a module/class/function actually
   belongs together and serves one clear purpose.
3. **Coupling** — modules depend on each other as little as possible; a
   change in one shouldn't ripple through unrelated ones.
4. **Encapsulation / information hiding** — internal implementation stays
   hidden behind a stable interface; only what's necessary is exposed.
5. **Layering / dependency direction** — lower-level/domain code shouldn't
   depend upward on higher-level/UI code.

## Reuse / duplication

6. **Reusability, DRY, modularity** — shared logic extracted once, not
   copy-pasted across call sites.
7. **Composability** — small units combine cleanly into larger behavior,
   rather than each combination needing its own bespoke code.

## Design principles (SOLID-adjacent)

8. **Single Responsibility** — one reason to change per module/class.
9. **Open/Closed** — extend behavior without modifying existing, working
   code.
10. **Dependency Inversion** — depend on abstractions/interfaces, not
    concrete implementations (makes swapping/testing easier).
11. **Interface Segregation** — several small, specific interfaces beat one
    big one nobody fully needs.

## Change management

12. **Change amplification / shotgun-surgery avoidance** — one conceptual
    change shouldn't require touching a dozen unrelated files (the
    practical symptom when SoC/cohesion are weak).
13. **Consistency** — the same kind of problem is solved the same way
    everywhere (naming, error handling, patterns) — lowers the cost of
    reading unfamiliar code.

## Human factors

14. **Testability** — well-separated code can be unit-tested in isolation
    without dragging in the world.
15. **Discoverability / navigability** — can someone find where a behavior
    lives without a repo-wide search?
16. **Complexity budget** — cyclomatic/cognitive complexity kept low enough
    per unit that a reader can hold it in their head.

## How to use this

When reviewing a module/file for modularization, score it against these
aspects explicitly rather than defaulting to "this file is too big." A
small file can still fail separation of concerns; a large file can still
have clean boundaries throughout. Findings should name *which* aspect is
violated and *why it matters practically* (what breaks, what gets harder),
not just restate a metric.
