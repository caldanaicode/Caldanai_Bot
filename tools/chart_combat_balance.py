"""Render a combat-balance scatter chart for every monster in the
bestiary (and a default Player baseline) and optionally post it
to a Discord channel as an image attachment.

Why this tool exists
--------------------

The combat-balance design conversation (small monsters reading
"too dodgy", HP-vs-defense outliers, etc.) keeps reaching for a
shared picture of where every creature sits in the trade-space.
Computing those numbers by hand from each plugin's dice strings
is error-prone — sizes carry multipliers, dodge/defense emerge
from body-part ratios, and Player baselines are different again.

This tool composes the same ``get_dodge`` / ``get_defense`` /
``health_max`` paths the live game uses, averages them across
multiple instantiations to flatten dice noise, and renders a
single scatter chart with monster name labels.

Default mode is **dry-run** — saves a PNG to disk so the
operator can preview before committing to a Discord post. Use
``--post`` to actually upload via discord.py.

Usage
-----

::

    python -m tools.chart_combat_balance              # dry-run, ./balance-chart.png
    python -m tools.chart_combat_balance --post       # upload to TEST game channel
    python -m tools.chart_combat_balance LIVE_DB_NAME --post
                                                       # upload to LIVE updates channel
    python -m tools.chart_combat_balance --output /tmp/balance.png
    python -m tools.chart_combat_balance --post --channel-id 123456789012345678

Default DB env var is ``TEST_DB_NAME``. **Channel default
varies by env**: TEST posts land in the active *games* channel
(where the tester bot lives + the operator is iterating in real
time); LIVE posts land in the configured *updates* channel
(player-facing announcement, same place as patch notes). Pass
``--channel-id <id>`` to override.

Token sourcing
--------------

- ``TEST_DB_NAME`` -> ``CLAUDE_TESTER_TOKEN`` env var (the tester
  bot, posts as ``@Vael Caldanai``). Same path as
  ``tools/bot_player.py``.
- ``LIVE_DB_NAME`` -> ``get_auth()["TOKEN"]`` (the main bot's
  token from MongoDB ``auth``). Same path as
  ``tools/post_patch_notes.py``.

Discord upload uses ``discord.py`` (already a project
dependency) — short-lived ``discord.Client``, ``fetch_channel``
the target, ``channel.send(file=discord.File(...))``, ``close``.
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
from collections import OrderedDict
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import matplotlib

# Force a non-interactive backend before pyplot imports — tools
# run headless on Windows + CI; the default backend would try to
# open a window or warn loudly.
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

from caldanai.lib.rpg.creatures.monsters import MonsterPlugin  # noqa: E402
from caldanai.lib.rpg.helpers.enums import Size  # noqa: E402
from caldanai.lib.rpg.helpers.plotting import (  # noqa: E402
    DEFAULT_ACCENT,
    style_axes_dark,
)

from tools._common import get_auth, live_db, use_db_env_var  # noqa: E402


_DEFAULT_OUTPUT = Path("./balance-chart.png")
_DEFAULT_TRIALS = 20
_DEFAULT_CAPTION = (
    "Combat balance — dodge x defense by size class. "
    "Marker size = HP. Equipment ignored."
)

# Color per Size category. Picked for legibility on Discord
# dark-mode (transparent PNG composites onto dark grey) — small
# critters get cool hues, big ones get warm, with a clean ramp
# in between.
_SIZE_COLORS: "Dict[Size, str]" = {
    Size.TINY:     "#7fdcff",  # ice blue
    Size.SMALL:    "#7cf0a4",  # mint
    Size.MEDIUM:   "#f0e57c",  # straw
    Size.LARGE:    "#f0a87c",  # peach
    Size.HUGE:     "#f07c7c",  # coral
    Size.COLOSSAL: "#d97cf0",  # violet
}


# --------------------------------------------------------------------
# Sample collection
# --------------------------------------------------------------------


def _enumerate_monster_classes() -> "List[type]":
    """Load monster plugins and return one class per registered
    monster, deduped on the class identity (so hydra variants
    don't double-count via aliases)."""
    MonsterPlugin.load_plugins()
    seen: set = set()
    out: list = []
    for plugin_cls in MonsterPlugin._PLUGIN_REGISTRY.values():
        if plugin_cls in seen:
            continue
        seen.add(plugin_cls)
        out.append(plugin_cls)
    # Stable order by class name so the chart annotation layout
    # is reproducible across runs (matplotlib's draw order is
    # input-order; same class list -> same overlap pattern).
    out.sort(key=lambda c: c.__name__.lower())
    return out


def _sample_monster_stats(
    plugin_cls: type, trials: int,
) -> Optional[dict]:
    """Instantiate a monster ``trials`` times with default args
    and return averaged dodge / defense / HP, plus the size and
    display name. Returns ``None`` when instantiation raises —
    don't let one broken plugin take the whole chart down."""
    dodges: list = []
    defenses: list = []
    hps: list = []
    size: Optional[Size] = None
    name: str = plugin_cls.__name__
    for _ in range(trials):
        try:
            inst = plugin_cls()
        except Exception as e:
            print(
                f"  ! skipping {plugin_cls.__name__}: instantiation "
                f"failed ({e})",
                file=sys.stderr,
            )
            return None
        try:
            dodges.append(int(inst.get_dodge()))
            defenses.append(int(inst.get_defense()))
            hps.append(int(inst.health_max))
        except Exception as e:
            print(
                f"  ! skipping {plugin_cls.__name__}: stat read "
                f"failed ({e})",
                file=sys.stderr,
            )
            return None
        if size is None:
            size = getattr(inst, "size", Size.MEDIUM)
        if getattr(inst, "name", None):
            name = inst.name
    if not dodges:
        return None
    return {
        "label": name,
        "size": size or Size.MEDIUM,
        "dodge": sum(dodges) / len(dodges),
        "defense": sum(defenses) / len(defenses),
        "hp": sum(hps) / len(hps),
    }


def _sample_player_stats(trials: int) -> Optional[dict]:
    """Build a default Player baseline, when a clean construction
    path is available. Players take many keyword args — we only
    need defense / dodge / HP / size, all of which have defaults
    on the constructor (defense=6, dodge=6, health_max=20,
    size=MEDIUM via Creature). Returns ``None`` and prints a
    note when the import or construction fails — we'd rather
    skip the baseline than crash the chart."""
    try:
        from caldanai.lib.rpg.creatures.player import Player
    except Exception as e:
        print(
            f"  ! skipping player baseline: import failed ({e})",
            file=sys.stderr,
        )
        return None
    dodges: list = []
    defenses: list = []
    hps: list = []
    size: Optional[Size] = None
    for _ in range(trials):
        try:
            p = Player()
        except Exception as e:
            print(
                f"  ! skipping player baseline: construction "
                f"failed ({e})",
                file=sys.stderr,
            )
            return None
        try:
            dodges.append(int(p.get_dodge()))
            defenses.append(int(p.get_defense()))
            hps.append(int(p.health_max))
        except Exception as e:
            print(
                f"  ! skipping player baseline: stat read failed "
                f"({e})",
                file=sys.stderr,
            )
            return None
        if size is None:
            size = getattr(p, "size", Size.MEDIUM)
    if not dodges:
        return None
    return {
        "label": "player (default)",
        "size": size or Size.MEDIUM,
        "dodge": sum(dodges) / len(dodges),
        "defense": sum(defenses) / len(defenses),
        "hp": sum(hps) / len(hps),
        "is_player": True,
    }


def collect_samples(
    trials: int = _DEFAULT_TRIALS,
    include_player: bool = True,
) -> "List[dict]":
    """Collect averaged stat samples for every loaded monster
    (and optionally a default Player baseline). Returns a list of
    sample dicts with ``label`` / ``size`` / ``dodge`` /
    ``defense`` / ``hp`` keys."""
    samples: list = []
    for cls in _enumerate_monster_classes():
        s = _sample_monster_stats(cls, trials)
        if s is not None:
            samples.append(s)
    if include_player:
        ps = _sample_player_stats(trials)
        if ps is not None:
            samples.append(ps)
    return samples


# --------------------------------------------------------------------
# Plotting
# --------------------------------------------------------------------


def _hp_to_marker_area(hp: float, all_hps: "List[float]") -> float:
    """Map HP to scatter marker area in points^2.

    Linear-rescale so the smallest HP creature gets a readable
    minimum marker and the largest stays inside a sane upper
    bound — a HUGE dragon dwarfs a TINY pixie by 8x in HP_max
    alone, plus dice spread, so a raw proportional mapping
    leaves pixie marker invisible.
    """
    if not all_hps:
        return 80.0
    lo = min(all_hps)
    hi = max(all_hps)
    if hi <= lo:
        return 200.0
    min_area = 80.0
    max_area = 800.0
    t = (hp - lo) / (hi - lo)
    return min_area + t * (max_area - min_area)


def build_figure(samples: "List[dict]") -> "plt.Figure":
    """Render the dodge x defense scatter as a matplotlib figure.

    X axis defense, Y axis dodge, color by Size, marker area by
    HP_max, label per point. Player baseline (when present) is
    drawn with a star marker so it pops.

    Caller owns saving and closing the figure — see
    :func:`save_figure_to_path` for the dry-run path or use
    :func:`caldanai.lib.rpg.helpers.plotting.fig_to_file` for the
    Discord-attachment path.
    """
    fig, ax = plt.subplots(figsize=(11, 8))
    ax.set_title(
        "Caldanai bestiary — dodge x defense (innate, equipment ignored)",
        color=DEFAULT_ACCENT,
        fontsize=14,
    )
    ax.set_xlabel("defense (averaged)")
    ax.set_ylabel("dodge (averaged)")

    if not samples:
        # Empty-data degenerate case — draw the axes anyway so
        # the file isn't broken; consumers (tests) just check for
        # a non-empty PNG.
        style_axes_dark(ax, accent_color=DEFAULT_ACCENT, grid_axis="both")
        return fig

    all_hps = [s["hp"] for s in samples]

    # Plot per-size groups so the legend reads cleanly. Iterate
    # in Size enum order (TINY -> COLOSSAL) for a logical legend.
    plotted_sizes: "OrderedDict[Size, None]" = OrderedDict()
    for size_cat in Size:
        group = [s for s in samples if s["size"] == size_cat]
        if not group:
            continue
        plotted_sizes[size_cat] = None
        color = _SIZE_COLORS.get(size_cat, DEFAULT_ACCENT)
        for s in group:
            area = _hp_to_marker_area(s["hp"], all_hps)
            marker = "*" if s.get("is_player") else "o"
            # Player marker wants a chunkier base area so the
            # star isn't a tiny smear at default sizes.
            if s.get("is_player"):
                area = max(area, 250.0)
            ax.scatter(
                [s["defense"]], [s["dodge"]],
                s=[area],
                c=[color],
                marker=marker,
                edgecolors=DEFAULT_ACCENT,
                linewidths=0.6,
                alpha=0.85,
                label=size_cat.name if size_cat not in plotted_sizes else None,
            )

    # Annotate every point with the creature label. Small offset
    # in pixels so the dot itself stays visible underneath. Use
    # the size-category color so an outlier visually ties to its
    # marker.
    for s in samples:
        ax.annotate(
            s["label"],
            xy=(s["defense"], s["dodge"]),
            xytext=(6, 4),
            textcoords="offset points",
            fontsize=9,
            color=_SIZE_COLORS.get(s["size"], DEFAULT_ACCENT),
        )

    # One legend entry per size class. Build manually since the
    # per-point labels above would create one entry per point.
    handles = []
    labels = []
    for size_cat in plotted_sizes:
        color = _SIZE_COLORS.get(size_cat, DEFAULT_ACCENT)
        handles.append(
            plt.Line2D(
                [], [], marker="o", color=color, linestyle="",
                markersize=9, markeredgecolor=DEFAULT_ACCENT,
                label=size_cat.name,
            ),
        )
        labels.append(size_cat.name)
    if any(s.get("is_player") for s in samples):
        handles.append(
            plt.Line2D(
                [], [], marker="*", color=DEFAULT_ACCENT, linestyle="",
                markersize=12, label="player",
            ),
        )
        labels.append("player")
    legend = ax.legend(
        handles=handles,
        labels=labels,
        loc="best",
        facecolor=(0, 0, 0, 0),
        edgecolor=DEFAULT_ACCENT,
        labelcolor=DEFAULT_ACCENT,
        fontsize=9,
    )
    if legend is not None:
        legend.get_frame().set_alpha(0.4)

    style_axes_dark(ax, accent_color=DEFAULT_ACCENT, grid_axis="both")
    # Both-axis grid is cleaner than the default "y" for a
    # scatter — readers pull positions off both axes.
    return fig


def save_figure_to_path(fig: "plt.Figure", path: Path) -> None:
    """Write the figure to ``path`` as a transparent PNG and
    close the figure. Mirrors what ``fig_to_file`` does for the
    Discord-attachment path, but writes to disk instead of a
    BytesIO so the operator can preview the file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        fig.savefig(
            path, format="png", transparent=True, bbox_inches="tight",
        )
    finally:
        plt.close(fig)


# --------------------------------------------------------------------
# Discord upload
# --------------------------------------------------------------------


def _resolve_target_channel(
    db_env_var: str, channel_id_override: Optional[int],
) -> Tuple[int, str]:
    """Resolve which channel to post to. ``channel_id_override``
    short-circuits the lookup. Otherwise:

    - **TEST_DB_NAME**: target the active *games* channel (where
      the tester bot lives + the operator is actually watching).
      Mirrors ``tools/bot_player._resolve_test_channel_id``. The
      updates channel is wrong default for TEST — operators
      iterate on chart output in the same channel they're
      playtesting in, not in a separate announcements feed.
    - **LIVE_DB_NAME**: target the configured *updates* channel.
      LIVE chart posts are player-facing balance announcements
      that belong in the same place as patch notes.

    Returns ``(channel_id, friendly_label)``. Raises
    :class:`SystemExit` with operator guidance when no candidate
    is configured."""
    if channel_id_override is not None:
        return int(channel_id_override), f"channel {channel_id_override}"
    use_db_env_var(db_env_var)
    if db_env_var == "TEST_DB_NAME":
        docs = list(
            live_db().games.find(
                {"channel_id": {"$exists": True}},
                {"channel_id": 1, "guild_id": 1},
            )
        )
        if not docs:
            raise SystemExit(
                "No game found in TEST_DB_NAME.games. Run the bot "
                "once in the test channel to initialize a game doc, "
                "or pass --channel-id <id> to override."
            )
        if len(docs) > 1:
            guilds = ", ".join(str(d.get("guild_id")) for d in docs)
            raise SystemExit(
                f"Multiple games found in TEST_DB_NAME.games "
                f"({guilds}). Pass --channel-id <id> to disambiguate."
            )
        channel_id = int(docs[0]["channel_id"])
        return (
            channel_id,
            f"TEST game channel (guild {docs[0].get('guild_id')}, "
            f"channel {channel_id})",
        )
    docs = list(
        live_db().servers.find({"channels.updates": {"$exists": True}})
    )
    if not docs:
        raise SystemExit(
            f"No guilds with an updates channel configured under "
            f"{db_env_var!r}. Set one via Discord: "
            f"$config channel updates <#mention> — or pass "
            f"--channel-id <id> to override."
        )
    if len(docs) > 1:
        listing = ", ".join(
            f"{d.get('name') or d['guild_id']} (channel "
            f"{d['channels']['updates']})"
            for d in docs
        )
        raise SystemExit(
            f"Multiple updates channels found under {db_env_var!r}: "
            f"{listing}. Pass --channel-id <id> to disambiguate."
        )
    doc = docs[0]
    channel_id = int(doc["channels"]["updates"])
    label = (
        f"{doc.get('name') or 'unnamed-guild'} "
        f"(guild {doc['guild_id']}, channel {channel_id})"
    )
    return channel_id, label


def _resolve_token(db_env_var: str) -> str:
    """Pick the bot token to authenticate the upload with.

    TEST -> ``CLAUDE_TESTER_TOKEN`` env var (tester bot,
    ``tools/bot_player.py`` lineage). LIVE -> the auth document's
    ``TOKEN`` field via ``get_auth()`` (same path
    ``tools/post_patch_notes.py`` uses)."""
    if db_env_var == "TEST_DB_NAME":
        token = os.environ.get("CLAUDE_TESTER_TOKEN")
        if not token:
            raise SystemExit(
                "CLAUDE_TESTER_TOKEN env var not set. Drop the "
                "tester-bot token in .env under that name and "
                "re-run."
            )
        return token
    auth = get_auth()
    token = auth.get("TOKEN")
    if not token:
        raise SystemExit(
            f"Auth document on {db_env_var!r} has no TOKEN field — "
            "can't authenticate to Discord."
        )
    return token


async def _post_via_discord_py(
    token: str, channel_id: int, png_path: Path, caption: str,
) -> None:
    """Upload the PNG as a message attachment using discord.py's
    native multipart support. Short-lived ``discord.Client`` —
    connect, send, close, exit. No Gateway-side state to worry
    about beyond the brief ``on_ready`` handshake."""
    import discord  # type: ignore

    intents = discord.Intents.none()
    intents.guilds = True  # required for fetch_channel on a guild channel
    client = discord.Client(intents=intents)

    posted: dict = {}

    @client.event
    async def on_ready() -> None:
        try:
            channel = await client.fetch_channel(channel_id)
            msg = await channel.send(
                content=caption,
                file=discord.File(str(png_path), filename="balance.png"),
            )
            posted["id"] = str(msg.id)
            posted["channel_id"] = str(channel.id)
        finally:
            await client.close()

    await client.start(token)
    if "id" in posted:
        print(
            f"  posted message id={posted['id']} "
            f"to channel {posted['channel_id']}",
        )


# --------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(
        description=__doc__.split("\n\n")[0],
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    ap.add_argument(
        "db_env_var",
        nargs="?",
        default="TEST_DB_NAME",
        help=(
            "Env var holding the Mongo DB name to target for "
            "channel discovery + (LIVE only) auth-token lookup. "
            "Default: TEST_DB_NAME (post lands in TEST). Pass "
            "LIVE_DB_NAME to target the live updates channels."
        ),
    )
    ap.add_argument(
        "--post",
        action="store_true",
        help="Actually upload the PNG to the resolved updates "
             "channel via discord.py. Without this flag, runs "
             "in dry-run mode (writes the PNG to disk and exits).",
    )
    ap.add_argument(
        "--output",
        type=Path,
        default=_DEFAULT_OUTPUT,
        help=(
            f"Path to write the PNG in dry-run mode "
            f"(default: {_DEFAULT_OUTPUT}). Also written before "
            f"upload in --post mode so the file is on disk for "
            f"reference."
        ),
    )
    ap.add_argument(
        "--channel-id",
        type=int,
        default=None,
        help="Override the channel id discovered from the DB's "
             "servers.channels.updates registry.",
    )
    ap.add_argument(
        "--trials",
        type=int,
        default=_DEFAULT_TRIALS,
        help=(
            f"Number of instantiations to average per creature "
            f"(default: {_DEFAULT_TRIALS}). Higher values flatten "
            f"dice noise at the cost of plugin-construction time."
        ),
    )
    ap.add_argument(
        "--no-player",
        action="store_true",
        help="Skip the default-Player baseline marker.",
    )
    ap.add_argument(
        "--caption",
        type=str,
        default=_DEFAULT_CAPTION,
        help="Text to post alongside the image attachment.",
    )
    args = ap.parse_args(argv)

    print("Collecting samples...")
    samples = collect_samples(
        trials=args.trials, include_player=not args.no_player,
    )
    monster_count = sum(1 for s in samples if not s.get("is_player"))
    print(f"  {monster_count} monsters charted", end="")
    if any(s.get("is_player") for s in samples):
        print(" + 1 player baseline")
    else:
        print()

    fig = build_figure(samples)
    save_figure_to_path(fig, args.output)
    size_bytes = args.output.stat().st_size if args.output.exists() else 0
    print(f"  wrote {args.output} ({size_bytes:,} bytes)")

    if not args.post:
        print()
        print("Dry-run only. Re-run with --post to upload.")
        return 0

    channel_id, label = _resolve_target_channel(
        args.db_env_var, args.channel_id,
    )
    token = _resolve_token(args.db_env_var)
    print(f"Posting to {label} ...")
    asyncio.run(
        _post_via_discord_py(token, channel_id, args.output, args.caption),
    )
    print("Done.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
