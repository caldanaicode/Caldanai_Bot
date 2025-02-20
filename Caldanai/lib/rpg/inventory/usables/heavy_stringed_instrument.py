from random import choice

from bson import ObjectId

from Caldanai.lib.rpg import parse
from Caldanai.lib.rpg.creatures import Creature
from Caldanai.lib.rpg.creatures.player import Player
from Caldanai.lib.rpg.helpers.enums import Qualities
from Caldanai.lib.rpg.inventory import Usable


class UsablePlugin(Usable):
    def __init__(self, iid: ObjectId = None, quality: Qualities = None):
        super().__init__(
            iid=iid,
            name="heavy, stringed instrument",
            desc="Not what you wanted when you asked for phat lewt.",
            unit_weight=10.0,
            unit_value=8,
            image="heavy_stringed_instrument128.png",
            quality=quality,
        )

    def use(self, user: Creature = None) -> str:
        if user is None:
            return parse("A @1 seems to play of its own accord...", self)

        p_name = f"{'the ' if not isinstance(user, Player) else ''}@2"
        p_name_caps = p_name if isinstance(user, Player) else p_name.capitalize()

        msgs = [
            f"{p_name_caps} strums the strings of @2a @1.",
            f"A playful melody erupts from {self.get_full_name()} as {p_name}'s fingers dance along the strings.",
            f"{p_name_caps} sounds out a few tentative chords on @2a @1.",
        ]
        return parse(choice(msgs), self, user)
