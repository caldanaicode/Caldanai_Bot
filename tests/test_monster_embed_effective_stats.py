"""Spawn-embed Defense / Dodge fields display values that match
what the player actually faces in combat.

**Defense (post 2026-04-28 contract shift)** — embed shows the
TORSO-EFFECTIVE defense (``effective_defense_for_part(creature,
torso)``), the d{N} pool a torso-aimed swing actually rolls
absorption against. Pre-shift the embed showed bare creature-level
``get_defense()``, which hid per-part bonuses (e.g. bearowl torso
+3, golem torso/head +4) so the displayed number under-reported
real torso resistance.

**Dodge** — still anchored to ``get_dodge()`` (per-part dodge
variance is dominated by size scaling, not part bonuses; the
mismatch problem doesn't apply).

The numeric value is parsed off the embed field text (the field
may carry a trailing bandage marker for injury-reduced stats —
see ``test_creature_embed_injury_marker``); we strip that and
compare integers.
"""

from __future__ import annotations

import re

from caldanai.lib.rpg.creatures import effective_defense_for_part
from caldanai.lib.rpg.creatures.body_parts import BodyPartPlugin
from caldanai.lib.rpg.creatures.monsters import MonsterPlugin
from caldanai.lib.rpg.helpers.enums import Size


BodyPartPlugin.load_plugins()
MonsterPlugin.load_plugins()


def _embed_field_value(embed, name: str) -> str:
    for f in embed.fields:
        if f.name == name:
            return f.value
    raise AssertionError(
        f"missing embed field {name!r}; have: "
        f"{[f.name for f in embed.fields]}"
    )


def _parse_int(field_value: str) -> int:
    """Pull the leading integer out of an embed field that may carry
    a trailing bandage marker / commas."""
    match = re.match(r"\s*([\d,]+)", field_value)
    if not match:
        raise AssertionError(f"no integer in embed field {field_value!r}")
    return int(match.group(1).replace(",", ""))


def _spawn(stem: str):
    cls = MonsterPlugin.get_plugin_class(stem)
    if cls is None:
        raise AssertionError(f"unknown monster stem {stem!r}")
    return cls()


def _torso_effective(creature):
    """Mirror ``Creature._embed_defense_value`` for assertions:
    torso-effective for bodied creatures, ``get_defense()`` for
    body-less."""
    torso = creature.get_part("torso") if creature.body_parts else None
    if torso is None and creature.body_parts:
        torso = next(
            (p for p in creature.body_parts
             if getattr(p, "is_critical", False)),
            creature.body_parts[0],
        )
    if torso is None:
        return creature.get_defense()
    return effective_defense_for_part(creature, torso)


class TestEmbedShowsTorsoEffectiveDefense:
    """Embed Defense == torso-effective defense (the d{N} pool a
    torso swing rolls absorption against)."""

    def test_bearowl_embed_defense_is_torso_effective(self):
        """LARGE bearowl: torso defense_bonus=+3 lands on top of the
        size-scaled creature pool. The embed should surface the +3."""
        m = _spawn("bearowl")
        assert m.size is Size.LARGE
        embed, _ = m.get_embed()
        displayed = _parse_int(_embed_field_value(embed, "Defense"))
        torso = m.get_part("torso")
        assert torso is not None
        expected = effective_defense_for_part(m, torso)
        assert displayed == expected
        # Sanity: with torso defense_bonus=+3 the torso-effective
        # number should exceed bare creature-level get_defense().
        assert displayed > m.get_defense()

    def test_goblin_embed_defense_is_torso_effective(self):
        """SMALL goblin: torso has no defense_bonus, so torso-
        effective should match get_defense() for the goblin (the
        contract still holds — this is the no-bonus case)."""
        m = _spawn("goblin")
        assert m.size is Size.SMALL
        embed, _ = m.get_embed()
        displayed = _parse_int(_embed_field_value(embed, "Defense"))
        torso = m.get_part("torso")
        assert torso is not None
        expected = effective_defense_for_part(m, torso)
        assert displayed == expected

    def test_golem_embed_defense_includes_torso_plate(self):
        """Golem torso has defense_bonus=+4. Embed should reflect."""
        m = _spawn("golem")
        embed, _ = m.get_embed()
        displayed = _parse_int(_embed_field_value(embed, "Defense"))
        torso = m.get_part("torso")
        assert torso is not None
        expected = effective_defense_for_part(m, torso)
        assert displayed == expected

    def test_hydra_embed_defense_anchors_on_torso(self):
        """Hydra has multiple necks/heads but a single torso —
        embed picks that one and the value matches the per-part
        resolver call."""
        m = _spawn("hydra")
        embed, _ = m.get_embed()
        displayed = _parse_int(_embed_field_value(embed, "Defense"))
        torso = m.get_part("torso")
        assert torso is not None
        expected = effective_defense_for_part(m, torso)
        assert displayed == expected

    def test_skeleton_embed_defense_is_torso_effective(self):
        """Skeleton has a torso even with low base defense — the
        contract math still applies."""
        m = _spawn("skeleton")
        embed, _ = m.get_embed()
        displayed = _parse_int(_embed_field_value(embed, "Defense"))
        torso = m.get_part("torso")
        assert torso is not None
        expected = effective_defense_for_part(m, torso)
        assert displayed == expected

    def test_pixie_tiny_defense_is_torso_effective(self):
        """TINY pixie: torso-effective on a tiny creature should still
        match the per-part resolver."""
        m = _spawn("pixie")
        assert m.size is Size.TINY
        embed, _ = m.get_embed()
        displayed = _parse_int(_embed_field_value(embed, "Defense"))
        torso = m.get_part("torso")
        assert torso is not None
        expected = effective_defense_for_part(m, torso)
        assert displayed == expected

    def test_bodyless_creature_falls_back_to_creature_defense(self):
        """Spirit (no body parts) falls back to creature-level
        get_defense() — per-part lookup isn't applicable."""
        m = _spawn("spirit")
        assert not m.body_parts
        embed, _ = m.get_embed()
        displayed = _parse_int(_embed_field_value(embed, "Defense"))
        # Body-less fallback: same as creature-level emergent.
        assert displayed == m.get_defense()


