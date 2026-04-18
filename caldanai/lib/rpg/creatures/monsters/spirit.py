"""``Spirit`` monster plugin — incorporeal undead.

Design notes
============

Spirits are the one creature that intentionally has **no body parts**.
Physically, there's nothing to target — you can't aim at the ghost's
left arm because there isn't one. The combat system's legacy
whole-body path handles this cleanly:

- ``target.body_parts`` is empty → ``pick_random_part`` returns None
  → ``target_part`` on the AttackResult is None.
- The rendering leaves the "→ part" suffix off (no target_part).
- ``Creature.apply_damage`` with no target_part uses the legacy
  ``self.health -= amount`` path.
- Dodge/defense emergence falls back to the raw ``self.dodge`` /
  ``self.defense`` values (see ``Creature.get_dodge`` /
  ``get_defense``).
- ``$look`` on a spirit renders no "Body Parts" field (the shared
  renderer returns empty when there are no parts).

The cost of this is that spirits sidestep the injury-tracking and
per-part display systems — which is exactly the point. A ghost is
supposed to feel mechanically unusual.

Trait profile makes physical weapons near-useless:

- ``BLUDGEONING / SLASHING / PIERCING * 0.1`` — your sword passes
  through.
- ``LIGHT * 2.5`` — holy banishment works spectacularly.
- ``FIRE * 1.25`` — pure heat chars them out slowly.
- ``MAGICAL * 1.0`` — magic treats them like any other target.
- ``DARK * 0.25`` — they are of the dark.

Spirit-specific mechanics layered on top
========================================

- **Life drain** (``drain_ratio = 0.5`` on the natural attack):
  every successful hit heals the spirit by half the damage dealt.
  Generic mechanism living in ``NaturalAttackSource.drain_ratio`` +
  ``Creature._on_attack_resolved``.
- **Cold counter-touch** (``_on_attacked`` override): melee attackers
  take a small amount of cold damage just for closing to melee range.
  Encourages ranged / magical engagement.
- **First-physical-hit narrative** (``apply_damage`` override): the
  first time a player swings physical for trivial damage, surface
  "your blade passes through" as a teaching moment.
- **Fade state** (≤25% HP): drain stops working ("the stolen warmth
  slips through it now") because the spirit is too thin to siphon.
  Closes the otherwise-exploitable drain-heals-keep-fighting loop
  while preserving narrative weight.
"""

from random import choice
from typing import Optional

from caldanai.lib.rpg.combat.attack_source import (
    AttackSource, NaturalAttackSource,
)
from caldanai.lib.rpg.combat.attack_result import AttackResult
from caldanai.lib.rpg.creatures.classifications import Undead
from caldanai.lib.rpg.creatures.monsters import MonsterPlugin
from caldanai.lib.rpg.creatures import Creature
from caldanai.lib.rpg.helpers.dice import Dice
from caldanai.lib.rpg.helpers.enums import (
    AggressionLevels, DamageTypes, Reach, Size, TimePartitions,
    WeatherPatterns,
)
from caldanai.lib.rpg.helpers.parser import parse


