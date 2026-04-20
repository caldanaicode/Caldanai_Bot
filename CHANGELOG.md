# Changelog

All notable changes to the Caldanai Bot project will be documented in this file.

## [Unreleased]

### 2026-04-19 — `$spawn destroy` Admin Command

New admin-gated subcommand under `$spawn` for forcing body-part
destruction on the current monster. Fuzzy-matched like `$kill` /
`$target` (`$spawn destroy h.1 h.2` works), variadic. Fires each
part's `on_destroyed` hook but does NOT itself kill the
monster — part-driven death (e.g. hydra's zero-heads rule) fires
on the next combat round via `check_part_driven_death`, which is
the code path playtesters need to exercise.

Lives under `$spawn` (alongside `$spawn kill`, `$spawn monster`,
etc.) because `destroy` is already an alias of `$attack` in the
user cog — a bare `$destroy` would collide.

Intended for setup in playtest scenarios where landing specific
part-destruction sequences via natural combat would take many
rounds of lucky rolls.

### 2026-04-19 — Parser Expansion + API-Narrator Groundwork

Scaffolding for the future Claude-API narrator (see
`memory/project_phase2_api_narration.md` and the local
[[API Narrator Prompt]] doc) shipped alongside directly-useful
parser upgrades. Nothing wired to the API yet — just the
primitives the integration will consume.

- **`parser.article()`** — moved from `hydra._article` and
  migrated two in-tree reinventions (parser internal + item
  `get_article`) to use the shared helper. Parser is the single
  source of truth for English-grammar utilities.
- **`@Nnp` auto-article for monsters** — parser bug fix. Previously
  `@Nnp` rendered "goblin's" (no article) even for article-using
  creatures, despite the docstring promising "the goblin's". Now
  matches the documented intent. `@Ndnp` still works idempotently.
- **Case-sensitive form letters** — uppercase anywhere in a token's
  form string implies capitalization: `@1A` ≡ `@1ac`, `@1D` ≡
  `@1dc`, `@1Np` ≡ `@1npc`. Authoring intent lives in case
  choice directly instead of a preprocessor guessing sentence
  boundaries. Explicit `c`/`l`/`t`/`u` still win for edge cases
  (bare-name cap via `@1c`, title case via `@1dt`, full upper
  via `@1u`).
- **`@Nm` Discord mention form** — for actors carrying
  `member.mention` (Players), emits the Discord mention string;
  falls through to the bare name for monsters / NPCs. Possessive
  composition: `@Nmp` / `@Nma` / `@Nmnp` → `<@!id>'s`. Uses
  `discord.Member.mention` rather than hardcoding `<@!{id}>` so
  the parser stays aligned with discord.py's canonical format.
- **Narrator-output lint functions** — `parser.lint_narrative(s)`
  and `parser.lint_output(obj)` auto-fix the mechanical failure
  modes observed in Sonnet validation runs (invalid noun-mode
  combos `@Nno` etc., duplicate `@Nm*` per string, sentence-start
  capitalization, mid-sentence over-capitalization) and warn on
  literal-pronoun leaks. `its` / `itself` get softened warnings
  plus a per-occurrence whitelist (`its wearer`, `its blade`, etc.)
  that fully suppresses the common inanimate-object cases.
- **New tools** — `tools/parse_template.py` renders arbitrary
  `@`-tokened templates through `parse()` with stubbed actors (for
  iterating on LLM-generated narratives without spinning up the
  full game). `tools/postprocess_narrator_output.py` is the CLI
  wrapper around the parser's lint functions — reads JSON from
  stdin / file, emits cleaned JSON + warnings.

`CLAUDE.md` token cheat-sheet updated to reflect the case-sensitive
convention and `@Nm` mention form.

### 2026-04-19 — Hydra Decapitation Death: Timing + Flavor

The hydra's "last head destroyed" path fires cleanly now — same
round it happens, with correctly-timed `$loot` — instead of
round-late with a free post-death retaliation in between.

- **New `Creature.check_part_driven_death()` hook** — runs in the
  combat loop before the HP-based `is_dead()` branch so monsters
  can declare themselves dead on body-part state alone. Default
  returns `None` (opt-in per monster).
- **Hydra override** detects 0 non-critical heads, zeroes
  `self.health`, and returns the decap narration. The old
  detection inside `on_combat_round` (which fired AFTER
  retaliation) is gone; `on_combat_round` is now regrowth +
  cooldowns only.
- **Grammar + pool** — prior decap line had a grammar bug;
  replaced with a correct-article 3-line pool. Per-variant flavor
  is still backlogged.

Also: test-architecture hardening that the hydra work surfaced.
`tests/conftest.py` now autouse-isolates `random` module state
around every test — any test (or tool invocation from a test)
that seeds `random` no longer poisons the RNG for later tests.
Per-monster backwards-compat tests (sheep, dragon, giant, goblin,
toad) also mirror `get_defense` / `get_dodge`'s min-1 clamp so a
low stat roll × small size_mod doesn't flake `int()` truncation
against an equality assert.

### 2026-04-19 — Social Warmth: `$warmth` + 14 Social Verbs

Players can now tune how warmly they receive and attempt social
gestures, per-command and per-other-player. Replaces the hard-
coded `$hug` sidestep with a tunable consent-style model.

- **Scale**: `cold | cool | neutral | warm | hot` plus input
  aliases (`friendly`, `aloof`, `ardent`, …).
- **Resolution**: target governs acceptance (what happens), actor
  governs intent (flavor tint). Target-side wins the asymmetry.
- **Data**: `Player.social = {"defaults": {cmd: level},
  "per_player": {uid_str: {cmd: level}}}`. Stored only when the
  player sets something; legacy players load as empty.
- **Privacy**: `$warmth` output is DM-only; channel sees a brief
  ack. `$warmth set` echoes in channel when invoked publicly, DM
  when from DM.
- **Wildcards**: `$warmth set all <level>` / `$warmth clear all`
  apply across every warmth-aware command.
- **Mention-misparse**: `$warmth clear @player` auto-routes to
  `clear all @player`; `$warmth set @player <level>` returns a
  tailored error rather than echoing `<@id>`.

New cog `rpg_social_commands.py` (with `$hug` and `$haunt` moved
in) houses:

- `$warmth` / `$warmth set <cmd> <level> [@player]` /
  `$warmth clear <cmd> [@player]`.
- 12 warmth-aware verbs (`hug`, `high_five`, `fistbump`,
  `salute`, `comfort`, `poke`, `nod`, `glare`, `shank`, `tickle`,
  `taunt`, `wink`) with 5-level intent/acceptance pools and
  dead-invoker / dead-target flavor.
- 5 self-directed solos (`pose`, `cheer`, `cry`, `wave`, `bow`).
  Mentions passed alongside are silently ignored
  (documented-intentional).

Monster-side reactions via `Creature.on_social(cmd, actor,
invocation)` — generalized from `on_hugged` with back-compat
delegation. Bandit ships `$high_five` (3-pool with 1-in-3 steal
chance, community-suggested) and its hug + high-five flavor
rewritten 2-party + italicized. `$comfort` WARM/HOT beats tuned
from pre-embrace forms to offering gestures. Wink HOT-vs-NEUTRAL
"mirror" leak fixed.

### 2026-04-19 — Player / Combat / Flavor Fixes

Grab-bag of correctness issues surfaced in live playtest.

- **`PlayerManager.add_player`** — missing
  `self.players[uid] = player` meant new players couldn't join
  until the next bot restart rehydrated them from Mongo. First
  reported by a tester who couldn't run `$join`.
- **`on_member_update` listener** — Discord display-name edits now
  sync live instead of waiting for a bot restart.
- **Doppelganger `imitate()`** — now copies target's gender and
  pronouns alongside name/stats, so mimicked narration agrees.
- **Golem arrival line** — `@1s` → `@1sc` so the sentence starts
  with capitalized "His" rather than bare "his".
- **Combat `resolve_attack` auto-infers attacker** — callers no
  longer need to pass the `attacker` kwarg explicitly; inferred
  from `sequence.attacker`. Every `Creature` override kept in sync
  with the new signature.
- **`critical_part_kill` signal** — `ResolutionResult` carries an
  explicit flag for deaths via critical-part destruction, so the
  "0 vs X remaining" summary skip is no longer mis-triggered on
  magic-bypass / status-tick kill paths.
- **Injury-feedback owner attribution** — feedback lines now
  prepend `@1npc` owner ("Caels's right leg appears severely
  wounded") instead of the bare part name.

### 2026-04-19 — `$pray` Heal-Amount Display Fix

`$pray` rolls 17–19 heal body HP and fully restore one injured
part. The announcement used to report only the body-HP delta —
"imbuing him with 1 points of health" when an arm missing 8 HP
was also being restored in the same beat.

Now reports `total_heal = body_heal + part_restore_amount` with
correct singular/plural ("1 point" / "3 points"). Mechanics
unchanged.

### 2026-04-19 — Operator Tooling: `render_flavor`, `inspect_tests`, `rename_in_tree`

Three new `tools/*.py` modules, each replacing an inline-python
shape that would otherwise force per-call permission approvals.

- **`render_flavor`** — renders a monster's flavor strings,
  `on_hugged`, and `on_social` branches through the parser.
  Catches parse-token bugs (`@1d` vs `@1dc`, `@1np` vs `@1's`)
  before they hit a live channel.
- **`inspect_tests`** — AST-level pytest file inspector (count /
  list / structure / find / json). Replaces ad-hoc `grep "def
  test_"` parsing.
- **`rename_in_tree`** — bulk literal multi-pair replace across
  a file glob with dry-run default.

Top-level `CLAUDE.md` added documenting the parse-token cheat-
sheet and the "prefer tools over inline python" convention, so
future agent sessions don't default to one-off `python -c` calls.

### 2026-04-19 — `tail_channel.py` Default Buffer: 500 → 5000

Bumped the `--follow` inspector's default ring buffer from 500 to
5000 messages. Costs a few MB of RAM at most, buys ~10× the
retention so an all-day idle tail still has a useful window to
peek into. `--buffer-size` override still works either direction.

### 2026-04-19 — Shutdown Log Visibility

Promoted two per-task-cancel beats from DEBUG to INFO and added an
INFO line at the start of `_stop_per_game_routines` so LIVE logs
(which run at INFO) show the shutdown sequence beat-by-beat
(dispatcher drain, per-game routine stop, watchdog / save /
batch_write cancel, final flush, exit) instead of silently
eliding the whole middle. Matters when diagnosing a shutdown hang.

### 2026-04-19 — `tail_channel.py` Polish: Mentions, ANSI, Spacers, Timerange

- **User-mention resolution**: `<@id>` / `<@!id>` in message
  content now render as `@<player_name>` via a one-shot lookup
  against the game's players collection. Unknown ids
  (non-players) stay raw so the reader can still investigate.
- **ANSI strip**: SGR color escapes from `$health` / body-parts
  panels (`\x1b[2;32m…\x1b[0m` and the bare-bracket form some
  serializers leave behind) are scrubbed before text rendering.
- **Zero-width embed spacer fields**: Discord's vertical-spacer
  fields (name and value both a zero-width unicode char) flattened
  to a noisy `​: ​` line; now skipped entirely.
- **Timerange flags for `tail_peek`**: `--after <ISO-timestamp>`
  synthesizes a Discord snowflake and uses it as the `since`
  cursor; `--before <ISO-timestamp>` applies client-side as an
  upper bound. Combine for a full timerange view of the buffer.

### 2026-04-18 — Qualname Fallout: `$stimer` Lookup + Routine Log Label

Two stragglers from the earlier `_Routine` qualname refactor:

- **`$stimer` / `$spawn` admin display** always reported "Next spawn
  is not yet determined…" even when the spawn routine was clearly
  live. Both cogs queried `find_routine("do_spawn")`, but routines
  register under `__qualname__` (`"Game.do_spawn"`) — strict equality
  missed forever. Fixed by passing `game.do_spawn.__qualname__` at
  both call sites.
- **"Game routine running:"** debug log printed the bare method name
  instead of the qualified form, so `WeatherDaemon.tick` and
  `CelestialDaemon.tick` both showed up as just `tick`. Switched to
  `self.name` (already the qualname form the registry uses).

`GameClock` regression test pins the qualname-vs-barename contract
so a future caller can't rediscover the same trap.

### 2026-04-18 — Operator Tooling: `tail_peek.py`

Companion to `tail_channel.py`. Wraps `GET /tail` on the local
inspector and pretty-prints the JSON as pastable markdown
(`##` header per message, `>`-quoted body, metadata footer with
buffer usage / dropped count / latest id for easy cursor reuse).

```
python -m tools.tail_peek                      # full buffer
python -m tools.tail_peek --since <id>         # incremental
python -m tools.tail_peek --tail 10            # last 10
python -m tools.tail_peek --json               # raw passthrough
```

Stateless — no cursor file on disk (the ring buffer is the
whole point of the in-memory design). Error paths print an
operator-friendly hint if `tail_channel --follow` isn't
running, rather than a stack trace.

### 2026-04-18 — Operator Tooling: `tail_channel.py`

New `tools/tail_channel.py` fetches the last N messages from a
game's channel (default 10) and, with `--follow`, keeps polling
new ones via REST (`after=<last_seen_id>`). Coexists with the
live bot — no Gateway connection. Channel discovery is per-game:
the tool picks from live games in the selected DB and resolves
channel names via Discord so the picker is human-readable.
`--channel-id` skips discovery entirely.

Embed-aware content rendering: monster spawn cards, `$spawn` /
`$help` info embeds, `$look` panels, and any other embed-only
messages render their title / description / fields as text
instead of showing up blank.

**In-memory inspector in `--follow` mode.** Tool holds a
`deque(maxlen=500)` ring buffer and serves `GET
http://127.0.0.1:8765/tail?since=<cursor>` returning JSON
(`messages`, `dropped_count`, `buffer_size`, `buffer_max`). Lets
an on-demand inspector pull backlog without grepping stdout or
hitting Mongo. `--buffer-size` and `--port` tune it.
Loopback-bound, no auth.

Added `DiscordRestClient.get_channel` to `tools/_common.py` for
the channel-name resolution step.

### 2026-04-18 — Dragon Breath Math Fix

Breath now honors the victim's FIRE trait multiplier (fire-resistant
creatures take reduced damage, fire-weak take amplified). The rendered
damage total also lines up with reality — the previous code passed
post-defense damage into the `AttackResult`, so the shared renderer
subtracted defense a second time and reported a number smaller than
what was actually applied to the victim. Pre-existing; surfaced now
that enrage makes breath fire more often.

### 2026-04-18 — Dragon Enrage

Breath chance is no longer a flat 20% per round. Starts at 20%,
climbs `+10%` each round the dragon doesn't breathe, resets to
20% when breath fires. Long dragon fights get progressively more
existential instead of feeling the same at round 1 and round 10.

Any dragon body part dropping to destroyed — including a wing,
which also grounds it — forces a breath on the dragon's next
turn with a rage intro prepended to the breath flavor. Wing-loss
gets a grounding-specific line; other destructions get a generic
rage bellow.

### 2026-04-18 — Operator Tooling: `tools/` + Per-Guild Channel Registry

Added a `tools/` subdirectory of standalone Python scripts that
talk to Discord *as the bot* via REST (no Gateway connection,
so they coexist with the live bot). Reduces copy-paste friction
for two operator workflows: posting patch notes and reading
the players' ideas channel.

**Per-guild channel registry on `servers`:**

```python
DB.GUILD_CHANNEL_KEYS = ("updates", "ideas")
DB.set_guild_channel(guild_id, key, channel_id)
DB.get_guild_channels(guild_id) -> dict
```

Channel ids stored under `channels.<key>` on each server doc.
Setter validates the key against the canonical set so a typo
can't write a garbage field. Configured from inside Discord:

```
$config                                   # show current registry
$config channel updates <#mention>
$config channel ideas <#mention>
```

`$config` lives on `BotAdminCommands`, owner / manage-guild
gated.

**`tools/_common.py`:** shared helpers for the tools — lazy
`MongoClient` against the live DB, `get_auth()` to pull the
bot token from the existing `auth` collection, channel
resolution, and a minimal `DiscordRestClient` (post / get
messages only).

**`tools/post_patch_notes.py`:** posts `.patch-notes-scratch.md`
(the file the pre-commit ritual writes) to every guild with
an `updates` channel registered. Dry-run by default;
`--post` to fire. `--guild` scopes to one. Refuses content
over Discord's 2000-char limit rather than silently truncating.
Records each successful post in
`tools/.last_posted.<DB_ENV_VAR>.json` (gitignored, one file
per database env so a LIVE post and a TEST post for the same
guild can never collide) so the edit tool can find what to
amend later.

**`tools/edit_patch_notes.py`:** edit a previously-posted
patch notes message in place via Discord's PATCH endpoint.
Defaults to editing each guild's most recent post recorded
by `post_patch_notes`; `--message-id` (with `--guild`)
overrides for cross-machine or pre-log scenarios. Dry-run
shows the existing content next to the new content;
`--post` applies the edit. Bots can only edit their own
messages, so the default path is naturally scoped to what
this tool produced.

**`tools/check_ideas.py`:** cursor-based fetch of new
messages from each guild's `ideas` channel, formatted as
planning-ready markdown (timestamp + author + verbatim
content). Per-guild cursor at
`tools/.ideas_cursor.<DB_ENV_VAR>.json` (gitignored, same
per-env isolation as `.last_posted`). `--reset` clears,
`--limit` sizes the first-run window. Partial failure across
guilds doesn't abort the rest.

**Per-env state file abstraction:** `_post_log` and
`check_ideas` both persist per-(env, guild) state and now
share `tools/_common.state_file_path` /
`load_state_file` / `save_state_file` helpers. Filename
schema is `.<base_name>.<DB_ENV_VAR>.json`; gitignore covers
`.last_posted.*.json` and `.ideas_cursor.*.json`.

**Shutdown polish:** the per-second `dispatcher.send`
`tasks.Loop` now gets explicitly cancelled right after the
drain, before `bot.close()`. Without this, it ticks against
a half-closed discord.py session and raises a noisy (benign)
`ClientException` that bubbles to `discord.ext.tasks`'s
catch-all.

**Lifted hardcoded DB names into env (`LIVE_DB_NAME`,
`TEST_DB_NAME`):** `db/__init__.py` previously hardcoded
`caldanaiTest` and `caldanaiDB`. Now read from
`caldanai.environment` so forks point at their own DBs without
a code edit. **Deploy note:** existing deployments must add
`LIVE_DB_NAME=...` (and `TEST_DB_NAME=...` for local dev) to
their `.env` before this lands — defaults are generic
placeholders, not the canonical names.

**Tools/Forks docs:** `tools/README.md` covers setup +
per-guild registration; `tools/.env.example` shows the env
vars the tools read.

**Tests:** ~85 new across `test_db.py` (channel registry
helpers, per-env file isolation), `test_bot_admin_commands.py`
(`$config` + `$config channel` sub-group), `test_tools_common.py`
(live-DB connection, REST client + edit/get_message,
channel resolution, env-var-driven DB selection),
`test_tools_post_log.py` (per-env record/lookup with
filesystem isolation), `test_tools_post_patch_notes.py` and
`test_tools_edit_patch_notes.py` (orchestration, dry-run,
exit codes, partial-failure), `test_tools_check_ideas.py`
(cursor round-trip, per-env isolation, format).

### 2026-04-18 — Durable Shutdown + Signal Integration

The ``shutdown`` console command used to hang until operator
SIGINT, and nothing flushed the DB write buffers before exit.
Restarts between ``batch_write``'s 1-minute drain cycles silently
lost player state — worst for DM-originated commands with no
operator visibility. ``SIGINT`` and container-stop signals didn't
reach the shutdown path at all. A redundant Discord-side
``$shutdown`` command duplicated the process-kill power from an
inappropriate surface.

Rebuilt as a single arc:

**New synchronous drain primitives:**
- ``DB.flush_all()`` — drains every collection's double-buffer
  plus the Mongo log-handler queue; swallows ``BulkWriteError``
  per collection so one failing collection doesn't eat the rest.
- ``save_all_now()`` in ``utils.py`` — extracted from the
  ``save_game_data`` task body so the periodic save and the
  shutdown save share one implementation.

**Rewritten ``ShutdownCommand`` — ordered contract:**
1. Announce and drain Dispatcher (30 s timeout).
2. Stop per-game clock ticks + ambience daemons.
3. ``state.set_shutdown()`` **before** ``await bot.close()`` —
   otherwise ``main.start_bot``'s
   ``while state.should_restart()`` loop sees ``bot.start``
   return and stands up a replacement bot mid-shutdown
   (regression caught in playtest).
4. ``await bot.close()``.
5. Cancel + await the ``watchdog``, ``save_game_data``, and
   ``batch_write`` task loops in that order — watchdog first so
   it can't restart ``batch_write``; cancel + await (not
   ``.stop()``, which is cooperative) so no mid-execution tick
   races the flush.
