"""Baseline ``Hydra`` monster plugin -- Phase 1.C item 3.2.

The hydra is the proving-ground monster that exercises the entire
Phase 1.A + 1.B foundation end-to-end. It is the first monster to:

- Compose body parts at ``__init__`` time (torso + 4 legs + tail +
  ``STARTING_HEADS`` live head instances with ``is_critical=False``).
- Override :meth:`Creature.get_attack_sources` to emit one
  :class:`NaturalAttackSource` per live hydra head (single-target
  multi-hit, like player dual-wielding).
- Implement turn-based regrowth in :meth:`MonsterPlugin.on_combat_round`:
  at the end of every combat round, if any heads were destroyed the
  hydra spawns 2 new heads per destroyed head, clamped to the
  ``MAX_HEADS`` cap.

Two independent death conditions
================================

1. **Critical torso destroyed** -- routed through the standard
   :meth:`Creature.apply_damage` critical-part death path from item
   1.9. The torso is composed with ``is_critical=True`` and its
   destruction instantly zeroes ``self.health``. Works regardless of
   how many heads the hydra still has.

2. **All live heads destroyed** -- checked in
   :meth:`on_combat_round` before regrowth runs. If a player wipes
   every live head in a single round, ``on_combat_round`` sets
   ``self.health = 0`` and returns a death flavor string. This check
   MUST fire before regrowth -- otherwise regrowth would always save
   the hydra and the "kill the last head in a single round" win
   condition would be unreachable.

Scope is strictly baseline
==========================

The following features are **queued** as Q.2-Q.7 in the Phase 1 design
doc and are intentionally NOT implemented here:

- Q.2 Variants (swamp, witch's familiar, Tiamat, default grotesque
  serpentine horror). Baseline uses a single ``flavor`` string.
- Q.3 Multi-target attack mode (heads pick different victims).
  :meth:`get_attack_sources` returns single-target multi-hit only.
- Q.4 Per-head damage types (Tiamat elemental). All heads share the
  hydra's class-level ``atk`` dice and ``dmg_type=None``.
- Q.6 Hydra breath attack. No ``breath_attack`` override; combat is
  pure claw-and-fang.
- Q.7 Whole-head loot. The user explicitly said whole hydra heads are
  too heavy for the current inventory system, so loot is small pieces
  only -- and even the small pieces re-use existing inventory items
  until a dedicated item-authoring phase.

Loot table
==========

Because new item plugins are deferred, the loot table re-uses existing
items from :mod:`Caldanai.lib.rpg.inventory.stackables` and
``usables/consumables``, chosen for vaguely-on-theme flavor:

- ``toad_slime`` (0.8): generic serpentine-monster ichor.
- ``leather`` (0.5): hide scraps from the mass of serpentine body.
- ``small_gem`` (0.3): swallowed treasure.
- ``wool`` (0.2): improbable but present -- the hydra swallowed a
  sheep, occasional surprise drop.

Late imports
============

:class:`NaturalAttackSource` is imported inside the methods that need
it rather than at module load. This matches the ``dragon.py`` pattern
and avoids pulling the combat subpackage into the hydra module's
import graph at class-definition time.
"""

from Caldanai.lib.rpg.creatures.body_parts.head import HeadPlugin
from Caldanai.lib.rpg.creatures.bodypart import BodyPart
from Caldanai.lib.rpg.creatures.monsters import MonsterPlugin
from Caldanai.lib.rpg.helpers.enums import AggressionLevels, Reach, TimePartitions
from Caldanai.lib.rpg.helpers.parser import parse


