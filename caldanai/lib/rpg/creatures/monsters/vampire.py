from random import choice, randint

from caldanai.lib.rpg import MonsterPlugin, parse
from caldanai.lib.rpg.combat.attack_result import AttackSequence
from caldanai.lib.rpg.creatures.body_part import BodyPart
from caldanai.lib.rpg.helpers.enums import (
    AggressionLevels, DamageTypes, Size, TimePartitions)
from caldanai.lib.rpg.creatures import Creature
from caldanai.lib.rpg.helpers.dice import Dice


class Vampire(MonsterPlugin):
    # Vampires fixate on the throat: ~40% of non-feeding attacks go
    # for the head (neck-bite targeting). This is a targeting bias
    # only — no status effect. Feeding is a separate path handled by
    # ``do_attack`` / ``feed`` when the vampire drops below half HP.
    #
    # Head exposure in melee is ``0.7``, so aiming at it inflates
    # effective dodge by ~1.43× — harder than a random swing but
    # still landable on a decent roll. Eye targeting (exposure ``0.1``)
    # was rejected for this reason: it inflates dodge 10×, making
    # the preference ~only reachable via a nat-20 override, which
    # wastes most "fixated" attacks.
    TARGET_PREFERENCES = {"head": 0.4}

    def __init__(self):
        super().__init__(
            name="vampire",
            atk="8d4",
            defense="1d4",
            dodge="3d10",
            health_max="18d12"
        )

        self.time_partition = TimePartitions.NOCTURNAL
        self.dies_from_time = True
        self.time_death = (
            "@1dc cries out in unimaginable pain as the light of day rolls over @1a body. Just as "
            "the sound becomes unbearable, @1s suddenly goes still, and @1a form explodes into a shower of miniature "
            "meteorites sailing in all directions."
        )
        self.flees_from_time = True
        self.time_flee = (
            "As the light of dawn approaches, @1d hisses with frustration, clearly unsatisfied "
            "with the night's hunt. With a final glare, @1s fades into a ball of shadow and zips away."
        )
        self.image = None
        self.aggression = AggressionLevels.RAMPAGE
        self.arrival = "Shadows coalesce into a humanoid shape as @1i materializes. @1ac hungry gaze sweeps the area."

        self.flavor = choice(
            [
                "@1dc radiates malevolent hunger.",
                "@1ac gaze is as sharp as @1a teeth.",
                "The shadows shifting about this @1 produce an aura of cold dread, as if defying the very existence of life.",
            ]
        )

        self.escape = choice(
            [
                "With nary a sound, @1d slips back into the darkness.",
                "@1dc melts into a pool of shadows, vanishing into the night.",
                "@1dc explodes into a cloud of bats, scattering in all directions.",
            ]
        )

        self.death = choice(
            [
                "@1dc screeches horribly as @1s bursts into flame. Soon, naught remains but ash.",
                "With a final gasp of disbelief, @1d slows to a halt as dark tendrils spread outward from @1a chest. "
                "After a moment, the husk crumbles and drifts away.",
            ]
        )

        self.traits[DamageTypes.ANY - (DamageTypes.FIRE | DamageTypes.LIGHT)] = 0.5
        self.traits[DamageTypes.LIGHT] = 2.0
        self.traits[DamageTypes.FIRE] = 1.5

        self.loot["cape"] = 0.2
        self.loot["high-collared_cape"] = 0.1
        self.loot["wand"] = 0.1

        self.body_parts = BodyPart.humanoid()

        self.size = Size.MEDIUM
        self._scale_part_hp()

    def feed(self, target: Creature) -> str:
        """
        Attempts to feed from a target, regenerating its own health.

        :param target: The creature being targeted.
        :return: A string indicating the results of the feeding
        """

        if target.health <= 0:
            return parse("@1dc sneers at the lifeless husk of @2.", self, target)

        amount = randint(1, target.health)
        attempt = Dice.quick_roll("1d20") + 4
        msg = (
            "@1dc's eyes darken as @1a gaze settles upon @2. With a burst of unbelievable speed, "
            "@1d's form blurs as @1s rushes headlong at @1a victim."
        )

        if attempt >= target.get_dodge():
            msg += "\n\n@2 stands paralyzed before @1d, and cries out as fangs plunge into " "@2a throat."

            msg += f"\n\n**@2 is drained of {amount} health!**"

            if m := target.apply_damage(amount):
                msg += f"\n\n{m}"

            msg += (
                "\n\n@1dc licks the blood from @1a lips, and a wicked smile carves a path across @1a face as "
                "wounds begin to mend."
            )
            self.apply_damage(amount * -2)

        else:
            msg += "\n\nAmazingly, @2's quick reflexes see @2o safely out of harm's way!"

        return parse(msg, self, target)

    def on_hugged(self, actor: Creature, invocation: str) -> str:
        responses = [
            "An overwhelming sense of foreboding roots @2 in place.",
            "The hungry, piercing gaze of @1d paralyzes @2.",
            f"@1dc smiles seductively at @2, encouraging the {invocation}...",
        ]

        response = choice(responses)
        if response == responses[2]:
            response += f"\n{self.feed(actor)}"

        return response

    def do_attack(self, creature: Creature) -> AttackSequence:
        if self.health / self.health_max <= 0.5:
            return AttackSequence(attacker=self, target=creature, narrative=self.feed(creature))
        return super().do_attack(creature)

    def attack_random(self, combatants: list, count=1):
        """Override the Phase 6b pipeline-driven base so the
        feed-at-low-HP mechanic survives the refactor. Mirrors the
        pre-6b behavior where ``do_attack`` swapped to a feed-only
        narrative sequence when HP <= 50%.

        Phase 6c/6d / API-narrator work may later port this onto a
        creature-level ``ACTION_REPERTOIRE`` with side-effect hooks;
        the thin override is the scope-appropriate Phase 6b fix."""
        if (
            combatants
            and 0 < count <= len(combatants)
            and self.health / self.health_max <= 0.5
        ):
            victim = combatants[0] if count == 1 else choice(combatants)
            return self.feed(victim)
        return super().attack_random(combatants, count)
