"""Sectioned checklist driver for the fuzzy-matching rework's
manual playtest. Fires each test command via :mod:`tools.bot_player`
against the TEST guild, with annotation headers preceding each
section so the channel log reads as a self-documenting record.

Why this exists
---------------

The fuzzy-matching rework touched eight commands across mention /
fuzzy / case-insensitive / typo paths. Manually typing every test
case is error-prone; missing a path is easy. This driver enumerates
the cases programmatically, paces them to avoid Discord rate-limit
or response-collision (combat round arrives before next command
gets typed), and lets the operator filter to one section at a time
when iterating on a specific bug.

Channel
-------

Defaults to the OOC engineering channel (``OOC_CHANNEL_ID`` env)
because the sweep mixes admin commands (``$creature destroy``,
``$spawn``) with non-combat commands (``$health``, ``$craft``,
``$warmth``) and shouldn't interfere with live combat state in
the regular TEST channel. Pass ``--combat`` to route to the
regular TEST channel instead (resolved through
``BOT_PLAYER_CHANNEL_ID`` / ``TEST_DB_NAME`` lookup, same as
``bot_player send``).

Usage
-----

::

    # Run the full sweep in the OOC channel (default).
    python -m tools.test_fuzzy_paths

    # Run one section.
    python -m tools.test_fuzzy_paths --section haunt
    python -m tools.test_fuzzy_paths --section equip

    # Force the TEST combat channel instead of OOC.
    python -m tools.test_fuzzy_paths --combat --section spawn

    # List sections and their commands without sending.
    python -m tools.test_fuzzy_paths --dry-run

    # List the section keys.
    python -m tools.test_fuzzy_paths --list

    # Pause after each section for manual verification (waits for
    # operator to press Enter before continuing).
    python -m tools.test_fuzzy_paths --pause-between-sections

Preconditions
-------------

Some sections need specific game state — a monster spawned, a
player in inventory with specific items, a player dead, etc. Each
section's :attr:`preconditions` block is announced as a
human-readable header before the commands fire. The operator is
responsible for setting up state (manually or via an earlier
section) — the driver does NOT spawn monsters or alter inventory.

Commands paced at ~2.5s default to leave room for combat-round
narration to land between sends.
"""
from __future__ import annotations

import argparse
import asyncio
import os
import sys
from dataclasses import dataclass, field
from typing import List, Optional, Tuple

# Reuse bot_player's posting machinery; it already handles channel
# resolution, token loading, and Discord REST plumbing.
from tools.bot_player import _post, _resolve_ooc_channel_id


@dataclass
class Section:
    key: str
    title: str
    preconditions: str
    cases: List[Tuple[str, str]] = field(default_factory=list)


