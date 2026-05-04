"""Stone field — Vael's invented landmark, made real.

Origin (recorded in synthesis 2026-05-02): bg Vael flagged each
walked-off golem in her interior framing as *"a stone, waiting to
wake"*. After enough golem-avoidance the clearing accumulated
*"a quiet stone field"* in her narration — a player-invented
landmark born from her own avoidance pattern. Caels' 2026-05-03
direction: **make it real.** Honor the in-fiction worldbuilding
by surfacing the stone field as a static object the players can
interact with.

V1 scope: a static, present-since-game-start landmark with three
sensory verb handlers (``$gaze`` / ``$touch`` / ``$listen``).
The "grows-with-each-golem-walk" beat that closes the loop on
Vael's noticing is reserved for a follow-up commit; for V1 the
field is just present, glyphs faintly active at night.

No state mutation in V1. No fuel, no weather reactivity. Stones
endure.
"""

import random
from typing import List, Optional

from caldanai.lib.rpg.helpers.enums import TimesOfDay
from caldanai.lib.rpg.helpers.parser import parse
from caldanai.lib.rpg.world.objects import StaticObjectPlugin


_NIGHT_PARTITION = TimesOfDay.DUSK | TimesOfDay.NIGHT


class StoneField(StaticObjectPlugin):
    name = "stone field"
    aliases = ["stones", "stone-field", "field of stones", "standing stones"]

    SUPPORTED_VERBS = ["gaze", "touch", "listen"]

    # ---------------------------------------------------------------
    # $look
    # ---------------------------------------------------------------

    def get_look_line(self, game) -> Optional[str]:
        if self._is_night(game):
            return parse(
                "@1Dc stands at the clearing's edge — stones half-"
                "buried, glyphs faintly catching the dark.",
                self,
            )
        return parse(
            "@1Dc rests at the clearing's edge — half-buried stones "
            "in slow ranks, waiting for nothing in particular.",
            self,
        )

    # ---------------------------------------------------------------
    # Verb handlers
    # ---------------------------------------------------------------

    def on_verb(self, verb: str, game, actor, *args) -> Optional[str]:
        if verb == "gaze":
            return self._on_gaze(game, actor)
        if verb == "touch":
            return self._on_touch(game, actor)
        if verb == "listen":
            return self._on_listen(game, actor)
        return None

    def _on_gaze(self, game, actor) -> Optional[str]:
        if self._is_night(game):
            pool = [
                "@2 gazes at the standing stones. The glyphs catch "
                "the dark — dim, patient, neither glowing nor not.",
                "Faint marks shift in the stones as @2 looks. Maybe "
                "the dark plays with the eye. Maybe not.",
                "@2 watches @1d. Each stone waits to wake. None do.",
            ]
        else:
            pool = [
                "@2 gazes at @1d. Half-buried, lichen-soft, ranked "
                "in some old order no one in this clearing remembers.",
                "@2 considers the stones, the way one considers old "
                "letters — there's something to read here, eventually.",
                "Sun touches the tops of the stones in @1d, warming "
                "moss and glyph alike. They keep their counsel.",
            ]
        return parse(random.choice(pool), self, actor)

    def _on_touch(self, game, actor) -> Optional[str]:
        if self._is_night(game):
            line = random.choice([
                "@2 lays a hand on a stone. Cold. Not the cold of "
                "weather — the cold of patience.",
                "Stone meets @2np palm. There's a slow steadiness in "
                "it that's older than the clearing.",
                "@2 touches a glyph. The mark is just chiseled rock. "
                "Probably.",
            ])
        else:
            line = random.choice([
                "@2 lays a hand on a sun-warm stone. The warmth lingers "
                "longer than it has any right to.",
                "Lichen brushes @2np fingers. The stone underneath is "
                "warm on top, cold underneath, the way old stones are.",
                "@2 traces a glyph with one fingertip. It's just a mark. "
                "It feels like a name being written back.",
            ])
        return parse(line, self, actor)

    def _on_listen(self, game, actor) -> Optional[str]:
        line = random.choice([
            "@2 listens at @1d. Silence — but a deep silence, the kind "
            "you can fall into.",
            "@2 stops, listens. The stones hold quiet around @1m, the "
            "way a still pool holds depth.",
            "@2 listens. The stones do not speak. They are very good "
            "at not speaking.",
        ])
        return parse(line, self, actor)

    # ---------------------------------------------------------------
    # Helpers
    # ---------------------------------------------------------------

    @staticmethod
    def _is_night(game) -> bool:
        clock = getattr(game, "game_clock", None)
        if clock is None:
            return False
        try:
            tod = TimesOfDay[clock.get_time_of_day().upper()]
        except (KeyError, AttributeError):
            return False
        return bool(tod & _NIGHT_PARTITION)
