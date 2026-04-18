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
- **First-physical-hit narrative** (also ``_on_attacked``): the first
  time a player lands a physical swing — regardless of the
  multiplier-chewed final damage — set a one-shot flag so the next
  ``on_combat_round`` can surface "your blade passes through" as a
  teaching moment. Lives on ``_on_attacked`` rather than
  ``apply_damage`` because the sequence helper skips
  ``apply_damage`` for zero-damage hits (and physical-vs-spirit is
  always zero after the 0.1 multiplier), so the flag would never
  set if it waited for damage to be applied.
- **Fade state** (≤25% HP): drain stops working ("the stolen warmth
  slips through it now") because the spirit is too thin to siphon.
  Closes the otherwise-exploitable drain-heals-keep-fighting loop
  while preserving narrative weight.
"""

from random import choice

from caldanai.lib.rpg.combat.attack_source import NaturalAttackSource
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

        # State tracker for the one-time fade announcement.
        # The per-attack "passes through like mist" line fires
        # every landed physical hit via ``_on_attacked`` — no flag
        # needed for that one; it's a per-hit observation, not a
        # one-shot callout.
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

    _PHYSICAL_TYPES = (
        DamageTypes.BLUDGEONING | DamageTypes.SLASHING | DamageTypes.PIERCING
    )

    def _on_attacked(self, attacker, source, result):
        """Runs on every landed attack against the spirit. Two
        concerns share this hook, both surfacing via
        ``result.extra_text`` so their narration lands inline with
        the attack-table row that observed the event (not tucked
        into a post-round footer).

        1. **Physical-passes-through callout** — on every landed
           physical hit, append "the blow passes through like
           mist" to ``result.extra_text``. Fires each physical
           attack, not just the first: the observation is per-hit
           evidence of the intangibility trait (physical multiplier
           truncates to 0), not a one-shot teaching moment.
           Weapon-agnostic wording so it reads correctly whether
           the player swings a blade, a stick, or a wand.
           Lives on ``_on_attacked`` (not ``apply_damage``) because
           physical hits multiply to zero damage and the sequence
           helper skips ``apply_damage`` on zero-damage results.
        2. **Melee cold counter-touch** — attackers inside melee
           reach take 1d4 cold damage from the freezing aura, with
           "chill saps N from the attacker" appended to
           ``extra_text``.

        Both append rather than overwrite so they compose cleanly
        with any prior ``get_hit_narration`` line and with each
        other (dual-wielded physical attack in melee range =
        "passes through like mist — chill saps N from the attacker").
        """
        if not result.hit():
            return  # no contact, no chill, no intangibility reveal

        if (
            source.damage_type is not None
            and (source.damage_type & self._PHYSICAL_TYPES)
        ):
            _append_extra_text(result, "the blow passes through like mist")

        if source.reach != Reach.MELEE:
            return
        cold = Dice.quick_roll("1d4")
        if cold <= 0:
            return
        attacker.apply_damage(cold, dmg_type=DamageTypes.WATER)
        _append_extra_text(result, f"chill saps {cold} from the attacker")

    # -- Combat round narrative ------------------------------------------

    def on_combat_round(self, damage_by_player) -> str:
        """One-time fade-state announcement.

        The first-physical-hit callout lives in ``_on_attacked`` now
        — surfaced via ``result.extra_text`` so it lands inline with
        the attack-table row, not after the monster's counter-attack.
        """
        if self._is_fading() and not self._has_faded:
            self._has_faded = True
            return parse(
                "@1dc thins, @1a outline rippling like heat haze. The "
                "stolen warmth slips through @1o now, leaking back "
                "into the world.",
                self,
            )
        return ""

    def on_hugged(self, actor: Creature, invocation: str) -> str:
        return choice([
            f"@2's arms close around a brief chill where @1d used to be. "
            f"@1dc has drifted a polite pace backward.",
            f"The {invocation} passes straight through @1o. @1dc regards "
            "@2 with something that might be pity.",
            f"@1dc does not respond to the {invocation} so much as fail "
            "to notice it. The chill lingers for a moment afterward.",
        ])


def _append_extra_text(result, snippet: str) -> None:
    """Append a snippet to an ``AttackResult.extra_text`` field,
    joining with ' — ' when there's already content. Extracted
    because ``Spirit._on_attacked`` has two independent hook
    consumers (intangibility callout + cold counter-touch) that
    both want to contribute to the same per-hit narration line."""
    existing = result.extra_text
    result.extra_text = f"{existing} — {snippet}" if existing else snippet
