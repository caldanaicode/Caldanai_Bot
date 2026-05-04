from random import choice

from caldanai.lib.rpg.areas import Area
from caldanai.lib.rpg.helpers import get_random_direction
from caldanai.lib.rpg.helpers.enums import Directions


class AreaPlugin(Area):
    # Meadow ambience — wildlife, breezes, weather-adjacent flavor.
    # Migrated 2026-05-03 from the legacy ``Game.do_ambience`` inline
    # pool; lines that draw on random helpers (direction, scent) are
    # callables so they evaluate fresh per pick.
    AMBIENCE_POOL = [
        "A squirrel bounds across the ground, and up a nearby tree.",
        "A bush rustles as something skitters unseen within.",
        lambda: f"A lonesome howl floats in from the {get_random_direction()}.",
        "Happy warbling resounds as a songbird flits across the area.",
        lambda: f"A pack of wolves serenades from the {get_random_direction()}.",
        "At the edge of the wood-line, a bear trundles about curiously for a moment before disappearing into"
        " the trees.",
        "The ground trembles slightly for a moment, though whether from earthquake or monstrosity is"
        " impossible to determine.",
        "A choir of insectile sound rises, thousands of tiny voices calling out to each other.",
        lambda: (
            f"A {choice('gentle|strong|slow|light|moderate'.split('|'))} breeze stirs the area, bringing the"
            f" scent of {choice('the sea|dust|pine|animal musk|death'.split('|'))} with it."
        ),
        "Some unknown creature blazes a trail throughout the tall grasses nearby.",
    ]

    def __init__(self):
        super().__init__()
        self.name = "The Beginning"
        self.brief = ""
        self.verbose = (
            "From the midst of an open meadow, a forest can be spotted to the south and east. Rolling "
            "hills lead to mountains along the northern horizon. To the west, a meandering river forms a delta as it "
            "joins the ocean."
        )

        self.directions = {
            Directions.NORTH: "It is difficult to ascertain much from this distance, but the rolling hills are dotted with trees "
            "and boulders. They seem to stretch for miles before meeting the base of the mountains. The peaks of "
            "the mountains are jagged and steep, with the tops of the tallest covered in an ever-present snow.",
            Directions.SOUTH
            | Directions.EAST
            | Directions.SOUTHEAST: "A sprawling expanse of immense trees stretches as far as the eye can see. Decidedly deciduous, "
            "the trees come in a plethora of varieties and colors. The canopy is thick and shadows quickly engulf "
            "what lies beneath.",
            Directions.WEST: "From this distance, the rivers appears calm and meandering. After a few gentle bends, it branches "
            "several times forming a rather large delta before the ocean consumes it. The ocean spreads beyond "
            "sight, its deep blue tint marred by the white caps of waves rolling toward the shore.",
        }
