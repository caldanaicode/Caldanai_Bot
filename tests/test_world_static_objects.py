"""Tests for the static-object plugin family + ambience combine
heuristic + Area's collect_ambience + cog dispatch.

Covers:
- StaticObjectPlugin discovery + registration
- Area.add_static_object / find_static_object (fuzzy)
- Area.collect_ambience integration (room pool + per-object roll)
- combine_ambience_lines heuristic (1/2/3 lines, dialogue-skip,
  name-decap)
- Campfire state machine (LIT → EMBERS → OUT) + verb handlers
- Campfire weather-reactive on_weather_change
- StoneField verb handlers
- World cog dispatch (target / no-target / sensory-self-directed)
- StaticObjectConverter (no static-object-specific test — covered
  via cog dispatch which exercises the same find path)
"""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from caldanai.lib.rpg.ambience import combine_ambience_lines
from caldanai.lib.rpg.areas import Area
from caldanai.lib.rpg.helpers.enums import (
    TimesOfDay, WeatherPatterns, WeatherSeverities,
)
from caldanai.lib.rpg.world.objects import StaticObjectPlugin
from caldanai.lib.rpg.world.objects.campfire import (
    Campfire, FireState, FUEL_DEFAULT, FUEL_PER_STICK,
)
from caldanai.lib.rpg.world.objects.stone_field import StoneField


@pytest.fixture(autouse=True)
def _load_static_object_plugins():
    """Tests reference Campfire/StoneField directly but the
    registry lookup also needs the registry populated."""
    StaticObjectPlugin.load_plugins()


def _make_game(
    *, time_of_day="NOON", weather_patterns=None, weather_severities=None,
):
    """Minimal Game stand-in for plugin / area tests."""
    game = MagicMock()
    game.channel = MagicMock()
    game.game_clock = MagicMock()
    game.game_clock.get_time_of_day.return_value = time_of_day
    if weather_patterns is None and weather_severities is None:
        weather = None
    else:
        weather = MagicMock()
        weather.active_patterns = weather_patterns or WeatherPatterns.CLEAR
        weather.severities = weather_severities or {}
        weather.severity_of = lambda p: (weather_severities or {}).get(p)
    game.weather = weather
    return game


# ---------------------------------------------------------------------------
# Plugin discovery + registry
# ---------------------------------------------------------------------------


class TestPluginDiscovery:
    def test_campfire_loaded_under_stem(self):
        cls = StaticObjectPlugin.get_plugin_class("campfire")
        assert cls is Campfire

    def test_campfire_aliases_resolve(self):
        for alias in ("fire", "flames", "embers"):
            assert StaticObjectPlugin.get_plugin_class(alias) is Campfire

    def test_stone_field_loaded(self):
        assert StaticObjectPlugin.get_plugin_class("stone_field") is StoneField

    def test_stone_field_aliases_resolve(self):
        for alias in ("stones", "standing stones", "field of stones"):
            assert StaticObjectPlugin.get_plugin_class(alias) is StoneField

    def test_unknown_returns_none(self):
        assert StaticObjectPlugin.get_plugin_class("definitely_not_a_thing") is None


# ---------------------------------------------------------------------------
# Area integration
# ---------------------------------------------------------------------------


class TestAreaStaticObjects:
    def test_add_and_find_by_stem(self):
        area = Area()
        cf = Campfire()
        area.add_static_object(cf)
        assert area.find_static_object("campfire") is cf

    def test_find_by_alias(self):
        area = Area()
        cf = Campfire()
        area.add_static_object(cf)
        assert area.find_static_object("fire") is cf
        assert area.find_static_object("flames") is cf

    def test_find_fuzzy(self):
        """``camp`` should resolve to ``campfire`` via fuzzy match."""
        area = Area()
        area.add_static_object(Campfire())
        assert isinstance(area.find_static_object("camp"), Campfire)

    def test_find_unknown_returns_none(self):
        area = Area()
        area.add_static_object(Campfire())
        assert area.find_static_object("xenoclypher") is None

    def test_find_with_no_objects_returns_none(self):
        area = Area()
        assert area.find_static_object("anything") is None

    def test_collect_ambience_walks_static_objects(self):
        """Each static object's maybe_emit_ambience is consulted
        per tick."""
        area = Area()
        cf = Campfire()
        area.add_static_object(cf)
        game = _make_game()

        with patch.object(cf, "maybe_emit_ambience", return_value="fire emits"):
            emissions = area.collect_ambience(game)
        assert "fire emits" in emissions

    def test_collect_ambience_skips_none_emissions(self):
        area = Area()
        cf = Campfire()
        area.add_static_object(cf)
        game = _make_game()

        with patch.object(cf, "maybe_emit_ambience", return_value=None):
            emissions = area.collect_ambience(game)
        # Only emissions list (may also contain a wildlife pool
        # roll, but the deterministic check is that None-returns
        # don't make it through).
        assert None not in emissions