class Spirit(Undead, MonsterPlugin):
    def __init__(self):
        super().__init__(
            name="spirit",
            atk="2d4",           # ethereal touch — draining, not crushing
            defense="1d4",       # no body to armor
            dodge="3d8",         # hard to hit what isn't physically there
            health_max="4d10",
        )

        self.time_partition = TimePartitions.NOCTURNAL | TimePartitions.CREPUSCULAR
        # Spirits manifest in still, spooky weather — clear nights,
        # overcast skies, and especially fog. Strong wind disperses
        # them (matches the daemon's fog/wind dispersal invariant),
        # and rain's chaotic movement drives them back to whatever
        # rest they're fleeing.
        self.weather_partition = (
            WeatherPatterns.CLEAR
            | WeatherPatterns.CLOUDY
            | WeatherPatterns.FOG
        )
        self.flees_from_time = True
        self.time_flee = (
            "@1dc thins at the edges as the first light of day filters in; "
            "@1a form dissipates with a sound like a long sigh."
        )
        self.image = None
        self.aggression = AggressionLevels.SURVIVE

        self.arrival = choice([
            "A cold drift of air precedes @1i — @1ic fades into view, "
            "translucent and softly glowing.",
            "The temperature drops several degrees and @1i resolves "
            "from the gloom, unsupported by any visible substance.",
            "@1ic slips through a wall that wasn't there a moment ago, "
            "pausing to regard the living with something like curiosity.",
        ])

        self.flavor = choice([
            "Vaguely humanoid, vaguely luminous, entirely unsettling. "
            "@1ac edges flicker as if uncertain of their own outline.",
            "The shape of someone who used to be. What's left trails "
            "slowly after @1a gestures.",
            "@1dc does not cast a shadow. Whatever still animates @1o "
            "seems to remember having a face.",
        ])

        self.escape = (
            "@1dc's attention wanders; @1s drifts through the nearest "
            "solid surface and is gone."
        )

        self.death = choice([
            "@1dc comes apart in slow ribbons of pale light, each one "
            "unravelling into nothing.",
            "With a sound like glass under snow, @1d's form collapses "
            "inward and winks out.",
        ])

        # ``Undead`` mixin (see classifications/undead.py) provides
        # the standard undead profile via setdefault: LIGHT 2.0,
        # FIRE 1.5, DARK 0.0, WATER 0.5. Spirit overrides each
        # value here for the incorporeal-undead flavor — most
        # damaging types matter much less, holy radiance matters
        # much more, and dark isn't a complete free pass (a ghost
        # is dark-aligned but not pure shadow). WATER is inherited
        # unmodified from the mixin.
        self.traits[DamageTypes.BLUDGEONING] = 0.10  # weapons pass through
        self.traits[DamageTypes.SLASHING] = 0.10
        self.traits[DamageTypes.PIERCING] = 0.10
        self.traits[DamageTypes.LIGHT] = 2.50         # holy banishes (stronger than standard undead)
        self.traits[DamageTypes.FIRE] = 1.25          # spirit fire is gentler than skeleton fire
        self.traits[DamageTypes.DARK] = 0.25          # not a free pass — ghosts aren't pure shadow
        self.traits[DamageTypes.MAGICAL] = 1.00       # magic treats ghosts normally

        # What does a ghost drop? Sometimes nothing. Occasionally a
        # trinket from before.
        self.loot["small_gem"] = 0.15
        self.loot["wallet"] = 0.10

        # Intentionally NO body parts — see module docstring.
        self.body_parts = []

        self.size = Size.MEDIUM
        # Don't call _scale_part_hp — nothing to scale, and the
        # symmetrization step is a no-op on an empty list anyway.

        # State trackers for one-time narratives.
        self._has_announced_intangibility = False
        self._has_faded = False

    # -- Faded state -----------------------------------------------------

    def _is_fading(self) -> bool:
        """Spirit drops below 25% HP — too thin to siphon life force,
        so drain disables. Narrative announcement fires once via
        ``on_combat_round``."""
        if self.health_max <= 0:
            return False
        return self.health / self.health_max < 0.25

    # -- Attack: ethereal touch with life drain --------------------------

    def get_attack_sources(self):
        """Single ethereal-touch attack with ``drain_ratio=0.5`` — the
        spirit heals half of damage dealt. Handled generically by the
        base ``Creature._on_attack_resolved`` reading ``drain_ratio``
        off the source."""
        return [
            NaturalAttackSource(
                atk="2d4",
                dmg_type=DamageTypes.DARK,
                label="Ethereal Touch",
                skill="natural",
                drain_ratio=0.5,
            ),
        ]

    def _on_attack_resolved(self, source, result):
        """Skip drain when fading — the narrative is that the spirit
        is too insubstantial to siphon warmth from the blow. Anything
        else (currently just the base drain logic) defers to super."""
        if self._is_fading():
            return  # no drain in this state
        super()._on_attack_resolved(source, result)

    # -- Reactive cold-touch on melee attackers --------------------------

    def _on_attacked(self, attacker, source, result):
        """Anyone who lands a melee blow takes 1d4 cold/water damage
        from the spirit's freezing aura. Adds to the incentive to
        engage at range or with magic. Appends to ``extra_text``
        rather than overwriting — ``get_hit_narration`` may have
        already set a flavor line there."""
        if source.reach != Reach.MELEE:
            return
        if not result.hit():
            return  # no contact, no chill
        cold = Dice.quick_roll("1d4")
        if cold <= 0:
            return
        attacker.apply_damage(cold, dmg_type=DamageTypes.WATER)
        chill = f"chill saps {cold} from the attacker"
        result.extra_text = (
            f"{result.extra_text} — {chill}" if result.extra_text else chill
        )

    # -- Apply damage: first-physical-hit narrative kicker ---------------

    _PHYSICAL_TYPES = (
        DamageTypes.BLUDGEONING | DamageTypes.SLASHING | DamageTypes.PIERCING
    )

    def apply_damage(
        self,
        amount,
        dmg_type=None,
        target_part=None,
    ) -> Optional[str]:
        """Detect the first time a player lands a (heavily-resisted)
        physical hit and set the one-shot intangibility-announcement
        flag; ``on_combat_round`` reads it next round and surfaces the
        narrative cue. Damage application defers to super.

        Historically returned ``None`` implicitly (dropping the
        MonsterPlugin death string), and combat paths don't depend on
        that return — ``Game.do_combat`` falls back to
        ``monster.death`` directly when the helper produces no death
        message. The signature is mirrored here for consistency with
        the rest of the Creature family; returning ``""`` preserves
        observable behavior (both ``None`` and ``""`` are falsy, so
        any ``if m:`` caller sees the same result).
        """
        super().apply_damage(
            amount,
            dmg_type=dmg_type,
            target_part=target_part,
        )
        if (
            not self._has_announced_intangibility
            and amount > 0
            and dmg_type is not None
            and (dmg_type & self._PHYSICAL_TYPES)
        ):
            self._has_announced_intangibility = True
        return ""

    # -- Combat round narrative ------------------------------------------

    def on_combat_round(self, damage_by_player) -> str:
        """Two one-time narrative announcements:
        1. First-physical-resisted hit: 'your blade passes through'.
        2. Crossing into fade state: 'too thin to siphon now'.
        Both fire at most once per encounter."""
        msgs = []
        if self._has_announced_intangibility and not getattr(
            self, "_intangibility_msg_emitted", False,
        ):
            self._intangibility_msg_emitted = True
            msgs.append(parse(
                "@2's blade passes through @1d like mist; what little "
                "force connects is shrugged off like a chill breeze.",
                self, *(p[0] for p in damage_by_player[:1]) or (self,),
            ) if damage_by_player else parse(
                "Steel passes through @1d like mist.", self,
            ))
        if self._is_fading() and not self._has_faded:
            self._has_faded = True
            msgs.append(parse(
                "@1dc thins, @1a outline rippling like heat haze. The "
                "stolen warmth slips through @1o now, leaking back "
                "into the world.",
                self,
            ))
        return "\n".join(msgs)

    def on_hugged(self, actor: Creature, invocation: str) -> str:
        return choice([
            f"@2's arms close around a brief chill where @1d used to be. "
            f"@1dc has drifted a polite pace backward.",
            f"The {invocation} passes straight through @1o. @1dc regards "
            "@2 with something that might be pity.",
            f"@1dc does not respond to the {invocation} so much as fail "
            "to notice it. The chill lingers for a moment afterward.",
        ])