6. ``save_all_now()`` → ``DB.flush_all()`` — atomic by
   construction (no ``await`` between them on the single-
   threaded loop).
7. Mongo client close.
8. ``os._exit(0)`` — escapes the blocking ``input()`` thread
   that would otherwise hold the interpreter open.

**Signal handlers in ``main.py``:** ``SIGINT`` / ``SIGTERM`` /
``SIGBREAK`` route via ``loop.call_soon_threadsafe`` onto the
same command queue ``cmd_loop`` reads, so a Ctrl+C fires the
exact same ``ShutdownCommand.execute`` sequence as typed input.
Missing signals on a given platform are silently skipped. The
handler logs the received signal name — diagnostic win for
hosting platforms whose stop semantics aren't documented.
``SIGKILL`` / Windows ``TerminateProcess`` remain uncatchable.

**Companion fix in ``input_loop``:** Windows Ctrl+C closes stdin
as a side effect, raising ``EOFError`` back into the input-loop
coroutine. Without handling, ``asyncio.gather`` cancelled
``cmd_task`` mid-shutdown. Input loop now catches ``EOFError``
and exits cleanly, letting the already-enqueued shutdown
complete.

**Removed the Discord ``$shutdown`` command** in
``bot_admin_commands.py`` along with the ``wait_to_close`` and
``flush_dispatcher`` helpers that only it used. Process control
doesn't belong on Discord — the console path is the legitimate
kill path and hosting panels cover the rest. No replacement
added; ``$game remove`` covers per-channel cleanup.

**Tradeoffs:** Ctrl+C now takes ~1.5 s (Dispatcher drain + DB
flush) instead of aborting instantly — durability over
responsiveness. ``os._exit`` skips ``atexit`` handlers and
Python's stdio flush; nothing load-bearing lives there.

**Tests:** ``test_db.py::TestFlushAll``,
``test_utils.py::TestSaveAllNow``, ``test_shutdown_command.py``,
``test_main_signal_handlers.py`` — drain correctness,
save/loop equivalence, full shutdown ordering (including the
set-shutdown-before-bot-close regression), cancel + await
semantics, and signal-handler platform tolerance.

### 2026-04-18 — Ambience Kill-Switches Split Per Subsystem

``$ambience`` was a single master flag that silenced three
unrelated subsystems at once (random local flavor, sunrise/sunset,
weather daemon). Split into a master plus three per-subsystem
flags; the master ANDs with each.

**New on ``Game``:**

```python
AMBIENCE_SUBSYSTEMS = ("local", "celestial", "weather")

def ambience_enabled(self, subsystem: str) -> bool:
    return self.enable_ambience and bool(
        getattr(self, f"enable_ambience_{subsystem}", True)
    )
```

Plus ``sync_ambience_daemons()`` which brings every daemon's
scheduling state in line with the current flags — called after
any toggle.

**Command surface:**

```
$ambience                       # show master + per-subsystem state
$ambience on | off              # master toggle
$ambience <subsystem> on | off  # local | celestial | weather
$ambience set on | off          # legacy alias for master
```

**Renamed:** ``SunriseSunsetDaemon`` → ``CelestialDaemon`` (file
``sunrise_sunset.py`` → ``celestial.py``) to make room for
planned sun/moon-traversal expansion without another rename.

**Persistence:** all four flags round-trip via ``to_dict`` /
``from_dict``; ``from_dict`` uses ``.get(..., True)`` so pre-
split documents load with every subsystem on.

**Pre-existing bug fixed:** the old ``ambience_set`` command
restarted the sunrise/sunset daemon on toggle but never the
weather daemon, orphaning weather narration at runtime.
``sync_ambience_daemons`` now handles all three uniformly.

**Routine-registry collision fix (playtest-surfaced):**
``GameClock._Routine.name`` was keyed on ``function.__name__``,
so ``WeatherDaemon.tick`` and ``CelestialDaemon.tick`` both
registered as ``"tick"`` and evicted each other under
``only_instance=True`` — the clock could only drive one of them
at a time. Keyed on ``__qualname__`` instead. ``add_routine``
is now **skip-if-found** instead of evict-and-replace (old
behavior silently reset ``time_added`` phase anchors and daemon
state on every ``sync_ambience_daemons`` call).
``CelestialDaemon.start`` made idempotent so repeated
``start()`` calls don't reset ``_last_tick_seconds``.
``find_routine`` logs on hits as well as misses for clearer
diagnosis.

**Tests:** ``Game.ambience_enabled`` truth table, ``to_dict``
flag emission, routine-registry collision regressions, skip-if-
found semantics, idempotent daemon start.

### 2026-04-18 — `$target` Command Polish

Three changes:

1. **Guard reorder:** when no monster is active, ``$target`` now
   answers ``"There's nothing to target!"`` regardless of
   combatants-list membership. The old order surfaced ``"Use
   $kill to join!"`` in idle channels — nonsense.

2. **Player-mention flavor:** ``$target <@mention>`` emits
   flavor-only responses in the spirit of ``$smite`` / ``$hug``.
   Five pools on ``RpgUserCommands``:
   - ``_TARGET_SELF_FLAVOR`` — self-targeting humor.
   - ``_TARGET_OTHER_FLAVOR`` — other-player humor.
   - ``_TARGET_BOT_FLAVOR`` — targeting the bot.
   - ``_TARGET_DEAD_INVOKER_FLAVOR`` / ``_TARGET_DEAD_TARGET_FLAVOR``
     — dead-invoker and live-targets-dead-player cases. Dead-invoker
     check runs first, before bot / doppelganger / target-player
     dispatch (regression fix — initial version had the bot branch
     bypass the death check).

3. **Doppelganger cooperation:** when the mentioned player's
   ``display_name`` matches the current monster's ``name``,
   nudge toward the body-part flow instead of emitting player
   flavor. Mirrors the ``$hug`` detection pattern.

**Tests:** flavor-pool structure + parse-token correctness,
guard-order regression, mention-type routing (self / other /
bot / doppelganger / dead-invoker across all mention types).

### 2026-04-18 — Shared Dead-Invoker Guard + Flavor-Pool Expansion

Eight commands had inline ``if player.is_dead(): dispatch
f-string; return`` blocks; four inventory handlers repeated
the exact same f-string. Consolidated into a shared helper with
per-command flavor pools.

**New on ``RpgUtilities``:**

```python
@staticmethod
def dead_invoker_guard(channel, player, flavor) -> bool:
    """Emit flavor and return True when player is dead; no-op False otherwise.
    ``flavor`` is a parse-template string OR a list (random pick)."""
```