# ---------------------------------------------------------------------------
# Combine ambience lines heuristic
# ---------------------------------------------------------------------------


class TestCombineAmbienceLines:
    def test_empty_returns_empty(self):
        assert combine_ambience_lines([]) == ""

    def test_one_line_passthrough(self):
        assert combine_ambience_lines(["A wolf howls."]) == "A wolf howls."

    def test_two_lines_glued_with_as(self):
        result = combine_ambience_lines([
            "A wolf howls in the distance.",
            "Embers drift on the breeze.",
        ])
        assert result == "A wolf howls in the distance, as embers drift on the breeze."

    def test_three_lines_oxford_comma(self):
        result = combine_ambience_lines([
            "Wind moves through the grass.",
            "A bird calls.",
            "Embers shower from the fire.",
        ])
        assert "Wind moves through the grass" in result
        assert "and embers shower" in result
        assert "a bird calls" in result

    def test_dialogue_lines_skip_combine(self):
        """A line containing ``"`` (escaped dialogue) forces
        newline-join for the whole batch — splicing dialogue mid-
        sentence reads awkwardly."""
        result = combine_ambience_lines([
            "Wind moves through the grass.",
            'The shepherd mutters "they wander, they always wander."',
        ])
        assert "\n" in result
        assert ", as " not in result

    def test_known_names_stay_capitalized(self):
        """Lines starting with a known proper noun (player /
        NPC name) shouldn't decap when spliced."""
        result = combine_ambience_lines(
            ["Wind moves through the grass.", "Wren writes in her notebook."],
            known_names=["Wren"],
        )
        assert "as Wren writes" in result

    def test_unknown_capital_decaps(self):
        result = combine_ambience_lines([
            "Wind moves.",
            "Embers drift.",
        ])
        assert "as embers drift" in result


# ---------------------------------------------------------------------------
# Campfire state machine + verb handlers
# ---------------------------------------------------------------------------


class TestCampfireState:
    def test_default_starts_lit_with_full_fuel(self):
        cf = Campfire()
        assert cf.fire_state == FireState.LIT
        assert cf.fuel == FUEL_DEFAULT
        assert cf.is_lit and not cf.is_embers and not cf.is_out

    def test_tick_fuel_drops_fuel(self):
        cf = Campfire()
        game = _make_game()
        cf.tick_fuel(game)
        assert cf.fuel < FUEL_DEFAULT

    def test_fuel_zero_transitions_out(self):
        cf = Campfire()
        cf.state["fire"] = FireState.EMBERS
        cf.state["fuel"] = 0
        line = cf.tick_fuel(_make_game())
        assert cf.fire_state == FireState.OUT
        assert line is not None
        assert "ash" in line.lower() or "smoke" in line.lower()

    def test_low_fuel_lit_transitions_to_embers(self):
        cf = Campfire()
        cf.state["fuel"] = 4  # just above embers threshold
        # Tick a couple times to push past threshold
        cf.tick_fuel(_make_game())
        cf.tick_fuel(_make_game())
        assert cf.fire_state == FireState.EMBERS

    def test_rain_accelerates_fuel_loss(self):
        """Rain at LIGHT severity doubles fuel loss."""
        cf_clear = Campfire()
        cf_rain = Campfire()
        clear_game = _make_game()
        rain_game = _make_game(
            weather_patterns=WeatherPatterns.PRECIPITATION,
            weather_severities={WeatherPatterns.PRECIPITATION: WeatherSeverities.LIGHT},
        )
        cf_clear.tick_fuel(clear_game)
        cf_rain.tick_fuel(rain_game)
        assert cf_rain.fuel < cf_clear.fuel


