from os import sep
from random import choice, random, sample
from typing import Dict, List, Optional, Union

from Caldanai import PluginManager
from Caldanai.lib.rpg import GameClock, parse
from Caldanai.lib.rpg.creatures import Creature
from Caldanai.lib.rpg.helpers.enums import (AggressionLevels, TimePartitions,
                                            TimesOfDay)
from Caldanai.lib.rpg.inventory import Inventory, Item
from Caldanai.Logger import get_logger

_log = get_logger(__name__)



class MonsterPlugin(Creature):
    """Base class for Monster-type plugins. This class should not be
    instantiated directly."""

    BASEPATH: str = sep.join([
        'Caldanai',
        'lib',
        'rpg',
        'creatures',
        'monsters'
    ])

    def __init__(
            self,
            name: Optional[str],
            atk: Optional[str],
            defense: Optional[Union[str, int]],
            dodge: Optional[Union[str, int]],
            health_max: Optional[Union[str, int]],
            health: Optional[int] = None,
            gender: Optional[str] = None,
            pronouns: Optional[str] = None
    ):
        super().__init__(
            name, atk, defense, dodge, health_max, health, gender, pronouns)

        self.aggression = AggressionLevels.PASSIVE
        self.time_partition = TimePartitions.CATHEMERAL
        self.dies_from_time = False
        self.time_death = ""
        self.flees_from_time = False
        self.time_flee = ""
        self.arrival = ""
        self.flavor = ""
        self.escape = ""
        self.death = ""
        self.loot: Dict[str, float] = {}

    def on_combat_round(self, damage_by_player: list) -> str:
        """Called after players attack but before the monster retaliates.
        Override to react to per-player damage dealt this round.

        :param damage_by_player: List of (Player, int) tuples with damage dealt this round.
        :return: An optional message string to display, or empty string.
        """
        return ""

    def on_spawn(self, game) -> str:
        """Called after the monster is placed into the game. Override to perform
        setup that requires access to the game state (players, channel, etc.).

        :param game: The Game instance this monster was spawned into.
        :return: An optional message string to display, or empty string.
        """
        return ""

    def apply_damage(self, amount: int) -> str:
        was_alive = self.health > 0
        super().apply_damage(amount)
        if was_alive and self.is_dead():
            return self.death

        return ""

    @staticmethod
    def get_random_monster(clock: GameClock) -> Optional['MonsterPlugin']:
        """Retrieves a random"""
        time = TimesOfDay[clock.get_time_of_day().upper()].value

        candidates = [
            cls for cls in PluginManager.LOADED_PLUGINS[MonsterPlugin]
            if bool(time & cls().time_partition)
        ]
        if not candidates:
            return None

        return choice(candidates)()

    # Returns a list of loot items
    def get_loot(self) -> list:
        items: List[Item] = []
        for name, freq in self.loot.items():
            if name not in Inventory.ITEMS.keys():
                Inventory.discover_items()

            if name in Inventory.ITEMS.keys():
                if random() <= freq:
                    item = Inventory.ITEMS[name].from_plugin(name, {})
                    if item:
                        items.append(item)
            else:
                _log.warning(f"No such item '{name}' found in the Inventory.ITEMS list.")

        return items

    def attack_random(self, combatants: list, count=1) -> str:
        if combatants and 0 < count <= len(combatants):
            victims = sample(combatants, count)
            msg = None
            for victim in victims:
                sequence = self.do_attack(victim)
                msg = sequence.to_markdown()
                total_dmg = sequence.total_damage()
                if total_dmg > 0:
                    msg += parse(victim.apply_damage(total_dmg), victim)

            return msg

        return None

    @staticmethod
    def load_plugins():
        PluginManager.load(MonsterPlugin, MonsterPlugin.BASEPATH)
