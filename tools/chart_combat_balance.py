"""Render a combat-balance chart for every monster in the bestiary
(and a default Player baseline) and optionally post it to a Discord
channel as an image attachment.

Why this tool exists
--------------------

The combat-balance design conversation (small monsters reading
"too dodgy", HP-vs-defense outliers, etc.) keeps reaching for a
shared picture of where every creature sits in the trade-space.
Computing those numbers by hand from each plugin's dice strings
is error-prone — sizes carry multipliers, dodge/defense emerge
from body-part ratios, and Player baselines are different again.

This tool composes the same ``get_dodge`` / ``get_defense`` /
``health_max`` / ``get_attack_sources`` paths the live game uses,
averages them across multiple instantiations to flatten dice
noise, and renders one of three views:

- ``scatter`` — dodge x defense, color by Size, marker area by HP
  (sqrt-scaled so a TINY toad doesn't get crushed by a COLOSSAL
  hydra in the encoding).
- ``survivability`` — offense x effective-HP-under-attack. Bakes
  HP, dodge, and defense into one "wall vs glass cannon" axis so
  the chart answers *who actually soaks* rather than *who looks
  like they should*.
- ``parallel`` — a parallel-coordinates plot crossing dodge,
  defense, HP, attack, and size. Each monster is a single line;
  outliers diverge from the cluster at one or more axes.

Default mode is **dry-run** — saves a PNG to disk so the
operator can preview before committing to a Discord post. Use
``--post`` to actually upload via discord.py.

Usage
-----

::

    python -m tools.chart_combat_balance              # dry-run scatter
    python -m tools.chart_combat_balance --view survivability
    python -m tools.chart_combat_balance --view parallel
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
import math
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


_DEFAULT_OUTPUT_TEMPLATE = "./balance-chart-{view}.png"
_DEFAULT_TRIALS = 20

# View id -> default caption. Captions explain what's plotted +
# what's encoded so a Discord scroller doesn't have to squint at
# axis labels to orient.
_VIEW_CAPTIONS: Dict[str, str] = {
    "scatter": (
        "Combat balance — dodge x defense by size class. "
        "Marker size = HP (sqrt-scaled). Equipment ignored."
    ),
    "survivability": (
        "Survivability — attack avg (X) vs effective HP under "
        "attack (Y, baking miss rate + damage reduction at "
        "baseline player skill). Marker = Size; size = HP."
    ),
    "parallel": (
        "Parallel coordinates — every monster as one line across "
        "dodge / defense / HP / attack / size. Lines diverging "
        "from the cluster at any axis are outliers."
    ),
}

# For survivability — average raw damage of a single player
# attack at baseline. Picked from the arcane-heavy slot's
# expected output (~2d6+1 = 8 avg). Defense subtracts off this
# linearly, so the constant is documented here so a future tuning
# pass can adjust it without spelunking the function body. Raise
# this number to model a high-skill / well-armed party (defense
# matters less); lower it to model a fresh starter (defense is
# devastating).
_BASELINE_AVG_RAW_DAMAGE = 8.0


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

# Numeric ramp for the parallel-coords "size" axis. The Size
# enum has a `value` attribute, but its numeric ordering isn't
# guaranteed to be 0..5 contiguous across Python versions — we
# pin our own ramp to keep the chart axis stable.
_SIZE_NUMERIC: "Dict[Size, float]" = {
    Size.TINY:     0.0,
    Size.SMALL:    1.0,
    Size.MEDIUM:   2.0,
    Size.LARGE:    3.0,
    Size.HUGE:     4.0,
    Size.COLOSSAL: 5.0,
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


def _avg_damage_from_sources(inst) -> float:
    """Sum the analytical expected damage across all attack
    sources a creature exposes per round.

    Dice expected value ``count * (sides + 1) / 2`` plus the
    static modifier baked into the spec, plus any skill / weapon
    bonuses surfaced by the source's ``make_attack_rolls``. We
    sum across sources because most monsters fire every source
    each turn (hydra heads, cyclops triple-swing, werewolf
    desperate-lunge bonus). This gives a proper "per-round
    offense" number.

    Returns ``0.0`` and prints a note when the source list raises
    — a chart that quietly drops a monster is worse than one with
    a zero.
    """
    try:
        sources = inst.get_attack_sources()
    except Exception as e:  # pragma: no cover - defensive
        print(
            f"  ! attack-source lookup failed on "
            f"{type(inst).__name__}: {e}",
            file=sys.stderr,
        )
        return 0.0
    total = 0.0
    for src in sources or []:
        try:
            _atk_roll, dmg_roll = src.make_attack_rolls(inst)
        except Exception as e:  # pragma: no cover - defensive
            print(
                f"  ! make_attack_rolls failed on "
                f"{type(inst).__name__}: {e}",
                file=sys.stderr,
            )
            continue
        # ``rolls`` length == die count (a fresh roll happened in
        # the Dice constructor); sides is preserved on RollData.
        # Analytical mean is more stable than reading dmg_roll.result
        # which would only sample a single roll.
        count = len(getattr(dmg_roll, "rolls", ()) or ())
        sides = int(getattr(dmg_roll, "sides", 0) or 0)
        die_avg = count * (sides + 1) / 2 if count and sides else 0.0
        die_avg += int(getattr(dmg_roll, "diceModifier", 0) or 0)
        die_avg += int(getattr(dmg_roll, "skillBonus", 0) or 0)
        die_avg += int(getattr(dmg_roll, "weaponBonus", 0) or 0)
        total += die_avg
    return total


def _sample_monster_stats(
    plugin_cls: type, trials: int,
) -> Optional[dict]:
    """Instantiate a monster ``trials`` times with default args
    and return averaged dodge / defense / HP / attack, plus the
    size and display name. Returns ``None`` when instantiation
    raises — don't let one broken plugin take the whole chart
    down."""
    dodges: list = []
    defenses: list = []
    hps: list = []
    attacks: list = []
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
            attacks.append(_avg_damage_from_sources(inst))
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
        "attack": sum(attacks) / len(attacks),
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
    attacks: list = []
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
            attacks.append(_avg_damage_from_sources(p))
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
        "attack": sum(attacks) / len(attacks),
        "is_player": True,
    }


def collect_samples(
    trials: int = _DEFAULT_TRIALS,
    include_player: bool = True,
) -> "List[dict]":
    """Collect averaged stat samples for every loaded monster
    (and optionally a default Player baseline). Returns a list of
    sample dicts with ``label`` / ``size`` / ``dodge`` /
    ``defense`` / ``hp`` / ``attack`` keys."""
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
# Plotting — shared helpers
# --------------------------------------------------------------------


def _hp_to_marker_area(hp: float, all_hps: "List[float]") -> float:
    """Map HP to scatter marker area in points^2 with sqrt
    scaling.

    Linear scaling on raw HP makes a TINY toad (18 HP) and a
    SMALL spirit (33 HP) collapse to almost identical marker
    sizes when the dataset's upper end runs to dragon (200+) and
    hydra (300+). Sqrt of the normalized HP fraction spreads the
    low end out — toad and spirit become visibly different even
    against a colossal hydra in the same chart. Ceiling /
    floor still bounds the absolute range so an outlier doesn't
    blow out the legend.
    """
    if not all_hps:
        return 80.0
    lo = min(all_hps)
    hi = max(all_hps)
    if hi <= lo:
        return 200.0
    min_area = 80.0
    max_area = 800.0
    # Normalize to [0, 1] then sqrt to bias visibility toward the
    # low end. ``hp`` may briefly fall outside [lo, hi] due to
    # caller-side stretching — clamp before sqrt to keep
    # math.sqrt happy with non-negative input.
    t_linear = max(0.0, min(1.0, (hp - lo) / (hi - lo)))
    t = math.sqrt(t_linear)
    return min_area + t * (max_area - min_area)


def _build_size_legend_handles(
    samples: "List[dict]", plotted_sizes: "OrderedDict",
) -> Tuple[list, list]:
    """Build a single legend entry per Size class plus an
    optional player-baseline entry. Per-point ``label=`` would
    create one legend row per point, so we hand-roll Line2D
    proxies."""
    handles: list = []
    labels: list = []
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
    return handles, labels


# --------------------------------------------------------------------
# Plotting — scatter (default view)
# --------------------------------------------------------------------


def build_figure(samples: "List[dict]") -> "plt.Figure":
    """Render the dodge x defense scatter as a matplotlib figure.

    X axis defense, Y axis dodge, color by Size, marker area by
    HP_max (sqrt-scaled so small-HP differences read), label per
    point. Player baseline (when present) is drawn with a star
    marker so it pops.

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

    handles, labels = _build_size_legend_handles(samples, plotted_sizes)
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


