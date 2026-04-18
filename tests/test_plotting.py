"""Tests for Caldanai.lib.rpg.helpers.plotting — fig_to_file and style_axes_dark."""

from unittest.mock import patch

import matplotlib
matplotlib.use("Agg")  # headless backend for CI

import matplotlib.pyplot as plt
import pytest

from discord import File

from caldanai.lib.rpg.helpers.plotting import (
    CYAN_ACCENT,
    DEFAULT_ACCENT,
    fig_to_file,
    style_axes_dark,
)


# ---------------------------------------------------------------------------
# fig_to_file
# ---------------------------------------------------------------------------

class TestFigToFile:
    def test_returns_discord_file_with_default_filename(self):
        fig, ax = plt.subplots()
        ax.plot([0, 1, 2], [0, 1, 4])
        result = fig_to_file(fig)
        assert isinstance(result, File)
        assert result.filename == "plot.png"

    def test_custom_filename_is_used(self):
        fig, ax = plt.subplots()
        ax.plot([0, 1, 2], [0, 1, 4])
        result = fig_to_file(fig, filename="usage.png")
        assert result.filename == "usage.png"

    def test_closes_figure_after_export(self):
        fig, ax = plt.subplots()
        ax.plot([0, 1, 2], [0, 1, 4])
        with patch(
            "caldanai.lib.rpg.helpers.plotting.plt.close"
        ) as mock_close:
            fig_to_file(fig)
            mock_close.assert_called_once_with(fig)

    def test_buffer_is_rewound_so_discord_can_read_it(self):
        fig, ax = plt.subplots()
        ax.plot([0, 1, 2], [0, 1, 4])
        result = fig_to_file(fig)
        # discord.File.fp is the underlying BytesIO; must be at byte 0
        # so Discord can upload the full payload.
        assert result.fp.tell() == 0
        # And it must actually have PNG bytes.
        header = result.fp.read(8)
        assert header[:4] == b"\x89PNG"


# ---------------------------------------------------------------------------
# style_axes_dark
# ---------------------------------------------------------------------------

class TestStyleAxesDark:
    def teardown_method(self):
        plt.close("all")

    def test_default_accent_is_applied(self):
        fig, ax = plt.subplots()
        style_axes_dark(ax)
        assert ax.xaxis.label.get_color() == DEFAULT_ACCENT
        assert ax.yaxis.label.get_color() == DEFAULT_ACCENT
        for spine in ax.spines.values():
            assert spine.get_edgecolor() == matplotlib.colors.to_rgba(DEFAULT_ACCENT)

    def test_custom_hex_accent(self):
        fig, ax = plt.subplots()
        style_axes_dark(ax, accent_color="#FF00FF")
        assert ax.xaxis.label.get_color() == "#FF00FF"

    def test_custom_rgba_accent(self):
        fig, ax = plt.subplots()
        style_axes_dark(ax, accent_color=CYAN_ACCENT)
        assert ax.xaxis.label.get_color() == CYAN_ACCENT
        for spine in ax.spines.values():
            assert spine.get_edgecolor() == CYAN_ACCENT

    def test_facecolor_is_transparent(self):
        fig, ax = plt.subplots()
        style_axes_dark(ax)
        # ax.get_facecolor returns RGBA; the 4th channel is alpha.
        assert ax.get_facecolor() == (0.0, 0.0, 0.0, 0.0)

    def test_figure_patch_is_transparent(self):
        fig, ax = plt.subplots()
        style_axes_dark(ax)
        assert fig.patch.get_alpha() == 0

    def test_grid_axis_defaults_to_y(self):
        fig, ax = plt.subplots()
        style_axes_dark(ax)
        # Default grid orientation is y (horizontal lines for vertical
        # bar/line charts). Verify the y-axis gridlines are visible.
        y_gridlines = ax.yaxis.get_gridlines()
        assert any(line.get_visible() for line in y_gridlines)

    def test_grid_axis_x_for_horizontal_bars(self):
        fig, ax = plt.subplots()
        style_axes_dark(ax, grid_axis="x")
        x_gridlines = ax.xaxis.get_gridlines()
        assert any(line.get_visible() for line in x_gridlines)
