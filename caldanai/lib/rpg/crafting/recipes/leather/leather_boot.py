from caldanai.lib.rpg.crafting import RecipePlugin as _Base


class RecipePlugin(_Base):
    output = "leather_boot"
    materials = {"leather": 2}
    skill = "leatherworking"
    min_skill = 0
