"""Attack results — the finished record of an attack.

An `AttackResult` holds everything produced by resolving one attack hit:
the dice rolls, damage dealt, multipliers applied, and the ability to
render itself as a Discord message. An `AttackSequence` groups multiple
results together (e.g., dual-wield, hydra heads) and knows how to render
the full attack action with an appropriate header.

Both classes are mutable dataclasses so monsters can adjust results
in-place during `resolve_attack` overrides (e.g., halving prime damage).
"""

import unicodedata
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Dict, List, Optional

from caldanai.lib.rpg.helpers.enums import DamageTypes
from caldanai.lib.rpg.helpers.roll_data import CombinedRoll


def _visual_width(s: str) -> int:
    """Approximates the visual width of a string in a monospace terminal.

    Treats emoji and East Asian wide characters as 2 columns, everything
    else as 1. This is a rough heuristic — Discord's actual rendering
    varies by client, but it's good enough for column alignment.
    """
    if not s:
        return 0
    width = 0
    for ch in s:
        if unicodedata.east_asian_width(ch) in ("W", "F"):
            width += 2
        elif ord(ch) >= 0x1F000:
            # Emoji and pictographic characters — most are double-width
            width += 2
        elif unicodedata.category(ch).startswith("M"):
            # Combining marks take no extra width
            pass
        else:
            width += 1
    return width


def _pad_visual(s: str, target_width: int) -> str:
    """Pads a string with spaces on the right to reach the target visual width."""
    padding = target_width - _visual_width(s)
    if padding <= 0:
        return s
    return s + " " * padding

if TYPE_CHECKING:
    from caldanai.lib.rpg.combat.attack_source import AttackSource
    from caldanai.lib.rpg.creatures import Creature
    from caldanai.lib.rpg.creatures.body_part import BodyPart


@dataclass
class AttackResult:
    """The resolved outcome of a single attack hit."""

    source: "AttackSource"
    combined: CombinedRoll
    damage: int                    # final damage after defense subtraction
    multiplier: float              # trait multiplier that was applied
    defense: int                   # target's defense value at resolution time
    dodge: int                     # target's dodge value at resolution time
    dmg_type: Optional[DamageTypes] = None
    extra_text: str = ""           # optional flavor text appended by subclasses
    auto_hit: bool = False         # True for attacks that bypass dodge (e.g., dragon breath)
    target_part: Optional["BodyPart"] = None  # body part targeted by this hit (None = legacy whole-body)

    def total_damage(self) -> int:
        """Returns the final damage this result contributes."""
        return self.damage

    def hit(self) -> bool:
        """Returns True if this attack was not a miss."""
        return not self.combined.isMiss

    @property
    def sub_damage(self) -> int:
        """The damage after multiplier but before defense subtraction."""
        return int(self.multiplier * self.combined.result)

    def to_display_parts(self) -> Dict[str, Any]:
        """Returns a dict of display-ready pieces for this result.

        Callers (typically `AttackSequence`) can use these pieces to build
        whatever layout they want — a per-hit diff block, a compact table
        row, a JSON log entry, etc. Subclasses can override to add keys
        like `prime_flavor` or other custom metadata.
        """
        dmg_type_str = str(self.dmg_type).title() if self.dmg_type else ""
        dmg_type_emoji = self.dmg_type.emoji if self.dmg_type else ""

        label = self.source.label if self.source else ""
        if self.target_part:
            # Always show the aimed-at part (hit or miss) — on a miss it
            # provides context for the dodge value in that row, which
            # varies by part exposure under per-part dodge scaling.
            label = f"{label} → {self.target_part.display_name}"

        return {
            "label": label,
            "roll_str": str(self.combined.attack),
            "hit_str": self.combined.get_hit_string(),
            "is_miss": self.combined.isMiss,
            "is_critical": self.combined.isCritical,
            "is_fumble": self.combined.isFumble,
            "auto_hit": self.auto_hit,
            "damage_breakdown": str(self.combined.damage),
            "raw_damage": self.combined.damage.result,  # raw dice total, before crit
            "damage_type_str": dmg_type_str,
            "damage_type_emoji": dmg_type_emoji,
            "sub_damage": self.sub_damage,
            "multiplier": self.multiplier,
            "final_damage": self.damage,
            "defense": self.defense,
            "dodge": self.dodge,
            "extra_text": self.extra_text,
        }

    def to_markdown(self, label: Optional[str] = None) -> str:
        """Render this result as a standalone Discord diff code block.

        This is used for standalone rendering (e.g., debugging or direct
        display); `AttackSequence.to_markdown` typically uses the compact
        table instead.

        :param label: Optional label prefix (e.g., 'Left', 'Right', 'Two-Handed').
            If None, no header is added (the caller is expected to provide one).
        :return: A Discord-formatted markdown string.
        """
        hit_mark = "-" if self.combined.isMiss else "+"
        dmg_type_str = f"{str(self.dmg_type).title()} " if self.dmg_type else ""
        emoji = self.dmg_type.emoji if self.dmg_type else ""
        sub = self.sub_damage

        header = f"**{label}:**" if label else ""

        msg = (
            f"{header}```diff\nAttack vs Dodge ({self.dodge}): "
            f"\n{hit_mark}    {self.combined.attack} ({self.combined.get_hit_string()})"
        )

        msg += (
            f"\n\n{dmg_type_str}Damage{' ' + emoji if emoji else ''}:\n{hit_mark}"
            f"    {self.combined.damage}"
            f"{' * 0' if self.combined.isMiss else ' * 2' if self.combined.isCritical else ''}"
            f"{' * ' + str(self.multiplier) if self.multiplier != 1 else ''} = {sub}"
        )

        if not self.combined.isMiss:
            msg += f"\n\nTotal ({sub}) vs Defense ({self.defense}) = {self.damage}"

        if self.extra_text:
            msg += f" {self.extra_text}"

        msg += "```\n"
        return msg


