from random import choice

from caldanai.lib.rpg.creatures.monsters import MonsterPlugin
from caldanai.lib.rpg.helpers.enums import AggressionLevels, TimePartitions, DamageTypes, Size
from caldanai.lib.rpg.creatures import Creature
from caldanai.lib.rpg.creatures.body_builder import humanoid_tree
from caldanai.lib.rpg.helpers.dice import Dice


class Giant(MonsterPlugin):
    BODY_TREE = humanoid_tree()

    # Age-variant size pool. Picked uniformly at spawn so any given
    # giant could be young (LARGE), mature (HUGE), or elder (COLOSSAL).
    SIZE_VARIANTS = [Size.LARGE, Size.HUGE, Size.COLOSSAL]

    # Per-hit narration: huge slabs of muscle and thick hide blunt
    # most damage; ranged attacks lose force across the distance.
    # Magic at giant-scale is the great leveller.
    HIT_NARRATIONS = {
        DamageTypes.MAGICAL:     "Arcane force ripples through @1a vast frame; even mountains feel magic.",
        DamageTypes.SLASHING:    "The blade opens a long, shallow line in @1a thick hide.",
        DamageTypes.PIERCING:    "The point sinks into @1a flesh but seems lost in the mass of @1o.",
        DamageTypes.BLUDGEONING: "The blow lands heavy; @1s shifts a half-step but doesn't fall.",
    }
    # Bow shafts read undersized against the target. Wand falls
    # through to base HIT_NARRATIONS[MAGICAL] (mountains-feel-magic).
    RANGED_NARRATIONS = {
        DamageTypes.PIERCING:    "The shot strikes @1d but seems undersized for the target — a thrown pebble against a hill.",
    }

    def __init__(self):
        super().__init__(
            name="giant",
            atk="2d10",
            defense="5d3",
            dodge="5d3",
            health_max="25d12"
        )

        self.time_partition = TimePartitions.DIURNAL
        self.image = None
        self.aggression = AggressionLevels.RAMPAGE
        self.arrival = "The ground trembles slightly as @1i trudges in."
        self.flavor = "This @1 would blend in nicely with the surrounding rocks, if @1s would stop moving."
        self.escape = "@1dc looks around the area with a wary eye, then lopes off to destinations unknown."
        self.death = (
            "@1dc wobbles unsteadily for a moment, then crashes backward into the earth sending out a "
            "small tremor."
        )

        # Anything fired at a giant under-delivers — the projectile
        # is undersized relative to the target. Same shape regardless
        # of damage type (arrow shaft or arcane bolt, both look
        # small against a hill). Captured as ranged_traits[ANY] so
        # both bow and wand pick it up at the dispatcher.
        self.ranged_traits[DamageTypes.ANY] = 0.75
        self.traits[DamageTypes.PIERCING | DamageTypes.SLASHING] = 1.0
        self.traits[DamageTypes.MAGICAL] = 1.50
        self.traits[
            DamageTypes.ANY - (DamageTypes.PIERCING | DamageTypes.SLASHING | DamageTypes.MAGICAL)
        ] = 0.5

        self.loot["rock"] = 0.7
        self.loot["sledgehammer"] = 0.2
        self.loot["spear"] = 0.2
        self.loot["ice_axe"] = 0.1
        self.loot["giant_toe"] = 0.25

        # Age-variant size pick: a young giant is LARGE, a mature one
        # HUGE, an elder COLOSSAL.
        self.size = choice(self.SIZE_VARIANTS)
        self._scale_part_hp()
        # Leathery hide over slab-of-meat mass — modest +2 torso armor.
        for part in self.body_parts:
            if part.name == "torso":
                part.defense_bonus = 2

    def on_hugged(self, actor: Creature, invocation: str) -> str:
        dmg = Dice.quick_roll("1d4")
        attempt = Dice.quick_roll("1d20")
        msg = f"*@2 approaches @1d for a {invocation}. @1dc flicks @2o away with a rumbling chuckle.*"
        if attempt >= actor.get_dodge():
            msg += f" @2 takes {dmg} point{'s' if dmg > 1 else ''} of damage!"
            # ``apply_damage`` returns a non-empty string on state
            # transitions (Player death / resurrection, Monster death)
            # and ``""`` otherwise. ``if m:`` handles both.
            m = actor.apply_damage(dmg)
            if m:
                msg += f"\n{m}"
        else:
            msg += "\n*@2 tumbles deftly to avoid taking damage!*"
        return msg
