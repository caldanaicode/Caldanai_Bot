import random
from typing import Any, Optional
from . import PetPlugin
from ...helpers.enums import TrophicLevels
from ...inventory.usables.consumables import Consumable


class Finch(PetPlugin):

    def __init__(
            self,
            name: Optional[str],
            gender: Optional[str],
            pronouns: Optional[str],
            bonded: Optional[Any]
    ):
        super().__init__(
            name, gender, pronouns, bonded
        )

        self.dietary_habits: TrophicLevels = TrophicLevels.GRANIVORE | TrophicLevels.FRUGIVORE
        self.activity_frequency: float = 0.8
        self.arrival = random.choice([
            "A tiny finch zips into the area, flitting about aimlessly.",
            "A rapid fluttering of tiny wings announces the arrival of a finch, who alights upon a branch.",
            "A small blur whirs across the area, tumbling into a patch of leaves with a soft chirp; a hungry finch peeks out nervously from the leaves."
        ])
        self.abandon = "The finch chirps in agitation, evasively darting around before disappearing into the distance."
        self.escape = "Perhaps seeking food elsewhere, the finch takes wing, vanishing to regions unknown."

    def eat(self, food: Consumable) -> str:
        pass

    def pet(self) -> str:
        pass