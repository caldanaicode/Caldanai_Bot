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

from caldanai.db import DB
from caldanai.lib.rpg.helpers.enums import TimesOfDay
from caldanai.lib.rpg.helpers.parser import parse
from caldanai.lib.rpg.world.objects import StaticObjectPlugin


_NIGHT_PARTITION = TimesOfDay.DUSK | TimesOfDay.NIGHT


class StoneField(StaticObjectPlugin):
    name = "stone field"
    aliases = ["stones", "stone-field", "field of stones", "standing stones"]

    SUPPORTED_VERBS = [
        "gaze", "touch", "listen",
        # Presence verbs (added 2026-05-04 with the new presence
        # cog). $bite intentionally omitted — Caels: stones do not
        # invite the absurd the way the fire does.
        "lean", "sit", "rest", "ponder", "tend",
    ]

    # ---------------------------------------------------------------
    # $look
    # ---------------------------------------------------------------

    def get_look_line(self, game) -> Optional[str]:
        count_phrase = self._stones_count_phrase(game)
        if self._is_night(game):
            return parse(
                f"@1Dc stands at the clearing's edge — {count_phrase} "
                f"half-buried, glyphs faintly catching the dark.",
                self,
            )
        return parse(
            f"@1Dc rests at the clearing's edge — {count_phrase} "
            f"half-buried, in slow ranks, waiting for nothing in particular.",
            self,
        )

    # ---------------------------------------------------------------
    # Verb handlers
    # ---------------------------------------------------------------

    def on_verb(self, verb: str, game, actor, **kwargs) -> Optional[str]:
        if verb == "gaze":
            return self._on_gaze(game, actor)
        if verb == "touch":
            return self._on_touch(game, actor)
        if verb == "listen":
            return self._on_listen(game, actor)
        # Presence verbs.
        if verb == "lean":
            return self._on_lean(game, actor)
        if verb == "sit":
            return self._on_sit(game, actor)
        if verb == "rest":
            return self._on_rest(game, actor)
        if verb == "ponder":
            return self._on_ponder(game, actor)
        if verb == "tend":
            return self._on_tend(game, actor)
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
            "@2 stops, listens. The stones hold quiet around @1d, the "
            "way a still pool holds depth.",
            "@2 listens. The stones do not speak. They are very good "
            "at not speaking.",
        ])
        return parse(line, self, actor)

    # ---------------------------------------------------------------
    # Presence-verb hooks (added with rpg_presence_commands cog)
    # ---------------------------------------------------------------

    def _on_lean(self, game, actor) -> Optional[str]:
        if self._is_night(game):
            pool = [
                "@2 leans against a half-buried stone. The stone is patient. The stone is also cold, and the cold goes through @2np cloak in slow steps.",
                "@2 props @2a shoulder against an upright. The dark settles around the lean. The stone holds.",
                "@2 leans into the night-cold of a glyph-marked stone. The mark, faint and patient, sits under @2np shoulder-blade.",
            ]
        else:
            pool = [
                "@2 leans against a sun-warm stone. The warmth keeps a slow promise against @2np spine.",
                "@2 props @2r against an upright. Lichen catches at @2np cloak. The stone is patient, the way stones are.",
                "@2 settles @2a weight against a half-buried stone. The stone takes the lean as it takes everything else: without comment.",
            ]
        return parse(random.choice(pool), self, actor)

    def _on_sit(self, game, actor) -> Optional[str]:
        if self._is_night(game):
            pool = [
                "@2 settles on a low stone. The cold is the cold of patience, and goes through @2np cloak slowly.",
                "@2 lowers @2r onto a flat stone-top. The dark is total beyond the field; the stones hold a quiet that holds @2o back.",
                "@2 finds a stone the right shape for sitting and sits. A faint glyph-glow catches at the edge of @2np vision and is gone again.",
            ]
        else:
            pool = [
                "@2 settles on a sun-warm stone. The top is warm, the sides are cool, the way old stones are.",
                "@2 lowers @2r onto a moss-soft stone. Lichen prints itself faintly into @2np palm.",
                "@2 finds a flat stone-top in the sun and accepts the offer. The stone holds @2np weight as if it has held weights longer than the clearing has been a clearing.",
            ]
        return parse(random.choice(pool), self, actor)

    def _on_rest(self, game, actor) -> Optional[str]:
        if self._is_night(game):
            pool = [
                "@2 rests among the stones. The dark is deep, the stones are patient, and the place holds @2o between them.",
                "@2 lets the stone-field hold @2o a while. The cold of the stones is steady; @2np breathing slows to match it.",
                "@2 stretches out near a leaning upright and closes @2a eyes. The faint glyph-glow keeps watch in @2np stead.",
            ]
        else:
            pool = [
                "@2 rests among the stones, sun warm on @2np cloak, lichen-smell in the air. The clearing keeps its quiet.",
                "@2 settles back against a sun-warmed upright. The stones do the work of holding @2o still.",
                "@2 lets the stone-field be the loudest thing in the world for a beat — which is to say, very quiet indeed.",
            ]
        return parse(random.choice(pool), self, actor)

    def _on_ponder(self, game, actor) -> Optional[str]:
        if self._is_night(game):
            pool = [
                "@2 considers @1d. Each stone waits to wake. None do. The waiting is older than @2 is.",
                "@2 stands among the stones and lets @2a thoughts move at the stones' pace, which is slower than thought generally moves.",
                "@2 watches the faint glyph-glow shift under the dark. Whatever @2 came here to weigh, the stones have weighed longer.",
            ]
        else:
            pool = [
                "@2 considers @1d. The sun is on the tops of the stones, and the stones are considering back, in their own slow way.",
                "@2 stands among the half-buried ranks and lets the stones hold the thought longer than @2 could alone.",
                "@2 watches the lichen on a glyph and feels the slow weight of a thing waiting. Each stone waits to wake. The thought waits with them.",
            ]
        return parse(random.choice(pool), self, actor)

    def _on_tend(self, game, actor) -> Optional[str]:
        if self._is_night(game):
            pool = [
                "@2 brushes lichen aside from a glyph by feel as much as sight. The mark glows the faintest fraction brighter under @2np thumb. Maybe.",
                "@2 wipes night-damp from a tilted stone-top with the edge of @2a sleeve. The stone takes the gesture without acknowledgement.",
                "@2 traces a chiseled line clear of moss in the dark. The dirt accepts. The stone, as ever, keeps its counsel.",
            ]
        else:
            pool = [
                "@2 brushes lichen aside from a glyph in the sun. The mark catches the light a little better for it.",
                "@2 wipes a smear of dirt from a stone-face with @2a thumb, working the line of an old chiseled mark. The stone is indifferent. The gesture lands anyway.",
                "@2 straightens a small leaned-aside fragment, settling it back among its ranks. The stone-field accepts the small care without comment.",
            ]
        return parse(random.choice(pool), self, actor)

    # ---------------------------------------------------------------
    # Helpers
    # ---------------------------------------------------------------

    def _stones_count_phrase(self, game) -> str:
        """Return the lead noun-phrase for ``get_look_line``.

        Estimate phrase rounded DOWN to the nearest ten, e.g.
        ``"180-ish stones"``. The lifetime golem-disengage tally
        (``monsters.golem.escaped`` in the per-channel stats doc)
        feeds the count; pre-stone-field walks fold in but the
        rough-estimate framing absorbs the inflation. Below a tier
        of ten the phrase falls back to ``"a thin scatter of
        stones"`` — the field is older than the clearing in lore,
        so a near-zero count is a fresh-deploy artefact rather
        than a narrative state.
        """
        count = self._golem_escape_count(game)
        rounded = (count // 10) * 10
        if rounded < 10:
            return "a thin scatter of stones"
        return f"{rounded}-ish stones"

    @staticmethod
    def _golem_escape_count(game) -> int:
        """Lifetime golem-disengage tally for this (guild, channel).

        Sums the persisted ``monsters.golem.escaped`` value with
        the in-memory ``game.monster_statics`` Counter so the count
        reflects walk-offs that haven't been flushed to Mongo yet
        by the periodic ``update_statics`` batch. Any read failure
        (no guild, no DB connection, missing doc) degrades to the
        in-memory value alone — never raises into ``$look``.
        """
        persisted = 0
        guild = getattr(game, "guild", None)
        channel = getattr(game, "channel", None)
        guild_id = getattr(guild, "id", None)
        channel_id = getattr(channel, "id", None)
        if guild_id is not None and channel_id is not None:
            try:
                doc = DB._mongoDB.statics.find_one(
                    {"guild_id": guild_id, "channel_id": channel_id}
                ) or {}
                persisted = int(
                    doc.get("monsters", {}).get("golem", {}).get("escaped", 0)
                )
            except Exception:
                persisted = 0
        in_flight = int(
            getattr(game, "monster_statics", {}).get("golem.escaped", 0)
        )
        return persisted + in_flight

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