@dataclass
class AttackSequence:
    """A complete attack action — possibly multiple hits from one attacker against one target."""

    attacker: "Creature"
    target: "Creature"
    results: List[AttackResult] = field(default_factory=list)
    narrative: str = ""  # Special narrative text (e.g., vampire feeding) that replaces normal result rendering
    multi_target: bool = False  # True when results span multiple victims (hydra multi-target)
    # Informational lines rendered inside the diff block above the table
    # — e.g. "Your right arm hangs limp and useless." when an attack
    # slot has been disabled by injury. Unlike ``narrative`` (which
    # replaces the table entirely), notes render alongside the table.
    notes: List[str] = field(default_factory=list)

    def total_damage(self) -> int:
        """Returns the sum of damage across all results in the sequence."""
        return sum(r.total_damage() for r in self.results)

    def any_hit(self) -> bool:
        """Returns True if at least one result in the sequence hit."""
        return any(r.hit() for r in self.results)

    def to_markdown(self) -> str:
        """Render the full attack sequence as a Discord message.

        Builds an appropriate header and a compact diff-block table
        containing all results in the sequence. When there are no
        results but there are notes (e.g. every attack slot is
        disabled by injury), render just the notes so the player
        sees why nothing happened.
        """
        if self.narrative and not self.results:
            return self.narrative

        if not self.results:
            if not self.notes:
                return ""
            header = self._build_header()
            body = "```diff\n"
            for note in self.notes:
                body += f"   {note}\n"
            body += "```\n"
            return f"{header}\n{body}" if header else body

        header = self._build_header()
        body = self._render_compact_table()
        return f"{header}\n{body}" if header else body

    def _render_compact_table(self) -> str:
        """Render results as a single compact diff-block table.

        Layout per row (normal attacks):
        prefix | label | roll v dodge → result | (breakdown) = raw | [‼️] * mult emoji = sub | → final

        The attack check collapses to a single column of the form
        ``{roll} v {dodge} → {HIT|MISS|CRIT|FUMBLE}``. This keeps the
        three values that describe the check (what was rolled, what it
        was checked against, what the outcome was) visually adjacent —
        essential when per-part exposure, multi-target, or multi-player
        combat makes dodges differ across sources.

        For auto-hit attacks (dragon breath), the check column collapses
        entirely since there's no roll or dodge to display.
        """
        parts_list = [r.to_display_parts() for r in self.results]
        all_auto_hit = all(p["auto_hit"] for p in parts_list)

        # Pre-build per-column strings so we can compute widths. The
        # comparison symbol encodes the check outcome at a glance —
        # ``≥`` when the roll met or beat dodge (the system is
        # meet-or-beat), ``≱`` when it didn't. CRIT and FUMBLE still
        # show in the ``→ Result`` column since the symbol only
        # carries the meet/beat bit, not the natural-20 / natural-1
        # flavor.
        check_col_list = [
            f"{p['roll_str']} {'≱' if p['is_miss'] else '≥'} {p['dodge']} → {p['hit_str']}"
            for p in parts_list
        ]
        dmg_col_list = [self._build_damage_column(p) for p in parts_list]
        mult_col_list = [self._build_mult_column(p) for p in parts_list]
        # Final column mirrors the Multiplier column's result (sub_damage)
        # so post-hook multipliers — e.g. math-teacher prime doubling —
        # don't create a silent jump between the row's math and the
        # "Final" total. Post-hook bumps are rendered on the extra_text
        # line below the row ("LORD OF PRIMES! * 2 = 58"), and still
        # contribute to the footer total via r.total_damage().
        final_col_list = [
            f"→ {0 if p['is_miss'] else p['sub_damage']}" for p in parts_list
        ]

        # Header labels per column (Def column removed — defense is
        # subtracted once from the per-player total, not per-source).
        # H_FINAL is the per-source damage output; H_CHECK is the
        # attack-check outcome. They're distinct columns.
        H_LABEL = "Source"
        H_CHECK = "Roll v Dodge → Result"
        H_DAMAGE = "Damage"
        H_MULT = "Multiplier"
        H_FINAL = "Final"

        label_w = max(len(H_LABEL), max(len(p["label"]) for p in parts_list))
        dmg_w = max(len(H_DAMAGE), max(len(s) for s in dmg_col_list))
        mult_w = max(len(H_MULT), max(len(s) for s in mult_col_list))
        final_w = max(len(H_FINAL), max(len(s) for s in final_col_list))

        if not all_auto_hit:
            check_w = max(len(H_CHECK), max(len(s) for s in check_col_list))

        total_damage = self.total_damage()

        lines = ["```diff"]

        # Informational notes (e.g. "Your right arm hangs limp and
        # useless.") render inside the diff block, above the auto-hit
        # banner / column header, so players see why a slot didn't
        # contribute before reading the table.
        for note in self.notes:
            lines.append(f"   {note}")

        # Auto-hit keeps its summary line (no roll / no dodge to stand in
        # for it). Non-auto-hit drops the header line entirely — the
        # per-row check column tells the whole story.
        if all_auto_hit:
            lines.append("   Auto-hit attack")

        # Column header row (plain text, no diff prefix)
        if all_auto_hit:
            header_row = (
                f"   {H_LABEL.ljust(label_w)} | {H_DAMAGE.ljust(dmg_w)} | "
                f"{H_MULT.ljust(mult_w)} | {H_FINAL.ljust(final_w)}"
            )
        else:
            header_row = (
                f"   {H_LABEL.ljust(label_w)} | {H_CHECK.ljust(check_w)} | "
                f"{H_DAMAGE.ljust(dmg_w)} | {H_MULT.ljust(mult_w)} | "
                f"{H_FINAL.ljust(final_w)}"
            )
        lines.append(header_row)

        for p, check_col, dmg_col, mult_col, final_col in zip(
            parts_list, check_col_list,
            dmg_col_list, mult_col_list, final_col_list,
        ):
            prefix = self._prefix_for(p)
            label = p["label"].ljust(label_w)
            dmg_padded = dmg_col.ljust(dmg_w)
            mult_padded = mult_col.ljust(mult_w)
            emoji = p["damage_type_emoji"]
            final_rendered = final_col.ljust(final_w) if emoji else final_col
            emoji_trailer = f" {emoji}" if emoji else ""

            if all_auto_hit:
                row = (
                    f"{prefix}  {label} | {dmg_padded} | {mult_padded} | "
                    f"{final_rendered}{emoji_trailer}"
                )
            else:
                check_padded = check_col.ljust(check_w)
                row = (
                    f"{prefix}  {label} | {check_padded} | "
                    f"{dmg_padded} | {mult_padded} | {final_rendered}{emoji_trailer}"
                )
            lines.append(row)

            if p["extra_text"]:
                lines.append(f"!  {' ' * label_w}   {p['extra_text']}")

        if self.multi_target:
            lines.append(f"   Total: {total_damage} damage")
        else:
            defense = self.results[0].defense if self.results else 0
            num_hits = sum(1 for r in self.results if r.damage > 0)
            if num_hits > 0:
                raw_after_defense = total_damage - defense
                final = max(num_hits, raw_after_defense)
                if defense and total_damage != final:
                    # Distinguish the "defense partially absorbed" case from
                    # the "defense fully absorbed but the 1-per-hit floor
                    # kicked in" case so the footer arithmetic reads
                    # honestly rather than looking like a math error.
                    if raw_after_defense < num_hits:
                        lines.append(
                            f"   Total: {total_damage} damage - {defense} defense, "
                            f"floored at {num_hits} (1/hit) → {final} damage"
                        )
                    else:
                        lines.append(
                            f"   Total: {total_damage} damage - {defense} defense "
                            f"→ {final} damage"
                        )
                else:
                    lines.append(f"   Total: {total_damage} damage")
            else:
                lines.append(f"   Total: {total_damage} damage")
        lines.append("```")

        return "\n".join(lines) + "\n"

    @staticmethod
    def _build_damage_column(parts: Dict[str, Any]) -> str:
        """Build the damage breakdown column.

        Cases:
        - Miss: blank — the attack didn't land, so the roll is irrelevant.
        - Breakdown already contains `=`: show as-is (DamageRoll added it)
        - Breakdown is a single number matching raw damage: show just the number
        - Otherwise: append `= raw` so the reader can see the total
        """
        if parts["is_miss"]:
            return ""
        breakdown = parts["damage_breakdown"]
        raw = parts["raw_damage"]
        if "=" in breakdown:
            return breakdown
        if breakdown.strip() == str(raw):
            return breakdown
        return f"{breakdown} = {raw}"

    @staticmethod
    def _build_mult_column(parts: Dict[str, Any]) -> str:
        """Build the multiplier column content for a row.

        Returns an empty string for misses. Crits get an explicit `* 2`
        prefix to mark the built-in crit doubling (the `CRIT` label in
        the hit column already signals the crit; this just shows the
        multiplier math clearly). The trait multiplier is always shown
        (including 1.0), followed by `= sub`. The damage-type emoji is
        rendered separately in a trailing column so it doesn't disrupt
        alignment of the rest of the row.
        """
        if parts["is_miss"]:
            return ""

        crit_prefix = "* 2 " if parts["is_critical"] else ""
        mult = parts["multiplier"]
        mult_str = f"{mult:g}" if isinstance(mult, float) else str(mult)
        return f"{crit_prefix}* {mult_str} = {parts['sub_damage']}"

    @staticmethod
    def _prefix_for(parts: Dict[str, Any]) -> str:
        """Returns the diff-block prefix character for a result's display parts."""
        if parts["is_critical"]:
            return "!"
        if parts["is_miss"]:
            return "-"
        return "+"

    def _build_header(self) -> str:
        """Build a per-sequence header string.

        Players get a Discord mention; other creatures get a capitalized name.
        Multi-target attacks (auto-hit results with multiple victims) get a
        generic "attacks everyone" header instead of naming one victim.
        """
        from caldanai.lib.rpg.creatures.player import Player

        if isinstance(self.attacker, Player) and getattr(self.attacker, "member", None):
            return f"<@!{self.attacker.member.id}>'s attack:"

        attacker_name = getattr(self.attacker, "name", "") or "Something"
        is_auto_hit_aoe = len(self.results) > 1 and all(r.auto_hit for r in self.results)
        if is_auto_hit_aoe:
            return f"**{attacker_name.capitalize()} attacks everyone:**"
        if self.multi_target:
            return f"**{attacker_name.capitalize()} lashes out:**"

        target_name = getattr(self.target, "name", "") or "the target"
        return f"**{attacker_name.capitalize()} attacks {target_name}:**"