# --------------------------------------------------------------------
# Plotting — survivability
# --------------------------------------------------------------------


def _miss_rate(dodge: float) -> float:
    """Probability that a baseline-skill player misses, given a
    monster's effective dodge.

    1d20 against the dodge target. Ceiling at 0.95 so a wildly
    over-dodgy monster (the math teacher's flying alpha pixie
    isn't far off) doesn't divide-by-zero downstream when we
    invert ``1 - miss_rate``.
    """
    return max(0.0, min(0.95, dodge / 20.0))


def _damage_reduction(defense: float, avg_raw_damage: float) -> float:
    """Fraction of incoming damage absorbed by defense, given
    ``avg_raw_damage`` raw output per swing. Capped at 0.95 so a
    wall of defense doesn't divide-by-zero in survivability."""
    if avg_raw_damage <= 0:
        return 0.0
    return max(0.0, min(0.95, defense / avg_raw_damage))


def _effective_hp(
    hp: float, dodge: float, defense: float,
    avg_raw_damage: float = _BASELINE_AVG_RAW_DAMAGE,
) -> float:
    """Effective HP under attack — what the displayed HP pool
    *feels* like once misses + defense are folded in.

    Formula::

        hp / ((1 - miss_rate(dodge)) * (1 - reduction(defense)))

    Both terms in the denominator are clamped strictly < 1 so the
    result stays finite even for a creature that's effectively
    untouchable on paper. The chart axis stays log-friendly.
    """
    miss = _miss_rate(dodge)
    reduction = _damage_reduction(defense, avg_raw_damage)
    hit_rate = max(1e-3, 1.0 - miss)
    pass_through = max(1e-3, 1.0 - reduction)
    return hp / (hit_rate * pass_through)


