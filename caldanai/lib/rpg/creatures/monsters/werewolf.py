"""``Werewolf`` monster plugin — LARGE cursed predator.

Design notes
============

The werewolf encountered is already in its lupine form — the curse
binds transformation to moonlight. This is modeled structurally
rather than with a status-effect transform:

- ``time_partition = NOCTURNAL`` — werewolves only spawn at night.
- ``flees_from_time = True`` + ``time_flee`` message — dawn forces
  the creature to retreat, presumably to resume human form
  somewhere out of sight.

Target preference: ~30% throat (`head`). Predatory but less
obsessive than the bearowl's 40% — werewolves are cursed humans,
not pure apex predators, so they're slightly less disciplined.

Trait profile: the traditional werewolf weakness is silver, but the
game doesn't model silver as a damage type. ``LIGHT * 2.0`` stands
in for holy/blessed vulnerability; otherwise standard physical.

Dawn-adjacent layered mechanics
-------------------------------

The base engine already handles the actual dawn-flee (see
``Game.check_time``). On top of that, this plugin layers:

- **Dawn desperation** — once the current hour is within ~1h of
  ``MORNING``, ``get_attack_sources`` adds a second "Desperate Lunge"
  alongside the normal bite, and ``on_pre_retaliation`` emits a
  one-time announcement. Mechanically: the werewolf *knows* time is
  running out and gets reckless. Untargeted (normal exposure
  weighting) — the desperation is about urgency, not precision.
- **Throat-bite narration** — when an attack destroys the target's
  head part, the attacker-side ``on_target_part_destroyed`` hook
  emits a distinctive predator-kill beat. Reinforces the throat-bite
  target preference that was already biasing head-selection.
- **Partial-human reveal on death** — the death narration is
  strengthened from "seems almost to flicker" into an explicit
  partial reversion, with an extra second line appended via
  ``apply_damage`` so the player gets the full reveal beat.
- **Flee loot (dead hook)** — ``flee_loot`` declares what the
  werewolf leaves behind on a dawn retreat (a shred of bloody
  clothing torn off as it bolts). ``get_flee_loot`` is not yet
  wired into the engine; this is the forward-compatible stub.
"""

from random import choice
from typing import List, Optional

from caldanai.lib.rpg.combat.attack_source import (
    AttackSource, NaturalAttackSource,
)
from caldanai.lib.rpg.creatures.monsters import MonsterPlugin
from caldanai.lib.rpg.creatures.body_builder import quadruped_tree
from caldanai.lib.rpg.creatures import Creature
from caldanai.lib.rpg.helpers.enums import (
    AggressionLevels, DamageTypes, Size, TimePartitions, TimesOfDay,
)
from caldanai.lib.rpg.helpers.parser import parse
from caldanai.lib.rpg.time import get_time_components, get_next_time