Handlers now read ``if RpgUtilities.dead_invoker_guard(...):
return`` — one line, consistent shape.

**Migrated:** ``$kill`` / ``$attack``, ``$hug``, ``$target``,
and the four inventory commands (``$equip`` / ``$stow`` /
``$sell`` / ``$item`` — the four identical inline f-strings
collapsed to one shared pool).

**Not migrated (by design):** ``$haunt`` uses death as a
required *input* (dead players can haunt; live can't). ``$pray``
has its own specialized dead-flavor branching. Neither fits the
gate-and-return shape.

**Variety bump:** each migrated command got a 5–7-line flavor
pool matching its emotional register — war-drum echoes for
attack, affectionate chill-against-the-veil for hug, dry
frustration for inventory.

**Tests:** guard behavior (alive/dead/string/list/parse-tokens);
every registered pool is non-empty and every line parses with
no surviving ``@`` tokens.

### 2026-04-18 — Partless-Creature Double-Damage Fix

Playtest: Spirit (16 HP) died to a single 10-damage crit that
should have left it at 7 HP. Leftover from the Phase 1 per-part
combat refactor:

- **Parts creatures:** ``Creature.apply_damage(amount,
  target_part)`` routes to the part; ``Game.do_combat`` applies
  body HP post-sequence via ``monster.health -= final_body_dmg``.
- **Partless creatures (Spirit):** ``target_part`` is always
  ``None``, so ``apply_damage`` used the legacy whole-body path
  and decremented ``self.health`` directly — *and* the caller
  subtracted again afterwards. Double-applied.

Fix in ``apply_sequence_to_target``: skip ``apply_damage`` when
the target has no body parts. Body HP is the caller's sole
responsibility across both paths. Partless death flows through
the caller's existing ``monster.health == 0`` fallback.

**Tests:** ``test_combat_resolution.py`` — the test that used to
pin the buggy behavior now pins the inverse (body HP unchanged
by the resolver; totals still accumulate for the caller).
Renamed to name the regression explicitly.

### 2026-04-18 — Spirit Intangibility Narration Fix

Spirit's "blade passes through like mist" callout was supposed
to surface on physical hits. It never fired: the flag gating it
lived in ``Spirit.apply_damage``, but ``apply_sequence_to_target``
skips ``apply_damage`` when damage is ``≤ 0`` — and physical vs.
Spirit always multiplies to ``0`` after the ``0.1`` multiplier.

Moved the narration into ``_on_attacked``, appending to
``result.extra_text`` on every landed physical hit. Two
improvements:

1. **Placement:** ``extra_text`` renders inline with the attack-
   table row (same home as the ``"chill saps N from the
   attacker"`` snippet), not tucked into a post-round footer.
2. **Per-hit, not one-shot:** the line is an observation of the
   current attack, not a teaching moment. Dual-wielders see it
   on both hits, return-engagers see it every time.
   ``_has_announced_intangibility`` flag removed.

Wording changed from ``"@2's blade passes through…"`` to
``"the blow passes through like mist"`` — weapon-agnostic
(blades, sticks, wands all look the same to a ghost). Spirit's
``apply_damage`` override removed; ``MonsterPlugin.apply_damage``
covers the death-string return.

**Tests:** ``_on_attacked`` now end-to-end — injects the mist
line on landed physical hits, fires every hit (not just the
first), skips non-physical and misses, composes with the melee
chill-counter snippet on the same ``extra_text``.

### 2026-04-18 — Target Preferences as Declarative Dict on `Creature`

Six monsters (Bearowl, Werewolf, Vampire, Pixie, Minotaur, Bandit)
each had a ``get_target_part_preference`` override that was just
``if random() < P: return PART``. Consolidated to a class-level
declarative attribute on ``Creature`` plus a single default method
implementation that every subclass inherits.

**New on `Creature`:**

```python
TARGET_PREFERENCES: Dict[str, float] = {}

def get_target_part_preference(self, target, source):
    for part_name, prob in self.TARGET_PREFERENCES.items():
        if random() < prob:
            return part_name
    return None
```

Dict iteration order (insertion order on Py3.7+) is significant:
each entry rolls ``random()`` independently and the first success
short-circuits. Empty dict = no bias, fall through to
exposure-weighted random targeting.

``Creature.has_target_preference`` collapses to
``return bool(self.TARGET_PREFERENCES)`` — no more identity-check
against ``Creature.get_target_part_preference`` vs an override.
``MonsterPlugin``'s previous redundant override of both methods
is gone; the dict is the single source of truth.

**Migrations** (all single-entry, RNG-count-identical to the old
overrides):
- Bearowl → ``{"head": 0.4}``
- Werewolf → ``{"head": 0.3}``
- Vampire → ``{"head": 0.4}``
- Pixie → ``{"eye": 0.3}``
- Minotaur → ``{"head": 0.5}``
- Bandit → ``{"leg": 0.3}``

Existing docstring rationale for each per-monster preference
preserved as a class-level comment above each ``TARGET_PREFERENCES``
declaration — no design intent lost.

Creatures with logic beyond flat-probability rolls (conditional on
target state, weapon reach, feed mechanics, etc.) override
``get_target_part_preference`` directly — the dict is for the
common case, not a straitjacket.

Players inherit the empty-dict default and never populate it;
their targeting is human-driven (``$kill <part>``) so the
declarative attribute is inert for them but costs nothing to
carry.

**Multi-entry semantics for future multi-preference creatures**:
per-entry independent coin flips, NOT partitioned ranges.
Documented in the class-level comment so future readers don't
assume a creature with ``{"head": 0.3, "leg": 0.3}`` always picks
exactly one.

### 2026-04-18 — `Game.get_player_by_user_id` Helper

Thin read-only façade over ``player_manager.players`` for callers
outside ``PlayerManager`` that need a user-id → ``Player`` lookup.
Shields callers (currently just ``Bot.on_command_completion``)
from the underlying dict shape. Mutation (``add_player`` /
``remove_player``) remains on ``PlayerManager``.

``Bot.on_command_completion`` migrated from the old
``in game.player_manager.players.keys() and player :=
game.player_manager.players[...]`` pattern to a single
``player := game.get_player_by_user_id(...)`` walrus. Semantically
identical (``.get()`` returns ``None`` when absent, truthy check
short-circuits the same way), one less layer of dict spelunking
in the call site.

Closes review finding 3.8.

### 2026-04-18 — Dead Hook Removed: `BodyPart.get_injury_flavor`

The base ``BodyPart`` class carried a ``get_injury_flavor(level)``
method defined in 2026-04 but never called by combat narration.
The actual narration flow goes through ``get_injury_string`` +
monster-level hooks; ``get_injury_flavor`` was vestigial. Removed
from the base class; corresponding default-value test dropped.

### 2026-04-18 — `GameClock._clocks` Registry Consolidated

The third parallel channel-id registry is gone. ``GameClock._clocks``
duplicated the channel → object lookup that ``Game._channel_routes``
already owns — removed entirely, along with the
``GameClock._register`` / ``_unregister`` classmethods that fed it.

**New:** ``GameClock.for_channel`` is now a two-line shim that
defers to ``Game._channel_routes`` via a method-local import:

```python
@classmethod
def for_channel(cls, channel_id):
    from caldanai.lib.rpg import Game
    game = Game.for_channel(channel_id)
    return game.game_clock if game is not None else None
```

All 9 existing ``GameClock.for_channel`` call sites (3 in ambience
daemons, 6 in the ``time`` module façade functions) keep working
unchanged — the shim preserves the pre-refactor shape while
routing through the single source of truth.

**Teardown simplified:** ``RpgUtilities.remove_game`` no longer
calls ``GameClock._unregister(channel_id)``. Just ``unregister_channel``
on the game is enough; the clock lookup falls through to ``None``
automatically.

**Lifecycle check:** verified every production lookup runs between
``register_channel`` and ``unregister_channel``. Both ``__init__``
and ``from_dict`` register before any daemon ``start()``; ``remove_game``
stops daemons and the clock tick before unregistering. No tick can
race the teardown.

**Completes slice 3 of the Game god-object shrinking** started with
the ``CombatState`` extraction (slice 1, 2026-04-17) and the
``do_health_regen`` move to ``PlayerManager`` (slice 2, 2026-04-18).
Three parallel channel-id registries are now two
(``Game._channel_routes`` as the truth, ``Bot.games`` as a view).

### 2026-04-18 — `do_health_regen` Moved to `PlayerManager`

Slice 2 of shrinking the ``Game`` god-object. ``Game.do_health_regen``
(and its private helper ``_most_injured_part``) were closed over
``player_manager.players`` + ``self.channel`` — no game-scoped state
they couldn't carry themselves. Moved to ``PlayerManager``.

**Change:**
- ``PlayerManager.__init__`` now accepts an optional ``channel`` param
  and stamps ``self.channel = channel``. Game passes it at construction;
  ``Game.from_dict`` re-stamps after resolving the channel from the bot
  cache. Routines that fire before the channel is bound silently skip
  dispatch.
- ``do_health_regen`` + ``_most_injured_part`` live on ``PlayerManager``.
- ``Game.__init__`` still owns scheduling:
  ``self.game_clock.add_routine(self.player_manager.do_health_regen,
  1800 / self.game_clock.time_scale)``. The routine's ``__name__``
  is preserved for ``GameClock``'s name-based lookup / deduplication.
- Five existing tests relocated from ``tests/test_game.py`` to
  ``tests/test_player_manager.py``; assertions unchanged, setup
  simplified to direct ``PlayerManager(channel=...)`` instead of full
  ``Game`` + ``GameClock`` + ``DB`` mocking. Breadcrumb left in
  ``test_game.py`` for future readers.

### 2026-04-17 — Monster Name Lookup → Plugin Registry

``Game.get_monster(name)`` re-globbed
``caldanai/lib/rpg/creatures/monsters/*.py`` on every admin
``$spawn monster <name>`` invocation, rebuilt a name list, then
re-imported the module. Meanwhile every monster class is already
loaded at startup via ``PluginManager.load`` into
``PluginManager.LOADED_PLUGINS[MonsterPlugin]``.

**New:** ``MonsterPlugin.get_plugin_class(name) -> Type[MonsterPlugin] | None``
— a classmethod backed by ``MonsterPlugin._PLUGIN_REGISTRY``.
``load_plugins`` now populates the registry keyed by **filename
stem lowercased** (not class name — ``MathTeacher`` lives in
``math_teacher.py`` and the admin spawn command addresses it as
``math_teacher``).

**`Game.get_monster`** becomes a registry lookup. Filesystem glob
and lazy ``importlib.util`` dance are gone, along with the
``importlib``, ``glob``, and ``os.path`` imports on that file.

**Behavior preserved exactly:**
- Case-insensitive match (lowercases the input) — same as before.
- On miss: ``Dispatcher.add`` "There is no such thing as a {name}!"
  + ``_log.error`` + ``return False``. Same as before.
- On hit: instantiates the class via ``cls()``. Same as before.

45 new tests in ``test_monster_plugin_registry.py`` — known-name
lookups, case variants, unknown-name misses, base class not in
registry, and a parametrized round-trip over every discovered
monster.

### 2026-04-17 — Sunrise/Sunset Narration → `SunriseSunsetDaemon`

``Game.do_ambience`` was mixing three unrelated concerns: the
``enable_ambience`` kill switch, the sunrise/sunset crossing
narration (tracked via ``_last_ambience_tick``), and the random
flavor-ambience roll. Split the middle one out onto the time
subsystem where it belongs.

**New:** ``caldanai/lib/rpg/ambience/sunrise_sunset.py`` —
``SunriseSunsetDaemon``, a sibling of ``WeatherDaemon`` following
the same clock-routine lifecycle pattern.

- Registers a 1-second routine via ``schedule_routine``.
- Each tick: advances the tracking window (even when gated), gates
  narration on ``Game.enable_ambience``, fires sunrise / sunset
  strings when ``last < boundary_s <= game_time``.
- Crossing predicate and narration strings (``SUNRISE_NARRATION``,
  ``SUNSET_NARRATION``) preserved verbatim — byte-identical
  user-visible output.
- **Window advances even while disabled**: a crossing that happens
  during an ``$ambience off`` stretch is NOT replayed when ambience
  is re-enabled. Locked in by
  ``test_no_buffered_crossing_replay_when_reenabled``.

**`Game.do_ambience`** shrinks to just the kill-switch guard + the
random flavor roll. ``_last_ambience_tick`` field removed entirely.

**Lifecycle symmetry with weather:**
- ``$ambience on/off`` admin command toggles the daemon alongside
  ``do_ambience``.
- ``RpgUtilities.remove_game`` stops ``game.sunrise_sunset``
  alongside ``WeatherDaemon``.

**Kill-switch semantics preserved** (option (a) in the plan):
``enable_ambience=False`` still suppresses sunrise/sunset narration,
matching pre-refactor behavior. Splitting them into separate kill
switches is a tracked follow-up, not in this change.

### 2026-04-17 — `apply_damage` Signature Standardized

The `apply_damage` family had drifted across ``Creature`` subclasses
(base → ``None``, ``MonsterPlugin`` → ``str``, ``Player`` → ``str``,
``BodyPart`` → ``None``). Standardized return types across the
Creature family and made ``apply_damage`` a pure damage-application
primitive — hook firing is now unambiguously the combat helper's
responsibility.

**Unified signature** on every override in the Creature family:

```python
def apply_damage(
    self,
    amount: int,
    dmg_type: Optional[DamageTypes] = None,
    target_part: Optional["BodyPart"] = None,
) -> Optional[str]:
    ...
```

Covers: ``Creature`` (base), ``Player``, ``MonsterPlugin``, ``Spirit``,
``Werewolf``. Return type now consistently ``Optional[str]`` with ``""``
as the "no event" default — falsy, so every ``if msg:`` caller pattern
continues to work unchanged.

**Hook firing is the caller's responsibility.** ``Creature.apply_damage``
routes damage to the targeted part, updates HP, handles critical-part
death, and returns. It does NOT fire ``on_injury_change`` or
``on_destroyed``. The ``apply_sequence_to_target`` combat helper owns
hook firing, coalescing transitions across a whole attack sequence
so multi-source sequences don't produce duplicate side effects (wing
grounding, doppelganger pain cries, etc.).

This replaces an earlier attempt at encoding the invariant via a
``fire_hooks`` kwarg. Post-review, that flag turned out to be
signature noise: no non-combat caller in the codebase routes a
``target_part`` (they all hit the legacy whole-body path), so the
``fire_hooks=True`` branch was never reached in production — it was
pinning a hypothetical future contract. Ripping it out strengthens
the "combat helper is the one and only hook-firing path" contract
and drops 5 mirrored signatures back to 4 params.

**Behavior preserved exactly** for every cog path ($pray, $smite,
$unsmite), monster body-floor applies, health regen, vampire feed,
dragon breath, etc. Combat paths continue to use the helper, which
continues to coalesce hooks.

**Tests**: 3 tests in ``tests/test_apply_damage.py::TestApplyDamageDoesNotFireHooks``
pin the "apply_damage never fires hooks" contract. The helper's own
hook-firing invariants remain covered in ``test_combat_resolution.py``
(22 tests unchanged).

**Punts**: ``BodyPart.apply_damage`` intentionally unchanged — no
BodyPart subclass overrides it, and it's outside the Creature family
the review targets. ``on_target_part_destroyed`` (attacker hook) stays
where it was — the combat helper owns it via its ``attacker=`` kwarg.

### 2026-04-17 — Channel Registry Consolidated (single source of truth)

``Bot.games`` and ``Game._channel_routes`` previously stored the
same ``channel_id → Game`` mapping in parallel with slightly
different lifecycles. ``RpgUtilities.remove_game`` had to poke
three places on teardown (``unregister_channel``,
``del bot.games[channel_id]``, ``GameClock._unregister``); miss one
and the game leaks.

**Change:** ``Bot.games`` is now a ``@property`` that returns a
``types.MappingProxyType`` live read-only view of
``Game._channel_routes``. External writes are no longer possible
(``TypeError`` at the type level) — the class registry is the
single source of truth.

- ``register_channel`` / ``unregister_channel`` remain the only
  write path; every existing caller (36 read sites across cogs,
  bot, helpers, db, console, tests) continues to work unchanged.
- Three direct writes removed:
  - ``bot.games[channel.id] = self`` in ``Game.__init__``
  - ``bot.games[game.channel.id] = game`` in ``add_game``
  - ``del bot.games[channel_id]`` in ``remove_game``
- Spillover channels (dungeon threads) registered via
  ``game.register_channel(extra_id)`` are now automatically
  resolvable through ``bot.games.get(extra_id)`` — the view and
  ``Game.for_channel`` share the same dict.
- ``GameClock._clocks`` registry consolidation is a sibling
  opportunity flagged in the systems review; intentionally
  out of scope for this change.

### 2026-04-17 — Combat Resolution Deduped (`apply_sequence_to_target`)

The per-hit "route → coalesce → fire hooks" loop was re-implemented
in three places with silent drift risk: ``Game.do_combat`` (player →
monster), ``MonsterPlugin.attack_random`` (monster → player), and
``Hydra.attack_random`` (multi-victim). Extracted into one pure
function in ``caldanai/lib/rpg/combat/resolution.py``.

**New:** ``apply_sequence_to_target(sequence, target, *, attacker=None)
-> ResolutionResult``. Returns ``body_damage_total`` (pre-floor),
``injury_feedback_lines``, ``death_msg``, ``num_hits``. Hook firing
invariants it enforces:

- ``on_injury_change`` fires at most once per part per sequence, on
  the final transition (multiple hits on one part coalesce).
- ``on_destroyed`` fires at most once per part that first crossed
  to USELESS during this sequence.
- ``on_target_part_destroyed`` fires on ``attacker`` — and ONLY when
  ``attacker`` is passed. Previously an implicit asymmetry (monster
  hit fired it, player hit didn't); now explicit.

**Callers still own the body-HP floor** (``max(num_hits, total -
defense)``) and the final ``target.apply_damage(final)`` vs
``target.health -= final`` choice, because that decision affects
downstream death-message plumbing and ``critical_kill`` detection.

**Migrations:**
- ``Game.do_combat``: player path — no ``attacker=`` passed.
- ``MonsterPlugin.attack_random``: monster path — ``attacker=self``.
- ``Hydra.attack_random``: per-victim bucketing with the helper
  called once per victim with ``attacker=self``. The hydra's old
  inline loop didn't fire ``on_target_part_destroyed`` — that was
  path-of-least-resistance during extraction, not design. Wiring
  it up matches the base ``MonsterPlugin.attack_random`` contract;
  observable output is unchanged today because
  ``MonsterPlugin.on_target_part_destroyed`` defaults to ``""``
  and hydra doesn't override it. Enables per-head-kill flavor in
  the future without touching the combat loop.
- ``Dragon.attack_random``: inherits the migrated base via
  ``super().attack_random()``. Its breath path doesn't use the
  per-part routing loop, so nothing to migrate there.

22 new tests in ``tests/test_combat_resolution.py`` pin the hook
invariants, the attacker-asymmetry, and the pre-floor aggregate
semantics.

### 2026-04-17 — `CombatState` Extracted from `Game`

First slice of shrinking ``Game`` toward a thinner core. The six
combat-scoped fields (``monster``, ``monsters``, ``combatants``,
``combat_targets``, ``looters``, ``loot``) and the
``end_combat`` routine moved into a dedicated
``caldanai/lib/rpg/combat_state.py::CombatState``.

**Design:**
- ``Game.combat`` is a single ``CombatState`` instance; each
  combat-scoped attribute on ``Game`` is now a ``@property``
  that proxies to ``self.combat``, with matching setters so
  existing whole-field assignments (tests, some cog paths) keep
  working.
- List/dict item-mutations (``game.combatants.append``,
  ``game.loot[key] = …``, etc.) work transparently through the
  getter's returned reference — no call-site changes.
- ``CombatState.end_combat`` owns the clearing order
  (``clear_combat_roles(looters)`` runs before the looters list
  is emptied — lock-in test guards this).
- ``Game.end_combat`` shrinks to a 3-line delegator.

**Serialization**: unchanged. These six fields were never in
``Game.to_dict`` — they're transient runtime state — and the
serialization code was not touched. ``TestGameSerialization::test_to_dict_keys``
continues to pin down the shape.

**Scope**: first of three planned ``Game`` slices. Still to do:
slice 2 moves ``do_health_regen`` to ``PlayerManager``; slice 3
consolidates the dual channel registry.

### 2026-04-17 — `fig_to_file` / `style_axes_dark` Plotting Helpers

The matplotlib → ``BytesIO`` → ``discord.File`` plumbing appeared
three times (``$chart``, ``$usage``, ``Player.get_chart_attacks``)
with subtle styling drift between them. Extracted into
``caldanai/lib/rpg/helpers/plotting.py``.

- ``fig_to_file(fig, filename="plot.png") -> discord.File``:
  the save/seek/wrap plumbing. Always closes the figure with
  ``plt.close(fig)`` after export.
- ``style_axes_dark(ax, accent_color=..., grid_axis="y")``:
  consistent Discord dark-mode styling (transparent figure +
  axis background, accent-colored ticks/labels, gridline axis).
  Per-chart accent preserved via param (``CYAN_ACCENT`` for
  ``$chart`` / ``get_chart_attacks``; ``DEFAULT_ACCENT`` for
  ``$usage``).

**Drift resolved**: ``$usage`` was the only call site explicitly
setting ``fig.patch.set_alpha(0)`` + transparent axis facecolor
(it was the newest caller with clear dark-mode intent); the
helper now always applies those. ``bbox_inches="tight"`` was
present in two sites and missing in ``get_chart_attacks`` —
helper standardizes on tight.

### 2026-04-17 — `_display_part_name` Collapsed Into `BodyPart`

The cog-side `RpgUserCommands._display_part_name` reimplemented
the codified → readable mapping already present on
``BodyPart.display_name`` / ``_display_with_article``. Deleted
the duplicate.

- ``_display_targets`` now resolves each codified name via
  ``monster.find_parts`` and delegates to
  ``BodyPart._display_with_article()``.
- Byte-identical output across all three branches: bare name
  (``"torso" → "the torso"``), numeric qualifier
  (``"head.2" → "head 2"``), directional qualifier
  (``"arm.left" → "the left arm"``).
- Safety fallback preserved: if a codified name fails to resolve
  to a part (e.g. destroyed between parse and display), the old
  string-only logic handles it inline.

### 2026-04-17 — `resolve_reply_channel` Helper

The idiom ``channel = game.channel if ctx.guild is not None else ctx``
appeared 11 times across inventory and info cogs. Replaced with a
single ``RpgUtilities.resolve_reply_channel(ctx, game)`` helper in
``caldanai/lib/rpg/helpers/utils.py``.

- 11 call sites migrated across ``rpg_inventory_commands.py`` (7)
  and ``rpg_info_commands.py`` (4).
- Helper uses ``getattr(ctx, "guild", None)`` so it gracefully
  handles ``Member`` / ``User`` shapes that lack ``.guild`` —
  strictly additive tolerance; no existing call site relied on
  the old ``AttributeError``.
- Exceptions intentionally preserved: ``$inventory`` always DMs
  ``player.member``, ``$games`` always DMs the author,
  ``$pronouns`` is ``@guild_only()`` — none went through the
  ternary.

### 2026-04-17 — Batched Member Load on Bot Startup

`PlayerManager.load_players` previously fetched each player's
Discord ``Member`` individually via ``guild.get_member`` then
``guild.fetch_member`` on cache miss — one REST round-trip per
player on a cold cache.

**Change:** skip the per-player REST fetch when the guild's
member cache is already populated (which it is, by default, when
the members intent is enabled — ``Intents.all()`` is set in the
bot configuration, minus presences). When the cache isn't
populated, one ``await guild.chunk()`` call warms it via a single
WebSocket member-chunk request instead of N REST fetches.

**Guardrails:**

- ``if not guild.chunked:`` gates the ``chunk()`` call.
  ``discord.py`` 2.x auto-chunks guilds at startup with the
  members intent enabled, so ``guild.chunked`` is typically True
  by the time ``on_ready`` fires — skipping the redundant call
  avoids a potential deadlock where issuing a second chunk
  request while the auto-chunk is still in-flight hangs the
  coroutine (observed during playtest).
- ``asyncio.wait_for(..., timeout=10)`` wraps the call so a
  stuck chunk drops through to the per-player ``fetch_member``
  fallback instead of hanging bot startup.
- Per-player fallback (``get_member`` → ``fetch_member`` →
  ``NotFound(10007)`` → ``remove_player`` for ex-members) is
  preserved in full — a chunk skip / failure / timeout never
  blocks a real member from loading.

For a guild of 30 registered players on a cold cache without
auto-chunk, startup goes from ~30 rate-limited REST fetches to
one chunk call. For a guild whose auto-chunk already ran (the
common case), startup is effectively zero network calls.

### 2026-04-17 — Body-Part Docstring Hygiene

Base body-part plugins (``caldanai/lib/rpg/creatures/body_parts/``)
were narrating monster-specific design rationale — doppelganger
pain cries, dragon-toes flying-flag cascade, scorpion/manticore
tail specials — in their class and module docstrings. The actual
code implementing those concerns lives on the relevant monster
classes, not on the base parts.

**Change:** monster-specific rationale moved to the consuming
monster class under a ``**Body part design note:**`` heading.
Base-part docstrings now describe only the generic part (HP,
exposure, debuffs, hooks used).

- Doppelganger pain cries consolidated onto ``Doppelganger``.
- Dragon flying-flag + toes DODGE cascade consolidated onto
  ``Dragon``.
- Non-loadbearing monster examples (scorpion/manticore tails,
  giant toes) genericized in place — the design note stays; the
  specific-monster reference goes.

Enforces the long-standing project rule that base parts do not
own monster-specific flavor.

### 2026-04-17 — `Player.is_injured()` / `heal_fully()` Consolidation

Consolidated five inline copies of the "is this player hurt?" and
"restore this player fully" idioms into two methods on ``Player``.

**New methods** (``caldanai/lib/rpg/creatures/player.py``):
- ``is_injured() -> bool`` — True if body HP is below max or any
  body part HP is below max.
- ``heal_fully() -> None`` — restores body HP and every part HP to
  max, resets regen bookkeeping, sets ``is_dirty``.

**Call sites deduped:**
- ``_is_injured(player)`` helper in ``rpg_info_commands.py`` (was
  using ``InjuryLevels.NONE`` — semantically identical to the
  ``health < health_max`` check and now collapsed to it).
- ``pray`` d20==1 (divine rain), d20>16 (single-heal predicate),
  and d20==20 (party-wide full heal) branches in
  ``rpg_user_commands.py``.
- ``unsmite`` resurrection path in ``rpg_admin_commands.py``.

**Behavior preserved:** pray's divine-rain branch still calls
``apply_damage(-max)`` first to emit the resurrection narration
when a dead player is healed, then ``heal_fully()`` to finish the
restore. ``unsmite`` was already discarding that message, so the
simplification is a straight swap.

### 2026-04-17 — `monster_statics` → `collections.Counter`

Replaced three manual counter-bump idioms
(``if k not in d: d[k] = 1 else: d[k] += 1``) in ``Game`` with a
single ``Counter`` instance.

**Changes:**
- ``Game.monster_statics`` is now a ``collections.Counter``.
  All three bump sites are now ``self.monster_statics[key] += 1``.
- ``update_statics`` in ``helpers/utils.py`` resets the counter
  to ``Counter()`` after draining to the DB statistics collection
  (preserves the type so subsequent bumps don't ``KeyError`` on
  missing keys).

**Serialization:** ``monster_statics`` is not part of
``Game.to_dict``/``from_dict`` — drains go directly to the DB
statics collection. Round-trip is unaffected; locked in with a
new regression test.

### 2026-04-16 — `$usage` Command Usage Charts

New ``$usage`` command renders horizontal bar charts of command
frequency from the ``user_command_statics`` collection.

**Scopes:**
- ``$usage`` — personal usage in this game.
- ``$usage game`` — all players in this game.
- ``$usage guild`` — server-wide across all games.
- ``$usage bot`` — bot-wide (admin only).
- ``$usage command <name>`` — alias breakdown for a single command
  (e.g. how often ``kill`` vs ``slay`` vs ``murder`` is typed).
- Optional numeric limit: ``$usage 10`` (top 10), ``$usage -5``
  (bottom 5). No number shows all.

**Channel-scoped statics:**
- ``on_command`` now records ``channel_id`` alongside ``guild_id``
  so per-game queries work going forward.
- ``update_statistic`` accepts optional ``channel_id`` for
  game-scoped aggregate counters (monster kills, command totals).
- ``update_statics`` passes ``channel_id`` from the game for both
  command totals and monster statics.

### 2026-04-16 — `$equip <name>.best` QoL Qualifier

New dotted qualifier for the equip command: ``$equip rock.best`` (or
``$equip rock.best left``) picks the highest-quality matching item
from inventory and equips it. Includes a no-demote rule — if an
equipped item of the same type already has equal-or-better quality,
it short-circuits with "already wielding the finest".

**``_resolve_best``**
(``caldanai/lib/cogs/rpg_inventory_commands.py``):
- Filters inventory via the existing ``filter(base)`` for Equipment
  matches, sorts by ``quality.value["multiplier"]`` descending, and
  compares the winner against any equipped same-plugin item.
- Empty base name (``$equip .best``) falls through to the normal
  path rather than matching every item in inventory.

Also removes the stale ``TODO`` from ``do_combat`` line 442 — the
combat-role reliability concern it flagged was resolved by the
``end_combat`` consolidation in the same session.

### 2026-04-16 — Combat Cleanup: Single Source of Truth

Combat teardown was scattered across ``on_monster_death``,
``cancel_combat``, ``kill_monster``, and inline code in
``do_combat``, each doing a different subset of cleanup. A player
whose combat role wasn't removed by one path might not be caught by
another. This consolidates all cleanup into ``Game.end_combat()``.

**``Game.end_combat()``** (``caldanai/lib/rpg/__init__.py``):
- New method — single source of truth for combat teardown. Clears
  monster, combatants, targets, removes the ``do_combat`` routine,
  and clears combat roles from participants (via ``self.looters`` —
  the authoritative list of players who received the role) before
  clearing looters.
- Does NOT touch ``self.loot`` — callers manage the loot lifecycle
  (generate, timer, or clear) before calling ``end_combat``.
- Does NOT start the spawn timer — callers follow up with
  ``set_spawn_timer`` when appropriate.

**Callers rewritten:**
- ``on_monster_death``: generates loot from ``self.looters``, then
  calls ``end_combat``, then schedules loot timer + spawn timer.
- ``cancel_combat``: clears loot, calls ``end_combat``, spawn
  timer.
- ``kill_monster``: admin kill no longer generates loot (was
  incorrectly piggybacking on ``on_monster_death``). Clears loot,
  calls ``end_combat``, spawn timer, shows death message only.
- ``do_combat`` error path (monster is None): calls ``end_combat``
  + spawn timer.
- ``set_spawn_timer``: no longer calls ``clear_combat_roles`` —
  that responsibility moved to ``end_combat``.

**``PlayerManager.clear_combat_roles``** / **``clear_player_combatant``**
(``caldanai/lib/rpg/player_manager/__init__.py``):
- ``clear_combat_roles`` now takes an explicit ``participants`` list
  instead of iterating every player in the game — targets only the
  players who actually received the role.
- ``clear_player_combatant`` dropped the ``in player.member.roles``
  guard. Role removal fires unconditionally — the cached role list
  drifts from server-side state after reconnects, so trusting it
  silently skipped removals. Discord is idempotent about removing a
  role the member doesn't have.

**``PlayerManager.remove_player``** — now includes ``COMBAT_MAIN``
in the roles stripped on ``$leave``, closing the theoretical leak
where a player leaving mid-combat kept the combat role.

**Tests** (``tests/test_game.py``, ``tests/test_player_manager.py``):
- ``TestEndCombat``: clears all combat state, doesn't touch loot,
  idempotent when no combat active.
- ``TestCancelCombat``: updated to verify loot + roles cleared.
- ``TestKillMonster``: no loot generated, spawn timer fires, roles
  cleaned.
- ``test_clear_combatant_fires_unconditionally``: replaces the old
  ``skips_if_no_role`` test — removal fires regardless of cache.

### 2026-04-16 — Item Favoriting

Players can now flag items to protect them from bulk-sell (and other
future destructive operations). Groundwork for the planned
``$sell duplicates`` command.

**Item model** (``caldanai/lib/rpg/inventory/item.py``):
- New ``Item.favorited: bool`` attribute, default ``False``.
- ``to_dict`` only writes ``"favorited": True`` when the flag is set
  — legacy item docs stay bit-for-bit identical until a player
  actually favorites something, so no migration is needed.

**Inventory** (``caldanai/lib/rpg/inventory/__init__.py``):
- ``load_item`` restores ``favorited`` from the data dict after the
  subclass ``from_plugin`` runs, so Stackable / Weapon / Armor /
  Usable / Consumable all inherit the round-trip for free.
- New ``Inventory.favorites()`` helper returning the tuple of
  favorited items — will be consumed by the upcoming
  ``$sell duplicates`` work.

**Commands** (``caldanai/lib/cogs/rpg_inventory_commands.py``):
- ``$favorite <item>`` (aliases ``fav``, ``lock``) — sets the flag on
  every match of the usual fuzzy item filter.
- ``$unfavorite <item>`` (aliases ``unfav``, ``unlock``) — clears it.
- ``$sell`` now strips favorited items from the sell list before
  dispatching ``player.sell``, emitting a
  ``Protected by favorite (★): ...`` notice so the player knows what
  was saved.

**Display** (``caldanai/lib/rpg/creatures/player.py``):
- ``get_inventory`` appends a ★ marker to each favorited row,
  alongside the existing ``[slot]`` suffix.

**Tests** (``tests/test_inventory.py``, ``TestFavorites`` class):
- Default ``False``, ``to_dict`` omits when false / writes when
  true, ``favorites()`` filters correctly, ``load_item`` restores
  the flag from data and leaves it ``False`` when absent.

### 2026-04-16 — Fuzzy Body-Part Targeting + Round-Robin Multi-Source

Body-part targeting now accepts abbreviations the same way inventory
lookup does, so ``$kill leg.r`` lands on ``leg.right`` and
``$target h.1`` lands on ``head.1``. The resolver also fans out
ambiguous tokens to every match (``$target leg`` → both legs), and
``do_attack`` cycles round-robin through multiple targets rather than
clamping extras to the last name.

**``Creature.find_parts(name)``**
(``caldanai/lib/rpg/creatures/__init__.py``):
- New method. Case-insensitive exact match wins; otherwise splits the
  query on ``.`` and each segment must be a prefix of the
  corresponding segment of the part name. Destroyed parts are
  filtered out.
- Segment-prefix (not raw substring) was picked after a review pass:
  substring let ``h`` falsely match ``arm.right`` because "right"
  contains an ``h``. Segment-prefix only matches ``h`` → head,
  hand.\*.
- Guards empty and degenerate queries (``""``, ``"   "``, ``".r"``,
  ``"leg."``, ``"leg..right"``) so they return ``[]`` instead of
  wildcard-matching.

**``_parse_part_targets``**
(``caldanai/lib/cogs/rpg_user_commands.py``):
- Rewritten on top of ``find_parts``. Every match expands to its
  canonical part name, deduped via ``seen``. Fixes the display bug
  where an ambiguous ``$target h`` rendered as "Caels shifts focus to
  the h!".

**``Creature.do_attack`` extras semantics**
(``caldanai/lib/rpg/creatures/__init__.py``):
- Changed from ``idx = min(i, len - 1)`` to ``idx = i % len``. Extra
  sources now cycle through the explicit-target list instead of
  pinning to the last name. A 5-head hydra given ``[leg.left,
  leg.right]`` now hits ``[left, right, left, right, left]`` rather
  than piling four heads onto ``leg.right``.
- ``_resolve_name`` closure simplified to delegate to ``find_parts``.

**Tests** (6 new + 1 existing file extended):
- ``tests/test_targeting_helpers.py`` — ``TestFindParts``: exact
  match, sided-prefix, abbreviation resolution, case-insensitive,
  destroyed-part exclusion, exact-match precedence over fuzzy, reject
  later-segment substring matches, over-length query, empty query,
  degenerate dotted query.
- ``tests/test_part_target_parsing.py`` (new) — 
  ``TestParsePartTargets``: canonical dotted names, fuzzy
  abbreviation, ambiguous expansion, ``h``-style multi-match,
  multi-token, unknown tokens dropped, duplicate dedup, empty input,
  partless monster, destroyed part skipped, bare-plus-dotted exact
  precedence, whitespace-only input.
- ``tests/test_combat_targeting_wiring.py`` —
  ``TestDoAttackFuzzyExplicitTargeting``: end-to-end chain
  (``leg.r`` → ``leg.right``) plus a 5-source hydra regression test
  verifying round-robin cycling.

### 2026-04-16 — Weather-Dependent Monster Spawns

First mechanical hook into the weather daemon: monsters can now
declare which weather conditions they spawn in, and
``get_random_monster`` filters the candidate pool by the game's
active weather alongside the existing time-of-day filter.

**``WeatherPatterns`` flag shift:**
- ``CLEAR`` moved from the sentinel value ``0`` to ``1`` — a real
  flag bit so it can participate in ``weather_partition`` bitwise
  masks. A sun-lover monster can now declare "only spawns in clear
  weather" as a proper flag.
- New ``WeatherPatterns.ALL`` = ``CLEAR | CLOUDY | FOG |
  PRECIPITATION | WIND`` as the permissive default.
- ``WeatherDaemon.active_patterns`` adjusted so it only OR's the
  currently-active components — no stray ``CLEAR`` bit when other
  patterns are active.

**``MonsterPlugin.weather_partition``:**
- New attribute, default ``WeatherPatterns.ALL`` (spawns in any
  weather). Per-monster override as a flag mask.
- ``get_random_monster(clock, weather=...)`` filters candidates by
  bitwise overlap with the active weather pattern. Weather arg is
  optional; omission defaults to ``ALL`` for backward compatibility.
- ``Game.get_monster`` passes ``game.weather.active_patterns``
  through automatically.

**Tagged monsters (thematic first pass):**
- **Spirit**: ``CLEAR | CLOUDY | FOG``. Dispersed by wind (matches
  the daemon's fog-dispersal invariant); rain drives them back.
- **Pixie**: ``CLEAR | CLOUDY | FOG``. Stained-glass wings tucked
  away in rough weather.
- Every other monster (skeleton, cyclops, werewolf, dragon,
  goblin, etc.) keeps the default ``ALL`` — any weather.

**Tests** (``tests/test_weather_spawn_filter.py``, 9 new):
- Default partition matches every pattern including CLEAR.
- Spirit and pixie weather profiles (regression guards).
- ``get_random_monster`` filter semantics: weather narrows
  candidates, no weather arg = permissive, time+weather compose,
  empty candidate pool returns None.
- ``WeatherPatterns.ALL`` covers every single bit.

### 2026-04-15 — Weather Daemon (First Subsystem on the Clock Registry)

First real use of the clock-registry architecture from earlier today.
Weather is now a live per-channel state machine rather than a stubbed
``Game.weather = None``, with narrative announcements, persistence,
admin tooling, and an almanac forecast.

**``WeatherDaemon``** (``caldanai/lib/rpg/ambience/weather.py``):
- Holds state as ``Dict[WeatherPatterns, WeatherSeverities]`` —
  each component (PRECIPITATION, WIND, FOG, CLOUDY) carries its own
  severity. Heavy rain in light wind is modeled distinctly from
  heavy wind driving a drizzle — useful for narration today and
  for per-component combat modifiers later.
- ``WeatherSeverities`` converted from ``IntFlag`` to plain ``Enum``
  (a single component has one severity level; combining LIGHT |
  HEAVY was never meaningful).
- Transitions roll new states on a randomized duration (60–480
  game-minutes), weighted by season: BRIGHTBLOOM mild, SOLSTIME
  occasional storms, LEAFGLOW windy/foggy, FROSTFALL heavy and
  windy. Physical invariants enforced (heavy wind disperses fog;
  precipitation absorbs standalone cloud).
- Daemon owns no Game reference — lives purely on ``channel_id``
  via the time-façade helpers + ``Game.for_channel`` for dispatch.
- ``schedule_routine`` / ``cancel_routine`` called on ``start`` /
  ``stop`` so the tick stops cleanly with ``remove_game``.
- Weather change announced as narrative text, not raw state
  ("Heavy rain drums steadily against the ground." not "state =
  PRECIPITATION:HEAVY").

**``Game`` integration:**
- Weather daemon constructed in ``Game.__init__`` (given a channel)
  and in ``Game.from_dict`` (given a loaded game).
- State persisted in ``Game.to_dict`` / restored in ``from_dict``
  so weather survives bot restarts with its current duration.
- ``remove_game`` stops the daemon before dropping the game from
  memory (no routines firing against a defunct channel).
- Startup "Caldanai Bot has just started!" now appends the current
  weather description so players don't have to ``$weather`` to
  orient themselves.

**Player-facing commands** (group: ``$weather``):
- Bare ``$weather`` — current weather description (anyone).
- ``$weather status`` — raw state + durations with real-time
  conversion (admin).
- ``$weather force <pattern> [severity]`` — override a component
  on top of current state (admin).
- ``$weather clear`` — wipe all components to clear skies (admin).
- ``$weather roll`` — skip the transition timer and re-roll based
  on current season (admin).
- Each admin subcommand individually guarded with
  ``is_owner`` / ``manage_guild`` checks — bare call stays open.

**Almanac forecast** (``$almanac``):
- New ``WeatherDaemon.forecast(season)`` method narrates likely
  weather based on seasonal weights, with a ~20% chance of a mild
  mispredict (swapping one forecast line with a slightly-wrong
  sibling). In-world almanacs should lie sometimes.

**Tests** (``tests/test_weather_daemon.py``, 21 new):
- Initial-state, ``describe()`` across patterns, per-component
  severity independence, wind-interacts-with-precipitation flavor
  distinctions, persistence round-trip, tick decrement + transition
  trigger, transition invariants (fog dispersal, cloud absorption),
  lifecycle hooks (start / stop scheduling).

**Exploration points deferred** (design + hooks ready, not built):
- Weather-dependent monster spawns via a new
  ``MonsterPlugin.weather_partition`` filter.
- Combat modifiers (RANGED penalty in wind, FIRE reduction in rain,
  HIT penalty in fog) reading ``weather.severity_of(component)``.
- Player body temperature accumulation in FROSTFALL + WIND, tying
  into the deferred status-effects system.
- Ambience plugin system (scaffolded design in memory) replacing
  the hardcoded ``do_ambience`` once we're ready to modularize.

### 2026-04-15 — One Game Per Channel: Runtime Rekey and Game-Scoped Players

Shifts the entire runtime from one-game-per-guild to one-game-per-
channel. Multiple games can now coexist in the same guild (on
different channels) without clobbering each other in memory or the
DB.

**``bot.games`` rekeyed from ``guild.id`` to ``channel.id``:**
- All 13 admin-command lookups in ``rpg_admin_commands.py`` now
  resolve via ``ctx.channel.id`` instead of ``ctx.guild.id``.
- ``check_game_exists`` checks channel-level, not guild-level.
- ``get_game(ctx)`` resolves via ``ctx.channel.id``.
- ``add_game`` registers under ``game.channel.id``.
- ``remove_game(guild_id, channel_id)`` takes both ids.
- ``$game create`` guard relaxed from "one per server" to "one per
  channel" using ``DB.get_game(guild_id, channel_id)`` instead of
  ``find_any_game_in_guild``.

**Game-scoped players:**
- ``Player`` gains ``channel_id`` attribute; ``to_dict`` persists it,
  ``from_dict`` reads it (``None`` for legacy docs). Players are now
  identified by (guild_id, channel_id, user_id) in the DB.
- ``DB.get_player``, ``update_player``, ``delete_player`` all take
  compound (guild_id, channel_id, user_id) filters.
- ``DB.delete_game`` now uses compound filter for player cleanup too
  — removing a game only deletes its own players, not every player
  in the guild.
- ``PlayerManager.load_players(guild, channel_id)`` stamps
  ``channel_id`` onto each loaded player at runtime, providing
  one-time adoption for legacy docs that pre-date game-scoping.
  Next ``save_game_data`` cycle writes ``channel_id`` to the doc.
- ``PlayerManager.add_player`` passes ``ctx.channel.id`` on new
  player creation. ``remove_player`` passes ``channel_id`` through
  to ``DB.delete_player``.
- ``get_games_for_user`` (DM command path) falls back gracefully
  for legacy player docs missing ``channel_id``.

**Backward compatibility:**
- ``find_players_by_guild_id`` remains for the load path — old docs
  without ``channel_id`` won't match a compound query. The guild-
  scoped load + runtime ``channel_id`` stamp = lazy migration.
- ``delete_all_players(guild_id)`` remains guild-wide for server-
  level cleanup (``delete_server``).

### 2026-04-15 — DB Layer: Per-Game Compound Filter (Step 2 of GameClock Refactor)

Follow-on to the clock registry work — shifts every per-game DB
operation from ``{guild_id}`` to ``{guild_id, channel_id}`` compound
filters. Schema was already compatible (``insert_game`` has written
``channel_id`` for a long time); this is strictly a code refactor
plus a sanity script.

**DB method changes (``caldanai/db/__init__.py``):**
- ``get_game_by_guild_id(guild_id)`` → ``get_game(guild_id, channel_id)``.
  Filter: ``{"guild_id": gid, "channel_id": cid}``.
- ``delete_game(guild_id)`` → ``delete_game(guild_id, channel_id)``.
  Game doc is dropped by compound key; player deletion stays guild-
  wide (flagged in the docstring as too aggressive for a real
  multi-game-per-guild world, but preserved since ``bot.games`` is
  still guild-keyed in memory).
- ``update_game(guild_id, dict, upsert)`` →
  ``update_game(guild_id, channel_id, dict, upsert)``.
- New ``find_any_game_in_guild(guild_id)`` — used by the
  ``$game create`` admin check to preserve the "one game per server"
  constraint without letting an in-memory collision silently clobber
  an existing game. Distinct method, distinct semantics.
- ``insert_game``, ``find_all_games``, ``delete_server`` unchanged.

**Call site updates:**
- ``Game.save()`` passes ``self.guild.id, self.channel.id``.
- ``Game.load(guild_id, bot)`` →
  ``Game.load(guild_id, channel_id, bot)``.
- ``$game create`` admin check uses ``find_any_game_in_guild`` so
  the "single game per server" message remains accurate.
- ``RpgUtilities.remove_game`` passes the game's channel id to the
  DB delete. No-ops cleanly when the in-memory game has no channel
  bound.
- ``save_game_data`` loop passes ``g.channel.id`` per iteration.
- ``Bot.on_guild_remove`` simplified: ``delete_server`` already
  DeleteMany's every game and player for the guild, so the
  redundant ``delete_game`` / ``delete_all_players`` calls are
  gone. Drop-through comment notes the previous redundancy.

**Sanity script** —
``scripts/migrations/2026_04_15_game_docs_sanity.js``:
- Reports any game doc missing ``channel_id`` (would be invisible
  to the new queries).
- Strips any stray legacy ``channelId`` (camelCase) field from
  game docs — user flagged having possibly seen these lurking.

**Tests updated:**
- ``tests/test_db.py`` — delete_game / update_game signatures;
  assertions extended to check the compound filter.
- ``tests/test_utils.py`` — ``save_game_data`` expectation now
  passes ``(guild_id, channel_id, dict)``.
- ``tests/conftest.py`` — shared DB mock now stubs ``get_game``
  and ``find_any_game_in_guild`` (was ``get_game_by_guild_id``).

**Remaining deferred work:**
- Players are still guild-scoped (``player.guild_id`` only), so
  a true multi-game-per-guild would have players shared across all
  games in the guild. Flagged in ``delete_game``'s docstring.
- ``bot.games`` is still keyed by ``guild.id``, enforcing one-game-
  per-guild at the runtime level. Relaxing this needs a separate
  look since add_game would need to route into a per-channel map.

### 2026-04-15 — Per-Guild Prefix Cache

Eliminates a per-message DB round-trip that fired on every chat line
the bot observed, not just commands. ``get_prefix`` (discord.py's
prefix resolver) was doing ``DB.get_server_by_guild_id`` for every
guild message to look up a prefix that almost never changes.

**Cache** in ``caldanai/lib/bot/__init__.py``:
- Module-level ``_prefix_cache: Dict[int, str]`` keyed by guild id.
- ``get_prefix`` now hits the DB only on cache miss; first lookup
  populates, subsequent lookups are O(1) dict access.
- DB exception → fall back to default ``"$"``, still caches so we
  don't hammer a broken DB. Regained throughput at the cost of one
  stale entry per guild in a hypothetical DB outage; ``$prefix``
  or a process bounce clears the stale state.

**Invalidation covered at three points**:
- ``$prefix`` admin command (``bot_admin_commands.py``) calls
  ``cache_prefix(guild_id, new_prefix)`` after the DB write.
- ``on_guild_remove`` handler calls ``evict_prefix(guild_id)`` when
  the bot leaves a guild.
- ``get_prefix`` itself lazy-populates on cache miss.

**Tests** (``tests/test_prefix_cache.py``, 13 new):
- Cache population / reuse / per-guild independence.
- DM bypass (``message.guild is None``).
- Explicit ops: ``cache_prefix``, ``evict_prefix``,
  ``clear_prefix_cache``.
- First-seen-guild path (DB miss → insert + cache default).
- DB failure fallback (caches default, doesn't crash).

Net effect: one DB query per guild per bot-lifetime instead of one
per message. On any active server this is the single biggest load
reduction since we added persistent players.

### 2026-04-15 — Clock Registry and Channel Routing (Step 1 of GameClock Refactor)

**Per-game clock registry on ``GameClock``:**
- Class-level ``_clocks: Dict[int, GameClock]`` keyed by ``game_id``
  (the primary Discord channel id).
- ``GameClock.for_game(game_id)`` returns the registered clock or
  ``None``. Module-level façade (below) is the preferred access path.
- Registration lifecycle in ``Game.__init__`` /
  ``RpgUtilities.remove_game`` — no clock leaks on teardown.
- One-way ownership preserved: clocks have no back-reference to their
  Game, avoiding circular-dependency hazards.

**Module-level façade in ``caldanai.lib.rpg.time``:**
- Read surface hands out concrete values, not the clock object:
  ``get_time_of_day(game_id)``, ``get_time_components(game_id)``,
  ``get_next_time(game_id)``, ``get_seconds(game_id)``. All return
  ``None`` when no clock is registered for ``game_id`` so callers
  don't have to defensively guard.
- Scheduling surface separate and explicit:
  ``schedule_routine(game_id, fn, seconds, run_once, only_instance)``
  and ``cancel_routine(game_id, fn)``. Grep for these call sites to
  find every subsystem touching tick scheduling.
- Subsystems no longer need a ``Game`` reference or a ``GameClock``
  handle to read time; a single ``game_id`` (opaque int) is enough.
  Weather daemons, monsters, ambience, and future dungeon ticks all
  use the same narrow surface.

**Channel routing on ``Game``:**
- Class-level ``_channel_routes: Dict[int, Game]`` maps Discord
  channel ids to their owning Game. Primary channel auto-registered
  at construction. Dungeon threads / side channels extend via
  ``register_channel(channel_id)`` / ``unregister_channel(channel_id)``
  when they open / close.
- ``Game.for_channel(channel_id)`` resolves an arbitrary channel to
  its owning game. Does not do thread parent-fallback automatically —
  callers register explicit routes, keeping the routing state
  predictable.
- ``Game.channel_id`` is a property deriving from ``self.channel.id``
  (no stored field — can't drift out of sync with ``self.channel``).
  ``None`` in pre-spawn / unit-test contexts where no channel is
  bound. Separate from ``Game.id`` which remains the Mongo ObjectId
  for DB identity.

**``_channel_id`` on Creature base:**
- ``Creature._channel_id: Optional[int]`` is the structural routing
  key every creature has — populated by ``Game.get_monster`` at
  spawn (right before ``on_spawn``). Creatures that need time-of-
  day or other game-scoped state use
  ``get_time_components(self._channel_id)`` etc. without any per-
  class plumbing.
- Populating at the caller (Game.get_monster) rather than in
  subclass ``on_spawn`` overrides means concrete monster plugins
  don't have to remember ``super().on_spawn(game)`` — they stay
  focused on flavor / narrative.

**Werewolf migrated to the façade:**
- ``self._clock = game.game_clock`` stash gone. ``on_spawn`` override
  removed entirely — inherits the base no-op now that ``_channel_id``
  is populated centrally.
- ``_is_near_dawn`` reads time via ``get_time_components(self._channel_id)``
  and ``get_next_time(self._channel_id)``. Narrow access — no scheduling,
  no clock object, can't accidentally mutate game state.
- Proves the façade end-to-end.

**What's not yet done (deferred to a second commit):**
- DB layer still filters by ``guild_id`` alone. Compound
  ``{guild_id, channel_id}`` filter to support multiple games per
  guild is the follow-up.
- Existing ``Game`` methods (``check_time``, ``do_health_regen``, etc.)
  still drive the clock directly. Opportunistic migration only when
  we touch them for feature reasons; no churn-for-churn.
- Thread parent-fallback in ``for_channel`` for auto-routing Discord
  threads to their parent channel's game. Not needed until dungeons.

**Tests** (19 new):
- ``TestClockRegistry`` — register / unregister / for_game / isolation
  between games.
- ``TestModuleLevelReadSurface`` — each façade function returns value
  for registered clocks, ``None`` for unknown ``game_id``.
- ``TestModuleLevelSchedulingSurface`` — schedule / cancel via façade
  correctly mutate the underlying clock; fail gracefully on unknown
  ``game_id``.
- ``TestChannelRouting`` on Game — auto-registration of primary
  channel, register / unregister of additional channels, ``for_channel``
  returns None for unknown.
- Werewolf dawn-desperation tests refactored to stub the façade
  functions via ``monkeypatch`` instead of wiring a mock clock.

### 2026-04-15 — Werewolf Dawn Mechanics and Attacker-Side Part-Destruction Hook

**Base hooks on ``MonsterPlugin``** (reusable by future monsters):
- ``on_target_part_destroyed(victim, part)`` — attacker-side hook
  called from ``attack_random`` on the USELESS transition. Monster-
  specific narration counterpart to ``BodyPart.on_destroyed``
  (which describes the injury from the victim's perspective). Both
  feed the same injury feedback block in ``attack_random``. Default
  no-op.
- ``flee_loot: Dict[str, float]`` + ``get_flee_loot()`` — mirrors
  ``loot`` / ``get_loot()`` for items potentially left behind on a
  time-based flee (e.g. a dawn-bolting werewolf dropping a shred of
  clothing). **Dead hook for now** — no engine caller yet; wiring
  into ``Game.check_time`` (or an equivalent escape path) is a
  follow-up when we generalize "monster leaves evidence" as a
  first-class concept.

**Werewolf — dawn-adjacent layered mechanics:**
- **Dawn desperation** — ``on_spawn`` stashes ``game.game_clock``;
  ``_is_near_dawn()`` returns true within ~1 in-game hour of the
  next ``MORNING`` transition. When desperate, ``get_attack_sources``
  appends a ``Desperate Lunge`` (2d8) alongside the normal bite —
  roughly doubles expected round damage. ``on_combat_round`` emits
  a one-time announcement the round desperation kicks in. The base
  engine's ``flees_from_time`` handling still manages the actual
  dawn-retreat; desperation is the narrative/mechanical lead-up.
- **Throat-bite narration** — ``on_target_part_destroyed`` fires
  a distinctive predator-kill beat when the destroyed part is the
  head. Reinforces the 30% throat-bite target preference that was
  already biasing head-selection.
- **Partial-human reveal on death** — fatal ``apply_damage`` appends
  a separate revelation sentence (three variants: "pelt thins in
  patches; a clavicle here, a human jawline there…", etc.). Death
  openers strengthened to pair cleanly with it. Two-beat reveal:
  the kill, then the recognition of what was killed.
- **Flee loot declaration** — ``flee_loot = {"leather": 0.5}``.
  Semantic declaration; rendering waits on engine wiring.

**Tests** — 11 new in ``test_new_monsters.py``:
- ``_is_near_dawn`` correctness (inside/outside window, wrong next-
  tod, missing clock handle).
- Desperate-lunge attack-source addition.
- Once-per-encounter desperation announcement.
- Throat-bite narration (head vs non-head).
- Flee loot declaration.
- Death revelation (fatal appends, non-fatal doesn't).

**Note**: ``self._clock = game.game_clock`` is an interim approach.
The in-progress clock-registry refactor (``GameClock.for_game(id)``
with module-level read/write functions) will migrate this to
``get_time_components(self._game_id)`` as its proving ground.

### 2026-04-15 — Parser Enrichment: Verb Agreement, Noun Possessive, and Order-Agnostic Casing

**Verb-agreement token** — ``@<n>v(singular|plural)``:
- Picks the singular or plural form based on ``actor.plural_verbs``.
  Used after a pronoun subject where English requires agreement with
  the pronoun's number (e.g. ``"they attack"`` vs ``"she attacks"``).
- ``Creature.plural_verbs`` property derives from the subjective
  pronoun via ``PLURAL_VERB_SUBJECTIVES`` (currently ``{"they"}``).
  Neopronouns (xe/ze/etc.) default to singular per convention; can
  be extended by adding entries to the frozenset.
- Name subjects ("Caels winces") still take singular verbs
  regardless of the player's pronoun — grammatical agreement follows
  the noun, not the person's identity. ``v(...)`` is only needed
  after a pronoun subject.
- Malformed tokens log WARNING: missing ``|``, extra ``|``, out-of-
  range actor reference. Unbalanced parens pass through literally
  (regex doesn't match), surfaced by the unknown-form-letter warning
  on the leftover ``v``.

**Noun-mode prefix** — ``n``:
- ``@1np`` renders the actor's name in possessive form. Modern AP
  style (``"Caels's"``, ``"the werewolf's"``) regardless of whether
  the name ends in 's'.
- ``n`` applies only to the immediately-following letter, then resets.
  Non-possessive combos (``ns``, ``no``, ``na``, ``nr``) collapse to
  bare name (no-op) since English names don't have distinct
  subjective/objective/etc. morphology.
- Composes with articles (``@1dnp`` → ``"the werewolf's"``) and
  casing (``@1cnp`` / ``@1npc`` → both capitalize the final output).
- Sweep: replaced literal ``@X's`` with ``@Xnp`` in player-facing
  narration (``rpg_user_commands.py``, ``player.py``,
  ``creatures/__init__.py``, ``body_part.py``). Monster files kept
  as-is — their ``@1d's``-style strings are uniformly singular and
  the conversion would be pure churn.

**Order-agnostic casing** (previously committed in the same parser
rewrite cycle):
- Content forms (articles, pronouns, noun-mode) apply in written
  order; casing forms (``c/l/t/u``) defer to the end regardless of
  position. ``@1cs`` and ``@1sc`` both produce the capitalized
  pronoun. Fixes a footgun where casing written before a pronoun
  would be silently clobbered by the pronoun substitution.

**Unknown-letter warnings**:
- Any form letter not recognized as article / pronoun / noun-mode /
  casing logs WARNING with the offending letter and surrounding
  token. Typos like ``@1x`` now surface during playtesting instead
  of producing silently-wrong narration.

**Form-letter constants and docstring**:
- Named constants at the top of ``parser.py`` (e.g.
  ``FORM_DEFINITE_ARTICLE``) replace implicit dict-key knowledge.
  Pronoun form letters derive from a new ``Pronouns.form`` property
  (first-char of the enum name by default), so adding a pronoun
  member auto-extends the parser grammar.
- Module docstring documents the full token grammar at a glance.

**Tests** (``tests/test_parser.py``, 49 total):
- Basic substitution (name, articles, pronouns, casing).
- Order-agnostic casing regression guards.
- Named-entity ``uses_article=False`` opt-out.
- Indefinite-article override (``"a unicorn"``).
- Unknown-form-letter warning + silent drop.
- Noun-possessive: all variants, composition with articles/casing,
  no-op for non-possessive noun-mode combos.
- Verb agreement: singular / plural / multi-actor independence /
  literal capitalization in verb content.
- Verb-agreement malformed inputs: missing pipe, extra pipes,
  unbalanced parens, out-of-range actor.
- ``Creature.plural_verbs`` derivation for they, she, he, and
  neopronouns.
- ``Pronouns.form`` first-char convention lock-in.

### 2026-04-14 — New Monsters, Classifications, Per-Hit Narration, and Damage-Type Aliases

**New monsters (7):**
- **Skeleton** (MEDIUM, undead) — bludgeoning ×2, light ×2, dark immune,
  piercing ×0.25. No eyes (HIT falls back to head). Per-damage-type
  narration tells the player what's working.
- **Cyclops** (HUGE) — single named ``eye`` part. Destroying it triggers
  **blind rage**: three wild swings of 3d10 each instead of one 2d10,
  with a one-time bellow narrative on the round the eye goes out. -5
  HIT penalty applies automatically via emergence.
- **Minotaur** (LARGE) — gore-bias 50% head via target-preference hook.
- **Pixie** (TINY) — magical-damage faerie sting, eye-poke fixation
  (~30%), wings + flying flag.
- **Werewolf** (LARGE) — quadruped lupine form, throat-bite bias (~30%),
  flees at dawn (``flees_from_time``).
- **Golem** (LARGE construct) — physical resistance (pierce ×0.25,
  slash ×0.5), magical vulnerability (×1.5), doesn't flee or die from
  time.
- **Spirit** (MEDIUM, undead, **no body parts** by design) — physical
  ×0.1, light ×2.5. Carries ``drain_ratio=0.5`` on its ethereal touch
  attack (heals from damage dealt). Cold counter-aura on melee
  attackers (``_on_attacked`` hook). Fade state at ≤25% HP disables
  drain. First-physical-hit narrative kicker explains why steel
  doesn't work.

**Classifications system (Rust-traits-style mixins):**
- New ``caldanai/lib/rpg/creatures/classifications/`` package.
- ``Undead`` mixin defines shared damage profile (LIGHT 2.0, FIRE 1.5,
  DARK 0.0, ICE 0.5) and ``"undead"`` flag, applied via
  ``setdefault`` so concrete subclasses can override per-creature
  values without losing the rest. Skeleton and Spirit migrated.
- ``Creature._resolved_hit_narrations`` walks ``__mro__`` and merges
  every ``HIT_NARRATIONS`` dict — subclass entries override mixin
  entries automatically. No ``{**Parent.X, ...}`` boilerplate.
- Forward-compatible for future Construct, Fae, Lupine, Demonic
  classifications.

**Per-hit damage-type narration:**
- ``Creature.HIT_NARRATIONS = {dmg_type: template}`` class-level dict.
- Surfaces in attack tables as ``extra_text`` when an attack lands.
- Skeleton example: bludgeoning → "Bones crack and splinter…",
  piercing → "The shaft whistles cleanly between brittle ribs…",
  light → "Holy radiance scorches the bone-walker's frame…".
- Communicates trait profiles in narrative language so players learn
  weapon choice through play.

**Capability methods on Creature:**
- ``can_fly()`` — functional flight capability (non-destroyed wings,
  or override for magical flight).
- ``is_flying()`` — currently airborne (``"flying"`` flag).
- ``has_eyes()`` — any eye body part.
- ``has_body_parts()`` — non-empty anatomy.
- ``has_target_preference()`` — class overrides the targeting hook.
- ``Creature.get_dodge`` and ``Dragon.get_dodge`` migrated to use
  ``is_flying()`` instead of poking ``self.flags`` directly.

**Predator target preference (selective):**
- Bearowl ~40% head, vampire ~40% head (eye → head after playtest
  found eye effective dodge of 60 was nat-20-only), bandit ~30% leg,
  minotaur ~50% head (gore), werewolf ~30% throat, pixie ~30% eye.
- Most monsters stay "dumb" — exposure-weighted random.

**Unified targeted-dodge math:**
- ``Creature.get_targeted_dodge(attacker, target_part, source)``
  becomes the single source of truth for the explicit-target dodge
  formula. Custom ``do_attack`` / ``attack_random`` overrides
  (hydra) reuse it instead of re-implementing.
- **Random targeting now also goes through the helper** — the tax
  follows the target part, not the intent. Fixes the asymmetry
  where a blind swinger could land an eye-shot more easily than
  a deliberate targeter. ``EXPOSURE_FLOOR = 0.3`` (was 0.05) caps
  the maximum dodge multiplier so eye-shots are reachable on solid
  rolls / nat 20s instead of nat-20-only.

**Cross-size dodge asymmetry:**
- ``attack_scale`` field added to Size enum.
- Effective dodge formula:
  ``base × clamp(attacker.scale / target.scale, 0.5, 2.0) / max(FLOOR, exposure)``
- TINY pixie attacking MEDIUM player has an easier time than the
  reverse. Clamp prevents extreme mismatches (pixie vs colossal
  dragon) from trivializing the math.

**Hydra multi-target damage routing fix:**
- ``Hydra.attack_random`` pre-dated the per-part routing refactor
  and was silently applying damage straight to body HP. Now mirrors
  ``MonsterPlugin.attack_random`` — picks per-part target via
  ``pick_random_part``, computes targeted dodge, routes per-result
  damage to parts, coalesces injury narration per victim per part.
  First-elemental-hydra fight now does what it should.

**Spirit-specific reactive hook:**
- New ``Creature._on_attacked(attacker, source, result)`` hook fires
  on the target after damage is computed. Default no-op. Spirit uses
  it for cold counter-touch on melee attackers (1d4 WATER damage).
  Forward-compatible for thorns armor, fire-aura monsters, etc.

**Drain-on-hit mechanic (sharable):**
- ``NaturalAttackSource`` carries a ``drain_ratio`` field (default
  0.0). Base ``Creature._on_attack_resolved`` reads it and heals
  the attacker by ``int(damage × drain_ratio)`` on a successful
  hit. Spirit declares 0.5; future life-drain monsters or weapons
  just pass the kwarg.
- ``Player._on_attack_resolved`` calls ``super()`` so future
  drain-weapons would just work for players.

**Damage-type elemental aliases:**
- New aliases on ``DamageTypes`` enum, each including the COMBINED
  bit so trait matching treats them as compound events:
  - ``ICE = WATER | DARK | COMBINED``
  - ``POISON = DARK | AIR | COMBINED``
  - ``LIGHTNING = LIGHT | AIR | COMBINED``
  - ``ACID = EARTH | WATER | COMBINED``
- Each alias gets a dedicated emoji: 🧊 ice, 🧪 poison, ⚡
  lightning, ⚗️ acid. Combat tables read at a glance instead of
  showing overloaded multi-emoji concatenations.
- ``DamageTypes.__str__`` rewritten as alias-aware: greedy match
  compound aliases first (largest bitmask first), then single-bit
  accumulation for remaining bits. Subclass output reads
  "slashing ice" rather than "slashing dark water".
- ``DamageTypes.canonical`` property returns the lossless storage
  form, appending "combined" when the COMBINED bit is set without
  being absorbed by a compound alias. Used for skill keys so
  COMBINED-bit weapons (torch, bow, wand) don't share storage
  keys with hypothetical non-COMBINED counterparts.
- ``DamageTypes.display_skill_name`` strips "combined" for
  player-facing display surfaces.
- Existing usages migrated: hydra (swamp/elemental head dmg_types
  and traits), ice_axe, undead mixin.
- **Mongo migrations** (``scripts/migrations/``):
  ``2026_04_14_skill_alias_rename.js`` rewrites legacy "dark water"
  / "dark air" / etc. skill keys to "ice" / "poison" / etc.
  ``2026_04_14_skill_combined_suffix.js`` backfills the canonical
  " combined" suffix on torch/bow/wand skill keys.

**Test invariants (parametrized over the monster registry):**
- ``tests/test_monster_invariants.py`` — universal invariants run
  against every ``MonsterPlugin`` (constructs cleanly, valid size /
  aggression / time_partition, non-negative stats, paired body
  parts symmetrized, traits non-negative, loot in [0,1], etc.).
- Capability-grouped tests:
  - ``TestFlyingCreatures`` — every monster spawning with the
    ``"flying"`` flag has wings; ``can_fly`` flips to False after
    wing destruction.
  - ``TestQuadrupedShape`` — fore/hindleg pairs present.
  - ``TestEyelessCreatures`` — HIT modifier falls back to heads.
  - ``TestNoBodyPartMonsters`` — ``render_body_part_status_table``
    empty; ``get_dodge`` uses raw value.
  - ``TestTimeFleeingCreatures`` / ``TestTimeDyingCreatures`` —
    narrative messages declared.
  - ``TestPredatorPreferences`` — overrides actually return a
    non-None preference within 200 samples (catches dead-code
    overrides).
  - ``TestCapabilityMethodsSelfConsistent`` — capability methods
    agree with internal state.
- ``tests/test_classifications.py`` — Undead mixin direct +
  registry-walking invariants ("every undead has LIGHT vulnerability
  ≥ 1.0", etc.).

**Other:**
- ``$inspect_monster`` is unchanged from last session but worth
  remembering: useful for verifying the new classifications applied
  the right traits / flags to a spawned monster.
- ``Giant.on_hugged`` ``len(None)`` crash fix (caught by the new
  universal ``test_on_hugged_returns_string`` invariant when running
  with non-Player actors).
- ``MathTeacher.LORD OF PRIMES`` extra_text dropped the
  ``__...__`` markers (no markdown effect inside ``\`\`\`diff``).
- New stackable item: ``bone_dust`` (60% drop from skeletons) +
  ``giant_toe`` (25% drop from giants).

**Test count:** 1716 passing (+~530 from session start).

---

### 2026-04-13 — Player Body Parts, Table Polish, and Healing Mechanics

A sprint of work on the body-parts system spanning combat readability,
player anatomy, predatory targeting, healing flows, and the hydra
multi-target routing fix.

**Player body parts (uncommitted → this batch):**
- Players now carry a fixed humanoid anatomy (head, torso, 2× arms,
  2× legs, 2× eyes). Head and torso are critical.
- `get_dodge`/`get_defense` emerge from body-part functionality (legs
  for dodge, torso for defense) plus armor bonuses on top. Injured
  legs visibly degrade dodge; a wounded torso shaves defense.
- Mongo persists `{instance_name: current_health}`; legacy entries
  rehydrate at full health, unknown keys are ignored, schema can
  evolve.
- `MonsterPlugin.attack_random` refactored to route per-result damage
  to the player's target part (injury tracking) and apply the
  post-defense total to body HP once, mirroring the
  player-attacks-monster path.
- Left/right pair symmetrization: both sides of an individual creature
  share one rolled `health_max` (max of the pair). Creature-to-creature
  variance remains; within-body asymmetry does not.

**Combat table polish (`51a49b5`, `b644569`):**
- Attack-check columns collapse into one "Roll v Dodge → Result"
  column so roll, dodge, and outcome read together — essential when
  per-part exposure or multi-target dodges differ across sources.
- Final column mirrors Multiplier's sub-damage; post-hook multipliers
  (math-teacher prime doubling/halving) render on an extra-text line
  instead of creating silent jumps.
- Miss rows show blank Damage, and aimed-at-part appears on misses too
  so a `Left → head | 1 v 25 → MISS` row explains its own inflated
  dodge at a glance.
- Footer distinguishes "defense partially absorbed" from "1/hit floor
  kicked in" — no more `13 damage - 13 defense → 2 damage` reading
  as broken arithmetic.
- Injury messages coalesce across a sequence so dual-wield on the same
  part emits one transition message, not one per hit.

**Q.5 HP rebalance + per-part dodge scaling (`cad3487`):**
- Body-part HP raised across the board (eye 1d4→1d6, tail 1d6→1d10,
  arm/wing 1d8→2d8, head 1d8→3d10, leg 1d10→2d10, torso 2d10→6d10).
  Non-crit hits can no longer one-shot core parts at MEDIUM size.
- Explicit part targeting scales dodge by `1/exposure` so aiming at a
  low-exposure part (eye 0.1, head 0.7) is harder to land. Random
  targeting pays the exposure tax through weighted selection.
  Nat-20 always hits regardless of effective dodge.

**Hook double-fire (`e6e6569`):**
- `Creature.apply_damage` stopped firing `on_injury_change` /
  `on_destroyed` internally. `do_combat` is the single call site,
  firing each hook exactly once per part per attack action. Wing
  grounding no longer echoes; doppelganger pain cries fire once.

**Target-preference hook (predatory monsters):**
- New `Creature.get_target_part_preference(target, source)` hook —
  return a part name to bias targeting, or `None` for baseline
  exposure-weighted random ("dumb" striking). Honored preferences pay
  the exposure tax on dodge.
- Bearowl ~40% head (killing bite). Vampire ~40% head (neck bite /
  fixation — flavor only, not a status effect). Bandit ~30% leg
  (cripple the mark). Goblin, giant, hydra, dragon, math teacher,
  doppelganger stay dumb (chaos / theme / simplicity).

**Disabled attack slots:**
- When a player's arm is at `USELESS`, that hand's attack source is
  filtered out of `get_attack_sources`. Two-handed weapons require
  both arms — either one useless and no attack fires.
- Attack rendering surfaces a note inside the diff block: "The right
  arm hangs limp and useless." Silent drop replaced with explicit
  feedback.

**`$health` table with dot + ANSI:**
- New shared `Creature.render_body_part_status_table()` used by both
  `$health` (players) and `$look` (monsters).
- Dot gauge (🟢 🟡 🟠 🔴 ⚫) + ANSI-colored status word inside a
  ```ansi fence. Mobile clients without ANSI still get the dot + word.
- Canonical mapping in `INJURY_LEVEL_DISPLAY` so any future injury
  rendering imports one source of truth.
- `$look monster` embed gets a "Body Parts" field. HP numbers omitted
  there to avoid the Model-D body-vs-parts arithmetic confusion —
  status words and dots carry the story.
- `$health hurt` / `$health injured` caught part-injured players, not
  just body-HP-injured, and appends a colored injured-parts suffix.
- `$health` regen clause now reads "next tick +N HP" (honest about
  the value being a per-tick charge, not a rate) and hides when regen
  is 0.

**Healing mechanics (Option D pending external items):**
- `do_health_regen` ticks every 30 game-min (7.5 real-min at
  `time_scale=4`), ramp +2/tick. Full heal ~75 real-min at 100 HP.
- Each tick heals body HP and the single most-injured part (triage
  by fractional HP), both clamped at max.
- Regen resets to 0 only when every pool (body + every part) is back
  at max.
- `BodyPart.apply_damage` clamps to `health_max` upward (healing no
  longer overshoots).
- Threshold crossings during regen emit `@`-parsed flavor via
  `BodyPart.get_recovery_string()`: "Caels winces as feeling returns
  to her right arm." / "…is starting to mend." / "…is nearly back to
  full strength." / "…feels as good as new."
- `$unsmite` fully restores body HP *and* all parts, resets regen,
  and accepts part-injured players (not only body-HP-injured).
- `$pray` part-aware:
  - **Nat 20** → full restoration (body + all parts); "radiant column
    of light" narrative.
  - **Nat 17–19** → existing computed body heal + fully restore ONE
    most-injured part.
  - **Nat 1 sacrifice rain** → other players get body HP *and* all
    parts restored.
  - Candidate filter catches part-injured players.

**Hydra multi-target parts routing (the "first elemental hydra"
bug):**
- `Hydra.attack_random` pre-dated the per-part routing refactor and
  was silently applying damage straight to body HP. Now each head's
  action picks a target part weighted by its reach, stores it on the
  `AttackResult`, routes per-result damage to the part for injury
  tracking, coalesces injury narration per victim per part, then
  applies the post-defense total to body HP. Parity with the base
  `MonsterPlugin.attack_random`.

**Math teacher signature fix:**
- `MathTeacher.resolve_attack` accepts and forwards the `target_dodge`
  kwarg added by the per-part dodge work (fixes a live-combat
  `TypeError` crash).

**Owner-only `$inspect_monster` (`$im`):**
- DMs a recursive pprint of the current monster's state + attack
  sources. Defaults to a `.py` attachment so Discord's inline
  preview applies Python syntax highlighting. Flags: `compact`
  (strip debuff tables / flavor), `inline` (use code fences instead
  of the file), `stats` / `parts` / `attacks` (section filter).
- Channel confirmation only; internals never leak to player channels.

**Tests:**
- 1186 total. Significant additions covering per-part dodge scaling,
  target-preference hook, disabled-arm behavior, part-HP round-trip,
  pair symmetrization, regen threshold narration, and the
  apply-damage-doesn't-fire-hooks contract.

---

### Phase 1: Body Parts System (`ae6ee79`)
The big one — monsters now have targetable body parts with injury tracking, debuffs, and explicit player targeting.

**New features:**
- Every monster has body parts (head, torso, arms, legs, wings, tail as appropriate)
- Per-source random part targeting in combat, weighted by weapon reach
- Explicit targeting: `$kill arm.left`, `$kill arm.left leg.right` for dual-wield split
- `$target` command for mid-combat target changes
- Injury feedback in combat log ("The left arm shows signs of moderate damage.")
- Critical part destruction kills the monster (head or torso)
- Hydra: new monster with regenerating heads, multi-head attacks, and a head cap
- Dragon: VARIANTS table with the 62-toe flavor variant (grounded = -62 dodge)
- Bandit: steal disabled when arms/legs are destroyed
- Doppelganger: deep-copies target's body parts and injury state on imitation
- Body composition templates: `BodyPart.humanoid()`, `quadruped()`, `quadruped_winged()`
- Codified dot-notation part naming (`arm.left`, `foreleg.right`, `head.2`)

**Combat rebalance:**
- Defense subtracted once from per-player total (not per-hit) — restored pre-refactor dual-wield balance
- Damage routing: unified body HP, parts track absorbed damage for injury levels
- Part injury debuffs reduce monster stats (dodge, attack, defense, hit) as parts take damage

**Infrastructure:**
- `BodyPartPlugin` base class with plugin discovery (mirrors MonsterPlugin pattern)
- `BodyPart.make(plugin_name, **overrides)` factory with dice-string health_max support
- `AttackSource.reach` field (MELEE, REACH, THROWN, RANGED)
- `Creature.body_parts`, `Creature.flags`, `Creature.get_stat_modifier_total()`
- `pick_random_part()` with exposure-weighted selection
- `MonsterPlugin.apply_damage` and `Player.apply_damage` signatures extended for `target_part`
- `PluginManager.load` fix for sys.modules double-import bug
- Integration test suite under `tests/integration/`
- 1061 tests total

---

## [2026-04-10]

### Automated Code Review — 36 bugs found and fixed
Five rounds of automated reviewer/developer agent loops swept the entire codebase.

**Critical fixes (`0115a8a`):**
- Player.__hash__ added — sets/dict keys were crashing
- Game.__init__ no longer drops the load_players coroutine

**Security fixes (`e550af5`):**
- `reload_cog` and `shutdown` commands gated by `is_owner()` — were exploitable cross-guild

**High-priority fixes:**
- `RpgAdminCommands.create` now actually registers new games (dropped falsy insert_game guard)
- `PlayerManager.remove_player` spreads role args correctly, always deletes from memory
- `RpgInventoryCommands.sell` guards against None from inventory.filter
- `get_random_monster` infinite loop when no monster matches current time
- `GameClock._time_map` initialization (lazy init to avoid recursion)
- `attack` command dedupe now uses Player equality, not None-prone .id
- `Player.from_dict` guards missing equip_slots keys
- `Dispatcher.split_message` character-drop and spurious-separator fixes
- `Bandit.steal` and `Vampire.feed` guarded against `randint(1, 0)` crash
- `save_game_data` Mongo `_id` attribute vs dict access fixed
- `add_game` prefix/enable_ambience positional arg mismatch fixed
- `loot` admin command unit mismatch (minutes vs seconds) fixed
- `attack_random` message accumulation fixed (was overwriting per-victim)
- `parser.parse` re.sub backreference injection and infinite loop fixed
- `item_list_to_string` duplicate-name replace fixed
- `update_statics` server_totals arithmetic fixed
- `Player.apply_damage` member None guard for revival message
- `DB.batch_write` watchdog timestamp only bumps on actual success
- `Inventory.filter` trailing `.n` index support
- `Player.get_inventory` absolute index display
- `bot.on_error` safe args access

### Combat Refactor (`b8a4644`)
- Attack-source/attack-result architecture replacing monolithic do_attack
- Player.do_attack calls target.on_attacked per hit
- Combat message detail restored after refactor

### Watchdog Rework (`812ac2f`)
- Replaced rescan_plugins loop with per-game GameClock.tick watchdog

### Monster Completions
- Math Teacher monster finished and moved out of WIP (`7303f2c`)
- Doppelganger monster finished and moved out of WIP (`09eef12`)
- Doppelganger re-imitation via on_combat_round hook (`7a6d71b`)
- Selective monster spawn class resolution fix (`607d3f3`)

### Test Suite (`4f56a78`)
- 235 unit tests added covering DB, dispatcher, game, inventory, combat, players, monsters

### Infrastructure
- `startup.py` for git sync before launch (`3b40d67`, `8382ba7`)
- `batch_write` silent-death fix on DB reconnection (`945c4f8`)
- Game state recovery on restart (`72edaea`)
- 12 latent bugs fixed from initial code review (`5d28ae4`)
