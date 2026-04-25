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
- ``on_pre_retaliation`` emits a one-time bellow the round the eye
  goes out, so the wild-swing attack table that follows is
  contextualized — the bellow lands above the table because it's
  what causes the wild swings.

No target preference override — even rampaging, the cyclops is
flailing, not aiming. Standard exposure-weighted random selection.
"""

from random import choice

from caldanai.lib.rpg.combat.attack_source import (
    AttackSource, NaturalAttackSource,
)
from caldanai.lib.rpg.creatures.monsters import MonsterPlugin
from caldanai.lib.rpg.creatures.body_builder import node, paired
from caldanai.lib.rpg.creatures.body_parts.arm import ArmPlugin
from caldanai.lib.rpg.creatures.body_parts.eye import EyePlugin
from caldanai.lib.rpg.creatures.body_parts.foot import FootPlugin
from caldanai.lib.rpg.creatures.body_parts.hand import HandPlugin
from caldanai.lib.rpg.creatures.body_parts.head import HeadPlugin
from caldanai.lib.rpg.creatures.body_parts.leg import LegPlugin
from caldanai.lib.rpg.creatures.body_parts.neck import NeckPlugin
from caldanai.lib.rpg.creatures.body_parts.torso import TorsoPlugin
from caldanai.lib.rpg.creatures import Creature
from caldanai.lib.rpg.helpers.enums import (
    AggressionLevels, DamageTypes, Size, TimePartitions,
)
from caldanai.lib.rpg.helpers.parser import parse


class Cyclops(MonsterPlugin):
    # Humanoid with Phase D segmented limbs, plus a SINGLE eye
    # (no .left/.right suffix — no pair). The symmetrization
    # pass only syncs ``.left``/``.right`` names, and rendering
    # shows ``"eye"`` rather than ``"left eye"``.
    BODY_TREE = node(TorsoPlugin, name="torso", children=[
        node(NeckPlugin, name="neck", children=[
            node(HeadPlugin, name="head", children=[
                node(EyePlugin, name="eye"),
            ]),
        ]),
        *paired(
            ArmPlugin, "arm",
            children_builder=lambda side: [
                node(HandPlugin, name=f"hand.{side}"),
            ],
        ),
        *paired(
            LegPlugin, "leg",
            children_builder=lambda side: [
                node(FootPlugin, name=f"foot.{side}"),
            ],
        ),
    ])

    # Per-hit narration: cyclops is a huge sack of flesh — most
    # weapons land messily but cleanly. Mild fire sensitivity (the
    # only deviation from baseline 1.0×) gets its own line.
    HIT_NARRATIONS = {
        DamageTypes.FIRE: "Flame finds @1a coarse hair and oily skin readily; @1s bellows at the unfamiliar pain.",
    }

    def __init__(self):
        super().__init__(
            name="cyclops",
            atk="2d10",          # huge club, big swings
            defense="2d8",       # thick hide
            dodge="1d6",         # sluggish — HUGE size already pushes this down
            health_max="20d12",  # tanky
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

        self.size = Size.HUGE
        self._scale_part_hp()
        # Thick hide per creature comment above. The single eye keeps
        # its class-default SOFT_PART (clamps to 0) — signature weakness.
        for part in self.body_parts:
            if part.name == "torso":
                part.defense_bonus = 5

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

    def pick_actions(self):
        """B4 combat routes through the action-pool path (part
        DEFAULT_ACTIONS × ACTION_REPERTOIRE), which would otherwise
        make the blind-cyclops's ``get_attack_sources`` override
        dead code — the cyclops would keep politely chestbutting
        and biting even mid-rampage. Short-circuit here: when the
        eye is destroyed, abandon the part-vocabulary entirely and
        return the three flailing wild swings directly. Flavor
        matches mechanics — a blinded cyclops doesn't pick targets
        with discipline."""
        if self._is_blind():
            return self.get_attack_sources()
        return super().pick_actions()

    def on_pre_retaliation(self, damage_by_player) -> str:
        """One-time bellow the round the eye is destroyed. Returns
        empty string in all other cases (including subsequent blind
        rounds — the rage is ongoing but the *announcement* only
        fires once).

        Lives on ``on_pre_retaliation`` (not ``on_combat_round``) so
        the bellow lands above the wild-swing attack table — the
        bellow is what *causes* the wild swings, not a reaction to
        them."""
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