def build_survivability_figure(samples: "List[dict]") -> "plt.Figure":
    """Render the survivability view.

    X = monster's avg attack (per-round expected damage); Y =
    effective HP under attack at baseline player skill; color +
    legend by Size; marker area by raw HP_max (sqrt-scaled).

    The diagonal answers "wall vs lethal" — top-right is hard to
    kill *and* hits hard, bottom-left is glass cannon adjacent
    only because it dies fast. Outliers above-and-left are
    pure walls; outliers below-and-right are paper tigers.
    """
    fig, ax = plt.subplots(figsize=(11, 8))
    ax.set_title(
        "Caldanai bestiary — survivability vs lethality "
        f"(player avg dmg = {_BASELINE_AVG_RAW_DAMAGE:.0f})",
        color=DEFAULT_ACCENT,
        fontsize=14,
    )
    ax.set_xlabel("avg attack damage / round")
    ax.set_ylabel("effective HP under attack")

    if not samples:
        style_axes_dark(ax, accent_color=DEFAULT_ACCENT, grid_axis="both")
        return fig

    all_hps = [s["hp"] for s in samples]

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
            if s.get("is_player"):
                area = max(area, 250.0)
            eff_hp = _effective_hp(
                s["hp"], s["dodge"], s["defense"],
            )
            ax.scatter(
                [s.get("attack", 0.0)], [eff_hp],
                s=[area],
                c=[color],
                marker=marker,
                edgecolors=DEFAULT_ACCENT,
                linewidths=0.6,
                alpha=0.85,
            )

    for s in samples:
        eff_hp = _effective_hp(s["hp"], s["dodge"], s["defense"])
        ax.annotate(
            s["label"],
            xy=(s.get("attack", 0.0), eff_hp),
            xytext=(6, 4),
            textcoords="offset points",
            fontsize=9,
            color=_SIZE_COLORS.get(s["size"], DEFAULT_ACCENT),
        )

    handles, labels = _build_size_legend_handles(samples, plotted_sizes)
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
    return fig