class TestCampfireVerbs:
    def test_supports_all_five_verbs(self):
        cf = Campfire()
        for verb in ("light", "feed", "gaze", "touch", "listen"):
            assert verb in cf.SUPPORTED_VERBS

    def test_light_when_already_lit_returns_already_lit_flavor(self):
        cf = Campfire()
        actor = MagicMock(name="player")
        actor.name = "Caels"
        line = cf.on_verb("light", _make_game(), actor)
        assert line is not None
        assert "already" in line.lower() or "burning" in line.lower()

    def test_light_from_embers_promotes_to_lit(self):
        cf = Campfire()
        cf.state["fire"] = FireState.EMBERS
        cf.state["fuel"] = 1
        actor = MagicMock(name="player")
        actor.name = "Caels"
        actor.uses_article = False
        cf.on_verb("light", _make_game(), actor)
        assert cf.fire_state == FireState.LIT

    def test_feed_when_out_refuses(self):
        cf = Campfire()
        cf.state["fire"] = FireState.OUT
        actor = MagicMock(name="player")
        actor.name = "Caels"
        actor.uses_article = False
        line = cf.on_verb("feed", _make_game(), actor, fuel_arg=None)
        assert line is not None
        assert "cold" in line.lower() or "fail" in line.lower() or "striker" in line.lower()

    def test_feed_lit_with_inventory_stick_consumes_and_adds_fuel(self):
        cf = Campfire()
        cf.state["fuel"] = 10
        # Stick in inventory — Inventory in production is dict-like
        # with __getitem__/all() but no __iter__. The campfire's
        # _collect_fuel_items uses ``inventory.all()`` to avoid
        # Python's int-fallback infinite loop. Stub matches that
        # interface.
        stick = MagicMock()
        stick.name = "stick"
        stick.favorited = False
        actor = MagicMock(name="player")
        actor.name = "Caels"
        actor.uses_article = False
        actor.inventory = MagicMock()
        actor.inventory.all = MagicMock(return_value=(stick,))
        actor.is_equipped = MagicMock(return_value=False)
        actor.take_item = MagicMock(return_value=stick)

        cf.on_verb("feed", _make_game(), actor, fuel_arg=None)
        actor.take_item.assert_called_once_with(stick)
        assert cf.fuel == 10 + FUEL_PER_STICK

    def test_feed_uses_inventory_all_not_iter(self):
        """Regression: the campfire MUST iterate via
        ``inventory.all()`` — not ``list(inventory)`` or
        ``for x in inventory``. The production Inventory class
        defines ``__getitem__`` but not ``__iter__``, so direct
        iteration falls back to Python's int-indexing protocol
        and loops forever (``__getitem__`` returns ``None`` for
        int keys instead of raising IndexError). 2026-05-03 hang
        regression."""
        cf = Campfire()
        actor = MagicMock(name="player")
        actor.name = "Caels"
        actor.uses_article = False
        # Inventory stub: only ``all()`` works; iter raises and
        # __getitem__ would return None for any int key.
        inv = MagicMock(spec=["all"])
        inv.all.return_value = ()
        actor.inventory = inv
        actor.is_equipped = MagicMock(return_value=False)

        # Should NOT raise — should call .all() and resolve cleanly.
        cf.on_verb("feed", _make_game(), actor, fuel_arg=None)
        inv.all.assert_called()

    def test_gaze_returns_state_aware_line(self):
        cf = Campfire()
        actor = MagicMock(name="player")
        actor.name = "Caels"
        actor.uses_article = False
        line = cf.on_verb("gaze", _make_game(), actor)
        assert line is not None
        assert "caels" in line.lower() or "campfire" in line.lower() or "fire" in line.lower()

    def test_touch_when_out_no_damage(self):
        cf = Campfire()
        cf.state["fire"] = FireState.OUT
        actor = MagicMock(name="player")
        actor.name = "Caels"
        actor.uses_article = False
        actor.is_dead = MagicMock(return_value=False)
        actor.find_parts = MagicMock(return_value=[])
        actor.apply_damage = MagicMock()
        line = cf.on_verb("touch", _make_game(), actor)
        assert line is not None
        actor.apply_damage.assert_not_called()

    def test_touch_when_lit_applies_damage(self):
        cf = Campfire()
        actor = MagicMock(name="player")
        actor.name = "Caels"
        actor.uses_article = False
        actor.is_dead = MagicMock(return_value=False)
        actor.find_parts = MagicMock(return_value=[MagicMock()])
        actor.apply_damage = MagicMock(return_value="")
        cf.on_verb("touch", _make_game(), actor)
        actor.apply_damage.assert_called_once()

    def test_touch_when_dead_blocks_damage(self):
        """Dead actors must not be able to keep touching the fire —
        the bug Caels caught: a corpse kept getting flavor and the
        bot kept narrating burn-touches with no death gate."""
        cf = Campfire()
        actor = MagicMock(name="player")
        actor.name = "Caels"
        actor.uses_article = False
        actor.is_dead = MagicMock(return_value=True)
        actor.find_parts = MagicMock(return_value=[MagicMock()])
        actor.apply_damage = MagicMock()
        line = cf.on_verb("touch", _make_game(), actor)
        assert line is not None
        actor.apply_damage.assert_not_called()

    def test_touch_with_no_living_hand_or_arm_blocks_damage(self):
        """When both hands AND arms are gone (find_parts returns []),
        the touch must NOT silently spill damage to core HP via the
        no-target legacy path. Symbolic touch only — return flavor,
        skip apply_damage."""
        cf = Campfire()
        actor = MagicMock(name="player")
        actor.name = "Caels"
        actor.uses_article = False
        actor.is_dead = MagicMock(return_value=False)
        actor.find_parts = MagicMock(return_value=[])
        actor.apply_damage = MagicMock()
        line = cf.on_verb("touch", _make_game(), actor)
        assert line is not None
        actor.apply_damage.assert_not_called()

    def test_touch_falls_back_to_arm_when_no_living_hand(self):
        """Both hands destroyed → find_parts('hand') returns []. The
        toucher's stump (the arm) takes the burn instead, so damage
        STILL routes to a real part — never spills silently to core
        HP via target_part=None."""
        cf = Campfire()
        actor = MagicMock(name="player")
        actor.name = "Caels"
        actor.uses_article = False
        actor.is_dead = MagicMock(return_value=False)
        arm_part = MagicMock(name="arm")

        def find_parts(query):
            return [] if query == "hand" else [arm_part]
        actor.find_parts = MagicMock(side_effect=find_parts)
        actor.apply_damage = MagicMock(return_value="")
        cf.on_verb("touch", _make_game(), actor)
        # apply_damage must be called with the arm as the target,
        # not None.
        actor.apply_damage.assert_called_once()
        kwargs = actor.apply_damage.call_args.kwargs
        assert kwargs.get("target_part") is arm_part

    def test_touch_surfaces_apply_damage_return_string(self):
        """When apply_damage returns a transition string (gear-drop
        or death narration), the touch handler must append it. The
        original code dropped the return value — silent deaths."""
        cf = Campfire()
        actor = MagicMock(name="player")
        actor.name = "Caels"
        actor.uses_article = False
        actor.is_dead = MagicMock(return_value=False)
        actor.find_parts = MagicMock(return_value=[MagicMock()])
        actor.apply_damage = MagicMock(
            return_value="Caels crumples to the ground lifelessly!",
        )
        line = cf.on_verb("touch", _make_game(), actor)
        assert "crumples to the ground lifelessly" in line

    def test_listen_when_out_returns_silent_line(self):
        cf = Campfire()
        cf.state["fire"] = FireState.OUT
        actor = MagicMock(name="player")
        actor.name = "Caels"
        line = cf.on_verb("listen", _make_game(), actor)
        assert line is not None


