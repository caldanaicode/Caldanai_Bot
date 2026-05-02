"""Heal mechanics shared across all creatures.

Pulled out of :class:`Creature` 2026-05-01 so the base class doesn't
keep accreting concerns. Extracted from the pray d20=17-19 rewrite
that needed: a way to ask "how injured is this body" without poking
at parts, a way to revive critical-part-destroyed corpses without
the rolled-budget contention, and a way to apply a heal-budget
across parts and body in a way that mirrors the damage routing.

Future heal sources (potions, scrolls, magic, mob-vs-mob heals in
multi-monster combat) reuse the same primitives — the mixin lets
that grow without bloating Creature.
"""

import math
from typing import List, Tuple, TYPE_CHECKING

from caldanai.lib.rpg.helpers.parser import parse

if TYPE_CHECKING:
    from caldanai.lib.rpg.creatures.body_part import BodyPart


class HealMixin:
    """Heal primitives mixed into :class:`Creature`.

    Three orthogonal helpers:

    - :meth:`get_total_injury_surface` — measure the current wound
      surface (body HP gap + sum of part HP gaps). Drives heal-
      magnitude formulas so they scale off "what's actually
      damaged" rather than only the body line.
    - :meth:`divine_rescue` — free critical-part rescue plus body
      spark, for effects that should always-at-minimum revive the
      target regardless of any rolled magnitude.
    - :meth:`distribute_heal` — given a heal magnitude, split it
      across parts and body with the inverse of damage routing
      (2/3 to parts, 1/3 to body, with ratio-preserving spillover).

    Callers compose these freely:

    - Pray d20=17-19: ``divine_rescue()`` then ``distribute_heal()``
      with a rolled budget.
    - A future minor healing potion: ``distribute_heal()`` only,
      no rescue branch.
    - A divine-restoration scroll: ``divine_rescue()`` then a
      large-magnitude ``distribute_heal()``.

    The mixin assumes the host class exposes ``health``,
    ``get_health_max``, ``body_parts``, and ``apply_damage`` — the
    standard :class:`Creature` surface. ``is_dirty`` is set on the
    host where it exists; on hosts that don't track it (monsters
    today) the assignment is a harmless no-op attribute write.
    """

    def get_total_injury_surface(self) -> int:
        """Sum of body HP gap and per-part HP gaps — the residual
        wound surface a heal could meaningfully act against.

        Heal-magnitude formulas should scale off this rather than
        body HP alone: a creature with full body HP but a destroyed
        leg is still meaningfully wounded, and a heal that ignored
        the part dimension would land at zero magnitude.
        """
        body_gap = self.get_health_max() - self.health
        part_gap = sum(
            p.health_max - p.health
            for p in (self.body_parts or [])
        )
        return body_gap + part_gap

    def divine_rescue(self) -> Tuple[int, str, "List[BodyPart]"]:
        """Free critical-part rescue plus body spark — paid out of
        grace, not a rolled heal budget.

        Brings every part that's blocking ``is_dead`` from clearing
        back to 1 HP. That set is: every critical part with
        ``health <= 0`` (own zero), PLUS every ancestor (of any
        critical part) with ``health <= 0`` — because those
        ancestors cascade-destroy their critical descendants via
        ``BodyPart.is_destroyed``'s ancestor walk, even though the
        descendant's own HP is fine. If body HP is still at 0 after
        the part rescue, applies 1 HP through ``apply_damage`` so
        the resurrection narration tail ("gasps raggedly as life
        returns") fires for the player path.

        Two key design choices behind this shape, both 2026-05-01
        live-playtest fallout:

        1. We check ``part.health <= 0`` directly, NOT
           ``part.is_destroyed()``. The latter is a cascade — it
           returns True for any descendant whose ancestor is at
           zero. Rescuing on the cascade meant a critical part
           with FULL own HP (e.g. an intact head dangling off a
           destroyed neck) got OVERWRITTEN to 1 HP, losing the
           intact damage state.

        2. We rescue ancestors-of-critical, not just critical
           themselves. A non-critical neck whose destruction
           cascades fatal via ``head.is_destroyed`` ancestor walk
           must still be lifted off zero — otherwise ``is_dead``
           keeps returning True via the head-cascade after the
           rescue is done. This catches design-intentional cases
           (neck is non-critical to keep its USELESS debuff row
           reachable, see ``neck.py``) without forcing every such
           ancestor to be flagged ``is_critical``.

        Use this when an effect should always-at-minimum revive the
        target (e.g. pray d20=17-19, divine restoration scrolls,
        boss-tier resurrection magic). The roll-determined heal
        then layers on top via :meth:`distribute_heal`.

        :return: (grace_hp_applied, revive_msg, healed_parts) where
            ``healed_parts`` are parts whose injury level changed
            from the rescue.
        """
        # Capture is_dead BEFORE the rescue so we can detect any
        # transition (HP-zero or cascade-destroyed) and fire the
        # gasping narration uniformly. Without this, cascade-only
        # revives (body HP > 0 but cascade-destroyed via ancestor)
        # would silently re-light without the resurrection beat
        # because ``apply_damage``'s tail is HP-only.
        was_dead = self.is_dead()

        # Collect rescue targets first so we don't mutate the tree
        # while iterating it.
        parts_to_rescue: "List[BodyPart]" = []
        seen = set()
        for part in (self.body_parts or []):
            if not part.is_critical:
                continue
            if part.health <= 0 and id(part) not in seen:
                parts_to_rescue.append(part)
                seen.add(id(part))
            for ancestor in part.ancestors():
                if ancestor.health <= 0 and id(ancestor) not in seen:
                    parts_to_rescue.append(ancestor)
                    seen.add(id(ancestor))

        healed_parts: "List[BodyPart]" = []
        grace_hp = 0
        for part in parts_to_rescue:
            old_level = part.get_injury_level()
            part.health = 1
            grace_hp += 1
            self.is_dirty = True
            if part.get_injury_level() != old_level:
                healed_parts.append(part)

        # Body spark — direct write rather than ``apply_damage(-1)``
        # because ``apply_damage``'s tail check is HP-based and
        # would no-op if the cascade was already cleared by the
        # part rescue. We narrate the revive ourselves below
        # against the pre-rescue ``was_dead`` snapshot.
        if self.health <= 0:
            self.health = min(self.health + 1, self.get_health_max())
            self.is_dirty = True
            grace_hp += 1

        revive_msg = ""
        if was_dead and not self.is_dead():
            mention = (
                f"<@!{self.member.id}>"
                if getattr(self, "member", None) is not None
                else self.name
            )
            revive_msg = parse(
                f"{mention} suddenly gasps raggedly as life returns to @1o!",
                self,
            )

        return grace_hp, revive_msg, healed_parts

    def distribute_heal(
        self, total_heal: int
    ) -> Tuple[int, int, "List[BodyPart]", str]:
        """Distribute ``total_heal`` HP across parts and body using
        the inverse of damage routing.

        Damage routes 1x → part + x/2 → body, so healing inverts to
        2/3 → parts, 1/3 → body. Spillover from the part budget
        flows into the body at half-rate (4 saved → 2 body, 2 lost)
        so the routing stays honest in both directions.
        Magnitudes that "would have been wasted" because parts are
        already healed don't translate one-for-one into body HP —
        they pass through the same 2:1 valve damage does.
        Part priority — three tiers, each ordered worst-first by
        health/health_max ratio: (1) critical-AND-destroyed parts
        come first because lifting them off zero clears the
        ``is_dead`` gate; (2) critical-but-injured parts buffer
        the next death; (3) non-critical parts take whatever
        remains.
        Use after :meth:`divine_rescue` for full-revive heals, or
        standalone for buffer / top-up heals (potions, regen,
        non-revive scrolls).

        :param total_heal: Total HP magnitude the effect intends
            to deliver, before the 2:1 split.
        :return: ``(parts_applied, body_applied, healed_parts,
            body_msg)``. ``healed_parts`` only includes parts whose
            injury level transitioned; ``body_msg`` is the return
            from the body ``apply_damage`` (e.g. resurrection tail
            from the player path) or empty string.
        """
        if total_heal <= 0:
            return 0, 0, [], ""

        part_budget = (total_heal * 2) // 3
        body_budget = total_heal - part_budget

        # Floor: any non-zero heal magnitude must reach at least 1
        # HP somewhere effective. Without the floor, ``total_heal=1``
        # gives ``part_budget=0`` (integer division) and the full
        # body_budget=1 lands on a possibly-full body — which
        # clamps to 0 and the caller's narration falls through to
        # the "tingle" no-effect branch despite a real heal roll.
        # Caels 2026-05-01 after a d20=17 / total_heal=1 case
        # produced "imbuing... tingle" on an injured target.
        if part_budget == 0:
            part_budget = 1
            body_budget = max(0, body_budget - 1)

        def _heal_priority(p):
            if p.is_critical and p.is_destroyed():
                tier = 0
            elif p.is_critical:
                tier = 1
            else:
                tier = 2
            return (tier, p.health / p.health_max)

        injured_parts = [
            part for part in (self.body_parts or [])
            if part.health < part.health_max
        ]
        sorted_parts = sorted(injured_parts, key=_heal_priority)

        healed_parts: "List[BodyPart]" = []
        remaining_part_budget = part_budget
        parts_applied = 0

        for part in sorted_parts:
            if remaining_part_budget <= 0:
                break
            needed = part.health_max - part.health
            spent = min(needed, remaining_part_budget)
            if spent <= 0:
                continue
            old_level = part.get_injury_level()
            part.health += spent
            remaining_part_budget -= spent
            parts_applied += spent
            self.is_dirty = True
            if part.get_injury_level() != old_level:
                healed_parts.append(part)

        spillover_to_body = remaining_part_budget // 2
        body_to_apply = body_budget + spillover_to_body

        # Measure the body delta around ``apply_damage`` so the
        # caller-visible ``body_applied`` is what actually landed,
        # not what was intended. ``apply_damage`` clamps to
        # ``health_max``, so a body-full target silently absorbs
        # the body slice — reporting the intent would over-state
        # the heal magnitude in the narration.
        body_before = self.health
        body_msg = self.apply_damage(-body_to_apply) if body_to_apply else ""
        body_applied = self.health - body_before

        return parts_applied, body_applied, healed_parts, body_msg
