"""``Cyclops`` monster plugin — HUGE one-eyed brute.

Design notes
============

The signature feature is the **single eye**. Where most humanoids
don't bother with eye parts at all (the default ``BodyPart.humanoid``
template is eyeless for monsters), the cyclops has exactly one — named
``eye`` rather than ``eye.left``/``eye.right``. This interacts with
the existing ``Creature.get_hit_modifier`` emergence in a satisfying
way:

- ``get_hit_modifier`` checks for eyes first, falling back to heads.
- With one eye, full functionality = ratio 1.0, HIT penalty 0.
- Destroy the eye and functionality drops to 0.0 → HIT penalty -5.

Blinding a cyclops is a *very* real thing to aim for, but it doesn't
make the cyclops *safer* — it triggers **blind rage**:

- ``get_attack_sources`` returns *three* wild swings instead of one,
  each rolling ``3d10`` instead of the normal ``2d10``.
- Each swing still pays the -5 HIT penalty automatically (via
  ``Creature.get_hit_modifier``), so individual swings land less
  often, but with three rolls of bigger dice the *expected* round
  damage is roughly tripled. Bad luck during a blinded fight can
  catch a complacent player off-guard.
- ``on_combat_round`` emits a one-time bellow the round the eye
  goes out, so the table that follows is contextualized.

No target preference override — even rampaging, the cyclops is
flailing, not aiming. Standard exposure-weighted random selection.
"""

from random import choice

from caldanai.lib.rpg.combat.attack_source import (
    AttackSource, NaturalAttackSource,
)
from caldanai.lib.rpg.creatures.monsters import MonsterPlugin
from caldanai.lib.rpg.creatures.body_part import BodyPart
from caldanai.lib.rpg.creatures import Creature
from caldanai.lib.rpg.helpers.enums import (
    AggressionLevels, DamageTypes, Size, TimePartitions,
)
from caldanai.lib.rpg.helpers.parser import parse


class Cyclops(MonsterPlugin):
    def __init__(self):
        super().__init__(
            name="cyclops",
            atk="2d10",          # huge club, big swings
            defense="2d8",       # thick hide
            dodge="1d6",         # sluggish — HUGE size already pushes this down
            health_max="10d10",  # tanky
        )

        self.time_partition = TimePartitions.CATHEMERAL
        self.image = None
        self.aggression = AggressionLevels.RAMPAGE

        self.arrival = choice([
            "The ground shudders as @1i lumbers into the clearing, a "
            "single eye fixing on whoever moves first.",
            "A deep, guttural rumble precedes @1i; its lone eye rolls "
            "lazily across the party.",
            "@1ic stoops through the treeline, uprooted saplings dangling "
            "from @1a fist.",
        ])

        self.flavor = choice([
            "A mountain of pale muscle topped with a single unblinking "
            "eye. @1sc seems surprised to see anyone so small.",
            "This @1 smells of wet stone and old meat. Its gaze is "
            "bewildered, then murderous.",
            "Easily twice the height of a tall man, with one great eye "
            "that tracks movement like a bird of prey.",
        ])

        self.escape = (
            "@1dc grunts, confused by the commotion, and turns to stomp off "
            "toward distant hills."
        )

        self.death = choice([
            "@1dc's knees buckle; the ground shakes as @1s hits it, "
            "the light fading from @1a single eye.",
            "@1dc lets out a long, low moan — almost mournful — and topples "
            "like a felled oak.",
        ])

        # No particular trait profile — the cyclops is just a big angry
        # sack of meat. Mild fire sensitivity for pseudo-realism.
        self.traits[DamageTypes.FIRE] = 1.25

        # Loot — sledgehammer-class gear plus whatever it's been hoarding.
        self.loot["sledgehammer"] = 0.5
        self.loot["warhammer"] = 0.3
        self.loot["rock"] = 0.9
        self.loot["wallet"] = 0.5
        self.loot["small_gem"] = 0.3

        # Standard humanoid torso/limbs, plus a single eye.
        # The eye is named without .left/.right because there is no
        # pair — this matters for the symmetrization pass (which only
        # syncs ``.left``/``.right`` names), and for how rendering
        # displays the part ("eye" rather than "left eye").
        parts = BodyPart.humanoid()
        parts.append(BodyPart.make("eye", name="eye"))
        self.body_parts = parts

        self.size = Size.HUGE
        self._scale_part_hp()

        # Tracks the one-time blind-rage announcement so the bellow
        # only fires the round the eye actually goes out, not every
        # round thereafter.
        self._has_raged = False

    def _is_blind(self) -> bool:
        eye = self.get_part("eye")
        return eye is not None and eye.is_destroyed()

    def get_attack_sources(self):
        """Single 2d10 swing normally; three 3d10 wild swings when
        blinded. The -5 HIT penalty applies automatically to each
        swing via ``Creature.get_hit_modifier``."""
        if self._is_blind():
            return [
                NaturalAttackSource(
                    atk="3d10", label="Wild Swing", skill="natural",
                ),
                NaturalAttackSource(
                    atk="3d10", label="Frenzied Smash", skill="natural",
                ),
                NaturalAttackSource(
                    atk="3d10", label="Berserk Strike", skill="natural",
                ),
            ]
        return super().get_attack_sources()

    def on_combat_round(self, damage_by_player) -> str:
        """One-time bellow the round the eye is destroyed. Returns
        empty string in all other cases (including subsequent blind
        rounds — the rage is ongoing but the *announcement* only
        fires once)."""
        if self._is_blind() and not self._has_raged:
            self._has_raged = True
            return parse(
                "@1dc bellows in blinding agony, gore streaming from the "
                "ruined socket. @1sc lashes out wildly in every direction, "
                "no longer caring what @1s hits!",
                self,
            )
        return ""

    def on_hugged(self, actor: Creature, invocation: str) -> str:
        return choice([
            "@1dc stares down at @2 with a single enormous eye, "
            "utterly baffled by the gesture.",
            "@1dc rumbles and half-heartedly pats @2 with a fist the size "
            "of a small boulder. @2 is briefly compressed.",
            f"@1dc does not understand being {invocation}ged, and opts to "
            "pick @2 up like a doll instead.",
        ])