class Werewolf(MonsterPlugin):
    BODY_TREE = quadruped_tree()

    # Throat-bite bias: ~30% of attacks target the head. Less
    # obsessive than the bearowl (40%) because the werewolf is a
    # cursed human, not a pure predator — still instinctual but a
    # little more scattered.
    TARGET_PREFERENCES = {"head": 0.3}

    # Window, in game-hours, before the current time rolls over into
    # MORNING during which the werewolf is considered "desperate".
    _DESPERATION_WINDOW_HOURS = 1.0

    def __init__(self):
        super().__init__(
            name="werewolf",
            atk="2d8",       # bite + claw
            defense="1d6",
            dodge="2d8",
            health_max="8d10",
        )

        self.time_partition = TimePartitions.NOCTURNAL
        self.flees_from_time = True
        self.time_flee = (
            "@1dc throws back @1a head and howls as the first grey light of "
            "dawn creeps across the sky. Before the second breath, @1s has "
            "bounded into the treeline and is gone."
        )
        self.image = None
        self.aggression = AggressionLevels.RAMPAGE

        self.arrival = choice([
            "A low, unhurried growl drifts from the shadows; @1i pads into "
            "view, eyes reflecting moonlight like two pale coins.",
            "Claws click against stone as @1i rounds the corner, hackles "
            "raised and lips already peeled back from yellowed teeth.",
            "@1ic bursts from the underbrush in a coiled rush, too large "
            "for a wolf and too canny for an animal.",
        ])

        self.flavor = choice([
            "Too big. Too deliberate. This is no ordinary wolf — "
            "something human stares out from behind those eyes.",
            "@1dc moves with a terrible patience, the way something "
            "hungry does when it is not yet desperate.",
            "The pelt is matted in patches, as if @1s was caught "
            "between shapes once and the seams never quite took.",
        ])

        self.escape = (
            "@1dc circles once, gauging the odds, then melts back into "
            "the forest with a final snarl."
        )

        # Death strings describe the fatal blow; the partial-human
        # reveal is appended afterward in ``apply_damage`` so it
        # consistently lands regardless of which opener rolled.
        self.death = choice([
            "@1dc collapses with a rattling whine, a final tremor running "
            "the length of @1a frame.",
            "@1dc sags onto @1a side, the great ribcage shuddering once "
            "and then going still.",
            "@1dc drops mid-lunge, claws scoring the earth in a last "
            "reflexive spasm before @1s stops moving.",
        ])

        # Post-death revelation appended by ``apply_damage``. Separated
        # from the fatal-blow line so the moment lands as its own beat.
        self._death_revelation = choice([
            "As the body cools, the pelt thins in patches; a clavicle "
            "here, a human jawline there, push up through the fur. "
            "Whatever @1s was in life, @1s was not only a wolf.",
            "The carcass gives a slow, dry shiver — and when it stills "
            "again the proportions are subtly wrong for a wolf. Long "
            "fingers curl inside what had been paws.",
            "Under the moonlight the dead shape seems to *remember* "
            "itself: snout shortening by degrees, spine uncoiling, until "
            "what lies in the grass is almost — almost — a person.",
        ])

        # Weakness to holy (silver-stand-in via LIGHT).
        self.traits[DamageTypes.LIGHT] = 2.00
        self.traits[DamageTypes.FIRE] = 1.50
        self.traits[DamageTypes.BLUDGEONING] = 0.75  # muscle under pelt
        self.traits[DamageTypes.PIERCING] = 1.25

        self.loot["leather"] = 0.6
        self.loot["shortsword"] = 0.1  # presumably human's gear
        self.loot["wallet"] = 0.2

        # Dawn-flee evidence. Not yet wired into the engine (see base
        # ``MonsterPlugin.flee_loot`` comment) — declaring it here so
        # the hook is meaningful once a caller exists.
        self.flee_loot["leather"] = 0.5

        # Quadruped shape for the wolf form (head, torso, 4 legs, tail).

        self.size = Size.LARGE
        self._scale_part_hp()

        # ``self._channel_id`` is inherited from Creature and populated
        # by ``Game.get_monster`` at spawn. Narrow access to time
        # state goes through the ``caldanai.lib.rpg.time`` façade —
        # the werewolf can't accidentally mutate the clock or reach
        # into arbitrary Game internals.
        self._announced_desperation = False

    # -- Dawn desperation -----------------------------------------------

    def _is_near_dawn(self) -> bool:
        """True when the next time-of-day boundary is ``MORNING`` and
        we're within ``_DESPERATION_WINDOW_HOURS`` of crossing it.

        The base engine's ``check_time`` already handles the actual
        flee transition — this window is strictly narrative/desperate
        territory in the lead-up.
        """
        if self._channel_id is None:
            return False
        components = get_time_components(self._channel_id)
        next_time = get_next_time(self._channel_id)
        if components is None or next_time is None:
            return False
        h, m, _ = components
        next_name, next_h, next_m = next_time
        if next_name != TimesOfDay.MORNING.name:
            return False
        remaining = ((24 if h > next_h else 0) + next_h + next_m / 60) - (h + m / 60)
        return remaining < self._DESPERATION_WINDOW_HOURS

    def get_attack_sources(self) -> List[AttackSource]:
        """Standard bite normally. When dawn is near, a second
        ``Desperate Lunge`` joins the bite — roughly doubles expected
        damage output, mirroring cyclops-style multi-source emergence.
        Normal exposure weighting on target selection (desperation is
        about urgency, not aim)."""
        sources = super().get_attack_sources()
        if self._is_near_dawn():
            sources = list(sources) + [
                NaturalAttackSource(
                    atk="2d8",
                    label="Desperate Lunge",
                    skill="natural",
                ),
            ]
        return sources

    def on_pre_retaliation(self, damage_by_player) -> str:
        """One-time announcement when desperation kicks in. Subsequent
        rounds stay desperate (get_attack_sources keeps adding the
        lunge) but don't re-announce.

        Lives on ``on_pre_retaliation`` so the desperation flare lands
        above the werewolf's attack table — the dawn-pressure mood
        shift is what fuels the upcoming desperate lunge, not a
        reaction to it."""
        if self._is_near_dawn() and not self._announced_desperation:
            self._announced_desperation = True
            return parse(
                "@1dc's nostrils flare toward the eastern horizon. "
                "Dawn's weight settles on @1o and @1s bolts forward "
                "with teeth bared — nothing to lose now.",
                self,
            )
        return ""

    # -- Throat-bite narration ------------------------------------------

    def on_target_part_destroyed(
        self, victim: Creature, part: BodyPart,
    ) -> str:
        """Predator-signature narration when the werewolf's attack
        destroys the victim's head (throat bite connecting). Other
        parts defer to the default (no attacker-side beat)."""
        if part.name == "head":
            return parse(
                "Jaws close around @2's throat with a sickening crunch; "
                "@1dc worries the grip once, twice, and does not let go.",
                self, victim,
            )
        return ""

    # -- Death: fatal blow + partial-human reveal -----------------------

    def apply_damage(
        self,
        amount: int,
        dmg_type: Optional[DamageTypes] = None,
        target_part: Optional[BodyPart] = None,
    ) -> Optional[str]:
        """Extends the base death message with the transformation
        reveal when the damage is fatal. The reveal renders as a
        second sentence so combat narration reads as two distinct
        beats: the kill, then the recognition of what they killed."""
        msg = super().apply_damage(
            amount,
            dmg_type=dmg_type,
            target_part=target_part,
        )
        if msg and self._death_revelation:
            # msg is already the death string; parser tokens inside
            # the revelation are resolved against ``self`` (the dying
            # werewolf).
            msg = f"{msg}\n{self._death_revelation}"
        return msg

    def on_hugged(self, actor: Creature, invocation: str) -> str:
        return choice([
            f"@1dc tolerates the {invocation} for precisely one second, "
            "then @1a lips peel back in a warning snarl.",
            f"@1dc leans into the {invocation} for a bewildered moment "
            "before remembering what @1s is.",
            f"A deep growl rolls up through @1a chest as @2 attempts a "
            f"{invocation}. @2 decides perhaps later is better.",
        ])
