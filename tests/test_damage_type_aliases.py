"""Tests for the elemental damage-type aliases (ICE, POISON,
LIGHTNING, ACID), the alias-aware ``DamageTypes.__str__``, and the
trait-matching semantics that flow from compound damage types.

Player-skill key migration was handled as a one-shot Mongo script
(``scripts/migrations/2026_04_14_skill_alias_rename.js``) rather
than in-Python lazy migration; no related tests live here."""

import pytest

from caldanai.lib.rpg.creatures import Creature
from caldanai.lib.rpg.helpers.enums import DamageTypes


# ---------------------------------------------------------------------------
# Alias values are bitwise-equal to their broken-out forms
# ---------------------------------------------------------------------------


class TestAliasValues:
    """The aliases must equal ``COMPONENT_BITS | COMBINED`` exactly,
    so existing storage that wrote out the long form still resolves
    via the alias name."""

    def test_ice(self):
        assert DamageTypes.ICE == (
            DamageTypes.WATER | DamageTypes.DARK | DamageTypes.COMBINED
        )

    def test_poison(self):
        assert DamageTypes.POISON == (
            DamageTypes.DARK | DamageTypes.AIR | DamageTypes.COMBINED
        )

    def test_lightning(self):
        assert DamageTypes.LIGHTNING == (
            DamageTypes.LIGHT | DamageTypes.AIR | DamageTypes.COMBINED
        )

    def test_acid(self):
        assert DamageTypes.ACID == (
            DamageTypes.EARTH | DamageTypes.WATER | DamageTypes.COMBINED
        )


# ---------------------------------------------------------------------------
# __str__ honors the aliases
# ---------------------------------------------------------------------------


class TestAliasStringDisplay:
    def test_pure_alias_renders_as_name(self):
        assert str(DamageTypes.ICE) == "ice"
        assert str(DamageTypes.POISON) == "poison"
        assert str(DamageTypes.LIGHTNING) == "lightning"
        assert str(DamageTypes.ACID) == "acid"

    def test_alias_plus_physical_bit_orders_physical_first(self):
        """Convention: physical/weapon bits render first, then the
        alias name. Matches how the legacy output ordered things
        (``slashing dark water``, etc.)."""
        ice_axe = DamageTypes.SLASHING | DamageTypes.ICE
        assert str(ice_axe) == "slashing ice"

    def test_legacy_combo_without_combined_still_renders_broken_out(self):
        """A historical ``WATER | DARK`` value (no COMBINED) does NOT
        match the ICE alias and falls back to broken-out display.
        Important so the migrator can recognize legacy skill keys."""
        legacy = DamageTypes.WATER | DamageTypes.DARK  # no COMBINED
        assert str(legacy) == "dark water"

    def test_single_bit_unchanged(self):
        """Sanity: pure bits render unchanged from before."""
        assert str(DamageTypes.FIRE) == "fire"
        assert str(DamageTypes.PIERCING) == "piercing"

    def test_all_and_any_special_cases_preserved(self):
        assert str(DamageTypes.ALL) == "all"
        assert str(DamageTypes.ANY) == "any"

    def test_zero_is_empty_string(self):
        assert str(DamageTypes(0)) == ""


# ---------------------------------------------------------------------------
# Trait matching with COMBINED enforces compound-only triggering
# ---------------------------------------------------------------------------


def _make_creature(traits=None) -> Creature:
    c = Creature(
        name="target", atk="1d4", defense=1, dodge=1,
        health_max=20, health=20,
    )
    if traits:
        c.traits.update(traits)
    return c


class TestCompoundTraitMatching:
    """The whole point of the COMBINED bit: traits keyed on a
    compound alias only match compound-flagged incoming damage,
    not any single-bit overlap."""

    def test_ice_trait_matches_ice_attack(self):
        c = _make_creature({DamageTypes.ICE: 0.5})
        assert c.get_trait_multiplier(DamageTypes.ICE) == 0.5

    def test_ice_trait_does_not_match_pure_water(self):
        """Pure water shouldn't trigger ice resistance — the bug we
        explicitly fixed by introducing the COMBINED-bearing alias."""
        c = _make_creature({DamageTypes.ICE: 0.5})
        assert c.get_trait_multiplier(DamageTypes.WATER) == 1.0

    def test_ice_trait_does_not_match_pure_dark(self):
        c = _make_creature({DamageTypes.ICE: 0.5})
        assert c.get_trait_multiplier(DamageTypes.DARK) == 1.0

    def test_pure_water_trait_still_matches_ice_attack(self):
        """A trait keyed on pure WATER (the bit-overlap branch)
        still applies to a compound ICE attack — water-vulnerable
        creatures naturally feel ice damage too."""
        c = _make_creature({DamageTypes.WATER: 1.5})
        assert c.get_trait_multiplier(DamageTypes.ICE) == 1.5

    def test_compound_attack_with_extra_bit_still_matches_alias_trait(self):
        """An ice-axe deals SLASHING | ICE. A creature with an ICE
        trait should still feel the ice portion."""
        c = _make_creature({DamageTypes.ICE: 0.5})
        ice_axe_dmg = DamageTypes.SLASHING | DamageTypes.ICE
        # 0.5 (ice trait) is the highest matching → that wins.
        assert c.get_trait_multiplier(ice_axe_dmg) == 0.5