SECTIONS: List[Section] = [
    Section(
        key="haunt",
        title="$haunt — fuzzy monster names (was exact-only)",
        preconditions=(
            "Spawn a hexed hydra or other multi-word monster. "
            "Tester bot can be dead or alive — the fuzzy-name path "
            "fires regardless of player state, only the rendered "
            "flavor differs."
        ),
        cases=[
            ("Exact match", "$haunt hexed hydra"),
            ("Prefix-of-token (forcing case)", "$haunt hyd"),
            ("Single-letter (single monster present)", "$haunt h"),
            ("No-match fallback to ghostly flavor", "$haunt xyzzy"),
        ],
    ),
    Section(
        key="look",
        title="$look — routed through shared resolver",
        preconditions="Same monster as $haunt section.",
        cases=[
            ("Full name", "$look hexed hydra"),
            ("Prefix on second token", "$look hyd"),
            ("Single token", "$look hexed"),
            ("Direction (non-monster path)", "$look n"),
            ("Empty (room description)", "$look"),
        ],
    ),
    Section(
        key="creature_destroy",
        title="$creature destroy — was substring `in`, now fuzzy",
        preconditions=(
            "Admin-permission user. Monster spawned with multiple "
            "head/arm parts (hydra is ideal). Defaults to current "
            "monster when no name is provided."
        ),
        cases=[
            ("Default monster + part", "$creature destroy head.1"),
            ("Fuzzy monster + part", "$creature destroy hyd head.2"),
            ("Multi-part destroy", "$creature destroy arm.left leg.right"),
        ],
    ),
    Section(
        key="kill",
        title="$kill / $attack — combat with monster prefix + part",
        preconditions=(
            "Monster spawned (werewolf has foreleg/hindleg parts "
            "for the substring tier; hydra exercises the conflict_check)."
        ),
        cases=[
            ("Monster prefix peel", "$kill werewolf arm.left"),
            ("Typo on monster name (edit-distance)", "$kill werwlf arm.l"),
            ("Single-letter conflict_check (h → head, NOT hydra)", "$kill h"),
            ("Substring fallback on parts (l.l → both .left legs)", "$kill l.l"),
            ("Parts only", "$kill leg.r"),
        ],
    ),
    Section(
        key="target",
        title="$target / $aim — same as $kill for parts",
        preconditions=(
            "Already in combat against a monster with multiple parts."
        ),
        cases=[
            ("Single part", "$target leg.r"),
            ("Multi-target", "$target arm.left leg.right"),
            ("Substring fallback", "$target leg"),
            ("Clear targeting", "$target"),
        ],
    ),
    Section(
        key="health",
        title="$health — NEW: fuzzy player resolution",
        preconditions=(
            "Multiple players in the game (Caels + Vael + tester) "
            "with at least one having injuries for the keyword "
            "filters to populate."
        ),
        cases=[
            ("Own health (no arg)", "$health"),
            ("Keyword: all", "$health all"),
            ("Keyword: hurt", "$health hurt"),
            ("Keyword: injured", "$health injured"),
            ("Keyword: active", "$health active"),
            ("Fuzzy player by display-name prefix", "$health Cael"),
            ("Fuzzy player by Vael's name", "$health Vae"),
            ("Stripped-@ malformed mention", "$health @Caels"),
            ("Unknown player → fallback to own", "$health xyzzy"),
        ],
    ),
    Section(
        key="warmth",
        title="$warmth — NEW: FuzzyMemberConverter on `who` arg",
        preconditions=(
            "DM-only output — check tester bot's DMs, not the "
            "channel, for confirmation. ``set <verb> <level> [@who]`` "
            "and ``clear <verb> [@who]`` accept fuzzy username for "
            "`who`."
        ),
        cases=[
            ("Fuzzy username", "$warmth set hug 5 Cael"),
            ("Mention path", "$warmth set hug 5 @Caels"),
            ("Bare default (no who)", "$warmth set hug 4"),
            ("Clear with fuzzy username", "$warmth clear hug Cael"),
            ("Bad fuzzy → BadArgument", "$warmth set hug 5 nobodyxyz"),
        ],
    ),
    Section(
        key="craft",
        title="$craft — fuzzy + ambiguity + case_insensitive group",
        preconditions=(
            "Tester bot needs leather materials in inventory for the "
            "exact-name craft to succeed; the fuzzy / ambiguity / "
            "case paths surface from the resolver regardless of "
            "materials."
        ),
        cases=[
            ("Exact stem", "$craft leather_jerkin"),
            ("Prefix to unique recipe", "$craft jerkin"),
            ("Ambiguous (lists candidates)", "$craft leather"),
            ("Case-insensitive group invocation", "$CRAFT jerkin"),
            ("Subcommand: info via fuzzy", "$craft info jerkin"),
            ("Unknown recipe", "$craft xyzzy"),
        ],
    ),
    Section(
        key="equip",
        title="$equip — behavior change: prefix-wins + typo-tolerant",
        preconditions=(
            "Tester bot has a `wand` and a `magic_wand` in inventory "
            "(or equivalent name-collision pair). The behavior delta "
            "vs the old substring-only filter only shows when both "
            "are present."
        ),
        cases=[
            ("Exact wins (only literal wand)", "$equip wand"),
            ("Prefix-resolves alternate", "$equip mag"),
            ("Typo via edit-distance", "$equip wnd"),
            ("Quality selector still works", "$equip wand.best"),
            ("Fully-qualified bypass", "$equip wand.fine.1"),
            ("Multi-arg form", "$equip wand@l dagger@r"),
            ("Legacy 2-arg trailing slot", "$equip wand left"),
        ],
    ),
    Section(
        key="stow",
        title="$stow — same shared item resolver",
        preconditions="Tester bot has equipped items.",
        cases=[
            ("Placement key", "$stow worn"),
            ("Held shortcut", "$stow held"),
            ("Specific placement", "$stow head.worn"),
            ("Item-name fuzzy", "$stow wand"),
            ("Stow all", "$stow all"),
        ],
    ),
    Section(
        key="spawn",
        title="$spawn — rebuilt on shared resolver (expect no diff)",
        preconditions="Admin-permission user; clear the channel of monsters first.",
        cases=[
            ("Exact stem", "$spawn hydra"),
            ("Fuzzy prefix", "$spawn hyd"),
            ("Display-name alias", "$spawn flying math teacher"),
            ("Underscored stem", "$spawn math_teacher"),
            ("Unknown", "$spawn xyzzy"),
        ],
    ),
    Section(
        key="errors",
        title="Negative paths — verify clean error messages, not stack traces",
        preconditions="No special setup; failures should produce friendly text.",
        cases=[
            ("Mention to non-game-player",
             "$haunt <@!000000000000000000>"),
            ("Craft unknown", "$craft definitely_not_a_recipe"),
            ("Craft ambiguous", "$craft leather"),
            ("Health unknown player", "$health definitely_not_a_player"),
        ],
    ),
]


