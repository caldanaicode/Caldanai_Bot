"""Tests for fuzzy body-part target parsing in ``RpgUserCommands``.

Covers ``_parse_part_targets`` — the command-layer adapter that turns
``$kill leg.r`` into a canonical list of part-name strings for
``Game.combat_targets`` and downstream ``do_attack`` resolution.
"""

from caldanai.lib.cogs.rpg_user_commands import RpgUserCommands
from caldanai.lib.rpg.creatures import Creature
from caldanai.lib.rpg.creatures.body_part import BodyPart


def _make_monster() -> Creature:
    c = Creature(
        name="goblin", atk="1d4", defense=2, dodge=5, health_max=20,
    )
    c.body_parts = [
        BodyPart(name="head", health_max=10),
        BodyPart(name="torso", health_max=20),
        BodyPart(name="arm.left", health_max=8),
        BodyPart(name="arm.right", health_max=8),
        BodyPart(name="leg.left", health_max=10),
        BodyPart(name="leg.right", health_max=10),
    ]
    return c


def _cog() -> RpgUserCommands:
    return RpgUserCommands(bot=None)


class TestParsePartTargets:
    def test_exact_dotted_name_canonical(self):
        assert _cog()._parse_part_targets("leg.right", _make_monster()) == ["leg.right"]

    def test_fuzzy_abbreviation_canonicalises(self):
        """``leg.r`` must resolve to ``leg.right`` so display renders
        as 'the right leg' rather than 'the r leg'."""
        assert _cog()._parse_part_targets("leg.r", _make_monster()) == ["leg.right"]
        assert _cog()._parse_part_targets("leg.l", _make_monster()) == ["leg.left"]

    def test_ambiguous_token_expands_to_canonical_names(self):
        """``leg`` matches both legs — expand to both canonical names
        so display renders cleanly and ``do_attack`` can distribute one
        name per source slot."""
        assert _cog()._parse_part_targets("leg", _make_monster()) == [
            "leg.left", "leg.right",
        ]

    def test_short_ambiguous_token_expands_all_matches(self):
        """``h`` matches head and anything else containing 'h' — every
        match contributes a canonical entry. Guards against the
        regression where ambiguous tokens rendered as 'the h'."""
        m = _make_monster()
        m.body_parts.append(BodyPart(name="hand.left", health_max=6))
        m.body_parts.append(BodyPart(name="hand.right", health_max=6))

        result = _cog()._parse_part_targets("h", m)
        assert result == ["head", "hand.left", "hand.right"]

    def test_multiple_tokens(self):
        result = _cog()._parse_part_targets("arm.l leg.r", _make_monster())
        assert result == ["arm.left", "leg.right"]

    def test_unknown_tokens_are_skipped(self):
        """Monster name or gibberish should silently drop out."""
        result = _cog()._parse_part_targets("goblin arm.l", _make_monster())
        assert result == ["arm.left"]

    def test_duplicate_canonicalised_targets_deduped(self):
        """``leg.r leg.right`` both resolve to ``leg.right`` — keep one."""
        result = _cog()._parse_part_targets("leg.r leg.right", _make_monster())
        assert result == ["leg.right"]

    def test_empty_input(self):
        assert _cog()._parse_part_targets("", _make_monster()) == []
        assert _cog()._parse_part_targets(None, _make_monster()) == []

    def test_monster_without_body_parts(self):
        partless = Creature(name="slime", atk="1d4", defense=0, dodge=0, health_max=10)
        assert _cog()._parse_part_targets("anything", partless) == []

    def test_destroyed_part_is_skipped(self):
        """A fuzzy abbreviation that would resolve to a destroyed part
        must drop out so the 'no targetable part' warning can fire."""
        m = _make_monster()
        left_leg = next(p for p in m.body_parts if p.name == "leg.left")
        left_leg.health = 0
        assert left_leg.is_destroyed()

        assert _cog()._parse_part_targets("leg.l", m) == []
        # Sibling on the same base still resolves via fuzzy.
        assert _cog()._parse_part_targets("leg.r", m) == ["leg.right"]

    def test_bare_part_alongside_dotted_siblings_prefers_exact(self):
        """With a bare ``tail`` part plus ``tail.tip``, typing ``tail``
        must hit only the bare part (exact-match precedence)."""
        m = _make_monster()
        m.body_parts.append(BodyPart(name="tail", health_max=10))
        m.body_parts.append(BodyPart(name="tail.tip", health_max=5))

        assert _cog()._parse_part_targets("tail", m) == ["tail"]
        # Dotted abbreviation still reaches the child.
        assert _cog()._parse_part_targets("tail.t", m) == ["tail.tip"]

    def test_whitespace_only_input(self):
        assert _cog()._parse_part_targets("   ", _make_monster()) == []