class TestCampfireWeatherReactivity:
    def test_light_rain_starts_sputter_line(self):
        cf = Campfire()
        line = cf.on_weather_change(
            _make_game(),
            old_patterns=WeatherPatterns.CLEAR,
            new_patterns=WeatherPatterns.PRECIPITATION,
            old_severities={},
            new_severities={WeatherPatterns.PRECIPITATION: WeatherSeverities.LIGHT},
        )
        assert line is not None
        assert "hiss" in line.lower() or "sputter" in line.lower()
        # Light rain doesn't schedule the heavy-rain delayed extinguish.
        assert cf.state["extinguish_in"] == 0

    def test_heavy_rain_schedules_delayed_extinguish(self):
        cf = Campfire()
        line = cf.on_weather_change(
            _make_game(),
            old_patterns=WeatherPatterns.CLEAR,
            new_patterns=WeatherPatterns.PRECIPITATION,
            old_severities={},
            new_severities={WeatherPatterns.PRECIPITATION: WeatherSeverities.HEAVY},
        )
        assert line is not None
        assert cf.state["extinguish_in"] > 0
        # Subsequent ticks count down the timer; eventually extinguish.
        for _ in range(10):
            cf.tick_fuel(_make_game(
                weather_patterns=WeatherPatterns.PRECIPITATION,
                weather_severities={WeatherPatterns.PRECIPITATION: WeatherSeverities.HEAVY},
            ))
        assert cf.fire_state == FireState.OUT

    def test_wind_gust_emits_ember_shower(self):
        cf = Campfire()
        line = cf.on_weather_change(
            _make_game(),
            old_patterns=WeatherPatterns.CLEAR,
            new_patterns=WeatherPatterns.WIND,
            old_severities={},
            new_severities={WeatherPatterns.WIND: WeatherSeverities.HEAVY},
        )
        assert line is not None
        assert "ember" in line.lower()

    def test_no_weather_change_returns_none(self):
        cf = Campfire()
        line = cf.on_weather_change(
            _make_game(),
            old_patterns=WeatherPatterns.CLEAR,
            new_patterns=WeatherPatterns.CLEAR,
            old_severities={},
            new_severities={},
        )
        assert line is None

    def test_weather_change_when_out_returns_none(self):
        cf = Campfire()
        cf.state["fire"] = FireState.OUT
        line = cf.on_weather_change(
            _make_game(),
            old_patterns=WeatherPatterns.CLEAR,
            new_patterns=WeatherPatterns.PRECIPITATION,
            old_severities={},
            new_severities={WeatherPatterns.PRECIPITATION: WeatherSeverities.LIGHT},
        )
        assert line is None


