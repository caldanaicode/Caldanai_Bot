"""World — non-creature physical features that live in an Area.

Static objects (campfire, stone field, named tree, cairn, etc.)
live here, distinct from monsters / passersby (which spawn and
depart) and from the area's scenery prose (which is fixed).
A static object has state, responds to verbs, contributes to
ambience, and can react to weather.

Plugin discovery mirrors :class:`PasserbyPlugin` — auto-load from
``world/objects/<stem>.py`` at startup, instantiate per-area
when the area is registered with a game.
"""
