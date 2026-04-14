# Changelog

All notable changes to the Caldanai Bot project will be documented in this file.

## [Unreleased]

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
