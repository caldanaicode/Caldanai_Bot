# Changelog

All notable changes to the Caldanai Bot project will be documented in this file.

## [Unreleased]

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
