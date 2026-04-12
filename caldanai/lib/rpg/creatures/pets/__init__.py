from typing import Optional
from ..... import PluginManager

from .....logger import get_logger
from .. import Creature
from ...helpers.enums import TimePartitions, TrophicLevels
from ...inventory.usables.consumables import Consumable


_log = get_logger(__name__)


class PetPlugin(Creature):
    """
    Base class for Pet-type plugins. This class should not be
    instantiated directly.

    Pets are non-combative creatures, purely intended to add
    more variety to the RPG.
    """

    BASEPATH: str = 'caldanai/lib/rpg/creatures/pets'

    def __init__(
            self,
            name: Optional[str],
            gender: Optional[str] = None,
            pronouns: Optional[str] = None,
            bonded: Optional[Creature] = None
    ):
        super().__init__(
            name=name,
            gender=gender,
            pronouns=pronouns)

        self.time_partition = TimePartitions.CATHEMERAL
        self.arrival = ""
        self.flavor = ""
        self.escape = ""
        self.abandon = ""
        self.hunger = 0.0
        self.activity_frequency = 0.0
        self.dietary_habits = TrophicLevels.HERBIVORE
        self.bonded = bonded
        self.mood = 0.0

    def eat(self, food: Consumable) -> Optional[str]:
        """Feed a pet the provided consumable. This should be overridden to provide character in plugins."""
        if food.trophic_levels & self.dietary_habits and food.uses_left > 0:
            response, _ = food.use(self)
            return response
        else:
            return None

    def pet(self) -> Optional[str]:
        raise NotImplementedError("This must be overridden in the plugin")


PluginManager.load(PetPlugin, PetPlugin.BASEPATH)