class TestEmbedShowsEffectiveDodge:
    """Dodge field == ``creature.get_dodge()`` for any spawn (no
    contract change for dodge)."""

    def test_bearowl_large_dodge_is_size_scaled(self):
        """LARGE creatures get a 0.75 dodge multiplier — embed
        should show the post-multiplier value, not the raw roll."""
        m = _spawn("bearowl")
        embed, _ = m.get_embed()
        displayed = _parse_int(_embed_field_value(embed, "Dodge"))
        assert displayed == m.get_dodge()

    def test_goblin_small_dodge_is_size_scaled(self):
        """SMALL: 1.25 dodge_mod — small things are slipperier."""
        m = _spawn("goblin")
        embed, _ = m.get_embed()
        displayed = _parse_int(_embed_field_value(embed, "Dodge"))
        assert displayed == m.get_dodge()

    def test_pixie_tiny_dodge_is_size_scaled(self):
        """TINY: 1.5 dodge_mod — pixies should read genuinely
        slippery in the embed."""
        m = _spawn("pixie")
        embed, _ = m.get_embed()
        displayed = _parse_int(_embed_field_value(embed, "Dodge"))
        assert displayed == m.get_dodge()


class TestEmbedDisplayMatchesRuntime:
    """Cross-monster contract: every plugin's spawn embed agrees
    with what combat actually sees on the iconic part. Defense is
    the torso-effective resolver call (or ``get_defense()`` for
    body-less); dodge is creature-level. Catches drift between
    display and runtime resolution at unit-test speed; the sweep
    harness validator (``--validate-embed-stats``) runs the same
    check at scale against many fresh instances per monster."""

    def test_every_monster_embed_matches_runtime(self):
        registry = MonsterPlugin._PLUGIN_REGISTRY
        assert registry, "expected MonsterPlugin registry to be populated"
        mismatches = []
        for stem, cls in registry.items():
            try:
                m = cls()
            except Exception as exc:  # pragma: no cover - construct fail
                mismatches.append(f"{stem}: construct error {exc!r}")
                continue
            try:
                embed, _ = m.get_embed()
            except Exception as exc:  # pragma: no cover - embed fail
                mismatches.append(f"{stem}: embed error {exc!r}")
                continue
            disp_def = _parse_int(_embed_field_value(embed, "Defense"))
            disp_dodge = _parse_int(_embed_field_value(embed, "Dodge"))
            runtime_def = _torso_effective(m)
            runtime_dodge = m.get_dodge()
            if disp_def != runtime_def:
                mismatches.append(
                    f"{stem}: defense displayed={disp_def} "
                    f"runtime(torso-effective)={runtime_def}"
                )
            if disp_dodge != runtime_dodge:
                mismatches.append(
                    f"{stem}: dodge displayed={disp_dodge} "
                    f"runtime={runtime_dodge}"
                )
        assert not mismatches, "embed/runtime drift:\n  " + "\n  ".join(
            mismatches
        )
