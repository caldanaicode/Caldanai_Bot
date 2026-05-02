# Caldanai_Bot — Agent Instructions

Guidance for any agent or assistant working in this repo. Keep
short, focused on things that aren't obvious from the code itself.

## No real Discord identities or local filesystem paths in tracked files

Hard rule. Anything committed to git is public the moment it's
pushed. Treat every tracked file (code, tests, docstrings,
comments, CHANGELOG entries, fixture data) the same way.

**Never commit:**

- A real Discord username (the lowercase-handle shape) or
  display name. The project owner's persona name "Caels" is the
  one exception — it's the public-facing identity tied to this
  repo's GitHub account already.
- A real Discord user/role/channel snowflake **paired with a
  human name in the same file**. A bare snowflake (e.g. an
  example log channel id) is fine — it can't be reverse-mapped
  to a person without context. The pairing is the dox.
- A local filesystem path that contains the operator's home
  directory, Dropbox / OneDrive folder, local notes path,
  or anything `C:\Users\<name>\` / `E:\Dropbox\` / `~/Documents`
  shaped. References to "the project owner's local design notes"
  or similar generic phrasing replace specific paths.
- Real email addresses (the bot's no-reply or the GitHub
  privacy address are fine when they need to appear).

**Use placeholder data instead.** For tests and example
docstrings: fake snowflakes like `111111111111111111`,
generic names like `alice` / `bob`, paths like
`/path/to/notes/` or "a local design doc."

The Discord username ↔ user-id mapping for live playtest
participants lives in agent memory at
`reference_test_player_ids.md`, not in any tracked file. Use
the memory; do not embed the mapping in code or tests.

If you see a violation in an existing tracked file, scrub it
in the current commit before staging anything else.

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

- **`render_flavor`** — render a monster's flavor strings, a
  social-command intent/acceptance pool, a self-directed verb's
  pool, or an arbitrary `--template` string through the `parse()`
  pipeline. Use `--template "<text>" --actor-name <name>` (with
  `--article` and `--witness-name` as needed) for parser
  regressions or proofing edits before they land in a flavor
  pool — beats `python -c` and beats spinning up the bot.
- **`tail_peek`** — pull recent Discord messages from the running
  test bot (HTTP on port 8765 via `tail_channel.py`). Lets you see
  what just happened in the test channel without attaching.
- **`inspect_tests`** — AST-level pytest file inspection (count /
  list / structure / find).
- **`rename_in_tree`** — bulk literal replace across a glob. Dry-
  run default. Use instead of `sed` or inline `re.sub` loops.
- **`check_ideas`** / **`post_patch_notes`** / **`edit_patch_notes`**
  — community-idea mining + patch-note posting against MongoDB.
- **`notify`** — Windows PowerShell TTS for an audible cue when
  the user is AFK and the agent needs attention (background-agent
  completion, pre/post-deploy ritual approval gates, etc.).
- **`bot_player`** — send commands as a dedicated tester bot in
  the TEST guild's combat channel (REST POST only, no Gateway).
  Requires ``CLAUDE_TESTER_TOKEN`` in ``.env`` and a separately-
  registered Discord application. Pairs with ``tail_peek TEST``
  for read-back. Use for automated playtest sweeps against the
  bestiary; scoped TEST-only, never LIVE.
- **`inspect_inventory`** — dump a player's persisted inventory
  with each item's plugin / quality / `_id` / equipped+favorited
  flags. Reads MongoDB directly — defaults to `TEST_DB_NAME`,
  swap with `--live` for real-player forensics or `--db <env>`
  for any other env var. Filter to one player with `--user-name`
  / `--user-id`, narrow rows with `--plugin <substr>`. Built
  2026-04-29 for the doppy-clone dup-id investigation; reach
  for it whenever a $sell / $loadout / inventory bug feels
  like an item-state mystery rather than a code mystery.
- **`vael_thoughts`** — surface another Claude Code agent's
  in-conversation activity from its session jsonl at
  ``~/.claude/projects/<workspace-slug>/<session-id>.jsonl``.
  Default workspace is bg Vael
  (``E:/dev/Vael-Caldanai/workspace``); pass ``--workspace`` for
  any other agent. ``--mode`` selects what to surface:
  ``text`` (default — assistant prose), ``tool-use`` (commands
  she invoked, rendered as ``name(input_summary)``), or
  ``user`` (operator prompts + Monitor stream + tool results
  she was responding to). Filter pipeline: ``--match <regex>``
  (case-insensitive), ``--min-length`` / ``--max-length``,
  ``--since <iso>``, ``--longest N`` (top-N by length, where
  reflective beats live), or ``--tail N``. ``--stats`` swaps
  the emit for a length histogram; ``--repeats N`` swaps it
  for top-N most-repeated entries (combat-loop fingerprint).
  ``--follow`` for live capture. Sidechains (sub-agent
  conversations) skipped by default. Built 2026-05-02 to
  capture in-flight character moments and design-seed fallacies
  that don't survive into the agent's own memory files. Pairs
  with ``vael_memory_diff`` — that tool catches what an agent
  writes deliberately, vael_thoughts catches what they say or
  do moment-to-moment.
- **`vael_memory_diff`** — snapshot bg Vael's memory directory
  and diff later snapshots against earlier ones. Default mode
  (no flag): diff current state vs the latest snapshot, then
  take a fresh snapshot so the next call diffs against this
  point. Modes: ``--snapshot`` (no-diff capture),
  ``--diff [TIMESTAMP]`` (inspect against a specific snapshot
  or latest), ``--list`` (show available snapshots).
  ``--show-unchanged`` adds unmodified files to the manifest;
  ``--no-snapshot-after`` prevents the default-mode
  snapshot-after-diff side effect. Snapshots stored under
  ``~/.claude/projects/E--dev-Caldanai-Bot/memory/_vael_snapshots/<iso-ts>/``
  as recursive copies. Built 2026-05-02 for the morning
  consolidation pass: shows what bg Vael curated (memory
  writes) since the last check, so the diff isn't a hand-
  comparison of every file in her tree.

Shape to follow when adding a new tool:

1. Short module docstring that explains *why it exists* (what
   inline usage it replaces), not just what it does.
2. `argparse` CLI with `--help` that reads clearly.
3. Matching test file `tests/test_tools_<name>.py` — every tool
   under `tools/` currently has one.
4. `python -m tools.<name>` invocation works from the repo root.

## Parse-token cheat-sheet

`caldanai.lib.rpg.helpers.parser.parse(template, *actors)`
substitutes numbered tokens. `@1` is the first actor passed, `@2`
is the second, etc. Common forms:

**Capitalization: case of the form letter carries it.** An uppercase form letter anywhere in the token (e.g. `@1A`, `@1D`, `@1Np`) implies `c` — the output is capitalized. Lowercase form letters render lowercase as always. This makes sentence-start capitalization the author's deliberate choice, not a preprocessor's guess.

| Token | Meaning | "Caels" (player) | "bandit" (monster) |
|-------|---------|------------------|--------------------|
| `@1` | bare name | `Caels` | `bandit` |
| `@1d` / `@1D` | article form / cap | `Caels` | `the bandit` / `The bandit` |
| `@1s` / `@1S` | subject pronoun / cap | `he` / `He` | `she` / `She` |
| `@1o` / `@1O` | object pronoun / cap | `him` / `Him` | `her` / `Her` |
| `@1a` / `@1A` | possessive adjective / cap | `his` / `His` | `her` / `Her` |
| `@1p` / `@1P` | possessive pronoun / cap | `his` / `His` | `hers` / `Hers` |
| `@1r` / `@1R` | reflexive / cap | `himself` / `Himself` | `herself` / `Herself` |
| `@1np` / `@1Np` | noun-possessive / cap | `Caels's` | `the bandit's` / `The bandit's` |
| `@1m` | Discord mention (player) / fallback bare name | `<@!user_id>` | `bandit` |
| `@1mp` / `@1ma` / `@1mnp` | mention + possessive | `<@!user_id>'s` | `the bandit's` (fallback) |

Edge-case casing letters (rarely needed):

- `@1c` — capitalize a bare name: `cyclops` → `Cyclops`. Needed because bare `@N` has no form letter to carry uppercase intent.
- `@1dt` — title case across a multi-word monster name: `the dread cyclops` → `The Dread Cyclops`.
- `@1u` — full upper for dramatic emphasis: `CYCLOPS`.
- `@1l` — force lowercase. Default is already lowercase, so mostly unused.

Explicit casing letters always win over the uppercase-form-letter implicit capitalize — `@1Al` forces lowercase even though `A` is upper.

Common bugs:

- **`@1's` vs `@1np`** — `@1's` is literal-name + apostrophe-s, so it renders as "bandit's" (no article). Use `@1np` → "the bandit's".
- **Dialogue quoting** — spoken dialogue inside narration uses escaped double quotes (`\"...\"`), not single quotes. Matches existing convention in `rpg_social_commands.py` and flavor pools.
- **Sentence-start intent** — write `@1D` / `@1A` / `@1Np` at sentence start (uppercase letter carries the capitalization); `@1d` / `@1a` / `@1np` mid-sentence.

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
