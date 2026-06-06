"""Tests for tools.ansi_swatch — the Discord ansi palette-swatch generator."""

from tools.ansi_swatch import (
    build_block,
    build_lines_block,
    build_lines_block_once,
    parse_lines,
    SWATCHES,
    ESC,
    SAMPLE,
)


def test_block_is_an_ansi_fence():
    block = build_block()
    assert block.startswith("```ansi\n")
    assert block.endswith("\n```")


def test_one_labeled_line_per_swatch():
    body = build_block().splitlines()[1:-1]  # drop the two fence lines
    assert len(body) == len(SWATCHES)


def test_every_swatch_carries_real_esc_and_reset():
    block = build_block()
    # Real ESC bytes, not the literal characters ``\x1b`` — that's the
    # whole point of the tool (Discord needs the control byte).
    assert ESC in block
    assert "\\x1b" not in block
    for _label, sgr in SWATCHES:
        assert f"{ESC}[{sgr}m{SAMPLE}{ESC}[0m" in block


def test_covers_base16_256_and_truecolor():
    block = build_block()
    assert f"{ESC}[2;37m" in block            # dim white (junk candidate)
    assert f"{ESC}[38;5;208m" in block        # 256-color orange probe
    assert f"{ESC}[38;2;255;165;0m" in block  # truecolor orange probe


def test_parse_lines_handles_uncolored_and_blanks():
    assert parse_lines("plain=,green=0;32, ") == [("plain", None), ("green", "0;32")]


def test_lines_block_is_ragged_one_reset_per_line():
    block = build_lines_block([("short", "37"), ("a much longer line", "32")])
    assert block.count(f"{ESC}[0m") == 2  # per-row reset → ragged right edge


def test_lines_block_pad_fills_short_line_to_longest():
    block = build_lines_block([("a", "37"), ("abcdef", "37")], pad=True)
    assert "a     " in block  # 'a' padded with spaces to len('abcdef')


def test_lines_block_once_sets_bg_once_resets_once():
    block = build_lines_block_once([("one", "37"), ("two", "32")], bg="40")
    assert block.count(f"{ESC}[40m") == 1  # background opened once at the top
    assert block.count(f"{ESC}[0m") == 1   # reset once at the bottom
