from caldanai.lib.rpg.crafting import RecipePlugin as _Base


class RecipePlugin(_Base):
    output = "leather_greave"
    materials = {"leather": 4}
    skill = "leatherworking"
    min_skill = 0
