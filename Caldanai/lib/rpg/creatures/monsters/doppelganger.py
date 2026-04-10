from random import choice

from Caldanai.lib.rpg import get_random_direction, Player
from Caldanai.lib.rpg.creatures.monsters import MonsterPlugin
from Caldanai.lib.rpg.helpers.enums import AggressionLevels, TimePartitions, Qualities
from Caldanai.lib.rpg.creatures import Creature
from Caldanai.Logger import get_logger


_log = get_logger(__name__)


class Doppelganger(MonsterPlugin):
    def __init__(self):
        super().__init__(
            name="???",
            atk="2d10",
            defense="6d4",
            dodge="6d4",
            health_max="40d4"
        )

        self.time_partition = TimePartitions.CATHEMERAL
        self.aggression = AggressionLevels.RAMPAGE
        self.image = None

        self.arrival = choice(
            [
                "A pale creature with dimly-glowing putrid-yellow eyes lopes into the area.",
                "A lumpy, misshapen humanoid slinks into view.",
            ]
        )

        self.flavor = choice(
            [
                "This creature seems to defy definition as it is quite difficult to tell what, exactly, one is looking at.",
                "The flesh of this creature seems to shift both size and shape, disturbingly devoid of description.",
            ]
        )

        self.escape = choice(
            [
                '"Oh yes, I think I\'ll keep this one for a while," the creature exclaims with a creepy squeal of '
                "delight, loping swiftly out of view!",
                f'"You\'ll never catch this one, you meddling kids," the creature shrieks as it escapes to the '
                f"{get_random_direction()}!",
            ]
        )

        self.death = choice(
            [
                "The creature lets out a final cough before dissolving into shapeless ooze.",
                "The @1 coughs blood before collapsing to the ground.",
                '"In another life, you could have been me," the @1 gasps with @1a dying breath.',
            ]
        )

        self.loot["shortsword"] = 0.2
        self.loot["bandanna"] = 0.2
        self.loot["bow"] = 0.15
        self.loot["cheese_sandwich"] = 0.2
        self.loot["wallet"] = 0.25

    def on_spawn(self, game) -> str:
        """Imitates a random player on spawn."""
        players = list(game.player_manager.players.values())
        if players:
            target = choice(players)
            return self.imitate(target)
        return ""

    def imitate(self, target: Creature) -> str:
        """
        Assumes a creature's form and stats.

        :param target: The creature being targeted.
        :return: A string indicating the results of the imitation.
        """

        if not isinstance(target, Player):
            return ""

        self.name = target.name

        # Copy stats, taking the better of current vs target
        defense = target.get_defense()
        dodge = target.get_dodge()
        health_max = target.get_health_max()
        self.defense = max(self.defense, defense)
        self.dodge = max(self.dodge, dodge)
        # Take the min of current HP vs the new max so we don't heal
        new_max = max(self.health_max, health_max)
        self.health = min(self.health, new_max)
        self.health_max = new_max

        # Add the player's inventory items to the loot table with re-rolled rarity
        for item in target.inventory.all():
            quality = choice(list(Qualities))
            base_freq = quality.value["multiplier"] * 0.1
            self.loot[item.plugin] = self.loot.get(item.plugin, 0) + base_freq

        _log.debug(f"Doppelganger imitated {target.name}")

        return (
            "\nThe amorphous creature's body begins to shift, stretch, and squash. The form's movements are "
            f"both disturbing and fascinating, as it molds itself slowly into the likeness of {target.name}."
        )

    def on_combat_round(self, damage_by_player: dict) -> str:
        """Imitate whoever hit the hardest this round."""
        if not damage_by_player:
            return ""

        hardest_hitter = max(damage_by_player, key=damage_by_player.get)
        if isinstance(hardest_hitter, Player):
            return self.imitate(hardest_hitter)
        return ""

    def on_hugged(self, actor: Creature, invocation: str) -> str:
        return choice(
            [
                f"@1 breaks down crying at the first affection @1s has ever known, as @2 {invocation}s @1o.",
                f"@1 sneers at @2's attempt to {invocation} @1o.",
                f"@1 mirrors @2's {invocation} back perfectly, and for a moment it's unclear who is hugging whom.",
                f"@2 reaches out to {invocation} @1, but @1a form shifts uncomfortably and @2's arms pass through thin air.",
                f"@1 accepts the {invocation} with unsettling enthusiasm, @1a features flickering between faces.",
            ]
        )