# --------------------------------------------------------------------
# Plotting — parallel coordinates
# --------------------------------------------------------------------


_PARALLEL_AXES: List[Tuple[str, str]] = [
    ("dodge",   "dodge"),
    ("defense", "defense"),
    ("hp",      "HP"),
    ("attack",  "attack"),
    ("size",    "size"),
]


def _normalize_axis(values: "List[float]") -> "List[float]":
    """Linearly rescale ``values`` to [0, 1]. Degenerate case
    (all equal) collapses to 0.5 so the line still draws on the
    axis instead of getting clipped at 0."""
    if not values:
        return []
    lo = min(values)
    hi = max(values)
    if hi <= lo:
        return [0.5 for _ in values]
    return [(v - lo) / (hi - lo) for v in values]


def build_parallel_figure(samples: "List[dict]") -> "plt.Figure":
    """Render the parallel-coordinates view.

    Each monster is a line crossing five vertical axes (dodge,
    defense, HP, attack, size_numeric). Each axis is normalized
    to [0, 1] independently so the visual comparison stays
    meaningful across very different scales (HP ranges from
    ~15 to ~300; defense from 0 to ~12).

    Lines are colored by Size category and rendered at moderate
    opacity so a cluster reads through and a divergent monster
    visibly leaves the pack at one or more axes.

    No pandas dependency — we do the normalization + per-line
    plotting by hand.
    """
    fig, ax = plt.subplots(figsize=(12, 7))
    ax.set_title(
        "Caldanai bestiary — parallel coordinates "
        "(each line = one monster, axes normalized 0..1)",
        color=DEFAULT_ACCENT,
        fontsize=14,
    )
    ax.set_ylabel("normalized value (per-axis)")

    if not samples:
        style_axes_dark(ax, accent_color=DEFAULT_ACCENT, grid_axis="y")
        ax.set_xticks([])
        return fig

    # Build per-axis raw + normalized columns. Size lives as
    # ``size`` (Size enum) on the sample dict — the parallel-
    # coords view wants a numeric, so we map through
    # ``_SIZE_NUMERIC`` before normalization.
    raw_columns: Dict[str, List[float]] = {}
    for key, _label in _PARALLEL_AXES:
        if key == "size":
            raw_columns[key] = [
                _SIZE_NUMERIC.get(s["size"], 2.0) for s in samples
            ]
        else:
            raw_columns[key] = [float(s.get(key, 0.0)) for s in samples]
    normalized: Dict[str, List[float]] = {
        key: _normalize_axis(vals) for key, vals in raw_columns.items()
    }

    # X positions for each axis — equal spacing reads cleanly.
    x_positions = list(range(len(_PARALLEL_AXES)))

    # Per-monster line. Use the Size color so a quick scan reveals
    # the size-class clusters; player baseline gets a thicker /
    # dashed treatment to pop above the bestiary cloud.
    plotted_sizes: "OrderedDict[Size, None]" = OrderedDict()
    for idx, s in enumerate(samples):
        size_cat = s["size"]
        plotted_sizes[size_cat] = None
        color = _SIZE_COLORS.get(size_cat, DEFAULT_ACCENT)
        y_values = [normalized[key][idx] for key, _ in _PARALLEL_AXES]
        is_player = bool(s.get("is_player"))
        ax.plot(
            x_positions, y_values,
            color=color,
            alpha=0.9 if is_player else 0.6,
            linewidth=2.5 if is_player else 1.4,
            linestyle="--" if is_player else "-",
            marker="*" if is_player else "o",
            markersize=8 if is_player else 4,
            markeredgecolor=DEFAULT_ACCENT,
            markeredgewidth=0.4,
        )
        # Tiny label on the rightmost axis so a curious viewer
        # can trace a divergent line back to its monster.
        ax.annotate(
            s["label"],
            xy=(x_positions[-1], y_values[-1]),
            xytext=(6, 0),
            textcoords="offset points",
            fontsize=8,
            color=color,
            verticalalignment="center",
        )

    # X tick labels: which stat each axis is. Numeric range
    # caption underneath shows the [lo, hi] each axis was
    # normalized against, so a viewer can decode normalized 0.7
    # back to absolute units.
    tick_labels = []
    for key, label in _PARALLEL_AXES:
        col = raw_columns[key]
        if col:
            lo, hi = min(col), max(col)
            tick_labels.append(f"{label}\n[{lo:.1f}-{hi:.1f}]")
        else:
            tick_labels.append(label)
    ax.set_xticks(x_positions)
    ax.set_xticklabels(tick_labels)
    ax.set_xlim(-0.3, len(_PARALLEL_AXES) - 0.7)
    ax.set_ylim(-0.05, 1.1)

    # Vertical guide lines at each axis position so the eye
    # tracks the line's intersections cleanly.
    for x in x_positions:
        ax.axvline(x, color=DEFAULT_ACCENT, alpha=0.15, linewidth=0.8)

    handles, labels = _build_size_legend_handles(samples, plotted_sizes)
    legend = ax.legend(
        handles=handles,
        labels=labels,
        loc="upper right",
        facecolor=(0, 0, 0, 0),
        edgecolor=DEFAULT_ACCENT,
        labelcolor=DEFAULT_ACCENT,
        fontsize=9,
    )
    if legend is not None:
        legend.get_frame().set_alpha(0.4)

    style_axes_dark(ax, accent_color=DEFAULT_ACCENT, grid_axis="y")
    return fig


