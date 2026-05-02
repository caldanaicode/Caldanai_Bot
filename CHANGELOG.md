# Changelog

All notable changes to the Caldanai Bot project will be documented in this file.

## [Unreleased]

### 2026-05-01 — Heal-system rewrite: pray d20=17-19 + cascade-revive narration + neck-critical

Live `$pray` playtest exposed a corpse-revive bug — narration
read "imbuing them with N points of health!" but the player
stayed mechanically dead because `Creature.is_dead()` had a
hidden side-effect that zeroed `self.health` mid-heal whenever
a destroyed critical part was still detected. The surface fix
unraveled into a full rewrite of how pray, regen, and divine
intervention distribute heal magnitude.

- **`is_dead()` is now a pure predicate.** Damage paths
  (`Creature.apply_damage`, hydra's `check_part_driven_death`)
  own their own body-HP zeroing on critical-part destruction;
  `is_dead` just reads state.
- **`HealMixin` extracted to `creatures/healing.py`.** Three
  primitives Creature inherits: `get_total_injury_surface`,
  `divine_rescue` (free critical-part rescue + body spark),
  `distribute_heal` (2:1 part:body distribution). Future heal
  sources (potions, scrolls, magic, mob-vs-mob heals) reuse them.
- **Pray d20=17-19 rewrite.** Always-revives if the target was
  dead — every destroyed critical part rescued to 1 HP, body
  sparked to 1 if at 0, gasping narration fires. Then a rolled
  budget distributes 2:1 part-to-body, worst-first within tiers
  (critical-destroyed → critical → non-critical), with ratio-
  preserving spillover (4 saved part-HP → 2 body, 2 lost to
  the routing valve). Min-1 floor on small rolls so even a
  low d20=17 lands ≥1 HP somewhere effective.
- **Cascade-revive narration.** Pray and `do_health_regen` both
  capture `was_dead` at function entry and fire the gasping
  tail on cascade transitions (body > 0 but is_dead via
  critical-part destroyed → rescue clears it → alive).
  `apply_damage`'s tail was HP-only and missed this.
- **`neck.is_critical = True`** for humanoid anatomy. Direct
  kill on neck destruction. Hydra explicitly overrides
  `is_critical=False` on multi-necks (only the last head is
  critical per existing design).
- **`$creature destroy [@target | <monster-name>] <part>`** —
  lifted from `$spawn destroy`, now top-level under a
  `$creature` admin group. Targets players via mention or
  monsters via fuzzy name match. Routes through `apply_damage`
  with `target_part` so the canonical safety sweep zeros body
  HP on critical destruction and gear placements clear normally.
- **`$forcepray <d20-value> [@target]`** admin command for
  branch-testing pray narration deterministically. Bypasses
  the 60s pray cooldown and the d20 RNG. Owner / manage_guild.

### 2026-05-01 — Inventory $sort + doppy loot-volume fix

`$sort` (aliases: `organize`, `tidy`) re-slots inventory by
`(plugin asc, quality desc)` so duplicates land together and
the best copy of each plugin sits at the lowest slot. DM-routed
via the same `dm_target` selector `$inv` uses. Items keep their
`_id`s, so saved loadouts stay valid post-sort.

Doppelganger loot-pile cleanup: removed the for-loop in
`imitate` that augmented the loot table with the target's
inventory at re-rolled rarity. Pre-fix doppy kills produced
~8-9 items/kill (1 baseline + 6.5 augment + ~1 salvage); post-
fix is the static 5-entry baseline plus occasional salvage of
mimicked equipped gear. The 2026-04-29 dup-id fix already
covered the salvage pipeline; this finishes the volume-bomb
removal noted in that commit.

### 2026-04-29 — Doppy mimic dup-id corruption + drop-rate rebalance

`Doppelganger.imitate` deep-copies the target's body tree
including equipment `placements`, and `ObjectId` is immutable so
deepcopy preserves the source `_id` on every cloned Item. When
salvage or corpse-scavenge harvests one of those clones into the
killer's bag, the dup-id silently breaks every code path that
does `inventory[item.id]` first-match lookup —
`Player.take_item` returns None for siblings 2+N, so `$sell`
paths leave duplicates stranded. Surfaced live by
`$sell duplicates` finding 3 quality bandannas in Vael's bag
with one shared `_id`.

The investigation surfaced two related drop-rate problems in
the same `imitate` pipeline (loot-table accumulating across
imitations without reset, mimicked gear salvageable at standard
monster rates despite the organic-mimicry conceit), fixed
together.

- **Source-of-corruption fix** — `imitate` nulls `item.id` on
  every deep-copied placement. `Inventory.add` already promotes
  `id is None` to a fresh `ObjectId` at insertion, so a clone
  gets a real id only when it actually reaches a bag.
- **Loot-table reset on imitation** — `__init__` snapshots the
  doppy's five baseline loot entries; `imitate` restores that
  baseline before re-seeding from the new target's inventory.
  Pre-fix, a doppy that imitated three players rolled drops
  from all three at once.
- **Salvage-rate override** — Doppy `SALVAGE_SURVIVAL_CHANCE` =
  2/30 (vs base 2/3) and `CORPSE_SCAVENGE_CHANCE` = 1/30 (vs
  base 1/3). Order-of-magnitude lower; salvage still
  occasionally lands and the player's rolled rarity carries
  through, preserving the "kill your shadow, take its armor"
  flavor sustainably.
- **Shield against existing-state corruption** —
  `Inventory.__contains__` identity-based; `Inventory.remove`
  uses identity-based slot lookup; `Player.take_item` uses
  `item in self.inventory`. Pre-existing dup-id items in any
  player's bag become salable without intervention.

Reading-B balance concern (masterwork-wand farm) addressed
indirectly: drops still preserve rarity, but at ~1/10 the prior
frequency, so farming is no longer efficient. Reading-A flavor
stays.

Also: `tools/inspect_inventory.py` (new) dumps persisted
inventory with `_id` / quality / equipped+favorited flags for
investigations like this one. Defaults to `TEST_DB_NAME`,
`--live` for LIVE.

### 2026-04-29 — Inventory QoL: dup-label collapse, fully-qualified equip, `$sell duplicates`

Three QoL items closed off the back of the morning sell rebuild —
two surfaced live during playtest, one is the long-standing
"bulk-clear extras" ask.

- **Disambiguation collapses on identical labels.** When the
  resolver's "did you mean" candidates all render to the same
  string (e.g. two ordinary tee-shirts both projecting as
  ``tee-shirt.ordinary``), the hint can't help the player narrow
  further — surface the first match instead. New helper
  ``_ambiguity_or_first`` wraps the common pattern across
  ``equip`` / ``stow`` / ``item`` modes. Genuine ambiguity (two
  wands of different qualities → ``wand.fine`` and
  ``wand.superior``) still surfaces candidates as before.
- **Fully-qualified `$equip` bypasses the quality gate.**
  ``$equip wand.junk.1`` (or any ``.<quality>`` /
  ``.<quality>.<n>`` / ``.<n>`` form) now lands even when the
  current occupant is higher quality. The quality gate remains
  for bare ``$equip <name>`` and for ``.best`` — both auto-pick
  cases where accidental-downgrade protection is warranted.
  Detection: any selector other than ``best`` after the first
  ``.`` flips ``force_displace=True`` on the cog → ``Player.equip``
  call. Tier-3 cross-type and bare-name auto-best behavior
  untouched.
- **`$sell duplicates [n]` bulk-clears extras.** Group inventory
  by ``item.plugin``, drop equipped + favorited from the sale
  pool, then sell everything past the top ``n`` by quality.
  Default ``n=1`` keeps the best of each. ``$sell duplicates 2``
  preserves dual-wieldable pairs — the user's hammer for the
  Serena-bow scenario. Stackables (consumables) auto-stack to
  one entry per plugin so they trivially satisfy keep-1.
  Receipt headers count duplicates ("sold 4 duplicates (keeping
  1 of each)"); empty-result path surfaces a friendly
  "no duplicates to sell" instead of an empty receipt.
- New regression tests pin all three behaviors:
  ``test_dup_quality_collapses_to_first``,
  ``test_auto_equip_force_displace_bypasses_quality_gate``, and
  the ``tests/test_sell_duplicates.py`` module (6 cases covering
  keep-1 default, keep-N, favorited+equipped exclusion,
  per-plugin grouping, and the no-duplicates path).

### 2026-04-29 — `$sell` rebuild: dict-keyed inventory, hyphen-safe parser, identity equip-check, within-action stability

Five compounding bugs surfaced 2026-04-29 morning when Vael
couldn't `$sell junk` despite having unequipped junk in
inventory (junk tee-shirts only, three of them, one worn).

- **`Inventory` storage now `Dict[int, Item]`** keyed by 1-based
  slot. Slots stay compact (1..N, no gaps) via rekey-on-mutation.
  Observable behavior matches the prior `List[Item]` exactly;
  the dict shape sets up cleaner read patterns for the upcoming
  inventory-sort QoL work and gives mutators a stable handle to
  reason about.
- **`$sell <name-with-hyphen>`** no longer trips the range
  parser. The dash-as-range branch now matches `\d+-\d+` only;
  `tee-shirt` falls through to fuzzy-name resolution.
- **`$sell <indices>` equip-check** now uses
  `player.is_equipped(item)` (identity compare). Prior behavior
  matched by `Item.id` set membership, which on the live repro
  refused all three tee-shirts when only one was worn.
- **Within-action index stability.** Numeric inputs are pre-
  resolved to `Item` references upfront, before any sells fire.
  `$sell 35 38 43` now sells three distinct items as the player
  intended, instead of shifting after each sale and selling
  whatever ended up at 38 / 43 next.
- **"Must un-equip ... before selling them" → "selling it"**.
  Singular subject takes singular pronoun.
- **Equipped-skip receipt line**. Fuzzy-name `$sell` (e.g.
  `$sell tee-shirt` with only the worn copy in your bag) used
  to fail with "you don't seem to have anything matching" —
  the resolver pre-filtered equipped items, hiding their
  existence. Sell-mode resolution now returns every match;
  the candidate loop counts equipped skips and surfaces them
  in the receipt parallel to favorited skips: *"1 item skipped
  (equipped — `$stow` first)."*
- New `TestSlotStability` regression class pins the dict-storage
  contract: `filter("N")` returns the item at user-visible slot
  N, removes don't leave gaps, adds land in the next compact
  slot. 3978 tests pass overall (+4 from the new regression
  class).

### 2026-04-29 — Suppress post-flee `$loot` prompt when nothing fresh dropped

The post-combat `$loot` prompt was firing on flee exits even when
the fleeing creature dropped nothing — sheep walk-off, dragon
fly-off, math teacher dimensional retreat — because the announce
condition checked whether ANY items were in the loot pool.
Inherited stale ground-litter from a prior encounter (e.g.,
overburdened items the player couldn't pick up) made the global
pool non-empty, so the prompt fired anyway. Caels caught it live
mid-playtest 2026-04-29.

- `CombatState` now snapshots `loot_size_at_start` when a monster
  spawns. `_finalize_combat` compares end-size to start-size to
  decide whether THIS combat actually added anything fresh. Stale
  pool from prior encounters no longer triggers the prompt; the
  cleanup timer (`loot_expires`) still schedules off the
  has-any-loot check so old items get swept on schedule.
- New regression test `test_time_flee_with_only_stale_pool_no_loot_prompt`
  pins the bug case (pool non-empty but unchanged across the
  combat → no prompt). Existing `test_time_flee_with_salvage_emits_loot_prompt`
  / `test_time_flee_with_empty_pool_no_loot_prompt` still pass —
  fresh-salvage and empty-pool both behave as before.

### 2026-04-28 — Size-aware combat: region-collapse, COLOSSAL, age variants

Three small adjustments make size differences read consistently
during attack resolution and surface the new variant texture.

- `_REGION_COLLAPSE_THRESHOLD` is now applied at-or-above (`>=`)
  instead of strictly above (`>`). Player vs TINY pixie and
  Medium vs HUGE cyclops/giant/dragon now trigger eye → head /
  arm → torso roll-up; the previous `>` left the most-common
  ratio-2 cases falling through with no collapse.
- `COLOSSAL.attack_scale` 1.75 → 2.0. Restores the round
  scaling the design intent assumed; matches the size-ladder
  spread (TINY 0.5, MEDIUM 1.0, COLOSSAL 2.0).
- Age-variant `SIZE_VARIANTS` class attribute on dragon, giant,
  and hydra plugins. Each spawn now picks uniformly from a
  size pool: dragons & giants roll LARGE / HUGE / COLOSSAL,
  hydras roll LARGE / HUGE (no COLOSSAL — multi-headed-ness IS
  the apex flavor). Tests for these creatures patch the variant
  pick to read the actual rolled size.

### 2026-04-28 — Drop size-ratio remnant from per-part dodge

Creature size is already baked into `creature.get_dodge()` at spawn
via the Size enum's `dodge_mod` (TINY 1.5×, COLOSSAL 0.25×). The
`effective_dodge_for_part` resolver was re-applying an
attacker-vs-target `size_ratio` on top, which doubled-up: a Medium
player attacking a Tiny pixie saw per-part dodges clamped to 2×
the displayed body dodge (16 displayed → 32 effective torso, 33
effective wing). Caels diagnosed it live during the 2026-04-28
playtest as a remnant from before size baked into the base.

- `effective_dodge_for_part` no longer reads `attacker` for size
  scaling; `attacker` parameter retained for API stability with
  callers but unused. Per-part dodge varies only by exposure tax
  + depth + offset within the size-correct base.
- `SIZE_RATIO_MIN` / `SIZE_RATIO_MAX` constants removed (only
  used in this function).
- `ScaledDodgeTests` updated: `test_attacker_size_does_not_affect_dodge`
  replaces the size-ratio assertions; `test_dodge_cap_clamps_runaway_inflation`
  simplified to test the exposure-tax cap on its own.
- Region-collapse and selection-bias paths still cover the
  size-aware targeting story — only the dodge double-count was
  the bug.
- Pixie dodge bumped 5d3 → 8d3 follow-up: with the 2× cap gone,
  TINY needed real base dodge to stay pesky-not-trivial. New
  spread sits the pixie at ~24 effective body dodge, sk0 86%
  win-rate / sk20 100% (was ~50% / un-killable).

### 2026-04-28 — Social-pool flavor token fixes

Eight social-command flavor pool entries had `@1 ... @1` doubling
that rendered the actor's name twice ("Caels plants himself
mid-stride like Caels just kicked"). Replaced the second `@1`
with `@1s` (subject pronoun) across `pose`, `salute`, `hug`,
`nod`, `tease`, `taunt`, `stare`, `bow`. Caught proofing the
pose pool 2026-04-28; verified each fix via
`tools/render_flavor`.

### 2026-04-28 — Humanoid base-stat rebalance + sweep harness skill ladder

Defense/dodge values across humanoid monsters collapse onto a
shared baseline so the bestiary chart stops scattering by
historical accident and starts reading as a coherent power
curve. Size scaling carries differentiation between the small
goblins and the huge giants instead of bespoke die strings on
every plugin.

- **Baseline humanoids** (bandit, goblin) → `4d2 / 4d2`. Mean 6
  matches the player default; per-spawn variance ±2. Bandits
  and goblins also wear scrap armor for additional texture, so
  the modest base stays out of the way.
- **Signature humanoids** (skeleton, vampire, doppelganger,
  math_teacher, minotaur, giant, golem) → `5d3 / 5d3`. Mean 10;
  size_mod handles the LARGE / HUGE bumps. Restores meaningful
  threat to LARGE+ creatures (giant 94% → 71% beat-rate at
  skill-20, golem 100% → 91%, minotaur 100% → 92%).
- **Pixie** → `2d3 defense / 5d3 dodge`. The defense bump fixes
  TINY size_mod truncating her torso to 0; the dodge tightens
  to keep her landable for skilled players.
- **Werewolf** → `3d3+1 defense`. Bumped from `1d6` because
  LARGE size_mod still left her reading weaker than a fresh
  player. Floor-of-4 + LARGE = real threat without crowding the
  golem/minotaur tank tier.
- Skill progression sweep at QUALITY mace, 200 trials/scenario:
  bandit/goblin/skeleton stay 100% at all skills (mooks);
  vampire 3% → 40% across skill 0→20 (brutal early);
  giant 6% → 71%; golem 21% → 91%; cyclops 9% → 36%
  (never trivial); dragon 0% → 1% (apex preserved).
- `tools/playtest_combat_harness` cross-monster summary now
  renders win-rates at skill 0 / 5 / 10 / 20 instead of skill-20
  only — the progression line surfaces early-game balance the
  endpoint-only view was hiding.

### 2026-04-28 — Armor / dodge / loadout lift to `Creature`

Worn-armor aggregation, the spawn-time loadout pipeline, and the
low-quality dodge tax move from `Player` / `MonsterPlugin` down to
`Creature`. Monsters and players now share one defense / dodge /
loadout pipeline; the per-part decomposition no longer needs its
"Bypass Player.get_defense" workaround.

- `get_defense = _emergent_defense + worn`. `get_dodge = _emergent
  + worn - low-quality penalty`. Player overrides delete entirely.
  Monster `SPAWN_LOADOUT` armor now bumps creature-wide defense
  (matters for breath weapons / hydra body pool), not just per-part.
- `ARMOR_LOADOUT` → `SPAWN_LOADOUT`, `_apply_armor_loadout` →
  `_apply_loadout`, both lifted to `Creature`. Players fire it
  explicitly from `PlayerManager.add_player` so DB-hydrated
  returners don't re-roll fresh gear; `Player.SPAWN_LOADOUT = {}`
  for now (starter kits via this path is a future enhancement).
- Construction-order fix: `_scale_part_hp` and hydra head regrowth
  read `_emergent_defense` (intrinsic resilience), not `get_defense`,
  so a lucky loadout roll doesn't inflate per-part HP at spawn.
- LF line endings enforced via new `.gitattributes` so tool-driven
  re-saves on Windows stop flipping whole files into diff noise.

### 2026-04-28 — Body-parts table: per-part Def column with breakdown

Player-facing visibility for the per-part absorption pool. Both
`$look <monster>` and `$health <player>` (same renderer) now carry
a `Def` column showing `d{N} ({base}{±part_bonus}{±armor}{±drain})`
so the mechanic stops being invisible: torso-injury drain and worn-
armor bonuses are explicit, not just inferred from a degraded-part
emoji on the embed.

- New `effective_defense_breakdown(creature, part)` decomposes
  `effective_defense_for_part` into its four additive components
  (full-health base, part-specific bonus, local armor, torso-damage
  drain). Same arithmetic — components just survive to the renderer.
- New `_format_defense_cell(breakdown)` produces the cell string;
  zero components are omitted (`d20 (20)` not `d20 (20+0+0)`),
  totals ≤ 0 collapse to em-dash (matches the absorption helper's
  short-circuit on soft parts that floor to zero).
- `Creature.render_body_part_status_table` adds the `Def` column
  between `Status` and `Worn`. Body-less creatures still emit no
  table; format works identically for monsters and players.

### 2026-04-28 — Spawn embed: Defense re-anchored to TORSO-effective

Bare creature-level `get_defense()` hid per-part bonuses on the
spawn embed: a bearowl with torso `defense_bonus=+3` displayed
the underlying pool (e.g. 17) when a torso swing actually rolls
absorption against torso-effective (e.g. 20). Caels' 2026-04-28
call: "Make the embed show the end result. Leg was correct at 16
according to the embed, so the +4 for the torso is a magic number
on a creature with no armor bonuses."

- `Creature.get_embed` now routes Defense through the per-part
  resolver (`effective_defense_for_part`) anchored on torso —
  same code path `Creature.resolve_attack` uses when a torso
  swing lands. Body-less creatures (spirit) and anatomies without
  a literal "torso" fall back gracefully (creature-level
  `get_defense()` for body-less; first critical part otherwise).
- Dodge stays on creature-level `get_dodge()` — per-part dodge
  variance is dominated by size scaling, not part bonuses.
- `tools/playtest_combat_harness --validate-embed-stats` validator
  contract updated to assert `embed[Defense] ==
  effective_defense_for_part(creature, torso)`. 200 × 22 monsters
  = 4400 spawns pass clean.
- `tools/inspect_monster` header now reads
  `defense=raw->effective (torso N)` so the underlying creature
  pool stays diagnostic-visible alongside the number a player
  sees on `$look`.

### 2026-04-27 — Per-hit absorption rolls 1d{defense} (trial)

Pre-trial: a hit doing 10 raw against a defense-7 part deterministically
absorbed 7 — flat-subtract, no variance. The same exchange always
produced the same post-armor number.

Trial: each per-hit absorption now rolls `1d{defense}` and clamps
that against the incoming raw damage. defense 7 still caps the
absorption at 7 (max roll), but the average drops to 4 — same dice
shape as a 40k save. The dopamine moments cut both ways: a low roll
is a "breach" (full hit punches through), a high roll is a "block"
(armor catches almost everything), and the mid rolls are the 60%
case that used to be the deterministic floor.

The rebalance is **deliberately deferred**. Defense values are
unchanged — this trial accepts halved expected absorption to feel
out whether the variance is fun before re-tuning. Iteration lands
after a playtest feel-check.

The Def column in the combat table renders the rolled value AND
the underlying pool: `-4(d7)` reads as "4 absorbed against a d7
pool." Misses still render `-`; zero-defense parts still render
`0` (no roll fires for `1d0`).

Edge cases: `defense == 0` skips the roll entirely (no `1d0`),
`defense == 1` shortcuts past `Dice.from_ndn`'s `sides < 2`
rejection. Absorption is bounded above by the raw hit so armor
can't absorb more than the attack landed. The pre-trial
`max(1, sub_dmg - defense)` floor is **preserved** — a connecting
hit always registers at least 1 body-HP, even on a max-roll
absorption. Damage-type immunity (`multiplier == 0`) is the only
path to a true 0; that's gated upstream and untouched. Keeps
full-block hits visible to the downstream `damage > 0` /
`num_hits > 0` accounting (retaliation, injury feedback,
num_hits floor) — a hit that connects narratively shouldn't
vanish from the bookkeeping.

23 new tests pin the helper, the `resolve_attack` integration, the
`absorbed` field on `AttackResult`, and the Def column format.
A handful of pre-trial tests that pinned exact post-defense
damage values were updated to mock the absorption roll to its max
face — same expected damage, just no longer implicit.

### 2026-04-27 — Heal-target picker uses weighted body+critical-parts ratio

`$pray`'s 17-19 heal target and the new nat-1 single-target rain
picker both selected the most-injured player by raw body HP
percentage, with injured-part *count* as a tiebreaker. That
ranked a player with three lightly-bruised limbs above a player
with a critically-wounded head.

New `Creature.get_overall_health_scale(critical_weight=2.0)`
folds body HP and per-part HP into one weighted ratio (0-1,
lower = more injured). Body HP and `is_critical` parts (head /
torso / neck / etc.) carry 2x weight; non-critical parts (limbs,
eyes, peripheral) carry 1x. Both pickers now use it as their
sort key, so a player with a destroyed critical part outranks
a player with a destroyed limb, and gear-driven HP-max
differences wash out via percentage normalization.

5 new tests cover the helper directly: degenerate-no-parts case,
full-health = 1.0, critical-part-vs-limb ranking, the
`critical_weight` parameter scaling, and a worked-example case.

### 2026-04-27 — Drop body-parts table from monster arrival

Monster spawn used to emit two messages: the arrival flavor +
embed, and an immediate body-parts ASCII table. Players who
wanted to plan a target had it for free; everyone else had to
scroll past it every spawn. Hydras and dragons (20+ parts)
made the noise especially loud.

Removed the auto-emit. The parts table is still available via
`$look <monster>` (which renders the same table), so the
information isn't gone — players just have to ask for it. Cuts
~15 lines of noise off every spawn for visible-loadout monsters.

### 2026-04-27 — `$pray` nat-20 heals the entire party + hidden smite

The nat-20 prayer outcome now heals every injured player in the
game, not just the most-injured one. Each injured player gets
their own "radiant column of light" beat; uninjured players are
skipped (a "made whole" line for someone at full HP would mean
nothing). Mirrors the nat-1 sacrifice branch's per-player
iteration shape so the full party feels the divine swing in
either direction.

Also adds a hidden secondary 1d6 roll on nat-20: a 6 calls down
divine wrath on every spawned monster, one-shotting them via
the canonical damage path so the death pipeline (corpse-scavenge
sweep, loot pool, on_monster_death + end_combat) all fire
correctly. Effective rate: 1/20 × 1/6 = 1/120 prayers, ≈ 0.83%.

The smite is **deliberately undocumented** in patch notes — let
players discover it. CHANGELOG entry exists for technical
history; no player-facing announcement. Smite narration uses a
3-line flavor pool with storm / lightning / ash / cinders /
ozone vocabulary, inverting the nat-1 sacrifice's storm onto
the monster instead of the praying player.

The 17-19 branch (single-target partial heal + worst-part
restore) is unchanged.

**Coordinated nat-1 narrowing:** the nat-1 sacrifice's rain
used to fully heal the *entire* surviving party. With nat-20
now owning the party-wide sweep, the rain would have been a
free second copy of the same effect — and would have flattened
the "I died for you, comrade" beat into an everyone-gets-a-
prize sweep. The nat-1 rain now heals exactly **one** ally
(the most-injured non-praying player, fully), so the dramatic
moments stay singular and poignant. If no ally is injured, the
storm fires but no rain heal — the praying player's death
isn't paid back at all.

### 2026-04-27 — Fuzzy monster names across `$kill` / `$look` + salvage polish

`$kill <monster> [<part>...]` and `$look <monster>` now accept
prefix and typo-tolerant monster-name matches. `$kill hyd h.1`,
`$kill ske`, `$look gob`, `$kill mntaur head` all resolve to
the spawned monster as players intend, instead of the player
having to type the exact registered name.

Resolution: exact / word-token first, then prefix-of-any-word,
then `difflib.get_close_matches` at cutoff 0.75 (catches single-
character drops like `hdra` → "hydra"). Stdlib only.

`$kill` keeps a conflict guard — if the token also resolves to a
body part via `find_parts`, the part wins. So `$kill h` still
targets head/hand on every monster, even when the spawned
creature's name starts with `h`.

Both call sites delegate to a single `Creature.matches_token`
method, so the logic lives in one place. ($haunt and any other
spawned-monster command can be plugged into the same helper.)

Inline salvage narration now collapses duplicate same-item drops
on a destroyed part: two leathers from one bearowl foreleg read
as "Two leathers slip free of the bearowl's left foreleg." instead
of two identical lines. Stackable items with an explicit `plural`
attribute (wool → "tufts of wool") are respected when they appear
in salvage. Same collapse applies to the corpse-scavenge sweep.

Also: `bone dust` loot now reads "Vael Caldanai found some bone
dust" instead of "a bone dust" — the only Stackable that was
missing the `article="some"` field for its mass-noun shape.

### 2026-04-27 — `tail_channel --gateway` mode (reactions + edits + presence)

Adds a Gateway WebSocket mode to the channel tailer, alongside
the existing REST poll. Streams events live via the tester
bot's token (``CLAUDE_TESTER_TOKEN``):

- **Messages** — same content the REST poll fetches, just via
  push instead of polling. Round-trip drops from ~5s poll
  interval to immediate.
- **Edits** — ``MESSAGE_UPDATE`` events emit a fresh entry
  tagged ``[edited]`` so a reader sees the timeline as it
  played. REST poll can't observe these.
- **Reactions** — ``MESSAGE_REACTION_ADD`` events emit a
  one-line ``@user reacted with <emoji> to <id>`` entry.
  Useful for picking up acknowledgement signals (👍 / ack
  reactions) that REST poll strips entirely.
- **Presence** — the tester bot appears online while the
  Gateway client is connected, signaling to other players
  that the channel is being watched.

Implementation: discord.py ``Client`` with the minimal intent
set (guilds, guild_messages, guild_reactions, message_content).
Reuses the existing ``TailBuffer`` + HTTP inspector so
``tail_peek`` works identically against gateway-streamed
content. New ``_discord_message_to_raw`` adapter so the
existing message formatter doesn't need to learn discord.py's
object model.

Requires the tester bot's MESSAGE_CONTENT privileged intent
enabled in the Discord developer portal.

### 2026-04-27 — `$equip <name>` defaults to best-quality

Bare-name equip queries (no ``.<selector>``) now auto-pick the
highest-quality match. ``$equip wand`` with three wands in
inventory used to surface an ambiguity prompt; now it picks
the best one — same as ``$equip wand.best``.

Players asking for "a wand" generally mean their best wand.
The ambiguity prompt only kicks in when an explicit selector
fails to narrow (e.g. ``$equip wand.fine`` with two fine
wands — the selector itself didn't disambiguate, so the
player needs to retry).

Strict matching is preserved for index selectors (``wand.2``)
and quality selectors (``wand.fine``, ``wand.b`` → ``wand.best``).

### 2026-04-27 — Auto-equip: 3-tier slot priority (empty / same-type upgrade / cross-type swap)

Replaces the prior any-type quality-gated displace. Player
intent matters: ``$equip wand.best`` with two masterwork
shortswords held should still slot the wand in, since the
player explicitly asked for a wand by typing it. The previous
quality-gate refused that swap because the wand was lower
quality than the swords — wrong call.

Three-tier priority, first match wins:

1. **Empty compatible slot** — fill it.
2. **Same-type lower-quality occupant** — displace (upgrade
   in type). ``junk wand`` → ``masterwork wand`` swap without
   ``@l`` / ``@r``. Same plugin string = same item type.
3. **Cross-type occupant** — displace the worst-quality one
   (no quality gate). The player explicitly asked for type X
   by typing the item; we don't refuse based on cross-type
   quality. Picking the worst cross-type minimizes the loss
   when forced to trade.

Equal-or-worse same-type still refuses (no upgrade, no churn).

7 tests pin the priority order and edge cases (cross-type
swap ignores quality, same-type upgrade beats cross-type
swap, empty-slot-wins, equal-quality-stays).

### 2026-04-27 — Typo-tolerant part lookup + shared fuzzy primitives

`forl.r` on a werewolf now reaches `foreleg.right` instead of
falling through to random targeting. Adds Pass 4 to
`Creature.find_parts`: each query segment matches via
`is_prefix` OR within Levenshtein distance 1 of some prefix
of the name segment (length-matched ± 1). Catches one missing
char, one substituted char, one extra char.

The per-pair primitives moved to a new
`caldanai/lib/rpg/helpers/fuzzy.py`:

- **`is_prefix`** / **`is_substring`** — the existing cheap
  primitives, now exposed.
- **`is_within_one_edit`** — Levenshtein-1 against
  prefix-of-name in {len(query)-1, len(query), len(query)+1};
  bounded to query length ≥ 3.
- **`_levenshtein_le_1`** — threshold-1 distance, optimized
  for the threshold case (length diff > 1 short-circuits to
  False; equal-length walks until 2 differences; off-by-one
  walks until first mismatch then skips one char).

`Creature.find_parts` and `MonsterPlugin.find_plugin_classes`
both call the new primitives — the outer-walk strategy
(segment-aligned vs unordered tokens) stays at the call site
where the intent is clearest. Pass 4 uses prefix-OR-fuzzy per
segment so a typo in one segment doesn't block valid short
segments like `r` (below the fuzzy floor) from still matching.

37 new tests covering the primitives + the typo recovery
case + the prefix-wins / substring-wins invariants.

### 2026-04-27 — `$item` surfaces the dodge penalty on low-quality armor

Direct UX follow-up to the dodge penalty ship. Players were
seeing `defense: 1` on a junk rough jerkin and not understanding
why their dodge dropped on equip. The Armor embed now adds a
`dodge: -<N>` field when the piece's class declares a
`LOW_QUALITY_DODGE_PENALTY > 0` AND the instance is at quality
multiplier ≤ 1.0 (JUNK / ORDINARY). FINE+ pieces hide the field
because the penalty isn't paid at that quality; bare Armor
(default penalty 0) never shows it.

Field is plain `dodge` with the value negated so a piece's
penalty reads in the same column as any positive dodge bonus a
future armor piece confers — no separate "dodge tax" label.

7 new tests in `test_armor.py` covering the active-when-low,
hidden-at-fine-plus, never-on-zero-penalty cases.

### 2026-04-27 — `tools/journal.py` checked in + `edit` subcommand on bot_player and journal

`tools/journal.py` shipped earlier in the day's playtest but was
never staged. Adding it now alongside an `edit` subcommand on
both `bot_player` and `journal` so a tester-bot post mangled by
shell-quoting (an unescaped `$kill` swallowed inside double-
quotes is the canonical trip) can be patched in place instead of
leaving a duplicate-and-retry trail in the channel. Bots can
only edit messages they authored; trying to edit somebody else's
message yields a 403 from Discord.

### 2026-04-27 — Low-quality armor dodge penalty

Junk and ordinary armor now drag the wearer's dodge down a small
amount; FINE+ quality is unaffected. Differentiates crafted-leather
(light class) from scrap (heavy class) and sets up a future cloth
class for magic users.

- **`Armor.LOW_QUALITY_DODGE_PENALTY`** class attribute (default 0)
  on each armor piece; heavy/structural pieces override.
- **`Player._get_low_quality_armor_dodge_penalty()`** walks
  equipped armor and sums penalties for items at quality
  multiplier ≤ 1.0 (JUNK + ORDINARY).
- **`Player.get_dodge()`** subtracts the penalty, clamped at 0.
- **Per-piece values**: `rough_jerkin` 2, `rough_rerebrace` 1,
  `rough_greave` 1, `scrap_shin` 1, `leather_jerkin` 1. All
  smaller pieces stay at 0. Fully-kitted junk scrap costs
  -5 dodge; fine+ kits stay clean.
- Penalty applies globally (not per-part) — armor weight slows the
  whole creature, not just the armored part. Mirrors the existing
  `creature.get_dodge()` aggregate-armor model.

### 2026-04-27 — `bot_player --channel-id` for non-combat posting

`bot_player send` previously resolved the target channel from
the TEST DB's games collection (always the combat channel).
Adding `--channel-id <id>` lets it post to any channel the
tester bot has access to — e.g. the new in-character journal
channel where Caldanai writes session entries between
playtests. One-line API extension; default behavior
(DB-resolved combat channel) unchanged.

### 2026-04-27 — `_finalize_combat` consolidation + time-flee loot prompt

Pre-consolidation, the loot-announce + `loot_expires` schedule
was inlined in `do_combat`'s SURVIVE/VENGEFUL escape branch and
ABSENT entirely from `Game.check_time`'s `flees_from_time` path
— a werewolf bolting at dawn with leather still in the pool got
no announce. Player report flagged the gap.

- **`Game._finalize_combat(outcome)`** — universal end-of-combat
  shutdown: records the outcome flag (read by `$loot` for
  flee-vs-death wording), schedules `loot_expires` if there's
  anything in the pool, runs `end_combat` + `set_spawn_timer`,
  returns the loot-announce string for callers to thread into
  their own narration.
- **`cancel_combat` is now a one-line wrapper** with
  `outcome="flee"`. `on_monster_death` keeps its death-specific
  work (corpse-scavenge sweep, `get_loot` rolls, message
  construction with the "nothing to loot" alt-text) but hands
  the universal shutdown to `_finalize_combat`.
- **`check_time`'s time-flee branch** now consumes
  `cancel_combat`'s return and appends to its message — same
  shape `do_combat`'s SURVIVE-flee branch already used. Werewolf
  / spirit dawn-flee with salvage in pool now surfaces the
  prompt.
- **`Game.kill_monster` deliberately bypasses `_finalize_combat`
  and clears loot** — admin kills aren't real combat and
  shouldn't manufacture armor. Docstring beefed up so future
  cleanup doesn't try to "consolidate" it back in.
- **Test-fixture fixes**: three `cancel_combat = AsyncMock()`
  stubs in `test_corpse_scavenge`, `test_game_do_combat_parity`,
  `test_hydra_monster` now use `AsyncMock(return_value="")`.
  Pre-fix, the MagicMock return silently corrupted
  `escape_narration += announce` — covered by no assertion
  but a real coverage hole.

New `TestCheckTimeFlee` class in `tests/test_game.py` pins both
"with-salvage-emits-prompt" and "empty-pool-stays-silent" cases
so the time-flee branch has regression coverage without needing
a live dawn-werewolf encounter.

### 2026-04-27 — Held-weapons Phase 1: bandit shortsword via ARMOR_LOADOUT

Bandits can now spawn carrying a shortsword in their hand's
`held` placement, surfacing in `$look`'s "Wearing" column
alongside worn armor. On hand-destruction the held weapon drops
via the same `SALVAGE_SURVIVAL_CHANCE` (2/3) path that worn
armor uses, with quality preserved from the spawn-time roll.

- **No code changes to `_apply_armor_loadout` or `get_salvage`**
  — both already iterate `placements` slot-agnostically. Adding
  the `("shortsword", 0.20, "held", (50, 95))` entry to
  `Bandit.ARMOR_LOADOUT["hand"]` was sufficient.
- **`bandit.loot["shortsword"]` removed** to avoid double-rolls
  (the death-loot path used to roll a fresh shortsword
  unconditionally; now it's a held-loadout drop only when the
  bandit was visibly carrying one).
- **Bow stays in `bandit.loot` for now** — Phase 2 boundary,
  ranged weapons need monster-uses-them work first.

7 new tests in `tests/test_monster_salvage.py`'s
`TestBanditHeldWeaponLoadout` covering the shape pin, both RNG
boundaries, the drop path, survival-roll filtering, the
loot-dict migration, and a regression pin against a future
held-shield-bonus leaking defense via
`effective_defense_for_part`.

### 2026-04-27 — Clean-kill corpse-scavenge

When a monster died via critical-part-kill (e.g. one-shot crit
on the neck), worn pieces on parts that were never destroyed in
combat silently vanished — punishing the cleanest, most
efficient kills. Now those pieces get one final survival roll at
a reduced rate.

- **`MonsterPlugin.CORPSE_SCAVENGE_CHANCE = 1/3`** — lower than
  `SALVAGE_SURVIVAL_CHANCE` (2/3), per the design memo: severing
  a part to liberate gear is more aggressive than scavenging the
  body that fell with it intact.
- **`MonsterPlugin.get_corpse_scavenge()`** walks every
  `Equippable` body part with non-empty `placements`, rolls
  `CORPSE_SCAVENGE_CHANCE` per item, returns surviving
  `(part, item)` pairs. Placements clear regardless of survival
  outcome (idempotency).
- **`Game.on_monster_death`** runs the sweep BEFORE the death-
  loot extends so narration ordering reads cleanly: scavenge
  lines first ("A patchwork bracer slips free of the bandit's
  left arm."), then the loot prompt. Surviving instances
  round-robin across `self.looters` — each piece goes to exactly
  one player, no duplication. Pragmatic v1; killer-takes-all is
  a natural future tightening once last-hit attribution lands.

11 new tests in `tests/test_corpse_scavenge.py` covering the
unit contract (empty body, all-success, all-fail, idempotency,
quality preservation, the 1/3 threshold, bare-monster fallback)
and the integration path (loot routing, narration shape,
no-looters edge case).

### 2026-04-27 — `$kill <monster> [<part>...]` argument grammar

`$kill werewolf` used to emit "No targetable part matching
'werewolf' found. Attacking randomly." — technically correct
(every token after `$kill` was treated as a body-part
identifier) but reads as a bug. Players naturally type the
monster's name to engage it.

- **`_strip_leading_monster_token`** peels an optional leading
  monster-name token off the argument string before
  `_parse_part_targets` runs. Match rule mirrors `$look`'s
  `_monster_matches_look_target`: case-insensitive equality
  against `monster.name` OR equality against any whitespace-
  separated word token of that name (`"hydra"` catches "hexed
  hydra"). Fuzzy / prefix matching is deliberately NOT applied
  — `find_plugin_classes("h")` would otherwise consume `$kill h`
  against a Hydra and silently lose the part shortcut to `head`.
- **First-token only** — `$kill arm.left werewolf` keeps today's
  behavior (the trailing `werewolf` becomes an unknown part
  token and silently drops).

15 new tests in `tests/test_kill_command_grammar.py` covering
the four memo cases plus the ambiguity pin and the `$kill h`
regression.

### 2026-04-27 — Post-flee loot UX: announce prompt + flee-aware $loot wording

Pre-Phase-2 the only loot was death-rolled, so a fled monster
genuinely left nothing behind. Mid-combat salvage broke that
assumption: a player could dismember an arm, the monster could
bolt, and `$loot` would silently work with corpse-flavored
strings. Player report flagged the missing announce prompt; the
"pokes around the corpse" wording was already in the backlog.

- **Flee-with-loot prompt**: when `do_combat`'s escape branch
  fires and the loot pool has anything in it, append the same
  `"There might be something to $loot..."` mention-prompt that
  death uses. Schedules `loot_expires` so the items don't
  silently vanish. Prompt appended to `escape_narration` so it
  renders AFTER the bandit-bolts line (the standalone
  `loot_hint` slot renders before escape, which is right for
  death but reads backwards for flee).
- **`$loot` wording branches on combat outcome** via a new
  `Game.last_combat_outcome` flag (`"death"` / `"flee"`):
  - Empty pool, post-flee: "sifts the dust where the runaway
    stood, but nothing useful was left behind." (was: "pokes
    around the corpse, finding nothing useful.")
  - Non-combatant trying $loot post-flee: "casts about for
    what the runaway left behind, but finds nothing within
    reach." (was: "attempts to loot the corpse, but cannot
    interact with it.")
  - Death-path strings unchanged.

### 2026-04-26 — Bandit / goblin armor loadouts; salvage from worn pieces

Bandits and goblins now spawn wearing a random subset of the
scrap set, those pieces defend the parts they cover, and on
dismemberment the dropped armor comes from what they were
wearing — not a generic per-monster table that rolls regardless.
`$look` surfaces the gear pre-fight so a drop feels earned.

- **`MonsterPlugin.ARMOR_LOADOUT`** — class attribute keyed like
  `SALVAGE_DROPS`; each entry is `(stem, chance, slot, quality)`
  and rolls per-part-instance at construction. Quadrupeds' four
  legs roll independently for natural pair/mismatch variance.
  Equipped items already feed `effective_defense_for_part` via
  `BodyPart.placements`, so defense applies for free.
- **Two-layer salvage**: `get_salvage(part)` rolls
  `SALVAGE_SURVIVAL_CHANCE` (default 2/3) on each worn item, the
  actual instance drops with its spawn-rolled quality preserved.
  Generic `SALVAGE_DROPS` still rolls for non-equipment harvest
  (leather, scale). Bracer end-to-end rate ≈ 30% × 2/3 = 20%.
- **`$look` body-parts table gains a `Worn` column** showing each
  part's pieces inline. Dispatched as a separate plain message
  after the embed (embeds wrap wide tables; plain messages
  inherit full channel width).
- **Crash fix — `loot_expires` mid-combat race**: `loot_expires`
  is scheduled by the previous combat's death and calls
  `self.loot.clear()`. If it fired between rounds of the next
  combat, the looter's bucket vanished but `self.looters` still
  held them, so `on_monster_death` raised `KeyError`. Loot
  bucket re-asserted via `setdefault` every round + defensively
  in `on_monster_death`.
- **Test-fragility fixes** picked up while shipping:
  `_player_with_inventory` now pins `quality=ORDINARY` (a 50%
  JUNK roll was floor-ing tier-1 dodge bonuses to 0); the
  combat-parity `_spawn` helper re-seeds `random` after
  construction so future spawn-time RNG additions don't shift
  the deterministic combat sequence.



Previously `tail_channel` could only fetch the last N messages
(capped at 100) or `--follow` from a starting point. There was no
way to scan a specific window in the past — answering "how did
the patch land overnight?" required the inspector to have been
running before the patch shipped.

- **`--since-time TIME`**: paginate backwards via Discord
  `before` snowflakes until we cover everything from this time
  forward. Accepts relative (``9h``, ``30m``, ``2d``) or ISO
  8601 timestamps; naive ISO assumed UTC.
- **`--until-time TIME`**: optional upper bound, same format.
  Best for absolute ranges.
- **`--duration LENGTH`**: alternative upper bound — relative-
  format only — natural for relative windows
  (``--since-time 9h --duration 1h`` for the hour between 9h
  and 8h ago). Mutually exclusive with `--until-time`.
- Pagination capped at 50 batches × 100 messages = 5000;
  warning to stderr if hit so the operator knows the window
  was truncated rather than the channel quietly being empty.
- `DiscordRestClient.get_messages` extended with a `before`
  parameter so other tools can paginate backwards too.

19 new tests covering relative + ISO + edge-case parsing,
Discord epoch math, backfill pagination loop, and window
filtering.

### 2026-04-26 — Crafting system v1: leather chain (held for playtest)

The "monster materials → recipes → finished gear" loop. Bearowl
drops leather; players combine leather via skill-gated recipes to
produce a 6-piece leather armor set. Output quality emerges from
input quality + skill margin + variance. MVP scope is the leather
chain only; bone/scale/etc. ride later sets onto the same plumbing.

- **New ``$craft`` command group**:
  - ``$craft <item>``: attempt the craft. Gates in order — known? skill
    min? materials? — then rolls success against ``success_chance``,
    rolls quality on success, consumes materials (full on success,
    half on failure), grants skill XP either way.
  - ``$craft list``: enumerates recipes the player knows AND has
    materials for AND meets the skill minimum for, with current
    success % per row.
  - ``$craft info <item>``: shows materials, skill requirement,
    learned status (for ``requires_known`` recipes), and current
    success %.
- **New ``$learn`` command**: consume a recipe scroll from inventory,
  add the embedded recipe to ``player.known_recipes``. Already-known
  scrolls grant a small skill-XP refund (~10% of the recipe's
  ``min_skill``) instead of being wasted — duplicates are useful,
  not garbage.
- **``RecipePlugin`` base + discovery** at
  ``caldanai/lib/rpg/crafting/recipes/<set>/<stem>.py``. Plugin shape:
  ``output``, ``materials: Dict[str, int]``, ``skill``, ``min_skill``,
  ``requires_known``, ``xp_reward_success/failure``. Discovery walks
  the tree on first miss; warns loudly when a file's ``RecipePlugin``
  symbol resolves to the base class (the import-without-alias
  footgun).
- **Quality formula** in ``crafting/math.py`` (pure functions,
  seedable):
  - ``success_chance``: 0% below min skill, 50% at min, +10% per +25
    XP, capped at 95%.
  - ``roll_quality``: ``avg_input_rank + skill_bonus + variance``,
    clamped to the valid quality range. ``skill_bonus`` is +1 per 50
    XP above min, soft-capped at +2. Variance is ``randint(-1, 1)``
    most of the time, with a 1% jackpot/disaster of ±2.
- **``Stackable.from_plugin`` extended** to forward extra ``data``
  keys to the plugin ``__init__`` by name-introspection. Enables
  variant-bearing stackables like ``recipe_scroll`` (carries a
  per-instance ``recipe_name``) without a per-variant load path.
- **``recipe_scroll`` stackable**: weightless, stackable per-recipe.
  One file covers every recipe variant.
- **Latent fix** in ``Stackable.to_dict``: ``del d["_id"]`` →
  ``d.pop("_id", None)``. The prior delete was always operating
  on an absent key — exposed by the new scroll round-trip tests.
- **``Player.known_recipes: Set[str]``** — persisted as a sorted
  list, omitted from the saved doc when empty.
- **Bearowl + werewolf seed the leather pipeline** with parallel
  ``SALVAGE_DROPS`` (torso 0-3 leather, all legs 0-2 each;
  werewolf slightly leaner). Quality range ``(45, 60)`` skews
  ORDINARY-mode — well above the scrap-tier band. Bearowl bumped
  ``VENGEFUL → SURVIVE`` so it actually fights long enough to
  dismember (mirror-fix to the bandit bump from scrap salvage).
- **Leather armor set** (6 pieces, all under
  ``armor/leather/``): leather_cap (head), leather_bracer (forearms),
  leather_glove (gloves), leather_boot (feet), leather_greave (legs),
  leather_jerkin (torso). All ``def +1`` per piece except jerkin's
  ``def +2`` (it's the biggest). Per-piece costs scale with size:
  caps/gloves/boots/bracers cost 2 leather; greaves 4; jerkin 5.
- **Leather recipes** (6, all under ``recipes/leather/``): one per
  armor piece, all using ``leatherworking`` skill, ``min_skill = 0``
  (all basic / known by default), ``requires_known = False``.

77 new tests pinning the math (success/quality/jackpot paths),
plugin discovery, scroll round-trip + stacking, $craft success /
failure / refusal flows, $learn refund, and bearowl drop tables.

### 2026-04-26 — Salvage playtest fixes

Three issues surfaced in the first armored-bandit playtest:

- **Mid-combat salvage was wiped on monster flee.**
  ``Game.cancel_combat`` called ``self.loot.clear()`` —
  appropriate when the only loot was death-rolled (no death =
  no loot existed), but Phase 2's mid-combat salvage now
  populates ``self.loot`` before death. Cleared on flee. Removed
  the ``loot.clear()`` so players keep what they earned even when
  the monster bolts. ``loot_expires`` still cleans up uncollected
  items downstream.
- **"Nothing to loot" message lied when salvage existed.**
  ``Game.on_monster_death`` computed ``has_loot`` *after*
  ``end_combat()``, which clears ``self.looters`` — so the
  follow-up ``any(self.loot.get(p.user_id) for p in self.looters)``
  iterated an empty list and false-negatived the prompt. Switched
  to ``any(items for items in self.loot.values())`` which doesn't
  depend on the looters list.
- **Bandit aggression bumped VENGEFUL → SURVIVE.** VENGEFUL
  flees after one round; SURVIVE sticks until ~10% HP. Bandit
  fights are now long enough to drive parts to USELESS via
  damage instead of admin-destroy, which is the natural
  combat-driven path for the salvage loop.

### 2026-04-26 — Armor Phase 2: salvage-on-dismemberment + scrap set + subdir layout

The "destroying a body part yields a piece harvested from it"
gameplay loop. Pairs the existing destroyed-part-drops-gear hook
(items the part was *wearing* return on destruction) with a new
parallel hook (items the part itself *becomes*).

- **Scrap set** (11 pieces, all sub-`armor/scrap/`):
  ``rough_cap`` (head.worn), ``rag_hood`` (head.outer),
  ``scrap_collar`` (neck.accent), ``rough_jerkin`` (torso.worn),
  ``bandits_sash`` (torso.accent), ``patchwork_bracer``
  (arm.worn.lower), ``rough_rerebrace`` (arm.worn.upper),
  ``ratty_glove`` (hand.worn), ``rough_greave`` (leg.worn.upper),
  ``scrap_shin`` (leg.worn.lower), ``worn_boot`` (foot.worn).
  Mostly def +1 / hp +1 — small per-piece numbers,
  defense-leaning rather than dodge-aggregating so a full
  kit gives modest aggregate (sweep: bandit 68% → 74%, werewolf
  65% → 71%; bosses unchanged). No "unkillable god" outcome.
- **Salvage hook** on ``MonsterPlugin``: ``SALVAGE_DROPS`` dict
  (per-part-base-name → list of ``(item_name, drop_chance,
  quality_range)`` triples) + ``get_salvage(part_base_name)``
  helper. Drop chance and quality bias both roll independently;
  ``Qualities.from_scale`` already powers the latter.
- **Per-player loot accumulation**: ``Game.loot[user_id]`` now
  initializes when a player joins combat and *extends* through
  the fight (mid-combat salvage drops + end-of-combat creature
  loot all land in the same list), instead of being assigned
  once at ``on_monster_death``. Last-hit attribution per-part:
  the player whose resolve destroyed a part gets that part's
  salvage. Three players dogpiling one foot still drops one
  boot, to whoever's hit took it to USELESS.
- **``ResolutionResult.destroyed_parts``** new field — populated
  by the resolution helper when parts transition to USELESS, read
  by the salvage hook in ``Game._run_player_block``. Keeps
  resolution layer-pure (doesn't know about loot) while giving
  the Game layer everything it needs.
- **Bandit + goblin SALVAGE_DROPS** seeded with the scrap set.
  Ranges biased to JUNK-heavy with rare ORDINARY upticks
  (``(50, 95)`` randint, mapped through ``Qualities.from_scale``).
- **Set-organized armor subdirs**: ``Inventory.discover_items``
  walks ancestors to find the recognized type, ``Armor.from_plugin``
  falls through to a recursive subdir search after the flat
  import miss. Plugin stems remain globally unique. Existing
  flat pieces (cape, tee_shirt, mushroom_hat, etc.) untouched —
  they're not part of any thematic set yet.
- **Harness ``--armor`` flag** added (and ``--armor-quality``).
  Routes through ``Inventory.load_item`` so flat and subdir
  layouts both resolve. Lets balance sweeps verify "would a
  full scrap-kit player actually tip the curve?" answers
  (it doesn't — extremity defense doesn't fix the bottleneck
  on cyclops/dragon fights, AND it doesn't pile dodge enough
  to trivialize bandit fights, which is the design intent).

### 2026-04-26 — Armor rework Phase 1: per-part defense floor + small-numbers re-tune

Phase C localized defense to the part each armor piece is worn on,
which made hidden penalty scaling sharp: a masterwork mushroom hat
(base ``-2 def`` × MW 2.0 = ``-4``) crashed Serena's head defense
from 4 to 0 — a 100% nerf on one part. The local-defense model is
right; the per-piece magnitudes were tuned for B4 aggregation and
need to be smaller now that they bite locally.

- **Per-part defense floor** in ``effective_defense_for_part``: a
  part's effective defense never drops below half its no-armor
  natural baseline (``(base + intrinsic + offset − depth × coef)
  // 2``). Skull stays a skull regardless of what fragile cap is
  strapped on top. Floor scales with depth — head's floor is
  smaller than torso's, arm.lower's smaller than arm.upper's.
- **Re-tuned the existing 5 armor pieces** to small per-piece
  numbers so MW scaling can't crater anymore:
  - bandanna: ``dodge +2 / hp -1`` → ``dodge +1`` (drop the hp penalty)
  - mushroom_hat: ``dodge +2 / def -2`` → ``dodge +1 / def -1``
  - high-collared_cape: ``dodge -1 / def -1 / hp +5`` → ``dodge -1 / def -1 / hp +3``
  - tee_shirt and cape unchanged (already small).
- 4 new tests in ``test_effective_stats.py`` pin the floor
  behavior: cratering armor floors at half-natural, depth-aware
  floor varies by part, positive armor lifts above floor without
  capping, mixed positive+negative armor on same part combines
  then floors.

### 2026-04-26 — Action selection: shuffle parts before walking the budget

`_select_actions_within_budget` walked parts in body-tree depth-
first order (torso → neck → head → eyes → arms → legs) and picked
one action per part until ACTION_BUDGET ran out. Default budget
is 2, so torso (chestbutt) and head (bite/headbutt) burned the
budget every round and arms/legs were never reached. Live result:
humanoid monsters didn't punch, grab, kick, or stomp — ever.

The pool now shuffles uniformly before the walk. Bandit 200-
trial sample went from `100% chestbutt + 65/35 bite/headbutt` to
balanced across `punch / kick / chestbutt / bite / stomp / grab /
headbutt`. Hydra's heads pool is unaffected — hydra overrides
``attack_random`` and its head order is symmetric anyway.

### 2026-04-26 — Inline salvage narration in injury feedback

When a destroyed body part dropped a salvage piece, players had
no signal mid-combat — items materialized silently in
``Game.loot``, only revealed at post-combat ``$loot``. Each rolled
salvage now appends a line to the destroying player's
``injury_feedback_lines``: "*A patchwork bracer slips free of the
bandit's left arm.*" Lands inline with the destruction
announcement, so the salvage cause-and-effect reads in real time
instead of being a post-mortem surprise.

### 2026-04-26 — `$equip` refuses destroyed body parts

``$equip wand@r`` succeeded when the right arm was destroyed
(cascading ``hand.right`` to USELESS), silently riding the
placement on a part the player no longer had. ``Player.equip``
now gates each of its three cases on a new ``_placement_is_blocked``
helper that reads ``BodyPart.is_destroyed`` (which already cascades
through ancestors). Specific-slot equip refuses with a clear
message; auto-equip skips destroyed placements and lands on the
surviving counterpart; multi-slot two-handers refuse if any
required arm is destroyed.

### 2026-04-26 — `post_patch_notes` auto-prepends the UTC timestamp header

Operators were copy-pasting / hand-typing the
``**Patch notes — YYYY-MM-DD HH:MM UTC**`` header into every
scratch file. ``post_patch_notes`` now prepends the current-UTC
header at read time, so the scratch file is body-only. A legacy
header with a stale timestamp (left over from prior workflow) is
stripped first so the output never carries two timestamps.

### 2026-04-26 — Resistance hint flavor across the bestiary

Damage-type traits (``self.traits[DamageTypes.X] = 0.5``) shifted
the multiplier column in the combat table but offered no flavor
cue — players had to read the raw numbers to learn a vampire
shrugs off slashing or a golem laughs at piercing. Skeleton and
spirit had this; the rest didn't. Surfacing the same matchup
information through inline ``HIT_NARRATIONS`` flavor (the
existing skeleton pattern) keeps the combat table's column count
unchanged while making resistances learnable from narration.

- ``HIT_NARRATIONS`` dicts added to: vampire, werewolf, golem,
  dragon, pixie, bandit, goblin, giant, bearowl, toad, sheep,
  minotaur, cyclops, hydra. Spirit gained a FIRE entry to fill
  the one trait gap not already covered by ``_on_attacked``
  intangibility callouts or the ``Undead`` mixin's LIGHT/DARK
  defaults.
- All flavor lines avoid body-part-specific anatomy (no "ribs",
  "throat" etc.) so the same line reads correctly whether the
  player was aiming for head, leg, torso, or anywhere else.
- The ``HIT_NARRATIONS`` MRO-merge in ``Creature.get_hit_narration``
  already handles classification mixin defaults stacking with
  per-monster overrides, so no engine changes were needed.

### 2026-04-26 — Combat tables: ``ansi`` fence + per-row outcome dots

Legacy ``diff`` fence forced whole-line color via the ``+``/``-``
line prefix; the ``ansi`` fence lets us color the trailing
HIT/MISS/CRIT/FUMBLE word in the check column for desktop, and
replace the prefix glyph with an emoji dot for the mobile / ANSI-
stripped channel — both signals in lockstep.

- ``AttackSequence.to_markdown`` and ``AttackResult.to_markdown``
  emit ``\`\`\`ansi`` blocks instead of ``\`\`\`diff``.
- Per-row prefix swapped from ``+``/``-``/``!`` to dot emoji:
  🟢 hit, 🔴 fumble, 🟡 crit, ⚫ miss. Saturated red for the rare
  natural-1 fumble, gone-dark dot for the routine miss. Mirrors
  the ``INJURY_LEVEL_DISPLAY`` palette in ``helpers/enums.py``.
- New ``caldanai.lib.rpg.helpers.ansi`` module — full Solarized-Dark
  palette, intensity modifiers (``NORMAL``/``BOLD``/``DIM``/
  ``UNDERLINE``), and a single ``wrap(text, color, *,
  intensity=NORMAL)`` helper. The duplicated ``_ansi_wrap`` in
  ``cogs/rpg_info_commands.py`` collapses into the shared module.
- ANSI bytes are zero-width in Discord's renderer, so column
  alignment is unchanged. Width math runs against the plain
  un-coloured string; the outcome word is replaced post-``ljust``.
- Extra-text continuation lines (chill drains, vampire feeds, etc.)
  drop the ``!`` marker glyph and render as plain indented
  continuation under the row they belong to.

### 2026-04-26 — Combat round sectioning + cyclops/doppy/spirit/werewolf land before retaliation

`Game.do_combat` was string-concatenating round output in execution
order, which forced reactive-flavor (``on_combat_round``) to land
*after* the monster's retaliation attack table. Live cyclops
playtest surfaced the worst case: "*The cyclops bellows in blinding
agony, lashes out wildly*" appearing under the wild-swing table it
was supposed to introduce. Same shape lurked in doppelganger
imitation, spirit fade, werewolf desperation — all narration that
explains the upcoming attack.

- New `RoundOutput` dataclass (`caldanai/lib/rpg/combat/block.py`)
  with named slots: player blocks, injury feedback, total-damage
  row, death narration, loot hint, **pre-retaliation narration**,
  retaliation table, **post-retaliation narration**, escape. A
  `render()` method composes them into the final Discord message
  in fixed slot order — the structural fix for the cyclops bug.
- New `MonsterPlugin.on_pre_retaliation(damage_by_player)` hook;
  cyclops, doppelganger, spirit, werewolf migrated to it. Hydra
  stays on `on_combat_round` (head regrowth is post-retaliation
  state mutation, narration of which belongs *below* the attack
  table by design).
- `Game._run_player_block` now returns the populated
  `CombatBlock` (the block was being constructed and discarded
  before — `_ = CombatBlock(...)` with a "no downstream consumer
  yet" comment). Callers derive `damage`/`resolution` from
  `block.results`.
- Legacy `_do_combat_legacy` path untouched — still callable for
  one-line regression bisect during playtest.

### 2026-04-25 — ``$look`` word-token fallback for variant-named creatures

Live playtest caught that ``$look hydra`` / ``$look hexed``
against a spawned ``hexed hydra`` both silently returned "Nothing
to see here" — only the literal ``$look hexed hydra`` matched.
``RpgInfoCommands.look`` was doing exact
``target.lower() == game.monster.name.lower()`` with no fuzzy
fallback. Same UX gap surfaces on every variant-named species
(``flying math teacher``, ``swamp hydra``, etc.).

- ``RpgInfoCommands._monster_matches_look_target`` accepts the
  full name OR any whitespace-separated token from the name.
  ``hexed hydra`` → matches ``hexed hydra``, ``hexed``, ``hydra``.
  Partials like ``hex`` still fail (those want the bigger
  ``find_plugin_classes`` resolver shipped for ``$spawn``).
- Tactical patch, not the full resolver — ``$look`` only ever
  inspects ``game.monster`` (singular) so disambiguation isn't
  needed today. When multi-monster lands, ``$look`` should
  route through ``find_plugin_classes``.

13 regression tests in ``tests/test_look_target_match.py``
(exact / token / non-match including empty target and partial-
substring rejection).

### 2026-04-25 — Multi-target footer: ``Victim: untouched`` for untargeted-or-missed victims

The per-victim Total breakout previously emitted
``Victim: 0 raw - 0 absorbed → 0 damage`` for victims aimed at
but missed entirely — read as noise during the live hydra
playtest (e.g. when the hydra spat at one player and missed
everyone else, the footer still listed the unhit victims with
zero arithmetic).

Collapsed to ``Victim: untouched`` for the all-missed case so
the targeting info stays visible (per-row table still shows the
intended target part) without the noisy zero-arithmetic breakdown.
Hits still render the full ``raw - absorbed → damage`` breakdown.

``tools/render_combat_table`` gains a ``multi-target-untouched``
scenario so the layout regression is visible in the all-scenarios
sweep.

### 2026-04-25 — Haunt flavor: drop double-article on monster targets

Two ``$haunt`` non-Player templates double-applied the definite
article: each line interpolated ``'the '`` inline before a
``@2np``/``@2Np`` token that ALREADY prepends the article for
article-using creatures, rendering ``"the the hydra's ears"`` /
``"The the hydra's breath"`` (caught live by Caels mid-playtest).

Removed the inline ternary; the parser's noun-mode possessive
handles the article correctly. Sentence-start template upgraded
to ``@2Np`` so the implicit-capitalize carries through.

### 2026-04-25 — Stat block: bandage marker baseline switches to full-health emergent

Live test caught a false-positive on the previous comparison
(``emergent < self.defense`` / ``self.dodge``): a freshly-spawned
hydra rendered ``Dodge: 7 🩹`` with zero injuries because
``get_dodge`` bakes ``size_mod`` (HUGE 0.5, COLOSSAL 0.25, etc.)
into the emergent value — emergent is below intrinsic *by design*
for any non-Medium creature.

- New ``Creature._healthy_aggregate(getter)`` helper snapshots
  ``part.health`` for every body part, restores ``health_max``
  for the duration of ``getter``, and restores after. Try/finally
  so an exception in ``getter`` doesn't leave the creature in a
  fake-healthy state. No-op for body-less creatures.
- ``get_embed`` compares ``emergent_def`` / ``emergent_dodge``
  against ``self._healthy_aggregate(self.get_*)`` instead of the
  intrinsic ``self.*``. Marker now fires iff injury is *actually*
  reducing the displayed stat.

### 2026-04-25 — Stat block: bandage marker on injury-reduced Defense / Dodge

Phase C's localized stat aggregation has been visibly working
since the resolver shipped, but the embed stat block surfaced
falling Defense / Dodge as bare numbers with no annotation —
players read a mid-fight drop as a UI bug rather than the
intended "your body damage is reducing this stat" signal. Per
the 2026-04-24 playtest finding: "worth mentioning in player-
facing docs so players understand why their defense drops during
a fight (it'll look like a bug otherwise)."

- ``Creature.get_embed`` appends a 🩹 (bandage, U+1FA79) to the
  Defense / Dodge field values when the emergent stat falls
  below the creature's intrinsic base. Marker comparison is
  ``get_defense() < self.defense`` (and the dodge equivalent),
  which catches injury-reduced stats without lighting up
  armor-boosted stats.
- ``\U0001fa79`` escape used in source rather than a literal
  emoji so the Edit-pipeline doesn't surrogate-pair-mangle the
  codepoint (caught by the test the first time around).

Four regression tests: healthy creature has no marker on
Defense or Dodge; destroyed torso marks Defense; destroyed leg
marks Dodge.

### 2026-04-25 — Per-part dodge: absurdity ceiling on multiplicative inflation

``effective_dodge_for_part`` stacked size_ratio (up to 2.0) ×
exposure_tax (up to 2.0) multiplicatively, allowing the
multiplicative product alone to reach 4× base. The 2026-04-24
playtest observed dodge 32 against base 5 on a Tiny toadstool's
neck (6.4× base after additive depth/offset) — rip-and-tear
unplayable for that target even on a nat-20 from a maxed
character.

- ``DODGE_CAP_COEF`` constant (default 2.0) clamps the
  multiplicative product at ``base × DODGE_CAP_COEF``. Additive
  ``depth × DEPTH_COEFFICIENT`` and ``dodge_offset`` still apply
  on top, preserving per-part ordering for the depth-walk
  resolver (``test_big_vs_small_stall_rolls_up`` regressed
  briefly under a final-value cap; the multiplicative-only cap
  passes).
- Tunable from one place — alongside ``EXPOSURE_TAX_COEF`` and
  ``SIZE_RATIO_MAX`` — for future balance sweeps.

Two regression tests: cap saturates Big-vs-Tiny + zero-exposure
to 2× base; deeper part still ends above shallower part when
both saturate the cap.

### 2026-04-25 — Doppelganger pain summary: per-level grouping replaces per-part chart

The doppelganger emitted ONE pain-cry line per inherited injured
body part — N injured parts produced N lines, with left+right
pairs rendering identical text twice. Read like a doctor's chart
("Caldanai Playtester flexes his arm and winces..." × 4).

Per-level grouping collapses the noise: every non-NONE injury
level present produces exactly one line, listing every part at
that level via an Oxford-comma joiner ("his head, left eye, right
eye, left arm, and left hand now ruined and useless"). One beat
per severity tier, descending intensity (USELESS → MINOR).

- ``_PAIN_SUMMARIES_BY_LEVEL`` replaces the
  ``(base_part, InjuryLevels) → str`` ``_PAIN_CRIES`` table.
  4 level pools, each with 2-3 templates.
- Templates use a verb-on-actor / parts-as-prepositional-object
  structure ("@1 staggers as wounds tear open across @1a {parts}.")
  so the ``{parts}`` substitution doesn't trip subject-verb
  agreement regardless of part count.
- ``Doppelganger._pain_summary_lines`` walks ``self.body_parts``,
  groups by level, picks templates, renders. ``_oxford_join``
  sibling helper matches the gear-drop voice for consistency.
- ``_get_pain_cry`` removed (the per-part lookup helper has no
  consumer post-refactor).

7 existing per-part regression tests rewritten as per-level
tests covering: no-injury → no extra lines, single-injury → one
summary line, same-level multi-part → ONE line listing all,
multi-level → one line per level in descending order, NONE-
level → no summary, every level has at least one template
with the ``{parts}`` placeholder.

### 2026-04-25 — Destroyed-part gear drop now narrates per node

Stage 2a (commit ``3c573e7``) silently moved gear from a destroyed
part's placements back to the inventory pool. Players had no
in-fiction signal that their sword had unequipped — they'd swing
empty-handed next round and have to ``$gear`` to find out.

- ``BodyPart.gear_drop_flavor(items, creature)`` on the body-part
  base class — default voice: ``"@1A X (and Y) slip(s) free from
  @1a now-useless <part>."`` Singular/plural verb agreement,
  Oxford comma, empty-list returns empty string. Subclasses can
  override per-part if they want a unique voice (a wing's
  collapse beat differs from an arm).
- ``Player._drop_gear_on_destroyed_part`` returns the dropped-
  item list (was ``None``) AND now operates on the part's OWN
  placements — the Phase D subtree-cascade is handled by the
  ``apply_damage`` loop iterating every newly-useless part.
  Cascaded descendants report ``get_injury_level() == USELESS``
  via the ``ancestor.health <= 0`` check, so each node narrates
  its own dropped items: a wand held by the hand under a
  destroyed arm produces ``"…now-useless left hand."`` (NOT
  conflated under the arm's flavor).
- ``Player.apply_damage`` collects the per-part flavor lines and
  threads them into the return string before the death/revive
  tail — so the equipment beat lands while the player is still
  alive in the narrative.

Existing 13 stage-2a regression tests stay green. 3 new tests
cover the flavor format, cascade attribution (wand-on-hand under
destroyed arm renders against ``"left hand"``), and the empty-
placements no-flavor case.

### 2026-04-25 — Bandit escape flavor: stop promising theft

``"@1dc runs off, taking whatever @1s can grab."`` lied — bandits
don't currently steal on hit (only via the hug path), so the
flavor advertised loot the player would not find on their
inventory. Replaced with ``"@1dc spits a curse and bolts for the
treeline."`` until the steal-on-hit hook lands and the dramatic
flee can be gated on ``stole_anything``.

### 2026-04-24 — Combat output: per-row Def column + unified Total breakdown + attack-header caps fix

Three combat-output cleanups landing together since they share a
file and a playtest-finding parent:

- **Per-row ``Def`` column reintroduced** between Multiplier and
  Final. Phase C localized defense per-part, so each source row
  passes through a different absorber and warrants its own column.
  Hits show the absorbed amount (``-2``, ``-0`` for no absorption);
  misses show ``-``. Pre-Phase-C it had been removed because
  defense was player-wide; post-Phase-C the column belongs.
- **Total footer always shows the breakdown shape**
  (``Total: N raw - K absorbed → M damage``) regardless of whether
  ``K == 0``. Pre-fix, the same resolver rendered different
  summary rows on different monsters (skeleton vs werewolf in the
  2026-04-24 playtest), reading as a UI bug. Pairs with the per-
  row Def column so the bottom-line math mirrors the per-source
  story. Multi-target per-victim rows unify on the same shape.
- **Attack header preserves internal capitals** (``_capitalize_first``
  instead of ``str.capitalize``). The doppelganger imitates a
  player and renders ``**{attacker} attacks {target}:**`` with
  ``self.name = "Caldanai Playtester"`` — pre-fix the ``capitalize``
  call lowercased the ``P`` to produce ``**Caldanai playtester
  attacks Caldanai Playtester:**`` (verified live during 2026-04-24
  playtest). Companion to the parser-level fix from earlier today
  — same root cause (``str.capitalize`` lowercasing the tail), same
  helper.

New tool ``tools/render_combat_table`` covers all five combat-table
shapes (default / auto-hit / miss / no-absorption / multi-target)
in one render pass — bypasses the bot, replaces inline ``python -c``
when a layout edit needs visual verification.

### 2026-04-24 — ``tools.render_flavor`` gains ``--template`` mode

Arbitrary-template render mode for parser regressions and one-shot
proofing — bypasses the monster / part registries. Replaces the
``python -c`` reach when checking a single template against
synthetic actors.

- ``--template "<text>"`` renders verbatim against a synthetic
  actor (player-shape by default — ``uses_article=False``).
- ``--article`` flips @1 to monster-shape ("the bandit").
- ``--witness-name <name>`` (with optional ``--witness-article``)
  attaches a @2 actor for escape / flee / witness-bearing
  templates.
- ``--json`` shapes the same emit for scripting use.

### 2026-04-24 — Skeleton: ``Something animates @1d``

Bare ``@1`` token rendered "Something animates skeleton" — missing
article. ``@1d`` produces "the skeleton" via the standard
article-form pipeline.

### 2026-04-24 — Parser ``@Nc`` / implicit-capitalize preserves internal caps

``str.capitalize`` lowercases every character after the first, so
multi-word names rendered with the implicit-capitalize flag (any
uppercase form letter, e.g. ``@1Np`` at sentence start) lost their
internal capitals: ``"Caldanai Playtester"`` → ``"Caldanai
playtester's"``. Same bug bit doppelgangers post-imitation (their
``self.name`` carries the imitated player's casing) and any
Mc-/Mac-/O'-style monster name. Damage-flavor was the most visible
symptom because healing-flavor tokens didn't trigger the casing op.

- New ``_capitalize_first`` helper: first character up, rest
  unchanged.
- ``_CASING_FORMS`` dict now stores callables (custom helper for
  ``c``, ``str.lower`` / ``str.title`` / ``str.upper`` for the
  rest) and dispatch is direct rather than via ``getattr``.
- Regression test ``test_capitalize_preserves_internal_caps``
  covers the multi-word, McDonald, and ``@1Np`` damage-flavor
  cases.

### 2026-04-24 — Escape / flee flavor: ``@2`` witness wired through

Companion fix to the arrival ``@2`` witness landing in ``f3c7deb``.
The escape / flee parse paths still passed only the monster, so
templates like the pixie's "blows a kiss at @2 that smells faintly
of petrichor" silently fell back to ``@1`` — rendering "blows a
kiss at pixie".

- ``Game._pick_arrival_witness`` → ``Game._pick_witness``: name
  no longer pins it to the arrival path.
- New ``Game._build_witness_args`` helper centralizes the
  ``(monster,)`` / ``(monster, witness)`` tuple build that the
  arrival site was inlining. Both escape call sites in ``do_combat``
  now render through the same helper.

### 2026-04-24 — Bot-player DM routing: ``$inventory`` / ``$warmth`` / ``$games``

Allowlisted tester bots invoking DM-only commands silently
failed — Discord rejects bot→bot DMs (HTTP 50007), so the
dispatcher swallowed every reply. New ``RpgUtilities.dm_target``
falls back to the originating channel when the recipient is in
``PLAYER_BOT_ALLOWLIST``; real players keep getting DMs.

- ``RpgUtilities.is_bot_player`` — predicate for bare allowlist
  checks (also used to skip ``ctx.message.delete`` on bot-author
  invocations so the channel echo stays visible).
- ``RpgUtilities.dm_target(recipient, fallback_channel)`` — pure
  selector: channel for tester bots, recipient otherwise.
- Threaded through ``$games`` (``rpg_info_commands``),
  ``$inventory`` (``rpg_inventory_commands``), and ``$warmth``
  (``rpg_social_commands._send_dm`` plus the no-guild
  ``_ack_or_dm`` branch).

Tests: ``TestDmTarget`` covers regular member, non-allowlisted
bot, allowlisted bot, allowlist-without-fallback, and non-User
passthrough.

### 2026-04-24 — Phase C depth-walk resolver + Phase D segmented anatomy

Phase C and D ship together. Combat resolution walks from torso
down to the aimed body part, computing effective dodge / defense
per depth level. Arm and leg gain ``hand`` and ``foot`` child
nodes (Phase D); equipment placement vocabulary collapses to a
generic ``worn`` / ``held`` / ``outer`` / ``accent`` set.

**Operator note:** run the migration before this build touches
production, otherwise pre-D equipment silently drops at load:

    python -m tools.migrate_to_segmented_anatomy LIVE_DB_NAME          # dry-run
    python -m tools.migrate_to_segmented_anatomy LIVE_DB_NAME --write  # apply

Combat resolver:

- ``Creature._walk_to_aim`` walks root → aim. Each depth is a
  fresh dodge threshold. Same-size stalls miss cleanly; big-vs-
  small stalls roll up to the last-beaten part.
- ``effective_dodge_for_part`` composes base dodge, size-ratio
  and exposure scaling (the former ``get_targeted_dodge`` math),
  and an additive depth gradient.
- ``effective_defense_for_part`` localizes armor to the specific
  part it's worn on. Default unarmored parts absorb
  ``base - depth``; ``SOFT_PART`` spots (eye default) absorb
  ``int(base × 0.1)``; plated parts add intrinsic + local armor.
- Crit / fumble short-circuit to the aim point so the walk can't
  silently demote a crit to a miss by stalling mid-path.
- Removed ``get_targeted_dodge``, the ``target_dodge`` resolver
  parameter, and the ``PHASE_C_DEPTH_RESOLUTION`` flag. The
  depth-walk is the only combat-resolution path.

Segmented anatomy (Phase D):

- ``HandPlugin`` + ``FootPlugin`` as depth-2 children of arm and
  leg. Weapons land at ``hand.*.held``; boots at
  ``foot.*.worn``; gloves at ``hand.*.worn``; rings at
  ``hand.*.ring.1``.
- Placement keys collapse to the generic set
  ``worn`` / ``held`` / ``outer`` / ``accent`` with dotted sub-
  keys (``worn.upper``, ``ring.1``, ``earring.left``).
- ``EquipmentSlots`` enum unchanged; routing table lives at
  ``equipment_routing.SLOT_TO_PART_KEY``.
- ``tools/migrate_to_segmented_anatomy`` remaps existing player
  ``part_equipment`` docs via a single ``_KEY_REMAP`` table
  (old ``(part, key)`` → new). Dry-run default.

Doppelganger fixes:

- Keeps own ``health_max`` on imitation. Prior adoption of the
  target's max trivialized the fight (20HP player shift capped
  the doppy at 20HP).
- Early-return guard when re-imitating the same player; stops
  the per-round ``on_combat_round`` from re-running the full
  imitation ritual.
- ``uses_article = False`` so post-imitation ``@1np`` renders
  "Serena's" instead of "the serena's".
- Copies raw ``target.defense``, not the armor-aggregated
  ``.get_defense()``. Deep-copied body tree carries armor via
  localized placements; aggregated-copy would double-count.

Other fixes:

- ``$gear all`` no longer throws Discord error 50035. Phase D's
  27 placements + header exceeded the 25-field embed limit;
  ``get_equipment`` now groups placements per body part.
- Neck exposure raised from uniform 0.2 to a head-like
  0.6 / 0.7 / 0.8 / 0.9 (MELEE / REACH / THROWN / RANGED). The
  0.2 value produced 3.3× dodge multipliers on neck hits under
  the scaled-dodge formula — neck is not eye-tier geometry.
- Default ``defense_bonus`` flipped from ``SOFT_PART`` sentinel
  to ``0``. Eye opts into ``SOFT_PART`` explicitly. Old default
  clamped every unarmored part to zero absorption.
- Math teacher's "LORD OF PRIMES" narration no longer fires on
  zero-damage hits. Pre-defense prime roll that armor fully
  absorbed was emitting "/ 2 = 0" noise.

Stale-vocabulary sweep across ``mixins.py``, ``player.py``,
``utils.py``, ``rpg_inventory_commands.py``, and the ``neck`` /
``head`` plugins: docstrings and user-facing help text moved
from ``helm`` / ``cape`` / ``chest`` / ``amulet`` to the Phase D
generic-key vocabulary.

Tooling:

- ``playtest_combat_harness`` and ``playtest_monster_duel`` pick
  up a ``--depth-coef`` flag for tuning sweeps.
- Combat-harness player defaults updated to match live Player
  init (``def=6 dodge=6``) — the prior ``def=3 dodge=15``
  modeled a specific geared player, creating a B4-aggregation
  artifact that didn't correspond to fresh Players.
- Sweep captures land in a gitignored ``sweeps/`` directory.

Tests:

- New ``test_resolver_depth_walk`` + ``test_effective_stats``
  covering the walk and per-part helpers end-to-end.
- New ``test_tools_migrate_to_segmented_anatomy`` pinning the
  key-remap table, collision warnings, and all-None placements.
- Removed ``test_per_part_dodge`` (coverage folded into the new
  effective-stats + resolver tests).
- Fixed trivially-passing assertions in ``test_loadouts`` and
  ``test_destroyed_part_drops_gear`` that had survived Phase D
  renames unnoticed.

Suite: 3536 passing.

### 2026-04-22 — Gear loadouts: ``$loadout save / load / clear``

QoL follow-up to stage 2a. Players can snapshot their current
equipment under a named label (up to 3 per player) and restore
it with one command — dramatically less friction when gear
keeps dropping on limb-destroy hits.

- ``$loadout save <label>`` — snapshot current ``part_equipment``
  under ``<label>``. Labels store the player's original casing
  but look up case-insensitively (saving ``Combat`` after
  ``combat`` overwrites the same slot).
- ``$loadout load <label>`` — ``$stow all`` first, then
  re-equip every item in the saved set that's still in
  inventory. Missing items (sold, traded, lost) skip with a
  note; other items land.
- ``$loadout clear <label>`` — delete a slot.
- Bare ``$loadout`` lists every saved slot with item-count.

Capped at ``Player.MAX_LOADOUTS = 3`` — bump the constant if
we want more later, nothing else needs updating.

References stored are item IDs, not copies. The centralized
``Player._purge_item_refs`` is wired into ``take_item`` so any
"player no longer owns this" path (sell today, future trade /
admin-remove) automatically prunes the saved-loadout ref —
``$loadout load`` never tries to equip a ghost.

Aliases: ``$kit``, ``$gearset``, ``$outfit``.

20 new tests (19 base + 1 two-handed-purge) covering save,
overwrite, cap, load, skip-missing, clear, case-insensitivity,
purge-on-sell (single-slot + two-handed), and persistence
round-trip.

### 2026-04-22 — Equipment on parts, stage 2a: destroyed-part drop

Delivers the "limb-loss consequence" capstone promised when
stage 1 shipped. When a player body part transitions to
``InjuryLevels.USELESS``, every item at that part's placements
returns to the inventory pool — items stay in ``self.inventory``,
only the placement references clear, so the player hasn't LOST
anything, just lost the USE of it until the part heals.

``Player.apply_damage`` snapshots the set of already-useless
part names before dispatching to ``super().apply_damage()``, then
diffs post-damage state to identify newly-useless parts and
calls a new helper ``_drop_gear_on_destroyed_part`` on each.

Multi-placement handling is deliberate: ``_drop_gear_on_destroyed_part``
routes through ``Player.remove(item)`` which walks every
placement holding a given ``Item`` instance. So a two-handed
weapon occupying ``arm.left.held + arm.right.held`` comes off
BOTH arms when one arm is destroyed — a two-hander can't be
wielded with one good arm, and leaving the intact arm holding
a phantom reference would be a stuck state. Same shape covers
future multi-part items (cape-and-neck, manacles, magical sets).

Idempotent across repeated damage ticks: an already-USELESS part
does not re-drop its gear.

The drop is silent by design (no dispatched message) — the
existing combat narrative (``The left arm hangs limp and
useless.`` + injury lines) already surfaces the limb state to
the player. Adding a second "your bow slips from your grip"
line would pile onto already-busy combat tables.

Armor bonuses stop contributing naturally: ``get_armor_bonuses``
walks live placements, so a cleared placement means the item's
bonus no longer counts toward the player's aggregate stats.

13 new tests cover single-slot drop, two-handed dual-arm drop,
idempotency on already-useless parts, death-ordering, revive
stickiness, persistence round-trip, and multi-part items
spanning different body parts.

### 2026-04-22 — $roll honors NdN±C signed-constant modifier

Playtest follow-up to the 2026-04-21 dice-spec rework. The
``$roll`` command's ``check_dice`` helper was still doing a
naive ``dice.split("d")`` and reading ``"6-5"`` as the sides
count — any signed-modifier spec (``$roll 3d6+2``, ``$roll
2d8-1``) failed with "sides must be > 1" while other callers
(combat, ``Dice.quick_roll``) honored the signed form just fine.

Fix: ``check_dice`` now delegates to ``Dice.from_ndn`` for
parsing and returns ``(count, sides, modifier)``. ``$roll``
applies the modifier to the total, surfaces it in both verbose
(``rolls_sum + mod = total`` breakdown) and compact output
(``3d6-5 = 10`` form), and preserves the original error
messages for the common constraint-violation cases.

### 2026-04-22 — Equipment slots: sided split for left/right anatomy

Pre-rework, pair-slots (``ARMS``, ``FOREARMS``, ``GLOVES``,
``LEGS``, ``SHINS``, ``FEET``) were single enum bits that auto-
expanded to both sides via ``SLOT_PAIR``. That conflates "pair
item that spans both sides" with "sided item that fits either
side," which loses information for the upcoming limb-loss
consequences (a destroyed right arm should drop only right-side
gear, keeping the left glove on).

New shape: every left/right anatomical slot has its own bit,
with the old name preserved as a compound alias:
```
LEFT_ARM      RIGHT_ARM       ARMS      = LEFT_ARM      | RIGHT_ARM
LEFT_FOREARM  RIGHT_FOREARM   FOREARMS  = LEFT_FOREARM  | RIGHT_FOREARM
LEFT_GLOVE    RIGHT_GLOVE     GLOVES    = LEFT_GLOVE    | RIGHT_GLOVE
LEFT_LEG      RIGHT_LEG       LEGS      = LEFT_LEG      | RIGHT_LEG
LEFT_SHIN     RIGHT_SHIN      SHINS     = LEFT_SHIN     | RIGHT_SHIN
LEFT_FOOT     RIGHT_FOOT      FEET      = LEFT_FOOT     | RIGHT_FOOT
```

Single-sided items (``slots = LEFT_GLOVE``) occupy just that
side — players can mix-and-match a magic left glove with a
piercing right glove. Compound-alias items (``slots = GLOVES``)
fit either side, auto-equipping to the first empty placement.
Force-paired items declare ``GLOVES | MULTI_SLOT`` to fill
both.

``MULTI_SLOT`` stays available for items that must span
multiple placements but don't have a single-side equivalent
(old high-collared-cape's ``CAPE | NECK | MULTI_SLOT`` shape,
future manacles, magical sets that refuse to function alone).

``SLOT_PAIR`` kept as a mechanism but currently empty — every
previous entry has an equivalent via sided bits + compound
aliases. Table reserved for future content that truly needs a
single flag to force multi-placement without a sided variant.

Routing table (``SLOT_TO_PART_KEY``) gains per-side entries for
every new sided slot. ``LEFT_SIDE`` / ``RIGHT_SIDE`` aggregates
extended to include the new left/right bits so
``$equip bracer left`` narrows correctly to the left arm.

No items currently declare any of the reshuffled slots, so
zero content migration. 5 new routing tests cover the sided-
vs-compound-vs-MULTI_SLOT shapes.

### 2026-04-21 — Combat guard: two-hander detection on either arm

Defense-in-depth fix caught during playtest of the equipment-on-
parts migration. ``Player.get_attack_sources`` and
``get_disabled_attack_notes`` only checked ``arm.left.held`` for
the ``MULTI_SLOT`` flag. In a phantom state where a two-handed
weapon lived at ``arm.right.held`` only (with a one-hander at
``arm.left.held``), the two-handed-requires-both-arms
short-circuit was skipped — both weapons fired as separate
single-hand attacks, bypassing the balance restriction. Each
could even target a different body part independently.

``replace_equipment`` orphan-clear (2026-04-21) already makes
the phantom unreachable via the normal equip flow, but the
combat-level guard is worth hardening because a multi-slot item
could theoretically land at one arm only via any future path
(admin spawn tools, save-load edge cases). Now both arms are
checked; a multi-slot weapon on either is treated as
two-handed, and the stray one-hander at the other arm is
silently ignored.

### 2026-04-21 — Inventory-parity playtest follow-ups

Three fixes from the first playtest of the parity shipment:

**``$stow held`` broadens to every held item.** Previously a bare
key resolved to the first anatomy-order match, so ``$stow held``
only cleared one arm when dual-wielding. The expected read is
"stow everything in held" — broaden bare keys in stow mode,
leaving full ``arm.left.held`` form as the escape hatch when the
user wants exactly one side. ``$stow ring`` and other paired
keys follow the same rule. Two-handed weapons dedupe by
identity so ``remove()`` runs once.

**``$item held`` ambiguates when dual-wielding.** Same bare-key
matcher, opposite handling: ``$item`` can't meaningfully render
multiple embeds in one response, so a multi-placement match
surfaces the candidate list (``arm.left.held``,
``arm.right.held``) and the user picks one. Single-hand and
two-hander cases resolve cleanly (two-hander is one
``Item`` ref → single result).

**Two-handed replacement no longer leaves a phantom.** Bug from
playtest: equip a bow (two-handed → both arms) then ``$equip
rock@r`` — the rock landed at ``arm.right.held`` but the bow
stayed orphaned at ``arm.left.held``. ``replace_equipment`` now
walks every placement and clears any other reference to the
displaced item. Same fix covers future paired gear (gloves,
bracers) when swapped one-at-a-time.

### 2026-04-21 — Inventory-command parity (variadic + @-bind)

Uniform query grammar across ``$equip`` / ``$stow`` / ``$item``
/ ``$sell``. All four now accept the same ``<item>[@<hint>]``
shape; ``$equip`` and ``$stow`` go variadic for multi-item
invocations.

**Shared grammar:**
```
<raw>  ::= <item-query>[@<placement-hint>]
<hint> ::= l | left | r | right | _ | <part.key> | <key>
```

Examples::

    $equip wand.1 dagger                  # wand.1 auto → left, dagger auto → right
    $equip cape bandanna bow              # multi-equip across parts
    $equip dagger.best@r wand@l           # per-item placement
    $equip sword left                     # legacy 2-arg still works
    $stow helm wand                       # multi-stow
    $stow all                             # unequip everything
    $stow held@l                          # only the left hand
    $item head.helm                       # shows currently-worn helm
    $sell wand.junk rock 4-10             # multi-sell, per-query resolution

**Ambiguity surfaces to the player.** ``$equip wand`` with
multiple wands in inventory now returns a candidate list
(``Did you mean: wand.fine, wand.superior?``) instead of silently
grabbing the first match.

**Shared resolver layer.** New
:meth:`Player.resolve_item_query(query, mode)` returns an
:class:`ItemResolution` (items + ambiguity hints). Four modes:
``equip`` (item-first, single-select), ``stow`` (placement-first,
equipped-items-only, single-select), ``item`` (item-first with
placement fallback, single-select), ``sell`` (item-first,
excludes equipped, multi-select).
:meth:`RpgUtilities.resolve_items_or_notify` parses ``@`` bindings,
dispatches messages for no-match / ambiguity / bad-hint, and
returns ``(Item, placement)`` pairs.

31 new tests (20 resolver data layer, 11 messaging helper).

### 2026-04-21 — Equipment-on-parts UX polish

Three small follow-ups to the stage-1 equipment-on-parts
migration:

**Command-error hints.** ``Bot.on_command_error`` previously
passed silently on ``BadArgument`` and ``MissingRequiredArgument``
— a typo like ``$equip wand.1 left garbage`` produced nothing:
no channel response, no log. Now emits a ``DEBUG`` line for the
dev trail and sends a one-line hint to the invoker
(``I didn't quite catch that, <@!user>. Try $help <command>``).
Per-user-per-error-class cooldown of 10s suppresses channel
spam during a fast typo session. ``CommandOnCooldown`` and
``CommandNotFound`` stay silent by design.

**Item embed slot labels.** ``$item <name>`` embed's ``Slots``
field now shows the ``part.key`` placement form (``torso.cape``,
``arm.left.held``) matching ``$gear`` / ``$unequip`` rather than
the pre-migration enum names (``CAPE``, ``LEFT_HELD``). Multi-slot
items (two-handed weapons, paired gear) use ``+`` to signal
simultaneous occupation (``arm.left.held + arm.right.held``);
single-slot items with multiple compatible placements (a one-
hander that can go in either arm) use ``|`` (EITHER).

**``$stow`` / ``$unequip`` bare-key shortcuts.** New
``Player.find_equipped_by_placement`` resolves three input
shapes: full ``part.key`` (``head.helm``), bare key
(``helm`` / ``cape`` / ``held``), and key-with-dots
(``ear.left`` matches ``head.ear.left``). Bare-key lookup walks
anatomy in ``PLACEMENT_DISPLAY_ORDER`` so ambiguous cases
(``held`` with both arms occupied by different weapons) resolve
left-first. Two-handed weapons share their ``Item`` reference
across both arms, so ``$stow held`` on a two-hander naturally
clears both sides via the existing ``remove()`` walk.

33 new tests (9 error-hint, 8 embed-slots, 16 placement-resolver).

### 2026-04-21 — Per-game log context: fix for loaded games

Follow-up to the 2026-04-21 per-game log-context shipment.
``Game.from_dict`` constructs the game with ``channel=None``
(load-path pattern — channel is resolved afterward from the
bot's cache), which left ``GameClock._channel_id`` pinned to
``None``. Every tick then stamped ``channel_log_context(None)``
and the channel id never appeared on log lines for any game
loaded from the DB — which is every game, every restart.

Fresh games (``$game create``) worked because their constructor
receives a real ``channel``. Patched by updating the clock's
``_channel_id`` once ``game.channel`` resolves in
``Game.from_dict``.

### 2026-04-21 — Equipment on body parts (stage 1)

Collapses the parallel ``Player.equip_slots`` dict onto body-part
ownership. Items now live at
``part_equipment[part_name][key] = Item`` — a shield on the left
arm is a field on ``arm.left``, a hat on ``head``, a cape on the
``torso``. One addressing system replacing two.

**Migration is required before the new bot boots.** A one-shot
tool ``tools/migrate_equipment_to_parts.py`` translates existing
player documents. ``Player.from_dict`` raises a guided error on
any doc still carrying the legacy ``equip_slots`` field.

Deploy flow:
1. Shut down the bot.
2. ``python -m tools.migrate_equipment_to_parts`` (dry-run) —
   inspect the per-player diff.
3. Re-run with ``--write`` to apply.
4. Start the new bot; ``from_dict`` will confirm every doc is
   migrated.

**New body part: ``neck``.** Vestigial at landing — HP 8, non-
critical, no debuffs — to host amulet / jewelry items once they
ship and to anchor future werewolf throat-bite mechanics.

**Enum changes.** ``SHOULDERS`` and ``ABDOMEN`` deleted (no
items ever used them). Remaining slots map to ``(part, key)``
placements via ``equipment_routing.SLOT_TO_PART_KEY`` /
``SLOT_PAIR``. ``high-collared_cape`` dropped its dual
``NECK | CAPE | MULTI_SLOT`` declaration — now just ``CAPE``.

**$unequip accepts placement form.** ``$unequip arm.left.held``,
``$unequip head.helm``, ``$unequip torso.cape`` all work.
Falling back to item-name matching when the input isn't a
placement.

**$gear rendering.** Now walks ``PLACEMENT_DISPLAY_ORDER`` —
head-to-toe anatomy order. Two-handed weapons show at both
``arm.left.held`` and ``arm.right.held`` so the occupation is
visible.

Stage 2 (not in this commit): items on destroyed parts return
to inventory (temporary loss of access, not destruction) and
per-part armor-bonus routing.

30 new tests (15 routing, 15 migration tool) pin the contract.

### 2026-04-21 — Group subcommand dispatch: case-insensitive

Top-level ``Bot`` has ``case_insensitive=True`` but
``discord.ext.commands`` groups don't inherit — subcommands
dispatch case-sensitively unless each ``@group(...)`` sets its own
flag. ``$ambience Celestial on`` silently rejected even though
``$ambience celestial on`` worked. All nine cog groups (game,
warmth, weather, game-admin, roles, spawn, ambience, config,
config.channel) now pass ``case_insensitive=True``. New test
``test_group_case_insensitivity`` walks every cog's
``__cog_commands__`` and asserts the flag on every Group / nested
subgroup so future additions can't regress.

Free-text arg lookups audited (body parts via ``find_parts``,
monster names via ``MonsterPlugin.get``, ambience toggles via
``_parse_ambience_bool``, chat monster-name matching) — all
already lowercase both sides, no fix needed.

### 2026-04-21 — DB write pipeline: loop collapse + retry queue wired

**Loop collapse — worst-case write latency 2 min → 1 min.** The DB
write path used to be two independent ``@tasks.loop(minutes=1)``
loops: ``save_game_data`` enqueued dirty state, ``batch_write``
drained the queues. Phase offset between their ticks meant a
mutation could sit up to two minutes before reaching Mongo. The
``batch_write`` body moves into a new ``DB.drain_queues_once()``
static method; ``save_game_data`` calls it immediately after
``save_all_now()`` in the same tick, so a mutation now reaches
Mongo within one minute in the worst case.

**``DoubleBuffer.retry`` wired.** The retry sub-queue was an
unused stub — transient Mongo blips (``AutoReconnect``,
``ConnectionFailure``, ``NetworkTimeout``,
``ServerSelectionTimeoutError``) silently dropped the current
batch. ``drain_queues_once`` now catches those errors, requeues
the ops onto ``buf.retry``, and drains retry ops ahead of fresh
ops on the next cycle. ``BulkWriteError`` ops (schema violations,
duplicate keys) are still logged and dropped — retrying them
would loop forever.

Shutdown command, ``db_status`` console command, and ``DB.watchdog``
updated to the single-loop architecture. Three new regression
tests in ``TestDrainQueuesOnceRetry``.

### 2026-04-21 — Per-game log context + log-level sweep

**Per-game channel context in logs.** Log lines emitted inside a
specific game's scope now carry the channel id automatically for
post-hoc filtering / grouping in multi-game deployments. The
stdout rendering shifts from ``[caldanai.lib.rpg.time] - …`` to
``[caldanai.lib.rpg.time (824900326313164801)] - …`` when
context is set; Mongo log documents gain a ``channel_id``
field.

- New ``caldanai/log_context.py`` — ``channel_id_var``
  ``ContextVar`` + ``channel_log_context(channel_id)`` context
  manager. Absent context reads as ``None`` and the handler
  format falls back to the pre-refactor bracket shape, so
  non-game code paths (Dispatcher, main, db, top-level startup)
  are byte-identical.
- ``GameClock.__init__`` takes a ``channel_id`` kwarg; ``tick``
  wraps its body in the context manager so every routine the
  clock drives (monster hooks, weather daemon, ambience, combat
  pipeline composer) inherits the context without call-site
  changes.
- ``Bot.invoke`` override wraps each command invocation so cog
  command handlers emit under the ``ctx.channel.id`` context.
  Overriding ``invoke`` (rather than hooking
  ``before_invoke`` / ``after_invoke``) guarantees the ``with``
  block's reset fires on exit, including when the command
  raises.

**Log-level sweep.** Three downgrades, five upgrades, and one new
audit-trail path.

**INFO → DEBUG / WARNING (drop noise):**
- ``PluginManager.load`` per-item "Plugin loaded: X<Base>" lines
  were firing 26+ times at startup at INFO — downgraded to
  DEBUG. The total-count summary ("N plugins loaded") stays at
  INFO so operators still get a one-line confirmation without
  the per-plugin spam.
- ``Dispatcher.send`` oversized-message split log: INFO → DEBUG.
  An internal chunking step, not an operator-actionable event.
- ``Bot.on_command_error`` HTTP "Retry After N seconds" line:
  INFO → WARNING. Sits directly on an error branch; matching
  severity with its surrounding context.

**DEBUG → INFO (surface rare state transitions at live level):**
- ``RpgUtilities`` ``save_game_data`` loop start.
- ``DB.watchdog`` loop start.
- ``Game`` clock starting for game — pairs with the existing
  INFO "Game added for guild".
- ``Game.do_spawn`` admin / forced spawn (``$spawn monster X``).
  Wording normalized from "selectively" → "administratively"
  (player-facing ``$spawn monster`` IS an admin action — the
  word describes the path, not the mechanic).
- ``Game.do_ambience`` removing local ambience loop at game
  teardown.

**Admin-command audit trail.** ``Bot.on_command`` now emits an
INFO line for every invocation from a cog with ``admin`` in its
name (``BotAdminCommands`` + ``RpgAdminCommands``). Format:
``"Admin command: {author} ({user_id}) ran `{message.content}`"``.
Captures who did what with elevated permissions without
logging the noisier player-level commands.

10 regression tests in ``tests/test_log_context.py`` covering
the contextvar semantics (default, set, reset, nested,
exception-safe, explicit-None scoping) and the ``MongoHandler``
surfacing behavior (stdout bracket, Mongo entry field, legacy
shape when unset).

### 2026-04-21 — Q.6 latent-bug sweep: defense-param drop, summarize-damage fix, per-victim AOE footer

Three Q.6.2/Q.6.3 review-flagged latent bugs closed in one pass.

**`compute_body_hp_damage(defense=)` parameter removed.** The arg
was accepted for call-site compatibility but silently ignored
since Q.6.2 (defense is applied per-hit inside
``resolve_attack``, so ``result.damage`` is already post-defense).
A silently-ignored parameter is a footgun — future callers pass
a number, write a test that passes without the value mattering,
never realize it did nothing. Signature now raises ``TypeError``
if ``defense=`` is passed. Three production callers updated to
drop the ``victim.get_defense()`` call that was feeding it.

**`Creature.summarize_damage` double-subtract fixed.** The
pipeline-stage summary helper used ``max(num_hits,
body_damage_total - defense)`` — but ``body_damage_total`` is
already the sum of post-defense ``result.damage``, so the
subtract was a second bite at defense. Now routes through
``compute_body_hp_damage`` so this stage's summary matches
exactly what the other body-HP callers
(``MonsterPlugin.attack_random``, ``_run_player_block``,
``Hydra.attack_random``) actually apply. Latent until the Phase-7+
round composer wires this stage in; fixed now to prevent the
divergence from biting downstream.

**Multi-target / AOE footer: per-victim totals.** A multi-target
``AttackSequence`` (dragon breath, hydra AOE) used to render a
single ``Total: N damage`` across all victims, which mislead
readers into thinking everyone took ``N`` (Celowin's LIVE-
playtest observation on dragon breath). The footer now breaks
out one line per victim:

```
Caels: 19 raw - 3 absorbed → 16 damage  🔥
Serena: 15 raw - 3 absorbed → 12 damage  🔥
```

Grouping keys off ``result.victim`` when the pipeline populates
it; falls back to ``source.label`` for bespoke AOE paths
(dragon breath already uses the victim's display name as the
label). Dragon breath now also sets ``result.victim`` and marks
the sequence ``multi_target=True`` when hitting more than one
victim, so the shared renderer handles it uniformly.

Retired backlog memo: ``project_q6_latent_bugs.md``.

### 2026-04-21 — Dice spec: signed-constant modifier (``"NdM+C"`` / ``"NdM-C"``)

``Dice.from_ndn`` now parses an optional signed constant after
the ``NdM`` portion. ``"2d6"`` keeps working as before; ``"4d4+6"``
/ ``"3d10-2"`` add a flat bump/penalty to the rolled total.
Whitespace around the sign is tolerated (``"2d6 + 2"`` fine),
legacy forms like ``"d20"`` still default the count to 1.

- ``Dice.value`` now equals ``sum(rolls) + modifier`` — downstream
  consumers (``DamageRoll``, ``Ability``, ``quick_roll``) see the
  correct total without a separate modifier-tracking pipe.
- ``Dice.rolls`` stays raw per-die so a renderer can still show
  ``(r1 + r2) + C`` rather than a pre-combined single number.
- ``DamageRoll.__str__`` surfaces the dice modifier as its own
  term between the parenthesized roll sum and the skill / weapon
  bonuses: ``"2d6+2"`` rolled (6, 5) → ``"(6 + 5) + 2 = 13"``.
- Bare ``"2d6"`` with no bonuses renders as ``"(6 + 5)"`` — no
  ``+0`` noise.
- Weapons' runtime ``weapon_bonus`` pipe stays as-is (quality
  tiers produce per-instance dynamic bonuses that aren't cleanly
  expressible as a static constant in the spec). The two pipes
  coexist — a ``"1d6+2"`` weapon with a quality bonus of 3 would
  render as ``"(4) + 2 + 3 = 9"``.

**Dragon defense** migrated to the new syntax: ``defense="4d4+6"``
replaces the earlier ``defense="4d4"`` + inline ``self.defense
+= 6`` workaround.

22 regression tests in ``tests/test_dice_modifier.py``:
parser variants (with / without modifier, negative, whitespace,
implicit count, garbage), ``Dice.value`` / ``Dice.__str__`` /
``Dice.get_ndn`` round-tripping, and ``DamageRoll.__str__``
emitting the ``(rolls) + modifier + ... = total`` shape in all
four combinations (modifier only, modifier + weapon bonus, no
bonuses, negative modifier).

### 2026-04-21 — Fuzzy matching: part shorthand substring fallback + monster-name aliases

Two resolver widenings for common player shorthand that
previously failed silently.

**Part shorthand** — ``Creature.find_parts`` now runs a
per-segment substring fallback when strict per-segment prefix
matching returns nothing. ``$attack l.l`` on a werewolf (parts
``foreleg.left`` / ``hindleg.left``) now resolves to both legs
instead of routing to a random part. The prefix-wins invariant
holds: creatures with a literal ``leg`` part still resolve
``leg`` → literal leg, never the substring-of-foreleg branch.
Cross-segment bleed is still blocked (``h`` never matches
``arm.right``).

Surfaced in LIVE playtest 2026-04-21 (three ``$attack l.l``
attempts, random routing each time).

**Monster name aliases + fuzzy spawn** —

- ``MonsterPlugin.ALIASES`` class attr: plugins declare
  in-fiction display names that diverge from the filename stem.
  ``MathTeacher.ALIASES = ["flying math teacher"]``; ``Hydra``
  auto-populates from ``VARIANTS`` so ``"swamp hydra"`` /
  ``"hexed hydra"`` / ``"elemental hydra"`` all resolve.
- ``MonsterPlugin._PLUGIN_REGISTRY`` widens to include aliases
  alongside the filename stem — ``get_plugin_class("swamp
  hydra")`` now hands back the Hydra class directly, no changes
  needed in callers.
- ``MonsterPlugin.find_plugin_classes(query)`` — new fuzzy
  helper, two-pass (unordered token prefix, then substring
  fallback) with plugin-class deduping. Whitespace and dots
  tokenize identically (``"math.teacher"`` and ``"math
  teacher"`` both resolve).
- ``Game.do_spawn`` uses the fuzzy helper as a fallback when
  exact lookup misses: 1 match → spawn; >1 match → "Did you
  mean X, Y, Z?" prompt surfacing the candidate stems; 0 → the
  existing unknown-monster error.

Doppelganger's runtime-dynamic display name (``???`` pre-
imitation, copied-player's name post-imitation) remains
out of scope — the alias path assumes class-time-known names;
the ``doppelganger`` stem still works. Multi-monster
disambiguation (``hydra.1`` / ``goblin.2`` style) also deferred;
memo: ``project_fuzzy_monster_names.md``.

~12 regression tests covering the alias registrations, the
two-pass fuzzy semantics, cross-segment-bleed guards on the
part side, and the exact-prefix-substring tier ordering on
both.

### 2026-04-21 — Dragon flying-agility bonus + Doppelganger fresh-stats-per-switch

Two unrelated balance / design fixes bundled.

**Dragon dodge** — a flying dragon is now meaningfully harder to
hit than a grounded one of similar stats. ``Dragon.get_dodge``
applies a ``×1.5`` bonus on top of the base emergence when the
``flying`` flag is set, layered cleanly on the HUGE 0.5
``dodge_mod`` (which scales by mass, not aerial agility). The
base ``Creature.get_dodge`` already does the right thing when
the dragon is grounded — wings destroyed drops the flag, and the
mobility-source lookup falls through to legs — so an intact-legs
grounded dragon retains real dodge rather than collapsing to 0
the way LIVE playtest showed it could. Toed-variant ``-62``
grounded penalty is preserved.

**Doppelganger form-copy** — ``imitate`` now adopts the target's
stats outright instead of taking ``max(current, target)`` across
switches. Previously a doppy that copied a tanky player and
then shifted into a squishy target would keep the tank's
defense / dodge / HP — in-fiction "become this creature" should
mean exactly that, not "become an aggregate of everyone you've
copied." HP adoption preserves wound state: the doppy's current
``health`` is capped at the new ``health_max`` rather than
reset, so shifting doesn't heal damage. Resolves the persistent
64% torso-exploit gap on doppelganger in the sweep (the exploit
was largely an artifact of accumulated best-of stats after
repeated imitation).

Four regression tests added: two pinning the new Dragon dodge
shape (flying exceeds grounded; grounded with intact legs stays
nonzero) and two pinning Doppelganger's fresh adoption
(downgrade-on-switch + HP cap-at-new-max).

### 2026-04-21 — Combat fix: landed-hit damage floors at 1 under partial resistance

Under Q.6.3's per-hit defense, a landed hit against a partially-
resistant trait with a low damage roll could silently do zero
damage via ``int()``-truncation — e.g. werewolf's ``0.75x`` trait
on a d4 roll of ``1`` gave ``int(0.75) = 0``, the hit "landed" on
the roll check but dealt nothing and showed ``* 0.75 = 0 → 0`` in
the table. Now: landed hits floor at 1 both for the applied
damage and the displayed ``sub_damage``, so the connection always
registers. Full immunity (``multiplier == 0``) still reads as 0
— the floor only fires when the target is merely resistant.

Spotted by Caels in LIVE playtest 2026-04-21 after the Q.6.3 push.

**Balance impact (post-fix sweep, 25 trials, MASTERWORK, base
player):** the silent-zero was quietly depressing damage against
any resistance-heavy monster. Meaningful shifts:

- **Dragon** (0.5× most types, 0.75× pure piercing): win-rate at
  skill 0/10/20 was ``0/0/28%``, now ``0/36/40%``. Genuinely
  winnable with skill rather than capped at boss-unreachable.
- **Golem** (0.25× piercing, 0.5× slashing, 0.25× earth): exploit
  gap tightened from 44% to 32%; resistance-heavy armor no longer
  zeroes the low-roll hits that were making swings feel wasted.

No regressions on the unresisted roster (goblin / bandit / werewolf
/ skeleton / etc. still trivially beatable). Fix is a pure damage
floor — the balance numbers pre-fix were what we shipped Q.6.3
with, so the Q.6.3 tuning set assumed a silent zero that shouldn't
have existed; numbers are now closer to what we thought we were
tuning.

### 2026-04-21 — `tools/tail_*` consolidation: LIVE / TEST positional + new watcher + balance aggregator

Four tail tools now share a single ``LIVE`` / ``TEST`` first-
argument interface. The shortname maps to both the DB env var
(``LIVE_DB_NAME`` / ``TEST_DB_NAME``) and the default inspector
port (``LIVE=8765``, ``TEST=8766``). Operators no longer need to
remember which env lives on which port — ``ps`` / ``tasklist``
on the running process answers it directly.

```
python -m tools.tail_channel LIVE --follow     # starts inspector
python -m tools.tail_peek    LIVE --tail 20    # pretty-print
python -m tools.tail_watch   LIVE              # filtered watcher
python -m tools.tail_balance LIVE              # metrics roll-up
```

Plus:
- ``tools/tail_watch`` is a new filtered watcher that polls the
  inspector and emits only ``ERROR`` / ``COMPLAINT?`` / ``PLAYER-Q``
  / ``WIPE`` events — for overnight monitoring without the combat-
  chatter noise.
- ``tools/tail_balance`` rolls the last N hours of inspector buffer
  into a summary: spawn counts, monster escapes, player deaths,
  hit/miss/crit rates, per-player activity. ``--since-hours`` or
  ``--after`` for the window; ``--json`` for machine-readable.
- ``--help`` on all four tools now fronts the ``{LIVE|TEST}``
  positional in the usage line and leads the description with
  "FIRST ARGUMENT" so the required arg is impossible to miss.
- ``TAIL_ENVS`` mapping + ``resolve_tail_env`` helper added to
  ``tools/_common.py`` so any future tail-tool stays in sync.

### 2026-04-20 — Phase Q.6.2 / Q.6.3 Per-Hit Defense (final shape: additive integer bonuses)

Two-commit arc landing per-hit defense application. Q.6.2
introduced per-hit subtraction with a multiplicative
`defense_mod: float`; Q.6.3 (after playtest surfaced truncation
issues and over-tuning) reworked it to an additive
`defense_bonus: int`. The additive shape is the shipped version;
Q.6.2's multiplier-tier tank values (bearowl 1.4, golem 1.5,
etc.) were reinterpreted as integer bonuses.

**Formula** — `Creature.resolve_attack` now computes:

```
defense_per_hit = max(0, base_def + part.defense_bonus)
damage_per_hit  = max(1, sub_dmg - defense_per_hit)   # if hit
```

Defense subtracts per-hit rather than once-per-sequence, so an
armored torso actually gates part destruction (not just tints
the display). `compute_body_hp_damage` drops its own defense
subtract because damage is already post-defense.

**Default is `SOFT_PART` (-999)** on every shipped body-part
plugin — unarmored parts clamp to zero absorption regardless of
base_def. Armor is opt-in per monster so goblin / bandit /
minotaur / doppelganger feel squishy everywhere, and armored
creatures earn their tank feel via explicit per-part overrides.

**Tank content pass** (additive bonuses on top of creature base_def):

| Monster | Part | `defense_bonus` |
|---|---|---|
| bearowl | torso | +3 |
| golem | torso, head | +4 |
| cyclops | torso | +5 (eye stays `SOFT_PART` — signature weakness) |
| giant | torso | +2 |

**Stat-dice retuning** on top of the additive shift:
- `Golem` base defense `4d8` → `3d6` (tank bonuses do the rest).
- `Dragon` base defense `3d8` → `4d4 + 6` (range 10-22) via an
  inline `self.defense += 6` — `Dice.from_ndn` doesn't yet parse
  `"NdM+C"` (backlog memory captured).

**Display** — compact-table footer reads
`Total: {raw} raw - {absorbed} absorbed → {final} damage` when
armor absorbed some of the sequence; collapses to
`Total: N damage` when it didn't.

**Monster-specific downstream fixes:**
- `MathTeacher` prime-halving checks `sub_damage` (pre-defense)
  rather than post-defense, so Lord-of-Primes fires on the same
  rolls regardless of target defense.
- `Dragon.breath_attack` stores post-defense value, matching the
  resolve_attack convention.
- `inspect_monster` renders `defense_bonus` in the per-part
  readout (was `defense_mod`).

**Incidental:** `tools/playtest_combat_harness`'s
`--sweep-monsters` path distributes per-monster sweeps across a
`ProcessPoolExecutor` (modest speedup on Windows — the shape is
right for larger sweep matrices).

**Post-Q.6.3 sweep** (25 trials, MASTERWORK, base player): 6 of
9 monsters balanced (goblin / bandit / bearowl / cyclops / giant
/ dragon-as-apex-boss), golem moderate, minotaur + doppelganger
remain exploit-prone by design — both earmarked for later fixes
(minotaur needs literal equipment via equipment-on-parts;
doppelganger's torso gap self-heals once form-copy adopts
copied-target armor instead of max-of across switches).

Full suite green on Python 3.14 (3166 passed).

### 2026-04-20 — Fix `NameError` in `DamageTypes.from_skill_key`

Forward reference to `DamageTypes` in the method's return-type
annotation was a bare name inside the class body, which Python
evaluates at class-creation time — blowing up at import with
`NameError: name 'DamageTypes' is not defined`. Quoted the
annotation so it's a string forward-reference.

### 2026-04-20 — Dispatcher: Auto-Split Oversized Messages + Fence-Aware

A single text message > 2000 chars hit a warn-and-drop branch in
`Dispatcher.send()` instead of being chunked (`split_message`
existed as a helper but was never wired in). Hydra + 4 attackers
clears the limit (observed 2287 chars in prod warn logs). Now:
oversized text auto-splits; first chunk carries any embed/file,
rest are text-only.

`split_message` was also code-fence blind — a split mid-`` ``` ``
block would leave chunk 1 unclosed and chunk 2 rendered outside
the block. Combat tables use `` ```diff `` spans so every
multi-player swing broke the render. The splitter now tracks
fence state per-chunk, closes unclosed fences, and reopens the
same language in the next chunk. 20-char fence reserve against
the working limit so markers don't push chunks past the cap.

### 2026-04-20 — Monster Body HP Tuning (Q.6.1)

First content-audit pass following the Q.6 refactor. Seven
monsters' body HP dice bumped to match their intended size /
role — Q.6's body-HP-relative part scaling surfaced several
monsters whose rolled body HP was too small for a coherent
ratio (dragon body 150 / torso 145 reads correctly; cyclops
body 53 / torso 74 does not for a HUGE "tanky" creature).

| Monster | Before | After | Avg |
|---|---|---|---|
| bandit | 3d8 (13) | 4d12 | 26 |
| minotaur | 6d10 (33) | 14d12 | 91 |
| golem | 8d10 (44) | 25d12 | 162 |
| cyclops | 10d10 (55) | 20d12 | 130 |
| doppelganger | 20d6 (70) | 20d10 | 110 |
| bearowl | 15d10 (82) | 22d10 | 121 |
| giant | 15d12 (97) | 25d12 | 162 |

Post-tuning sweep (15 trials, MASTERWORK, skill-20, base
player): hydra stays OK (20% → 13%), dragon near-OK (20% →
27%), cyclops TRIVIAL → major (80% → 60%), giant TRIVIAL →
major (87% → 53%). Absolute fight difficulty increased across
the board — skill-20 no-target win rates dropped 7-20pp on
the tuned LARGE/HUGE bosses.

bearowl, golem, doppelganger, minotaur didn't close their gap
meaningfully via body HP alone — the `defense_mod` and
`BLEED_MOD` content levers (Q.6-shipped no-ops) are the
natural next lever. Full pre/post comparison + analysis lives
in the project owner's local design notes.

### 2026-04-20 — `tools/repeat` value-iteration mode (`--each`)

Extends the command-repetition runner with `--each <csv>` for
running a command once per value in a list, substituting `{v}`
per iteration. Complements the existing `{i}` iteration-number
token. Used to inspect every monster's Q.6-scaled part stats
in one allowlisted invocation:
`python -m tools.repeat --each pixie,goblin,... -- python -m
tools.inspect_monster {v}`.

+6 tests for the --each path.

### 2026-04-20 — Phase Q.6 Part HP + Bleed-Through Refactor

Balance refactor sitting on top of the Combat Pipeline stack.
Three structural changes + two no-op levers for future content.

**Critical-part HP is now body-HP-relative**: `critical_hp =
body_hp × size_scalar × def_scalar`, floored at half body HP.
Size bands TINY 0.4 → COLOSSAL 1.6; defense bands <10 → 1.5,
10-20 → 1.0, 20+ → 0.7. Hydra's torso climbs from ~50 to ~300
HP via this scaling — torso-target exploit gap drops from
80% to 20%, passing the boss-tier gate.

**Non-critical part HP is also body-HP-relative**: `part_hp =
body_hp × part_fraction × size_scalar`. Fractions: arm 0.20,
leg 0.25, tail/wing 0.15, eye 0.05, toe 0.03. Resolves the
"vampire arm is 9 HP while vampire body is 124 HP" incoherence
by anchoring part resilience to the creature's power budget.

**Body-HP damage flows from part-bleed**: replaces the flat
`max(num_hits, total - defense)` with
`max(num_hits, int(sum(dmg × bleed_rate) × BLEED_MOD) - effective_defense)`.
Per-part bleed rates: torso 0.7, head 0.6, arm/leg 0.3,
tail/wing 0.2, eye 0.1, toe 0.05. Non-critical part damage
still bleeds into body HP so "target-only-non-critical-parts"
can't farm XP without progressing toward a kill. Narrative
weight + anti-exploit in one lever.

**XP formula E**: `miss_xp=2` flat for attempts, `base_hit_xp
= 5 + floor(5 × √level)` plus `damage × bleed_rate × 1.5`
bonus for connected hits. Two-handed doubles both. Zero-damage
hits (trait immunity, e.g. physical vs spirit) still grant
base_hit_xp since the swing connected. Low-skill early-game
gets a gentler floor via miss XP; late-game parity tunes
to ~88% of pre-Q.6 rate.

**Migration**: one-time rescale on first load (gated by new
`skills_schema_version` field) rescales in-level XP progress
by `1/0.878` so existing players keep current skill levels
and don't perceive the rate drift. Idempotent via version
check, round-trips through to_dict/from_dict, dirty-marks for
persistence.

**No-op content levers shipped** (mechanism only, no monster
populates them yet):
- `BodyPartPlugin.defense_mod: float = 1.0` — damage-weighted
  into `compute_body_hp_damage`'s effective defense, so a
  tank's `torso.defense_mod = 2.0` would actually protect the
  body (not just display).
- `MonsterPlugin.BLEED_MOD: float = 1.0` — creature-wide bleed
  multiplier for skeleton/golem/vampire thematic tuning.

**Post-refactor tuning sweep** (15 trials, MASTERWORK gear,
base player HP=20 def=6 dodge=6):
- Hydra: 80% → **20%** exploit gap ✓
- Dragon: 27% → **20%** (stable, reference template) ✓
- Vampire: 67% → 27%
- Bandit: 27% → 7%
- 5 monsters (doppelganger, bearowl, golem, cyclops, giant)
  regressed because their rolled-low body HP now anchors
  low critical HP too. Deferred to Q.6.x content audit
  (body-HP dice tuning per monster + `BLEED_MOD` / `defense_mod`
  content overrides).

**Added** `tools/inspect_monster.py` for ad-hoc monster stat
inspection (replaces inline `python -c` dumps of scaled part
HP). 3096 → 3156 tests passing. Three consecutive clean runs.

### 2026-04-20 — `playtest_combat_harness` Multi-Monster Sweep

Extends the harness with `--sweep-monsters <stem1,stem2,...>` mode
for cross-monster balance-proofing in one invocation. Runs the
existing per-monster sweep (all 1H × 1H dual-wield combos + 2H
solos × 3 skill levels × 3 strategies) against each listed monster,
plus emits a condensed per-monster summary and a cross-monster
tuning chart at the end.

Per-monster summary tags the worst torso-target exploit gap as
`TRIVIALIZED` / `major` / `moderate` / `OK` so trivialized-by-
critical-part boss fights surface immediately. Monster header
line shows size, body HP, defense, dodge, torso HP, head HP —
the inputs to the scaling discussion.

`--verbose-sweep` also emits the full per-skill loadout table
per monster when the detail is wanted.

Initial 12-monster sweep (pixie → dragon) surfaced the pattern:
bearowl / golem / hydra all `TRIVIALIZED` by torso-target at
skill-20 MASTERWORK (exploit gaps 80-93%); vampire / minotaur /
giant / cyclops all `major`. Dragon's def=30 is the outlier that
keeps its gap at moderate (27%) — the template for what healthy
critical-part balance looks like.

### 2026-04-20 — `tools/playtest_combat_harness` End-to-End Combat Simulator

Drives the REAL pipeline stages headlessly — no Discord, no
Game orchestration. Balance-checking now sees true numbers:
part HP, exposure-weighted target-part selection, critical-
part kills (head destruction = instant kill regardless of
body HP), trait multipliers, skill-level bonuses, dodge/hit
rolls, and all the emergent behavior simpler sims can't model.

Usage examples:

```
# Celowin-ish dual-wield vs minotaur, 200 seeded trials
python -m tools.playtest_combat_harness \
    --weapon mace --offhand shortsword \
    --monster minotaur --trials 200

# Exercise the critical-part-kill path
python -m tools.playtest_combat_harness \
    --weapon shortsword --monster goblin \
    --target-part head --trials 200

# Two-handed MASTERWORK bow at skill 20 vs hydra
python -m tools.playtest_combat_harness \
    --weapon bow --quality MASTERWORK --skill 20 \
    --monster hydra --trials 50
```

Outputs per-scenario summary: win rate, min/max/mean rounds
per outcome, critical-part-kill rate, avg damage dealt and
received, top destroyed parts.

Smoke result: unarmed-equivalent (mace+shortsword ORDINARY
skill-10) vs goblin at head-target converts **100%** of wins
via critical-part kill — validates the "part-targeting is
overpowered" signal the simpler `playtest_action_dice` /
`playtest_weapon_sweep` couldn't surface because they don't
model critical parts.

Built on the Phase-6 completion: Player routes through
`pick_actions` → `pick_targets` → `resolve`; monster retaliates
via the pipeline-driven `attack_random`. Dispatcher and DB
patched at tool-entry so hook side effects don't reach Discord
or Mongo.

12 tests in `tests/test_tools_playtest_combat_harness.py`.

### 2026-04-20 — Combat Pipeline: Phase 6d Player Pipeline Port (end-to-end complete)

Player attacks now flow through the pipeline stages at runtime.
`Game._run_player_block` drives `pick_actions` → (explicit-part
resolution) → `resolve` → `render_table` → `narrate_results`
instead of wrapping legacy `Player.do_attack` +
`apply_sequence_to_target`. Every combat path in the game
(player + every monster + hydra + dragon + vampire) runs
through the pipeline — the refactor is structurally complete.

`Player.pick_actions`: one-line override returning
`self.get_attack_sources()` (already equipment-aware via the
existing Phase 1+ method — unarmed, one-weapon, two-handed,
arm-injury dropout all preserved).

`Player.render_table`: override that injects
`get_disabled_attack_notes()` into the synthetic
`AttackSequence` so "The right arm hangs limp and useless."
renders inside the diff block exactly as pre-6d. Notes-only
branch (both arms USELESS) still emits a damage=0 block with
no table rows — matches legacy shape.

Explicit-part targeting (`$target arm.left`, `$kill head`)
routes via tuple-form `Assignment(source, target=(monster,
part))`. `Creature.resolve` already handled tuple targets
since Phase 2. Dual-wield with multi-part targets cycles
`source[i] → part[i % len(parts)]` preserving pre-6d routing.

`CombatBlock` now carries real data — actions, assignments,
results, table, result_narratives. Local to
`_run_player_block` (no downstream consumer yet), but the
API-narrator bridge has real data to read when that work
lands.

`Player.do_attack` preserved unchanged as a legacy entry
point — tests and external callers still rely on it.
`Game._do_combat_legacy` is also still callable for one-line
rollback if a playtest regression surfaces.

Body-HP application stays in the round composer (Phase 6a
ownership): `max(num_hits, body_damage_total - defense)`
with the legacy `num_hits > 0 && not monster.is_dead()`
gates. XP / skill-gain via `_on_attack_resolved` fires from
inside `Creature.resolve` → preserved.

9 new `TestPlayerPipelinePort` tests (loadouts × 5 + tuple
routing + notes rendering + zero-source path). 4 parity
tests in `test_game_do_combat_parity.py` repointed from
`Player.do_attack` → `Player.pick_actions` / `Player.resolve`
monkey-patches; still pin what they originally asserted.

3075 → 3084 passing. Three consecutive clean runs.

Playtest focus:
- Dual-wield attack against multi-part monster: diff table
  shows Left + Right rows with correct labels and part
  routing.
- Explicit part-targeting (`$target arm.left`, `$kill
  head.1 head.2` on hydra) with both single- and multi-part
  names.
- Cripple an arm, then attack: disabled-note renders inside
  the diff block above the damage table.
- Both arms crippled: notes-only block, zero damage, no HP
  summary change.
- Critical-part kill (decapitate hydra / goblin head):
  HP summary suppressed, death beat lands.
- XP gain across a round of weapon-type hits.

### 2026-04-20 — Combat Pipeline: Phase 6c Dragon Thin-Override

Dragon's `attack_random` now follows the post-refactor thin-
override pattern (mirrors hydra/vampire): breath weapon pre-
empts the pipeline with its own bespoke math (AOE, FIRE trait
multiplier, auto-hit, post-defense subtract), and non-breath
turns delegate to `super().attack_random(...)` which drives the
Phase 6b pipeline-driven `MonsterPlugin.attack_random`.

Behavior parity: control flow byte-identical to pre-6c. Only
additions are a tightened return annotation (`Optional[str]`)
and a WHY-focused docstring naming the thin-override pattern +
Phase 6a compliance (breath applies body HP directly via
`victim.apply_damage`, never routes through `Creature.resolve`).

New `TestDragonBreathPathPreserved` (5 tests) pins:
- Breath flavor renders when cooldown/RNG align
- Non-breath branch produces pipeline-driven table with no
  breath flavor leak
- `_rounds_since_breath` counter bumps correctly across
  successive super-delegated turns
- Branch interleaving resets the counter cleanly
- Breath applies body HP exactly once (no double-apply)

3070 → 3075 passing. Three consecutive clean runs.

### 2026-04-20 — Combat Pipeline: Phase 6b MonsterPlugin Pipeline Port

`MonsterPlugin.attack_random` now drives the pipeline stages
(`pick_actions` → `pick_targets` → `resolve` → narration) in
place of the legacy `do_attack` + `apply_sequence_to_target`
loop. Every monster except hydra (Phase 4) and dragon (Phase 6c)
inherits the new path automatically. Output format preserved
line-for-line for the `count=1` production case (attack table
→ injury feedback → death beat).

Body HP is applied per-victim after resolve via the same
`max(num_hits, body_damage_total - defense)` formula the legacy
path used, gated on `num_hits > 0` and `not victim.is_dead()`.
Phase 6a removed body-HP from `Creature.resolve`, so this is
the only place body HP lands for non-player retaliation now.

Vampire regression caught in review: `Vampire.do_attack`
overrode the attack to fire `feed(victim)` at ≤50% HP, but the
pipeline port routes through `pick_actions` / `resolve` and
bypasses `do_attack`. Fixed with a thin `Vampire.attack_random`
override mirroring hydra's / dragon's pattern — checks HP up
front, returns `feed(victim)` when eligible, else delegates to
super. Pre-6b behavior preserved exactly. `TestVampireFeedRestoredInRetaliation`
pins both branches (low HP → feed fires, full HP → pipeline).

Dragon compat: dragon's own `attack_random` override calls
`super().attack_random()` for non-breath turns; that call now
drives the new pipeline code. Verified via
`TestDragonSuperCallStillWorks`.

3045 → 3070 passing (+25 tests covering monster port, vampire
restoration, dragon delegation). Three consecutive clean runs
via `tools/repeat`.

Playtest focus:
- Monster retaliation output shape across non-hydra monsters.
- Vampire feed at low HP (regression-fix surface).
- Dragon non-breath rounds.

### 2026-04-20 — Combat Pipeline: Phase 6a Body-HP Ownership Refactor

`Creature.resolve` no longer applies body HP — its contract is
now pure part-routing + aggregation. Callers (`Game.do_combat`,
`MonsterPlugin.attack_random`, `Hydra.attack_random`) own the
body-HP write explicitly. Prerequisite for Phase 6b/c/d
(porting all monsters + Player through the pipeline) because
without it, any caller that wrapped resolve AND applied body HP
of its own would double-apply.

`Game.do_combat` and `MonsterPlugin.attack_random` already owned
body HP today — no change needed. `Hydra.attack_random` gains
an explicit apply-damage block in its per-victim loop mirroring
MonsterPlugin's pattern (formula, guards, death-message capture
all identical).

New `TestResolveNoLongerAppliesBodyHP` pins the contract —
seeds until a hit lands, asserts `victim.health` unchanged
post-resolve. Would fail against the pre-6a shape.

### 2026-04-20 — `tools/repeat` Command Repetition Runner

New tool: `python -m tools.repeat -n 5 -- python -m pytest -q`
runs the given command N times in one outer process. Bash
for-loops (`for i in 1 2 3; do python -m tools.X; done`)
aren't matched by the `Bash(python -m tools.*)` permission
allowlist, so each loop body re-prompts for approval. A
dedicated runner keeps the outer invocation inside the allow-
list while iterating inside Python via `subprocess.run`.

`{i}` in any command arg is replaced with the iteration number
(1-indexed) — useful for varying seeds across runs. Auto-
substitutes `sys.executable` when the inner command starts with
`python` / `python3` so the subprocess uses the active venv's
interpreter (not the system Python).

`--stop-on-failure` aborts on the first non-zero exit;
`--quiet` suppresses per-iteration headers.

### 2026-04-20 — Combat Pipeline: Phase 5 Round Composer

Rewires `Game.do_combat` around a pipeline-driven round composer.
The monolithic player-attack loop becomes an ordered walk over
combatants in join order (was reverse-of-join via the pop-while-
iterating safe-remove artifact — design doc locked the change).
Each attacker produces a block via `_run_player_block`, and the
round composer aggregates damage tallies, death messages, and
HP summaries the same way as before. Output format preserved;
the user will see live combat play out identically except for
the turn-order change.

Player combat still runs its legacy `do_attack` +
`apply_sequence_to_target` internals inside the round composer
rather than routing through `Creature.pick_actions` / `resolve`
directly — routing through `Creature.resolve` would double-apply
body-HP damage (resolve's `victim.apply_damage(final)` plus the
round-composer's explicit `monster.health -= final_body_dmg`).
Fixing the ownership split is Phase 6+ work; Phase 5 stops at
the round-composer structure so playtest can confirm turn-order
change and no regression.

Pre-Phase-5 body preserved as `Game._do_combat_legacy` so the
call site can flip back in one line if a playtest regression
surfaces. Design doc Phase 7/8 eventually deletes the legacy.

New `tests/test_game_do_combat_parity.py` — 14 parity tests +
an autouse RNG seed fixture so combat rolls are deterministic
(attack hits, death-flavor choice, etc. would otherwise drift
across test orderings).

3014 → 3044 passing (+14 parity tests + 16 repeat tool tests
from the separate tooling commit).

Playtest focus:
- Turn order (join order now — players in the order they
  registered, not reverse).
- Hydra regrowth + decapitation (same path as before, routed
  through the new retaliation branch).
- RAMPAGE / SURVIVE re-entry (same game-clock routine).

### 2026-04-20 — Playtest Tooling: `playtest_weapon_sweep`

New tool for balance-proofing against the actual weapon catalog
(player attacks are weapon-driven, so sweeping the inventory
gives broader scope than per-player stat fiddling).

- **Default mode** sweeps every weapon in
  `caldanai/lib/rpg/inventory/equipment/weapons/` at `ORDINARY`
  quality + skill 10 against all six size tiers. 13 rows × 6
  cols matrix showing win rate and avg rounds per cell.
- **`--sweep-qualities`** fixes one weapon, iterates the six
  quality tiers (JUNK → MASTERWORK). Surfaces the known scaling
  quirk: 1dN weapons barely differentiate between ORDINARY /
  FINE / QUALITY / SUPERIOR because `bonus = int(dice_count ×
  multiplier)` collapses `1.0..1.75` to `1`. 2dN weapons scale
  smoothly (1/2/2/3/3/4).
- **`--sweep-skills`** iterates skill level snapshots
  (0 / 5 / 10 / 15 / 20), showing skill progression impact. A
  MASTERWORK spear at skill 20 cracks HUGE 14% of the time
  solo — closest any single-weapon setup gets.
- **`--offhand <name>`** adds dual-wield support. Every mode
  accepts it; dice list grows to `[main, offhand]`, both swing
  each round. `--offhand-quality` / `--offhand-skill` let the
  offhand diverge from the main-hand; both default to the
  main-hand values. Hit modifier uses the main-hand skill for
  both swings (approximation — the game would use each weapon's
  own skill per swing).

Player HP / defense / dodge aren't weapon-driven, so they
default to an "average player" profile (HP 20, def 3, dodge 15)
and are overrideable via `--player-hp / --player-defense /
--player-dodge`.

### 2026-04-20 — Playtest Tooling: `render_flavor` Body-Part Modes + `playtest_action_dice`

Two tool additions for balance-proofing the combat refactor
without spinning up the bot.

- **`render_flavor --part <name>`** — render a body-part
  plugin's `DEFAULT_ACTIONS` narrative pools through `parse()`.
  All 63 Phase-3 part-default templates proof-rendered in one
  invocation per part. Synthetic `@Np_target` stub points at
  `"left arm"` so the dynamic target-part token doesn't render
  empty.
- **`render_flavor --combat`** — walk a live monster instance's
  per-part `DEFAULT_ACTIONS` (including post-spawn wiring like
  hydra's per-variant repertoire). Needed to proof Phase-4
  hydra's wired action templates across all four variants.
- **`tools/playtest_action_dice`** — new tool. Rolls every
  Phase-3 size-scaled action across TINY→COLOSSAL and reports
  distributions (matrix mode), drills into one action at one
  size (focused mode), simulates rounds-to-kill against a
  single target (`--fight`), and runs two-sided duel
  simulations with optional hit-roll/dodge modeling (`--duel`).
  `--vs-sizes` sweeps one attacker against representative
  creature profiles per size tier in one invocation — avoids
  the bash-loop permission churn for iterated runs.

### 2026-04-20 — Combat Pipeline: Phase 4 Hydra Port

Hydra ported off its legacy 300-line custom combat pipeline onto
the Phase 2/3 base. `Hydra.attack_random` collapses from ~150
lines to ~50 as a thin driver around `pick_actions` /
`pick_targets` / `resolve` / `narrate_attempt` / `narrate_results`.
The `_select_round_actions` / `_assign_to_targets` /
`_build_narrative` methods and the module-level
`_NARRATIVE_TEMPLATES` dict are gone — all three roles now live
in `Creature` and are inherited. Output format is preserved
line-for-line, so live hydra combat reads the same post-refactor.

Per-variant repertoires (grotesque / swamp / hexed / elemental)
wire into each head's `DEFAULT_ACTIONS` at spawn via
`_wire_head_actions`, with per-head labels (`venomous bite`,
`dark pulse`, `elemental breath`, etc.) baked in at wire time
through `_narrative_for`. Tail and leg actions wire the same way
onto their respective parts. Torso's inherited `chestbutt`
default is filtered out — hydra is a heads/legs/tail attacker.

Hydra-specific overrides stay on the subclass:
- `get_action_budget` returns the dynamic `_compute_budget`
  formula (kept for breadth of existing test coverage).
- `pick_targets` delegates to the `round_robin_assignment`
  module helper.
- `_collect_part_action_pools` priority-sorts (heads → tail →
  legs) and filters non-attackers before the base's budget
  selection runs.
- Breath cooldown lives in an `is_available(actor, target)`
  callable on each wired breath entry, closing over the
  `_breath_cooldown[head.name]` dict.

Differential parity tests (`tests/test_combat_pipeline_vs_hydra.
py`) re-authored as Phase-4 invariant tests; the fixture's
test-scope monkey-patch is gone now that hydra permanently
carries its wired `DEFAULT_ACTIONS`. Legacy helper-method tests
in `test_hydra_expansion.py` ported to the pipeline surface.

Playtest focus areas (reviewer-flagged): multi-destroyed-head
budget edge cases; breath cooldown behavior across rounds and
regrowth; target-part dodge distribution; death ordering in
3+ victim scenarios. 3007 → 3014 passing.

### 2026-04-20 — Combat Pipeline: Phase 3 Content Population

Third phase of the combat pipeline refactor. Part-default action
content, two new parser tokens, registry rename, and callable-
native action-entry convention established. Still no runtime
surface — Phase 5 wires the stages into `Game.do_combat`.

- **Body-part `DEFAULT_ACTIONS`** populated on head (bite,
  headbutt), arm (punch, grab), leg (kick, stomp), tail
  (tail_swipe, tail_slam), wing (wing_buffet), torso (chestbutt).
  Ten actions total, 6–7 narrative templates each (63 templates).
  Dialogue-free — creature-level overrides do voicing later.
- **Size-scaled default dice** via `body_parts.action_dice.
  size_scaled_dice(action_name, Size)`. Entries can omit the
  `dice` field; `_resolve_action_dice` falls back through the
  size tier table. A naked goblin bites for 1d4, a naked dragon
  bites for 1d8, no creature-level override needed.
- **Parser tokens.** `@Np_target` reads the target part's
  `display_name` from a `result=` kwarg on `parse()` — used in
  authored-ahead templates where the hit part varies per roll.
  `@Np.<part_name>` does a fuzzy `find_parts` lookup on actor N —
  used by the API-narrator path when a template wants to
  reference a specific part. Both coexist with bare `@Np`
  (possessive pronoun) via the required `.` disambiguator.
- **Rename `ACTION_OVERRIDES` → `ACTION_REPERTOIRE`** with
  nested-dict shape (`Dict[str, Dict[str, Dict]]`, keyed by
  part-type then action-name). Merge semantics: key present in
  a part's defaults ⇒ deep-merge (modify); key absent ⇒ add a
  new action. One registry for both patterns.
- **Callable-field convention** for action entries. Recognized
  optional callables: `is_available(actor, target) -> bool`
  (pick-time conditional selectability; `target` is `None` at
  `pick_actions`), `get_dice(actor, target) -> str`, and
  `get_narrative(actor, target) -> List[str]`. Pure-dict entries
  still work unchanged. Callable exceptions are caught and
  logged (`_log.warning`) so author bugs surface in logs rather
  than silently dropping actions.

72 new tests (parser, body-part defaults, action repertoire
semantics). Full suite: 2998 passing.

### 2026-04-20 — Minotaur Flavor Capitalization Fix

Three minotaur flavor strings had lowercase form-letter tokens
(`@1a`, `@1s`) at sentence-start positions where capital forms
(`@1A`, `@1S`) were intended. Rendered as "her horns…",
"she appears…", "she snorts…" after a sentence-ending period.
Spotted in LIVE tail ("Corded muscle and a head full of hostile
intent. she appears…"). Every other monster already used the
convention correctly — minotaur was the outlier.

### 2026-04-20 — Combat Pipeline: Phase 2 Mechanical + Narrative Lift

Second phase of the combat pipeline refactor. Lifts generic
logic from hydra and today's shared combat code into real
implementations of `Creature`'s ten stage methods. No runtime
surface yet — `Game.do_combat` stays unwired until Phase 5.

- Real implementations: `pick_actions` (part-default collection
  + weighted-random budget selection), `pick_targets` (single-
  target default, honors `intended_target`), `resolve` (wraps
  `apply_sequence_to_target` per victim + applies body-HP
  damage), `narrate_attempt` (template pool + `parse()`),
  `narrate_results` (multi-victim injury-feedback lines),
  `narrate_target_death` (part-driven-death → `result.death_msg`
  → `self.death` → fallback dispatch), `summarize_damage` (with
  optional `health_snapshots` parameter so Phase 5 can match
  today's `vs {health_before}` output exactly), `render_table`,
  `reactions` (empty default), `narrate_attacker_death` (gated
  on non-empty reactions output).
- `BodyPartPlugin.DEFAULT_ACTIONS = {}` and
  `MonsterPlugin.ACTION_OVERRIDES = {}` added as empty class-
  level defaults; Phase 3 populates content.
- `get_action_budget()` method reads `ACTION_BUDGET` class attr
  by default; hydra will override the method in Phase 4 for its
  dynamic budget formula.
- Differential parity tests against hydra's legacy methods
  (`tests/test_combat_pipeline_vs_hydra.py`) using a test-scope
  fixture that wires `_REPERTOIRE_*` into each head's
  `DEFAULT_ACTIONS` — catches lifting bugs in Phase 2 rather
  than surfacing them in Phase 4 playtest.

2919 → 2925 passing.

### 2026-04-19 — `tools/notify` TTS Helper

Small operator tool: `python -m tools.notify "<message>"` speaks
the message via Windows PowerShell TTS. Intended as an audible
attention cue when the user is AFK and an agent needs approval
(background-agent completion, pre/post-deploy ritual gates,
etc.). Message goes to PowerShell via an env var so there's
zero shell-interpolation surface regardless of message content.

### 2026-04-19 — Combat Pipeline: Phase 1 Scaffolding

First phase of the combat pipeline refactor (see Obsidian
"combat-pipeline-refactor" design doc). Pure data-type
groundwork — new `CombatBlock`, `Assignment`, `ReactionEntry`
with `Anchor` enum, plus `MultiVictimResolutionResult`, plus
`intended_target` on `AttackSource` and `victim` on
`AttackResult`, plus `ACTION_BUDGET` + ten empty-body stage
methods on `Creature`. Nothing wired into `Game.do_combat` yet;
subsequent phases light up the stages one at a time. All types
designed to serialize cleanly so a future API-backed narrator
can consume a block without touching combat math.

### 2026-04-19 — Cog-Loader Error Propagation

When a cog failed to register (e.g. alias collision), startup hung
silently — the exception had been raised but `asyncio.gather`'s
cancellation cascade over the other in-flight cog-loading tasks
couldn't complete, so the process appeared frozen until SIGINT.
Switched the gather to `return_exceptions=True`, log every
failure, then re-raise the first so startup fails fast and loud.

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