# ---------------------------------------------------------------------------
# Emoji output honors compound aliases
# ---------------------------------------------------------------------------


class TestAliasEmojiDisplay:
    def test_pure_alias_emoji(self):
        assert DamageTypes.ICE.emoji == "🧊"
        assert DamageTypes.POISON.emoji == "🧪"
        assert DamageTypes.LIGHTNING.emoji == "⚡"
        assert DamageTypes.ACID.emoji == "⚗️"

    def test_alias_with_physical_bit_orders_physical_first(self):
        """Compound aliases concat AFTER physical / weapon emoji,
        matching the string display ordering."""
        ice_axe = DamageTypes.SLASHING | DamageTypes.ICE
        assert ice_axe.emoji == "🔪🧊"

    def test_legacy_combo_without_combined_falls_back_to_single_bits(self):
        """Storage that pre-dates the alias (no COMBINED bit) keeps
        the old broken-out emoji rendering."""
        legacy = DamageTypes.WATER | DamageTypes.DARK  # no COMBINED
        assert legacy.emoji == "🌑💧"

    def test_single_bit_emoji_unchanged(self):
        assert DamageTypes.FIRE.emoji == "🔥"
        assert DamageTypes.PIERCING.emoji == "🪡"

    def test_zero_emoji_is_empty(self):
        assert DamageTypes(0).emoji == ""


# ---------------------------------------------------------------------------
# Canonical (storage / keying) form preserves the COMBINED marker
# ---------------------------------------------------------------------------


class TestCanonicalForm:
    """``canonical`` is the lossless form used for skill keys and any
    other place that needs to round-trip the damage type via string.
    Player-facing display strips the technical marker via
    ``DamageTypes.display_skill_name``."""

    def test_alias_pure_form_omits_combined_word(self):
        """Compound aliases (ICE, POISON, etc.) already encode
        COMBINED in their name, so the canonical form is just the
        alias name — no extra ``" combined"`` suffix."""
        assert DamageTypes.ICE.canonical == "ice"
        assert DamageTypes.POISON.canonical == "poison"
        assert DamageTypes.LIGHTNING.canonical == "lightning"
        assert DamageTypes.ACID.canonical == "acid"

    def test_alias_with_physical_bit_omits_combined_word(self):
        """Slashing+ICE also omits ``"combined"`` because ICE absorbs
        the COMBINED bit."""
        ice_axe = DamageTypes.SLASHING | DamageTypes.ICE
        assert ice_axe.canonical == "slashing ice"

    def test_non_aliased_compound_appends_combined(self):
        """Torch (BLUDGEONING | FIRE | COMBINED) has no compound
        alias to absorb the COMBINED bit — canonical form makes it
        explicit so this skill key is distinct from a hypothetical
        non-COMBINED ``"bludgeoning fire"``."""
        torch = (
            DamageTypes.BLUDGEONING | DamageTypes.FIRE | DamageTypes.COMBINED
        )
        assert torch.canonical == "bludgeoning fire combined"

    def test_bow_canonical_form(self):
        bow = DamageTypes.PIERCING | DamageTypes.RANGED | DamageTypes.COMBINED
        assert bow.canonical == "ranged piercing combined"

    def test_wand_canonical_form(self):
        wand = DamageTypes.MAGICAL | DamageTypes.RANGED | DamageTypes.COMBINED
        assert wand.canonical == "ranged magical combined"

    def test_legacy_combo_without_combined_unchanged(self):
        """A legacy ``WATER | DARK`` (no COMBINED bit) doesn't get a
        spurious ``"combined"`` appended — only the actual COMBINED
        bit triggers the suffix."""
        legacy = DamageTypes.WATER | DamageTypes.DARK  # no COMBINED
        assert legacy.canonical == "dark water"

    def test_single_bit_unchanged(self):
        assert DamageTypes.FIRE.canonical == "fire"


class TestDisplaySkillName:
    """``display_skill_name`` strips the technical ``"combined"``
    marker so player-facing surfaces don't expose internal bookkeeping."""

    def test_strips_combined_suffix(self):
        assert DamageTypes.display_skill_name(
            "one-handed bludgeoning fire combined"
        ) == "one-handed bludgeoning fire"

    def test_passthrough_when_no_combined(self):
        assert DamageTypes.display_skill_name(
            "one-handed slashing ice"
        ) == "one-handed slashing ice"

    def test_passthrough_for_non_damage_skill(self):
        assert DamageTypes.display_skill_name("unarmed") == "unarmed"

    def test_idempotent(self):
        once = DamageTypes.display_skill_name("two-handed poison combined")
        twice = DamageTypes.display_skill_name(once)
        assert once == twice == "two-handed poison"
