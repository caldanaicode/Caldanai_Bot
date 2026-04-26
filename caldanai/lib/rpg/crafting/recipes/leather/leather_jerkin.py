from caldanai.lib.rpg.crafting import RecipePlugin as _Base


class RecipePlugin(_Base):
    output = "leather_jerkin"
    materials = {"leather": 5}
    skill = "leatherworking"
    min_skill = 0
