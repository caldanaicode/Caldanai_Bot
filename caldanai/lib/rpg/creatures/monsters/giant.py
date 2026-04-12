from caldanai.lib.rpg.creatures.monsters import MonsterPlugin
from caldanai.lib.rpg.helpers.enums import AggressionLevels, TimePartitions, DamageTypes
from caldanai.lib.rpg.creatures import Creature
from caldanai.lib.rpg.creatures.body_part import BodyPart
from caldanai.lib.rpg.helpers.dice import Dice


class Giant(MonsterPlugin):
    def __init__(self):
        super().__init__(
            name="giant",
            atk="2d10",
            defense="2d8",
            dodge="1d4",
            health_max="5d10"
        )

        self.time_partition = TimePartitions.DIURNAL
        self.image = None
        self.aggression = AggressionLevels.RAMPAGE
        self.arrival = "The ground trembles slightly as a @1 trudges in."
        self.flavor = "This @1 would blend in nicely with the surrounding rocks, if @1s would stop moving."
        self.escape = "The @1 looks around the area with a wary eye, then lopes off to destinations unknown."
        self.death = (
            "The @1 wobbles unsteadily for a moment, then crashes backward into the earth sending out a "
            "small tremor."
        )

        self.traits[DamageTypes.RANGED] = 0.75
        self.traits[DamageTypes.PIERCING | DamageTypes.SLASHING] = 1.0
        self.traits[DamageTypes.MAGICAL] = 1.50
        self.traits[
            DamageTypes.ANY - (DamageTypes.RANGED | DamageTypes.PIERCING | DamageTypes.SLASHING | DamageTypes.MAGICAL)
        ] = 0.5

        self.loot["rock"] = 0.7
        self.loot["sledgehammer"] = 0.2
        self.loot["spear"] = 0.2
        self.loot["ice_axe"] = 0.1

        self.body_parts = BodyPart.humanoid()

    def on_hugged(self, actor: Creature, invocation: str) -> str:
        dmg = Dice.quick_roll("1d4")
        attempt = Dice.quick_roll("1d20")
        msg = f"*@2 approaches the @1 for a {invocation}. The @1 flicks @2o away with a rumbling chuckle.*"
        if attempt >= actor.get_dodge():
            msg += f" @2 takes {dmg} point{'s' if dmg > 1 else ''} of damage!"
            m = actor.apply_damage(dmg)
            msg += f"\n{m}" if len(m) > 0 else ""
        else:
            msg += "\n*@2 tumbles deftly to avoid taking damage!*"
        return msg