def _section_by_key(key: str) -> Optional[Section]:
    for s in SECTIONS:
        if s.key == key:
            return s
    return None


def _format_header(section: Section) -> str:
    """Markdown-formatted annotation that lands in-channel before
    the section's commands. Discord renders the bold + bullet."""
    parts = [
        f"**🧪 fuzzy-rework checklist — `{section.key}`**",
        f"*{section.title}*",
        f"_Preconditions:_ {section.preconditions}",
    ]
    return "\n".join(parts)


async def _run_section(
    section: Section,
    *,
    pacing_seconds: float,
    dry_run: bool,
    pause_between_sections: bool,
    channel_id: Optional[int],
) -> None:
    print(f"\n=== {section.key}: {section.title} ===")
    print(f"Preconditions: {section.preconditions}\n")
    if not dry_run:
        await _post(
            _format_header(section), guild_filter=None,
            channel_id_override=channel_id,
        )
        await asyncio.sleep(pacing_seconds)
    for label, cmd in section.cases:
        print(f"  • {label}: {cmd}")
        if dry_run:
            continue
        # Annotation precedes the actual command so anyone reading
        # the channel later understands what the test was checking.
        await _post(
            f"// **{label}**", guild_filter=None,
            channel_id_override=channel_id,
        )
        await asyncio.sleep(0.5)
        await _post(
            cmd, guild_filter=None,
            channel_id_override=channel_id,
        )
        await asyncio.sleep(pacing_seconds)
    if pause_between_sections and not dry_run:
        try:
            input(
                f"\n→ section `{section.key}` complete. "
                f"Press Enter to continue, Ctrl-C to abort: "
            )
        except KeyboardInterrupt:
            print("\nAborted.")
            sys.exit(1)


async def _run(
    section_keys: Optional[List[str]],
    *,
    pacing_seconds: float,
    dry_run: bool,
    pause_between_sections: bool,
    channel_id: Optional[int],
) -> None:
    if section_keys:
        sections = [_section_by_key(k) for k in section_keys]
        missing = [k for k, s in zip(section_keys, sections) if s is None]
        if missing:
            raise SystemExit(
                f"Unknown section(s): {', '.join(missing)}. "
                f"Use --list to see available section keys."
            )
        sections = [s for s in sections if s is not None]
    else:
        sections = list(SECTIONS)

    for section in sections:
        await _run_section(
            section,
            pacing_seconds=pacing_seconds,
            dry_run=dry_run,
            pause_between_sections=pause_between_sections,
            channel_id=channel_id,
        )

    if dry_run:
        print("\n(dry run — nothing was sent)")
    else:
        print("\n✓ Sweep complete.")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        description=__doc__.split("\n\n")[0],
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    ap.add_argument(
        "--section", action="append", default=None,
        help=(
            "Run only the named section(s). Repeatable: "
            "``--section haunt --section look``. Default runs all."
        ),
    )
    ap.add_argument(
        "--list", action="store_true",
        help="List section keys and exit.",
    )
    ap.add_argument(
        "--dry-run", action="store_true",
        help="Print sections + commands without sending to Discord.",
    )
    ap.add_argument(
        "--pause-between-sections", action="store_true",
        help=(
            "After each section, wait for Enter before continuing. "
            "Lets the operator eyeball results without the next "
            "section's commands rolling in."
        ),
    )
    ap.add_argument(
        "--pacing", type=float, default=2.5,
        help=(
            "Seconds between commands. Default 2.5 — large enough to "
            "let combat-round narration land between sends without "
            "Discord rate-limiting."
        ),
    )
    ap.add_argument(
        "--combat", action="store_true",
        help=(
            "Route to the regular TEST combat channel instead of the "
            "OOC engineering channel. Default OFF — the rework sweep "
            "lands in OOC so it doesn't disrupt live combat state."
        ),
    )
    args = ap.parse_args(argv)

    if args.list:
        for s in SECTIONS:
            print(f"  {s.key:<22}  {s.title}")
        return 0

    # Channel resolution: default = OOC; --combat opts into the
    # bot_player default (TEST channel via DB lookup).
    if args.combat:
        channel_id: Optional[int] = None  # bot_player resolves TEST
    else:
        channel_id = _resolve_ooc_channel_id()

    asyncio.run(
        _run(
            section_keys=args.section,
            pacing_seconds=args.pacing,
            dry_run=args.dry_run,
            pause_between_sections=args.pause_between_sections,
            channel_id=channel_id,
        )
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
