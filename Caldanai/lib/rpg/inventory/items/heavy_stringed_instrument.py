from random import choice

from bson import ObjectId

from Caldanai.lib.rpg.creatures import Creature
from Caldanai.lib.rpg.creatures.player import Player
from Caldanai.lib.rpg.inventory.items import Item
from Caldanai.lib.rpg.inventory.rarity import Rarity


class ItemPlugin(Item):
	def __init__(self, iid: ObjectId = None, rarity: Rarity = None):
		super().__init__(
			iid=iid,
			name="heavy, stringed instrument",
			desc="Not what you wanted when you asked for phat lewt.",
			unit_weight=10.0,
			unit_value=8,
			image="heavy_stringed_instrument128.png",
			rarity=rarity,
			article='a',
			plugin='heavy_stringed_instrument'
		)

	def use(self, target: Creature = None) -> str:
		if target is None:
			return f"A {self.name} seems to play of its own accord..."

		p_name = f"{target.name if isinstance(target, Player) else 'a' + ('n ' if target.name[0] in 'aeiouh' else ' ') + target.name}"
		p_name_caps = p_name if isinstance(target, Player) else p_name.capitalize()

		msgs = [
			f"{p_name_caps} strums the strings of {target.pronouns['possessive']} {self.name}.",
			f"A playful melody erupts from {self.get_full_name()} as {p_name}'s fingers dance along the strings.",
			f"{p_name_caps} sounds out a few tentative chords on {target.pronouns['possessive']} {self.name}."
		]
		return choice(msgs)
