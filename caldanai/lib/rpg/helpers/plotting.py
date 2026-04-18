"""Shared matplotlib plumbing for Discord chart commands.

Three call sites (``$chart``, ``$usage``, ``Player.get_chart_attacks``)
historically reimplemented the same ``BytesIO`` → ``discord.File`` save
loop and re-rolled very similar Discord dark-mode axis styling with
small drift. These helpers centralize both so the charts stay visually
consistent and the figure handle is always closed (matplotlib leaks
memory if figures pile up)."""

from io import BytesIO
from typing import Optional, Tuple, Union

import matplotlib.pyplot as plt
from matplotlib.axes import Axes
from matplotlib.figure import Figure

from discord import File


# Default Discord dark-mode accent: a light gray that reads cleanly on
# both the dark and light client themes against a transparent canvas.
DEFAULT_ACCENT = "#DDDDDD"

# RGBA alias for the cyan/mint the dice-roll charts have always used.
CYAN_ACCENT: Tuple[float, float, float, float] = (0.0, 1.0, 0.7, 1.0)


def fig_to_file(fig: Figure, filename: str = "plot.png") -> File:
    """Render a matplotlib figure to a ``discord.File`` and close it.

    The figure is written as a transparent PNG with a tight bounding
    box — matching what ``$chart`` and ``$usage`` already produced and
    what ``Player.get_chart_attacks`` ought to have been doing. The
    figure is closed after export so repeated chart commands don't
    leak memory through matplotlib's global figure registry.

    :param fig: The matplotlib figure to render. Will be closed.
    :param filename: Attachment filename for Discord. Callers that
        embed the image with ``attachment://<name>`` must match this.
    :return: A ready-to-send ``discord.File`` wrapping the PNG bytes.
    """
    buffer = BytesIO()
    try:
        fig.savefig(buffer, format="png", transparent=True, bbox_inches="tight")
    finally:
        plt.close(fig)
    buffer.seek(0)
    return File(buffer, filename=filename)


def style_axes_dark(
    ax: Axes,
    accent_color: Optional[Union[str, Tuple[float, ...]]] = None,
    grid_axis: str = "y",
) -> None:
    """Apply the Discord dark-mode axis styling shared by chart commands.

    Colors axis labels, tick labels, spines, and grid lines with a
    single accent color, and makes the figure/axes background fully
    transparent so the PNG composites cleanly on whichever Discord
    theme the viewer has active. Callers still own the bar/line color
    and the title — this only touches the chrome around the data.

    :param ax: The matplotlib axes to style.
    :param accent_color: Color for labels, ticks, spines, and grid.
        Accepts anything matplotlib accepts (hex string, named color,
        or RGBA tuple). Defaults to ``DEFAULT_ACCENT``.
    :param grid_axis: Which axis carries the reference grid. Use
        ``"y"`` for vertical bars/lines (the gridlines are horizontal)
        and ``"x"`` for horizontal bars (the gridlines are vertical).
    """
    color = accent_color if accent_color is not None else DEFAULT_ACCENT

    ax.xaxis.label.set_color(color)
    ax.yaxis.label.set_color(color)
    ax.tick_params(axis="both", colors=color)
    ax.grid(True, axis=grid_axis, color=color, alpha=0.25)
    for spine in ax.spines.values():
        spine.set_color(color)

    # Make the figure/axes background fully transparent so savefig's
    # transparent=True actually produces a transparent PNG regardless
    # of the default matplotlib rcParams the caller inherited.
    fig = ax.figure
    if fig is not None:
        fig.patch.set_alpha(0)
    ax.set_facecolor((0, 0, 0, 0))