# --------------------------------------------------------------------
# View dispatch
# --------------------------------------------------------------------


_VIEW_BUILDERS = {
    "scatter":       build_figure,
    "survivability": build_survivability_figure,
    "parallel":      build_parallel_figure,
}


def build_view(view: str, samples: "List[dict]") -> "plt.Figure":
    """Dispatch to the right ``build_*`` function for the named
    view. Raises ``ValueError`` on an unknown view so a CLI typo
    fails loudly instead of silently rendering the default."""
    builder = _VIEW_BUILDERS.get(view)
    if builder is None:
        raise ValueError(
            f"unknown view {view!r}; valid: "
            f"{sorted(_VIEW_BUILDERS)}"
        )
    return builder(samples)


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
        "--view",
        choices=sorted(_VIEW_BUILDERS),
        default="scatter",
        help=(
            "Which chart to render. ``scatter`` is the original "
            "dodge x defense view; ``survivability`` plots offense "
            "vs effective-HP-under-attack; ``parallel`` is a "
            "parallel-coordinates view across all stats."
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
        default=None,
        help=(
            "Path to write the PNG in dry-run mode. Default "
            "depends on --view: ./balance-chart-<view>.png. "
            "Also written before upload in --post mode so the "
            "file is on disk for reference."
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
        default=None,
        help=(
            "Text to post alongside the image attachment. "
            "Default depends on --view (see _VIEW_CAPTIONS)."
        ),
    )
    args = ap.parse_args(argv)

    output_path: Path = (
        args.output
        if args.output is not None
        else Path(_DEFAULT_OUTPUT_TEMPLATE.format(view=args.view))
    )
    caption: str = (
        args.caption
        if args.caption is not None
        else _VIEW_CAPTIONS.get(args.view, _VIEW_CAPTIONS["scatter"])
    )

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

    print(f"Building view: {args.view}")
    fig = build_view(args.view, samples)
    save_figure_to_path(fig, output_path)
    size_bytes = output_path.stat().st_size if output_path.exists() else 0
    print(f"  wrote {output_path} ({size_bytes:,} bytes)")

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
        _post_via_discord_py(token, channel_id, output_path, caption),
    )
    print("Done.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