# ---------------------------------------------------------------------------
# StoneField
# ---------------------------------------------------------------------------


class TestStoneField:
    def test_supports_sensory_and_presence_verbs(self):
        sf = StoneField()
        # Sensory verbs (V1) plus presence verbs added 2026-05-04
        # with the new presence cog. $bite intentionally excluded
        # — stones do not invite the absurd the way the campfire
        # does (Caels' direction).
        assert sf.SUPPORTED_VERBS == [
            "gaze", "touch", "listen",
            "lean", "sit", "rest", "ponder", "tend",
        ]

    def test_gaze_returns_line(self):
        sf = StoneField()
        actor = MagicMock(name="player")
        actor.name = "Vael"
        actor.uses_article = False
        line = sf.on_verb("gaze", _make_game(), actor)
        assert line is not None
        assert "vael" in line.lower() or "stone" in line.lower()

    def test_touch_returns_line_no_damage(self):
        sf = StoneField()
        actor = MagicMock(name="player")
        actor.name = "Vael"
        actor.uses_article = False
        actor.apply_damage = MagicMock()
        line = sf.on_verb("touch", _make_game(), actor)
        assert line is not None
        actor.apply_damage.assert_not_called()

    def test_listen_returns_silence_flavor(self):
        sf = StoneField()
        actor = MagicMock(name="player")
        actor.name = "Vael"
        actor.uses_article = False
        line = sf.on_verb("listen", _make_game(), actor)
        assert line is not None
        assert "silen" in line.lower() or "quiet" in line.lower() or "speak" in line.lower()

    def test_unsupported_verb_returns_none(self):
        sf = StoneField()
        actor = MagicMock(name="player")
        actor.name = "Vael"
        line = sf.on_verb("light", _make_game(), actor)
        assert line is None

    def test_look_line_uses_rounded_estimate_when_count_at_least_ten(self):
        """`get_look_line` interpolates a "<N>-ish stones" phrase
        with N = floor(golem.escaped / 10) * 10. Vael walks every
        defensive golem; her in-fiction count of standing stones
        should be the world's record back at her. The rounded-down
        estimate sidesteps the unknown pre-stone-field tally:
        order-of-magnitude reads natural, exact counts would feel
        forensic."""
        sf = StoneField()
        game = _make_game()
        game.guild = MagicMock(id=1)
        game.channel = MagicMock(id=2)
        from collections import Counter
        game.monster_statics = Counter({"golem.escaped": 187})
        line = sf.get_look_line(game)
        assert "180-ish stones" in line
        assert "190-ish" not in line  # rounded down, not nearest

    def test_look_line_falls_back_below_ten(self):
        """Below the ten-tier the rough-estimate phrasing reads
        worse than a poetic fallback. The field is older than the
        clearing in lore — a fresh-deploy single-digit count is an
        artefact, not a narrative state."""
        sf = StoneField()
        game = _make_game()
        game.guild = MagicMock(id=1)
        game.channel = MagicMock(id=2)
        from collections import Counter
        game.monster_statics = Counter({"golem.escaped": 3})
        line = sf.get_look_line(game)
        assert "thin scatter" in line
        assert "-ish" not in line

    def test_look_line_safe_when_db_unreachable(self):
        """No guild / no channel / no DB → degrades gracefully to
        in-memory + fallback. ``$look`` must never raise."""
        sf = StoneField()
        line = sf.get_look_line(_make_game())  # no guild/channel attrs
        assert line is not None
        assert "thin scatter" in line


