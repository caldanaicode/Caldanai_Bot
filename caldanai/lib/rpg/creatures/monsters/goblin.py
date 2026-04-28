from random import choice
from caldanai.lib.rpg.creatures.monsters import MonsterPlugin
from caldanai.lib.rpg.helpers.enums import AggressionLevels, TimePartitions, DamageTypes, Size
from caldanai.lib.rpg.creatures import Creature
from caldanai.lib.rpg.creatures.body_builder import humanoid_tree
from caldanai.lib.rpg.helpers.dice import Dice


class Goblin(MonsterPlugin):
    BODY_TREE = humanoid_tree()

    # Per-hit narration: spiteful little things, brittle bones make
    # bludgeoning especially effective. Their innate magical
    # affinity sheds arcane attacks. Sliced/pierced flesh is sharp
    # but the bone gives easily.
    HIT_NARRATIONS = {
        DamageTypes.BLUDGEONING: "The blow lands with a sickening crack — goblin bones break easily.",
        DamageTypes.SLASHING:    "The blade scores @1d shallowly; sinewy hide tugs back against the cut.",
        DamageTypes.PIERCING:    "The point glances off @1a wiry build, finding less to bite into than it expected.",
        DamageTypes.MAGICAL:     "Arcane force slides off @1d strangely, as if @1s were already half-magical itself.",
    }

    # Spawn-time armor loadout — same scrap pieces as bandits
    # (goblins steal the same kind of mismatched gear), at lower
    # spawn rates because goblins are scrappier and lose pieces
    # easily. No collars / sashes / extra layers — the ornamental
    # bandit-flair touches don't fit goblin theming.
    SPAWN_LOADOUT = {
        "head":  [("rough_cap",        0.20, "worn",        (50, 95))],
        "torso": [("rough_jerkin",     0.20, "worn",        (50, 95))],
        "arm":   [("patchwork_bracer", 0.20, "worn.lower",  (50, 95))],
        "hand":  [("ratty_glove",      0.20, "worn",        (50, 95))],
        "leg":   [("rough_greave",     0.15, "worn.upper",  (50, 95))],
        "foot":  [("worn_boot",        0.20, "worn",        (50, 95))],
    }

    def __init__(self):
        super().__init__(
            name="goblin",
            atk="1d8",
            defense="1d10",
            dodge="1d10",
            health_max="3d10"
        )

        self.time_partition = TimePartitions.CATHEMERAL
        self.image = None
        self.aggression = AggressionLevels.SURVIVE
        self.arrival = choice(
            [
                f"With a spluttering snarl, @1i {choice('bursts|pads|runs'.split('|'))} into the area.",
                "A screeching laugh shatters the serenity that once lingered here, as @1i finds @1a way hither.",
            ]
        )

        self.flavor = choice(["This @1 is so ugly @1s is almost cute.", "A green and gray blob of stupidity."])

        self.escape = f"@1dc snorts, a vacant eye roaming the surroundings before @1s trudges off."
        self.death = (
            f"@1dc's eyes bulge as if @1s only now realized @1s was outmatched, and @1s flops onto the "
            f"ground unceremoniously."
        )

        self.traits[DamageTypes.BLUDGEONING] = 1.50
        self.traits[DamageTypes.PIERCING | DamageTypes.SLASHING] = 0.75
        self.traits[DamageTypes.MAGICAL] = 0.5

        self.loot["stick"] = 0.5
        self.loot["rock"] = 0.5
        self.loot["torch"] = 0.3
        self.loot["spear"] = 0.1

        self.size = Size.SMALL
        self._scale_part_hp()

    # Reacts to hugs.
    def on_hugged(self, actor: Creature, invocation: str) -> str:
        msg = f"@1dc hoots at @2 and backs away, flailing erratically."
        attempt = Dice.quick_roll("1d20")
        if attempt >= actor.get_dodge():
            dmg = Dice.quick_roll("1d4")
            msg += f" @2 is caught off-guard and takes {dmg} point{'s' if dmg > 1 else ''} of damage!"
            m = actor.apply_damage(dmg)
            msg += f"\n{m}" if m else ""
        else:
            msg += "\n@2 narrowly avoids @1d's thrashing!"

        return msg
