"""Composable gender / pronoun state for things-with-personhood.

Why this exists
---------------

:class:`Creature` (and its subclasses :class:`Player` /
:class:`MonsterPlugin`) carry gender and pronouns. With the
introduction of :class:`PasserbyPlugin` — non-combatant NPCs that
ALSO need pronoun handling but do NOT inherit from Creature —
keeping gender as a Creature intrinsic forces duplication. This
mixin extracts the concern into a single composable surface.

Design
------

- **Class-level declaration.** Subclasses set ``gender`` and
  ``pronouns`` as class attributes. ``pronouns`` is a comma-
  separated string in the format
  ``"subj,obj,poss_adj,poss_pron,reflex"`` — the same input
  format :class:`Creature` already accepts.
- **Instance-level override.** Subclasses with per-instance
  state (e.g. :class:`Player.gender` set at character creation,
  :class:`Creature.pronouns` parsed to a Dict in ``__init__``)
  override the class-level defaults via assignment to ``self``.
  The mixin doesn't constrain how each subclass stores pronouns
  internally.
- **Unified accessor.** :meth:`get_pronoun_dict` returns the
  Pronouns-enum-keyed dict the parser expects. Handles both
  storage shapes: an instance-level Dict (Creature) is returned
  as-is; a class-level string (PasserbyPlugin) is parsed on
  demand.

This means the existing :class:`Creature` behavior is unchanged
— ``__init__`` still parses the input string into a Dict and
stores it on ``self.pronouns``. The mixin just provides the
unified accessor and the class-level default that fills in for
plugin types that don't run a Creature-style __init__.
"""

from typing import Dict, Optional, Union

from caldanai.lib.rpg.helpers.enums import Pronouns


# Order of pronoun fields in the comma-separated string format.
# Matches :class:`Creature.__init__`'s parsing convention so the
# input format is interchangeable across consumers. Note that
# ``Creature`` ignores position 4 of the string and computes
# reflexive as ``objective + "self"``; this mixin matches that
# behavior so a comma-separated string parsed here yields the
# same dict as if it had been passed to ``Creature.__init__``.
_PRONOUN_PARSE_ORDER = (
    Pronouns.SUBJECTIVE,
    Pronouns.OBJECTIVE,
    Pronouns.POSSESSIVE,
    Pronouns.ADJECTIVE,
)


class GenderMixin:
    """Class-level gender / pronoun declaration with parser-
    compatible accessors. Composed into any class with personhood
    — :class:`Creature` (and its subclasses) and
    :class:`PasserbyPlugin` today; future NPC types tomorrow.

    Subclasses declare:

    .. code-block:: python

        class Wagoneer(PasserbyPlugin):  # PasserbyPlugin extends GenderMixin
            gender = "male"
            pronouns = "he,him,his,his,himself"

    The string format is the canonical input shape;
    :meth:`get_pronoun_dict` parses it on demand for parser
    consumption. Subclasses with per-instance state (like
    :class:`Creature`) can store ``self.pronouns`` as a Dict
    directly — the accessor handles both representations.
    """

    # Default gender; subclasses override at class- or instance-
    # level. ``"neutral"`` exists as a fallback so an entity can
    # always declare valid pronoun state without committing to a
    # gendered identity.
    gender: str = "neutral"

    # Default pronouns as a comma-separated string. Format:
    # ``"subj,obj,poss_pron,poss_adj,reflex"`` — five elements,
    # matching :class:`Creature.__init__`'s parsing order
    # (POSSESSIVE at position 2 = "theirs"/"hers"/"his";
    # ADJECTIVE at position 3 = "their"/"her"/"his").
    # Position 4 (reflexive) is decoration; reflexive is
    # always computed as ``objective + "self"``.
    pronouns: Union[str, Dict[Pronouns, str]] = (
        "they,them,theirs,their,themself"
    )

    def get_pronoun_dict(self) -> Dict[Pronouns, str]:
        """Return the Pronouns-enum-keyed dict the parser expects.

        Handles both internal representations:

        - **Dict** (Creature post-init): returned as-is.
        - **String** (PasserbyPlugin class-level): parsed on
          demand. Empty string or fewer than 5 elements falls
          through to the GenderMixin default to keep the parser
          well-fed regardless of declaration completeness.

        This is the unified parser-side accessor — call sites that
        need pronoun data should use this, not ``self.pronouns``
        directly, so internal storage can vary across subclasses.
        """
        raw = getattr(self, "pronouns", None)
        if isinstance(raw, dict):
            return raw
        return self._parse_pronoun_string(raw)

    @staticmethod
    def _parse_pronoun_string(raw: Optional[str]) -> Dict[Pronouns, str]:
        """Parse a comma-separated pronoun string into the
        Pronouns-enum-keyed dict shape. Defensive against missing
        or short input — falls through to the GenderMixin class-
        level default for elements that aren't supplied.

        Matches :class:`Creature.__init__`'s parsing exactly:
        positions 0-3 map to subjective/objective/possessive/
        adjective; reflexive is computed as ``objective + "self"``
        regardless of any 5th string element. The 5th element is
        decoration in the input format — present for readability,
        ignored by both this mixin and Creature.
        """
        default_parts = [
            p.strip()
            for p in str(GenderMixin.pronouns).split(",")
        ]
        if not raw or not isinstance(raw, str):
            parts = default_parts
        else:
            parts = [p.strip() for p in raw.split(",")]
            if len(parts) < len(_PRONOUN_PARSE_ORDER):
                # Pad missing positions from the default so the
                # dict stays complete even with short input.
                parts = parts + default_parts[len(parts):]
        result: Dict[Pronouns, str] = {
            slot: parts[i]
            for i, slot in enumerate(_PRONOUN_PARSE_ORDER)
            if i < len(parts) and parts[i]
        }
        # Reflexive = objective + "self" (Creature convention).
        objective = result.get(Pronouns.OBJECTIVE, "")
        if objective:
            result[Pronouns.REFLEXIVE] = objective + "self"
        return result

    def get_pronoun(self, slot: Pronouns) -> str:
        """Convenience accessor for a single pronoun slot. Returns
        the empty string if the slot isn't declared."""
        return self.get_pronoun_dict().get(slot, "")