# ---------------------------------------------------------------------------
# World cog dispatch
# ---------------------------------------------------------------------------


class TestWorldCogDispatch:
    def _make_cog(self):
        from caldanai.lib.cogs.rpg_world_commands import RpgWorldCommands
        return RpgWorldCommands(bot=MagicMock())

    def _make_ctx(self):
        ctx = MagicMock()
        ctx.message = MagicMock()
        return ctx

    def _make_player(self):
        p = MagicMock()
        p.name = "Caels"
        p.uses_article = False
        p.pronouns = {}
        return p

    def _make_game_with_objects(self):
        game = MagicMock()
        game.channel = MagicMock()
        game.game_clock = MagicMock()
        game.game_clock.get_time_of_day.return_value = "NOON"
        game.weather = None
        # Explicit None for entity slots — auto-Mock attrs would
        # return truthy fakes that intercept the verb-resolver
        # chain BEFORE static objects (passerby/monster come
        # earlier in priority order). The unified dispatcher
        # walks passerby → silhouette → monster → static_object,
        # so these must be unset for the chain to reach static
        # objects.
        game.passerby = None
        game.pending_silhouette = None
        game.monster = None
        game.player_manager = MagicMock()
        game.player_manager.players = {}
        room = Area()
        room.add_static_object(Campfire())
        room.add_static_object(StoneField())
        game.room0 = room
        return game

    @pytest.mark.asyncio
    async def test_active_verb_no_target_emits_prompt(self):
        cog = self._make_cog()
        game = self._make_game_with_objects()
        player = self._make_player()
        ctx = self._make_ctx()

        with patch(
            "caldanai.lib.rpg.helpers.verb_dispatch.RpgUtilities.get_game_and_player",
            new=AsyncMock(return_value=(game, player)),
        ), patch(
            "caldanai.lib.rpg.helpers.verb_dispatch.Dispatcher",
        ) as mock_dispatch:
            await cog.touch.callback(cog, ctx, target=None)

        added = [
            c.args[1] for c in mock_dispatch.add.call_args_list
            if len(c.args) >= 2
        ]
        assert any("but at what" in str(m).lower() for m in added)

    @pytest.mark.asyncio
    async def test_sensory_verb_no_target_uses_self_directed_pool(self):
        cog = self._make_cog()
        game = self._make_game_with_objects()
        player = self._make_player()
        ctx = self._make_ctx()

        with patch(
            "caldanai.lib.rpg.helpers.verb_dispatch.RpgUtilities.get_game_and_player",
            new=AsyncMock(return_value=(game, player)),
        ), patch(
            "caldanai.lib.rpg.helpers.verb_dispatch.Dispatcher",
        ) as mock_dispatch:
            await cog.gaze.callback(cog, ctx, target=None)

        # Self-directed pool dispatched a beat.
        assert mock_dispatch.add.called

    @pytest.mark.asyncio
    async def test_active_verb_with_target_dispatches_to_object(self):
        cog = self._make_cog()
        game = self._make_game_with_objects()
        player = self._make_player()
        ctx = self._make_ctx()

        with patch(
            "caldanai.lib.rpg.helpers.verb_dispatch.RpgUtilities.get_game_and_player",
            new=AsyncMock(return_value=(game, player)),
        ), patch(
            "caldanai.lib.rpg.helpers.verb_dispatch.Dispatcher",
        ) as mock_dispatch:
            await cog.light.callback(cog, ctx, target="campfire")

        assert mock_dispatch.add.called

    @pytest.mark.asyncio
    async def test_unknown_target_emits_fallback(self):
        cog = self._make_cog()
        game = self._make_game_with_objects()
        player = self._make_player()
        ctx = self._make_ctx()

        with patch(
            "caldanai.lib.rpg.helpers.verb_dispatch.RpgUtilities.get_game_and_player",
            new=AsyncMock(return_value=(game, player)),
        ), patch(
            "caldanai.lib.rpg.helpers.verb_dispatch.Dispatcher",
        ) as mock_dispatch:
            await cog.light.callback(cog, ctx, target="dragon")

        added = [
            c.args[1] for c in mock_dispatch.add.call_args_list
            if len(c.args) >= 2
        ]
        assert any("nothing here" in str(m).lower() for m in added)

    @pytest.mark.asyncio
    async def test_unsupported_verb_for_object_falls_through(self):
        """`$light stones` — stone field doesn't handle 'light'.
        Should treat as unknown target, not crash."""
        cog = self._make_cog()
        game = self._make_game_with_objects()
        player = self._make_player()
        ctx = self._make_ctx()

        with patch(
            "caldanai.lib.rpg.helpers.verb_dispatch.RpgUtilities.get_game_and_player",
            new=AsyncMock(return_value=(game, player)),
        ), patch(
            "caldanai.lib.rpg.helpers.verb_dispatch.Dispatcher",
        ) as mock_dispatch:
            await cog.light.callback(cog, ctx, target="stones")

        added = [
            c.args[1] for c in mock_dispatch.add.call_args_list
            if len(c.args) >= 2
        ]
        # Falls through with the standard "nothing here to light" line.
        assert any("nothing here" in str(m).lower() for m in added)

    @pytest.mark.asyncio
    async def test_feed_extracts_explicit_fuel_token(self):
        """`$feed campfire stick` should pass 'stick' as fuel arg
        to the campfire's on_verb."""
        cog = self._make_cog()
        game = self._make_game_with_objects()
        player = self._make_player()
        ctx = self._make_ctx()

        # Make the campfire's feed handler call observable.
        cf = game.room0.find_static_object("campfire")
        cf.on_verb = MagicMock(return_value="fed")

        with patch(
            "caldanai.lib.rpg.helpers.verb_dispatch.RpgUtilities.get_game_and_player",
            new=AsyncMock(return_value=(game, player)),
        ), patch(
            "caldanai.lib.rpg.helpers.verb_dispatch.Dispatcher",
        ):
            await cog.feed.callback(cog, ctx, target="campfire stick")

        # on_verb called with verb='feed', fuel_arg='stick' as kwarg.
        # The dispatcher forwards extras by name through StaticObject's
        # handle_verb → on_verb path (per #63 fix 2026-05-07; was
        # positional, fragile). The cog passes fuel_arg=<token> on the
        # call to dispatch_expressive_verb.
        cf.on_verb.assert_called_once()
        args = cf.on_verb.call_args.args
        kwargs = cf.on_verb.call_args.kwargs
        assert args[0] == "feed"
        assert kwargs.get("fuel_arg") == "stick"
