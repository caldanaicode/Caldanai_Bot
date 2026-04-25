"""Regression tests for the body-injury indicator on the
``$look`` / spawn embed's stat block.

Surfaces "this stat is reduced because of body damage" via a 🩹
marker next to Defense / Dodge when the emergent value falls
below the creature's intrinsic base. The 2026-04-24 playtest
flagged silent stat drops as confusing — Phase C's localized
aggregation is visibly working, but a falling number with no
annotation reads as a UI bug.

Marker logic is "emergent < intrinsic", not "any injury exists":
a minor injury that doesn't actually move the aggregate stays
unannotated. Conversely, armor pushing a stat ABOVE intrinsic
doesn't trigger the marker (the player just equipped it; the
boost is self-explanatory).
"""

from caldanai.lib.rpg.creatures.body_parts import BodyPartPlugin
from caldanai.lib.rpg.creatures.player import Player


BodyPartPlugin.load_plugins()


def _fresh_player() -> Player:
    return Player(uid=1, gid=2, cid=3)


def _embed_field_value(embed, name: str) -> str:
    for f in embed.fields:
        if f.name == name:
            return f.value
    raise AssertionError(f"missing embed field {name!r}; have: "
                         f"{[f.name for f in embed.fields]}")


class TestNoMarkerOnHealthyCreature:
    def test_defense_field_has_no_marker(self):
        p = _fresh_player()
        embed, _ = p.get_embed()
        assert "\U0001fa79" not in _embed_field_value(embed, "Defense")

    def test_dodge_field_has_no_marker(self):
        p = _fresh_player()
        embed, _ = p.get_embed()
        assert "\U0001fa79" not in _embed_field_value(embed, "Dodge")


class TestMarkerOnInjuredCreature:
    def test_destroyed_torso_marks_defense(self):
        """Torso destruction should cripple defense aggregation —
        emergent drops below intrinsic."""
        p = _fresh_player()
        torso = p.get_part("torso")
        # Bypass apply_damage's death check by setting health
        # directly. The aggregation still reads the part state.
        torso.health = 0
        # Sanity: emergent should now be below intrinsic.
        assert p.get_defense() < p.defense
        embed, _ = p.get_embed()
        assert "\U0001fa79" in _embed_field_value(embed, "Defense")

    def test_destroyed_leg_marks_dodge(self):
        """Leg destruction reduces emergent dodge below intrinsic."""
        p = _fresh_player()
        leg = p.get_part("leg.left")
        leg.health = 0
        assert p.get_dodge() < p.dodge
        embed, _ = p.get_embed()
        assert "\U0001fa79" in _embed_field_value(embed, "Dodge")