class Hydra(MonsterPlugin):
    """Baseline grotesque serpentine hydra.

    Multi-headed cathemeral monster with turn-based head regrowth, a
    critical torso, and a single-target multi-hit attack pattern (one
    attack source per live head). See module docstring for the full
    design rationale, queued features, and loot-table explanation.
    """

    #: Maximum simultaneously-live heads the hydra can support. Destroyed
    #: heads above this cap produce flavor text about the hydra's
    #: biological limit instead of regrowing.
    MAX_HEADS = 10

    #: Starting head count. The hydra spawns with this many live heads
    #: and can regrow up to :attr:`MAX_HEADS` through combat. Starting
    #: below the cap makes regrowth visible and dramatic over the first
    #: few rounds; starting at 10 would hide the mechanic entirely
    #: until the player lands a kill on the cap.
    STARTING_HEADS = 3

    def __init__(self):
        super().__init__(
            name="hydra",
            # Low per-head, multiplied by N live heads in
            # get_attack_sources. A hydra with 3 live heads throws 3 *
            # 1d6; at 10 heads it's a 10 * 1d6 hailstorm, roughly on
            # par with a dragon's 3d10 single-source hit but split
            # across independent rolls so defense / dodge apply per
            # head (until Q.1 restores the per-total rule).
            atk="1d6",
            defense="2d6",
            # Lower than the dragon's 3d10 -- the hydra is a big
            # lumbering beast, hard to outright whiff but easy to
            # land blows on.
            dodge="2d8",
            # Tough main HP to survive the long head-chopping fight.
            health_max="20d10",
        )

        self.time_partition = TimePartitions.CATHEMERAL
        self.image = None
        self.aggression = AggressionLevels.RAMPAGE
        self.arrival = (
            "A writhing mass of scales erupts from the murk as a @1 looms "
            "into view, heads hissing in unison."
        )
        self.flavor = (
            "A grotesque serpentine @1 coils with surprising grace, its "
            "many heads swaying in a hypnotic unison. The ground around "
            "it is slick with sulfurous runoff."
        )
        self.escape = (
            "The @1 slithers back into the murk, its heads twisting in "
            "mocking farewell."
        )
        self.death = (
            "The @1's remaining heads sag lifelessly, and with a final "
            "bone-wet shudder, the whole writhing bulk collapses into a "
            "still, steaming mound."
        )

        # Loot table -- EXISTING items only. Whole hydra heads are too
        # heavy for the current inventory system (design doc Q.7), and
        # dedicated hydra-themed items (scales, fangs, blood) are
        # deferred until after Phase 1. See the module docstring for
        # the rationale behind each pick.
        self.loot["toad_slime"] = 0.8
        self.loot["leather"] = 0.5
        self.loot["small_gem"] = 0.3
        self.loot["wool"] = 0.2

        self.body_parts = [p for p in BodyPart.quadruped() if p.name != "head"]
        # Mark the torso as critical (hydra dies when torso is destroyed)
        for p in self.body_parts:
            if p.name == "torso":
                p.is_critical = True
                break
        for i in range(self.STARTING_HEADS):
            self.body_parts.append(
                BodyPart.make("head", is_critical=False, name=f"head.{i + 1}",
                              exposure={Reach.MELEE: 0.4, Reach.REACH: 0.5,
                                        Reach.THROWN: 0.7, Reach.RANGED: 1.0})
            )
        self._next_head_number = self.STARTING_HEADS + 1

    def get_attack_sources(self):
        """Return one :class:`NaturalAttackSource` per live hydra head.

        All sources target the same creature (the one
        :meth:`Creature.do_attack` is called with) -- this is a
        **single-target multi-hit** pattern, like a player
        dual-wielding. Multi-*target* attacks (different heads picking
        different combatants) are queued as Q.3 and explicitly out of
        scope for the baseline hydra.

        Per-head damage types (required for the Tiamat elemental
        variant) are queued as Q.4. Every head here emits a source
        with ``dmg_type=None`` using the hydra's class-level ``atk``
        dice string.

        **Defensive headless fallback**: if no live heads remain, this
        method still returns a list with one source. In normal play
        :meth:`on_combat_round` fires the last-head death check before
        the next attack round, so this branch should be unreachable.
        It exists so that an unexpected mid-round call (e.g. from a
        retry path) can't crash with an empty-list error.
        """
        from Caldanai.lib.rpg.combat.attack_source import NaturalAttackSource

        live_heads = [
            p for p in self.body_parts
            if isinstance(p, HeadPlugin) and not p.is_critical
            and not p.is_destroyed()
        ]

        if not live_heads:
            # Defensive: return a minimal natural source labeled as
            # "headless flailing" so we neither crash nor silently
            # attack with zero sources.
            return [
                NaturalAttackSource(
                    atk=self.attack,
                    dmg_type=None,
                    label=f"{self.name.title()} (headless flailing)",
                    skill="natural",
                )
            ]

        return [
            NaturalAttackSource(
                atk=self.attack,
                dmg_type=None,
                label=f"{self.name.title()} ({head.name})",
                skill="natural",
            )
            for head in live_heads
        ]

    def on_combat_round(self, damage_by_player) -> str:
        """Turn-based regrowth + last-head death check.

        Fires at the end of each combat round after player attacks
        resolve. Ordering is load-bearing:

        1. **Death check first.** If the hydra has ZERO live heads,
           the hydra dies -- there is no brain left to direct it.
           ``self.health`` is set to 0 and a death flavor string is
           returned. This check MUST fire before regrowth, otherwise
           regrowth would always save the hydra and the "kill every
           head in a single round" win condition would be unreachable.
        2. **Count destroyed heads** (of any age -- regrowth catches
           up from earlier rounds, not just the current round).
        3. **Spawn replacements.** 2 new heads per destroyed head
           (traditional hydra mythology), clamped by the available
           slots under :attr:`MAX_HEADS`. If the cap is already full,
           returns a "biological limit" flavor string.
        4. **Clean up destroyed heads** from ``body_parts`` so they
           don't contribute debuffs or appear in the targeting pool.

        New heads are appended to ``self.body_parts`` with unique
        names (``"head.N"``) so per-head attack-source labels
        remain distinguishable in combat display.
        """
        live_heads = [
            p for p in self.body_parts
            if isinstance(p, HeadPlugin) and not p.is_critical
            and not p.is_destroyed()
        ]
        destroyed_heads = [
            p for p in self.body_parts
            if isinstance(p, HeadPlugin) and not p.is_critical
            and p.is_destroyed()
        ]
        live_count = len(live_heads)

        # 1. Death check -- no live heads means death BEFORE regrowth.
        #    If this check moved below regrowth, the hydra would
        #    always spawn 2 new heads from the first destroyed stump
        #    and the "kill every head in a single round" win
        #    condition would be unreachable.
        if live_count == 0:
            self.health = 0
            return parse(
                "The last head falls. With no brain to direct it, @1's "
                "body collapses in a lifeless heap.",
                self,
            )

        # 2. Count destroyed heads (any age).
        destroyed_count = len(destroyed_heads)
        if destroyed_count == 0:
            return ""  # Nothing to regrow, nothing to say.

        # 3. Regrowth budget: 2 per destroyed head, capped by the
        #    number of free slots under MAX_HEADS.
        slots_available = max(0, self.MAX_HEADS - live_count)
        to_spawn = min(destroyed_count * 2, slots_available)

        # Spawn new heads with unique names using the counter.
        for i in range(to_spawn):
            self.body_parts.append(
                BodyPart.make(
                    "head", is_critical=False,
                    name=f"head.{self._next_head_number}",
                    exposure={Reach.MELEE: 0.4, Reach.REACH: 0.5,
                              Reach.THROWN: 0.7, Reach.RANGED: 1.0},
                )
            )
            self._next_head_number += 1

        # Remove destroyed heads from body_parts -- they've been
        # replaced (or the cap was reached).  This prevents destroyed
        # heads from contributing USELESS debuffs and from appearing
        # in the targeting pool.
        self.body_parts = [
            p for p in self.body_parts
            if not (isinstance(p, HeadPlugin) and not p.is_critical
                    and p.is_destroyed())
        ]

        if to_spawn == 0:
            return parse(
                "The @1's severed stumps writhe but produce nothing -- "
                "it has reached its biological limit.",
                self,
            )

        if to_spawn == 1:
            return parse(
                "A single new head forces its way from a severed stump "
                "-- the @1 is nearing its biological limit.",
                self,
            )
        return parse(
            f"Where the severed heads fell, {to_spawn} more burst from "
            f"the stumps with bone-wet cracks.",
            self,
        )
