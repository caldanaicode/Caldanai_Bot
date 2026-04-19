# Caldanai_Bot — Agent Instructions

Guidance for any agent or assistant working in this repo. Keep
short, focused on things that aren't obvious from the code itself.

## Prefer `tools/` over inline `python -c`

**If you catch yourself writing `python -c "..."` with more than a
trivial expression — stop, and build a `tools/*.py` module
instead.** Then invoke the tool.

Reasons:

- Inline Python snippets (`python -c`, Bash heredoc pythons, `.venv
  python <(cat)`) each force a fresh permission approval. They're
  also one-shot — the next session reaches for the same snippet
  and gets approved again.
- A tool under `tools/` gets approved once by the permission
  harness and stays reusable forever. Future-you (or a future
  agent) will look at `tools/` first and find what they need.
- "Reusable broadly" beats "specific one-shot." Generalize to the
  need — e.g. `tools/render_flavor.py` covers flavor-proofing for
  any monster or social cmd, not just "the bandit tonight."

Existing tools (`python -m tools.<name> --help` for details):

- **`render_flavor`** — render a monster's flavor strings, or a
  social-command intent/acceptance pool, or a self-directed
  verb's pool, through the `parse()` pipeline. Use this *before*
  reaching for inline Python when proofing parse tokens.
- **`tail_peek`** — pull recent Discord messages from the running
  test bot (HTTP on port 8765 via `tail_channel.py`). Lets you see
  what just happened in the test channel without attaching.
- **`inspect_tests`** — AST-level pytest file inspection (count /
  list / structure / find).
- **`rename_in_tree`** — bulk literal replace across a glob. Dry-
  run default. Use instead of `sed` or inline `re.sub` loops.
- **`check_ideas`** / **`post_patch_notes`** / **`edit_patch_notes`**
  — community-idea mining + patch-note posting against MongoDB.

Shape to follow when adding a new tool:

1. Short module docstring that explains *why it exists* (what
   inline usage it replaces), not just what it does.
2. `argparse` CLI with `--help` that reads clearly.
3. Matching test file `tests/test_tools_<name>.py` — every tool
   under `tools/` except `render_flavor` currently has one.
4. `python -m tools.<name>` invocation works from the repo root.

## Parse-token cheat-sheet

`caldanai.lib.rpg.helpers.parser.parse(template, *actors)`
substitutes numbered tokens. `@1` is the first actor passed, `@2`
is the second, etc. Common forms:

| Token | Meaning | "Caels" (player) | "bandit" (monster) |
|-------|---------|------------------|--------------------|
| `@1` | bare name | `Caels` | `bandit` |
| `@1d` | name with article | `Caels` | `the bandit` |
| `@1dc` | capitalized article form | `Caels` | `The bandit` |
| `@1s` / `@1sc` | subject pronoun / cap | `he` / `He` | `she` / `She` |
| `@1o` | object pronoun | `him` | `her` |
| `@1a` | possessive adjective | `his` | `her` |
| `@1r` | reflexive | `himself` | `herself` |
| `@1np` / `@1npc` | name-possessive / cap | `Caels's` | `the bandit's` / `The bandit's` |

Common bugs:

- **`@1dc` mid-sentence** produces "The bandit" (capitalized)
  where the sentence wants "the bandit". Use `@1d` unless at
  sentence start.
- **`@1's` vs `@1np`** — `@1's` is literal-name + apostrophe-s, so
  it renders as "bandit's" (no article). Usually want `@1np` →
  "the bandit's".
- **Dialogue quoting** — spoken dialogue inside narration uses
  escaped double quotes (`\"...\"`), not single quotes. Matches
  existing convention in `rpg_social_commands.py` and flavor pools.

Always render-proof new flavor strings with
`python -m tools.render_flavor ...` before shipping.

## Monsters are Python plugins

Monsters live in `caldanai/lib/rpg/creatures/monsters/<stem>.py`
and subclass `MonsterPlugin`. This is the deliberate design — do
not propose extracting monster definitions to data files
(YAML / TOML / JSON). Flavor-text-only extraction has been
partially considered, but `monsters-as-data` is explicitly off the
table per the project owner.

## Social-warmth system

Player-vs-player social verbs (hug, high_five, comfort, etc.)
live in `caldanai/lib/cogs/rpg_social_commands.py` with warmth
resolution in `caldanai/lib/rpg/helpers/warmth.py`. Key contracts:

- **Target governs acceptance**, actor governs intent. The target
  player's warmth decides *what happens*; the actor's warmth
  tints *how they attempted*.
- `$warmth` settings are always DM-only. Channel only gets a
  brief "Sent you a DM" ack.
- Monster-vs-player social lands through `Creature.on_social(cmd,
  actor, invocation)` → per-monster `SOCIAL_REACTIONS` dict or
  `on_hugged` for the hug-back-compat path. Add new monster
  reactions by overriding `on_social`.
