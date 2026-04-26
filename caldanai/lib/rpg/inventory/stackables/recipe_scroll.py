"""Recipe scroll — a stackable item that teaches a single recipe.

Encodes the recipe it teaches in ``recipe_name`` so a single
plugin file covers every variant. Stacking compares
``recipe_name`` so scrolls for different recipes don't merge into
one stack. Weightless on purpose — a small parchment shouldn't
eat into the inventory weight budget.
"""
from bson import ObjectId

from caldanai.lib.rpg.helpers.enums import Qualities
from caldanai.lib.rpg.inventory.stackables import Stackable


class StackablePlugin(Stackable):
    def __init__(
        self,
        iid: ObjectId = None,
        quality: Qualities = None,
        count: int = 1,
        recipe_name: str = "",
    ):
        # Pretty-print: "leather_jerkin" → "leather jerkin recipe"
        readable = recipe_name.replace("_", " ") if recipe_name else "blank"
        super().__init__(
            iid=iid,
            name=f"{readable} recipe",
            desc=(
                f"A folded parchment with the steps for crafting "
                f"{readable}. ``$learn`` it to add to your known recipes."
            ),
            unit_weight=0.0,
            unit_value=10,
            image=None,
            quality=quality,
            article="a",
            plural=f"{readable} recipes",
            count=count,
        )
        self.recipe_name = recipe_name

    def can_stack(self, other: "StackablePlugin") -> bool:
        return (
            super().can_stack(other)
            and getattr(other, "recipe_name", None) == self.recipe_name
        )

    def to_dict(self) -> dict:
        d = super().to_dict()
        d["recipe_name"] = self.recipe_name
        return d
