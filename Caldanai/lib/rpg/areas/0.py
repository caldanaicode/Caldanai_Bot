from Caldanai.lib.rpg.areas import Area
from Caldanai.lib.rpg.helpers.enums import Directions


class AreaPlugin(Area):
	def __init__(self):
		super().__init__()
		self.name = "The Beginning"
		self.brief = ""
		self.verbose = "From the midst of an open meadow, a forest can be spotted to the south and east. Rolling " \
					   "hills lead to mountains along the northern horizon. To the west, a meandering river forms a " \
					   "delta as it joins the ocean."

		self.directions = {
			Directions.NORTH: "It is difficult to ascertain much from this distance, but the rolling hills are dotted "
							  "with trees and boulders. They seem to stretch for miles before meeting the base of the "
							  "mountains. The peaks of the mountains are jagged and steep, with the tops of the "
							  "tallest covered in an ever-present snow.",

			Directions.SOUTH: "A sprawling expanse of immense trees stretches as far as the eye can see. Decidedly "
							  "deciduous, the trees come in a plethora of varieties and colors. The canopy is thick "
							  "and shadows quickly engulf what lies beneath.",

			Directions.EAST: "A sprawling expanse of immense trees stretches as far as the eye can see. Decidedly "
							  "deciduous, the trees come in a plethora of varieties and colors. The canopy is thick "
							  "and shadows quickly engulf what lies beneath.",

			Directions.SOUTHEAST: "A sprawling expanse of immense trees stretches as far as the eye can see. Decidedly "
								  "deciduous, the trees come in a plethora of varieties and colors. The canopy is "
								  "thick and shadows quickly engulf what lies beneath.",

			Directions.WEST: "From this distance, the rivers appears calm and meandering. After a few gentle bends, "
							 "it branches several times forming a rather large delta before the ocean consumes it. "
							 "The ocean spreads beyond sight, its deep blue tint marred by the white caps of waves "
							 "rolling toward the shore."
		}
