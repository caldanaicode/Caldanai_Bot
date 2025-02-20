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

    def apply_damage(self, amount: int) -> str:
        was_alive = self.health > 0
        super().apply_damage(amount)
        if was_alive and self.is_dead():
            return self.death

        return ""

    @staticmethod
    def get_random_monster(clock: GameClock) -> 'MonsterPlugin':
        """Retrieves a random"""
        time = TimesOfDay[clock.get_time_of_day().upper()].value

        monster = choice(PluginManager.LOADED_PLUGINS[MonsterPlugin])()
        while (not bool(time & monster.time_partition)):
            monster = choice(PluginManager.LOADED_PLUGINS[MonsterPlugin])()

        return monster

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
            m = None
            for victim in victims:
                m, d = self.do_attack(victim)
                if d > 0:
                    m += parse(victim.apply_damage(d), victim)

            return m

        return None

    @staticmethod
    def load_plugins():
        PluginManager.load(MonsterPlugin, MonsterPlugin.BASEPATH)
