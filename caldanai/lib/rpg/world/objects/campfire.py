"""Campfire — first static object. A persistent fixture of the
clearing that crackles, can be tended, can extinguish in rain,
and rewards the foolish with burns.

Design beats (Caels 2026-05-03):

- Starts lit. Players walk into a world that's already alive.
- Fuel ticks down on a schedule — sticks become an actively
  valuable inventory item beyond their combat use.
- Weather is reactive: light rain sputters, heavy rain takes a
  few rounds before extinguish, gusty wind throws embers.
- Touching the fire damages the touching hand (status-effect
  hook reserved for "catch fire" in V2).
- Ambience more pronounced at night (DUSK, NIGHT — when the
  fire is the world's loudest source).

Fuel as a real resource: starting fuel is 30 units (~30 minutes
at 1 unit/minute). A stick is +3. Rain accelerates loss; gusty
wind slightly accelerates loss too. Fuel reaching zero
extinguishes the fire via the same path rain takes (different
flavor: "guttering and dim" instead of "hissing").
"""

import random
from enum import Enum
from typing import Dict, List, Optional, Tuple

from caldanai.lib.rpg.helpers.enums import (
    DamageTypes,
    InjuryLevels,
    TimesOfDay,
    WeatherPatterns,
    WeatherSeverities,
)
from caldanai.lib.rpg.helpers.parser import parse
from caldanai.lib.rpg.world.objects import StaticObjectPlugin


class FireState(Enum):
    """Tri-state for the campfire. EMBERS is the "neither lit nor
    out" middle — the player can re-light from embers cheaply (no
    starter fuel needed); from OUT they need to provide fuel to
    re-establish.

    State transitions:
        OUT → LIT       : $light, requires fuel
        OUT → EMBERS    : (not reachable; embers fade to OUT, not the reverse)
        EMBERS → LIT    : $light, free
        EMBERS → OUT    : fuel timer fades
        LIT → EMBERS    : fuel ≤ embers_threshold
        LIT → OUT       : weather extinguish (rain) — skips embers
    """
    LIT = "lit"
    EMBERS = "embers"
    OUT = "out"


# Starting fuel + threshold tuning. Starts at FUEL_DEFAULT, ticks
# down on a 1-unit-per-minute schedule, drops to EMBERS at the
# threshold, OUT when EMBERS_DURATION ticks past zero.
FUEL_DEFAULT: int = 30
FUEL_EMBERS_THRESHOLD: int = 3
FUEL_PER_STICK: int = 5

# Burn rate multipliers under weather. Rain doubles fuel loss
# (LIGHT) or quadruples (HEAVY/SEVERE). Wind slightly accelerates.
FUEL_RATE_BY_RAIN: Dict[WeatherSeverities, float] = {
    WeatherSeverities.LIGHT:    2.0,
    WeatherSeverities.MODERATE: 3.0,
    WeatherSeverities.HEAVY:    4.0,
    WeatherSeverities.SEVERE:   4.0,
}
FUEL_RATE_BY_WIND: Dict[WeatherSeverities, float] = {
    WeatherSeverities.LIGHT:    1.0,   # breeze, no acceleration
    WeatherSeverities.MODERATE: 1.25,
    WeatherSeverities.HEAVY:    1.5,
    WeatherSeverities.SEVERE:   2.0,
}

# How many fuel "units" of fire-life to lose per minute under
# rain BEFORE the heavy-rain hard-extinguish kicks in. Heavy and
# severe rain trigger an immediate 2-3 minute delayed extinguish
# regardless of fuel.
HEAVY_RAIN_EXTINGUISH_MINUTES: int = 2

# Touch damage. Small enough that a single touch is foolish-but-
# survivable; repeated touches will rack up. dN_LIT for an active
# fire, dN_EMBERS for warm-but-not-flaming embers.
TOUCH_DAMAGE_LIT_DICE: str = "1d4"
TOUCH_DAMAGE_EMBERS: int = 1


# Cadence for the campfire's own ambience roll. 1/N tick chance
# during DAY periods; bumped during NIGHT (the fire is the loud
# thing in the dark). Per-state pacing — LIT speaks more often
# than EMBERS or OUT.
AMBIENCE_ROLL_LIT_DAY:    int = 2400
AMBIENCE_ROLL_LIT_NIGHT:  int = 800
AMBIENCE_ROLL_EMBERS:     int = 3600
AMBIENCE_ROLL_OUT:        int = 6000


# Sets used for time-of-day classification of "night" pronunciation.
_NIGHT_PARTITION = TimesOfDay.DUSK | TimesOfDay.NIGHT


class Campfire(StaticObjectPlugin):
    name = "campfire"
    aliases = ["fire", "flames", "embers"]

    SUPPORTED_VERBS = [
        "light", "feed", "gaze", "touch", "listen",
        # Presence verbs (added 2026-05-04 with the new presence cog).
        "sit", "rest", "lean", "tend", "ponder", "bite",
    ]

    # ---------------------------------------------------------------
    # Lifecycle
    # ---------------------------------------------------------------

    def __init__(self) -> None:
        super().__init__()
        self.state = {
            "fire": FireState.LIT,
            "fuel": FUEL_DEFAULT,
            # Tick-counter for delayed weather extinguish. Set when
            # heavy rain starts; decremented on the burn timer; when
            # zero, extinguishes.
            "extinguish_in": 0,
        }

    @property
    def fire_state(self) -> FireState:
        return self.state["fire"]

    @property
    def fuel(self) -> int:
        return self.state["fuel"]

    @property
    def is_lit(self) -> bool:
        return self.fire_state == FireState.LIT

    @property
    def is_embers(self) -> bool:
        return self.fire_state == FireState.EMBERS

    @property
    def is_out(self) -> bool:
        return self.fire_state == FireState.OUT

    # ---------------------------------------------------------------
    # Fuel timer — called from a per-minute clock routine wired up
    # by Game on area registration. (Wired in the Game integration
    # step; for now it's a method the campfire exposes so external
    # scheduling can drive it.)
    # ---------------------------------------------------------------

    def tick_fuel(self, game) -> Optional[str]:
        """Decrement fuel by one (modulated by weather). May
        transition state to EMBERS or OUT and return narration.
        Returns ``None`` on no state change."""
        if not self.is_lit and not self.is_embers:
            return None

        # Delayed weather extinguish takes priority.
        if self.state["extinguish_in"] > 0:
            self.state["extinguish_in"] -= 1
            if self.state["extinguish_in"] <= 0:
                self.state["fire"] = FireState.OUT
                self.state["fuel"] = 0
                return parse(
                    "@1Dc gives up its last sputter against the rain "
                    "and goes dark.",
                    self,
                )
            return None

        # Compute the per-tick fuel loss from active weather.
        loss = self._weather_burn_multiplier(game)
        self.state["fuel"] = max(0, int(self.state["fuel"] - loss))

        if self.is_lit and self.state["fuel"] <= FUEL_EMBERS_THRESHOLD:
            self.state["fire"] = FireState.EMBERS
            return parse(
                "@1Dc settles into embers, glow dimming, hungry now.",
                self,
            )
        if self.is_embers and self.state["fuel"] <= 0:
            self.state["fire"] = FireState.OUT
            return parse(
                "@1Dc fades to ash and a curl of grey smoke. The "
                "warmth slips away.",
                self,
            )
        return None

    def _weather_burn_multiplier(self, game) -> float:
        """Combined fuel-loss-per-tick from currently-active weather.
        Reads :class:`WeatherDaemon.severities` directly (no separate
        WeatherStrain enum — the existing IntFlag + severity dict is
        rich enough)."""
        weather = getattr(game, "weather", None)
        if weather is None:
            return 1.0
        rain_sev = weather.severity_of(WeatherPatterns.PRECIPITATION)
        wind_sev = weather.severity_of(WeatherPatterns.WIND)
        rain_mult = FUEL_RATE_BY_RAIN.get(rain_sev, 1.0) if rain_sev else 1.0
        wind_mult = FUEL_RATE_BY_WIND.get(wind_sev, 1.0) if wind_sev else 1.0
        # Multiplicative compounding — heavy rain in heavy wind
        # accelerates faster than either alone.
        return rain_mult * wind_mult

    # ---------------------------------------------------------------
    # Verb dispatch
    # ---------------------------------------------------------------

    def on_verb(
        self, verb: str, game, actor, **kwargs,
    ) -> Optional[str]:
        if verb == "light":
            return self._on_light(game, actor)
        if verb == "feed":
            # ``fuel_arg`` arrives as a kwarg from the cog via the
            # unified dispatcher's ``handle_verb`` → ``on_verb``
            # forwarding path. By-name extraction (vs. positional
            # ``args[0]``) is order-independent and survives future
            # verbs adding more kwargs alongside.
            fuel_arg = kwargs.get("fuel_arg")
            return self._on_feed(game, actor, fuel_arg)
        if verb == "gaze":
            return self._on_gaze(game, actor)
        if verb == "touch":
            return self._on_touch(game, actor)
        if verb == "listen":
            return self._on_listen(game, actor)
        # Presence verbs.
        if verb == "sit":
            return self._on_sit(game, actor)
        if verb == "rest":
            return self._on_rest(game, actor)
        if verb == "lean":
            return self._on_lean(game, actor)
        if verb == "tend":
            return self._on_tend(game, actor)
        if verb == "ponder":
            return self._on_ponder(game, actor)
        if verb == "bite":
            return self._on_bite(game, actor)
        return None

    def _on_light(self, game, actor) -> Optional[str]:
        if self.is_lit:
            line = random.choice([
                "@1Dc is already burning briskly.",
                "@1Dc crackles as if to say it's already lit.",
                "Flames lift in @1np hearth — already lit, thanks.",
            ])
            return parse(line, self)
        if self.is_embers:
            self.state["fire"] = FireState.LIT
            self.state["fuel"] = max(self.state["fuel"], FUEL_PER_STICK)
            return parse(
                "@2 coaxes the embers back into flame. @1Dc takes "
                "the gift of breath and burns again.",
                self, actor,
            )
        # OUT — needs fuel to re-establish
        fuel_item = self._find_fuel_in_inventory(actor)
        if fuel_item is None:
            return parse(
                "@2Np striker finds nothing to catch — @1d needs "
                "fuel before it can take flame. A stick would do.",
                self, actor,
            )
        actor.take_item(fuel_item)
        self.state["fire"] = FireState.LIT
        self.state["fuel"] = FUEL_PER_STICK * 2
        return parse(
            "@2 lays down a {fuel} and works the strikers patiently. "
            "@1Dc catches, hesitant at first, then committed.".format(
                fuel=fuel_item.name,
            ),
            self, actor,
        )

    def _on_feed(self, game, actor, fuel_arg: Optional[str]) -> Optional[str]:
        if self.is_out:
            return parse(
                "@1Dc is cold dirt — feeding will not help. Try "
                "@2np striker first.",
                self, actor,
            )
        fuel_item = self._resolve_fuel_arg(actor, fuel_arg)
        if fuel_item is None:
            if fuel_arg:
                return parse(
                    "@2 has no `{fuel}` to feed @1d.".format(fuel=fuel_arg),
                    self, actor,
                )
            return parse(
                "@2 has nothing fuel-shaped to feed @1d. Sticks "
                "from the road would do.",
                self, actor,
            )
        actor.take_item(fuel_item)
        was_embers = self.is_embers
        self.state["fuel"] += FUEL_PER_STICK
        # If fuel pushes past the embers threshold, restore LIT.
        if was_embers and self.state["fuel"] > FUEL_EMBERS_THRESHOLD:
            self.state["fire"] = FireState.LIT

        # State-aware fire response so the player can FEEL what the
        # feed did. Three bands:
        # - was embers, now lit again → bright recovery
        # - lit, fuel still low/middling → eager take
        # - lit, fuel near max → calm acceptance (nothing dramatic)
        if was_embers:
            response = random.choice([
                " The embers crackle back into proper flame, hungry and grateful.",
                " The embers leap to life around the new wood — back to a real fire now.",
                " The embers catch, climb, settle into proper flame again.",
            ])
        elif self.state["fuel"] < FUEL_DEFAULT // 2:
            response = random.choice([
                " The flames lift to take it, eager.",
                " The fire snaps and crackles around the new wood.",
                " Sap pops as the wood catches; flames grow a hand taller.",
            ])
        else:
            response = random.choice([
                " The fire accepts it, calm and steady.",
                " The flames take the wood without fuss.",
                " The fire eats into the new wood with patient appetite.",
            ])

        return parse(
            "@2 feeds a {fuel} to @1d.{response}".format(
                fuel=fuel_item.name, response=response,
            ),
            self, actor,
        )

    def _on_gaze(self, game, actor) -> Optional[str]:
        pool = self._gaze_pool_for_state(game)
        if not pool:
            return None
        return parse(random.choice(pool), self, actor)

    def _on_touch(self, game, actor) -> Optional[str]:
        # Dead actors can't feel anything. Block before any damage —
        # without this, a corpse can keep $touching the fire and the
        # bot keeps narrating it.
        if hasattr(actor, "is_dead") and actor.is_dead():
            return parse(
                "@2 reaches for @1d, but the warmth doesn't find what's "
                "already gone. @1Dc keeps its own counsel.",
                self, actor,
            )
        if self.is_out:
            return parse(
                "@2 touches cool ash. @1Dc gives nothing back.",
                self, actor,
            )
        # Pick a target part. ``find_parts`` excludes destroyed parts,
        # so once both hands are gone we walk up to the arms — touching
        # with a stump still costs the player something. If the arms
        # are gone too, the touch is symbolic only — better to refuse
        # than to silently spill damage to core HP via the no-target
        # legacy path.
        target_part = self._pick_touch_target(actor)
        if target_part is None:
            return parse(
                "@2 leans toward @1d, but there's nothing left to "
                "offer it. The flame doesn't catch on absence.",
                self, actor,
            )

        if self.is_embers:
            damage = TOUCH_DAMAGE_EMBERS
            line = (
                "@2 touches the embers — a sharp warmth, more "
                "warning than wound. Worth heeding."
            )
        else:  # LIT
            from caldanai.lib.rpg.helpers.dice import Dice
            damage = Dice.quick_roll(TOUCH_DAMAGE_LIT_DICE)
            line = random.choice([
                "@2 touches @1d. The fire bites — bright, immediate, "
                "instructive.",
                "@2 reaches for @1d and learns, the way fire teaches: "
                "all at once.",
                "Flame finds @2np fingers. The lesson lands "
                "before the flinch does.",
            ])

        # Capture injury-level transitions so we can narrate when the
        # touched part visibly worsens — the original silent path made
        # repeated touches feel weightless even as HP vanished.
        try:
            pre_injury = target_part.get_injury_level()
        except Exception:
            pre_injury = None
        transition = actor.apply_damage(
            damage, dmg_type=DamageTypes.FIRE, target_part=target_part,
        ) or ""
        try:
            post_injury = target_part.get_injury_level()
        except Exception:
            post_injury = pre_injury

        rendered = parse(line, self, actor)
        if pre_injury is not None and post_injury != pre_injury:
            worsen = self._worsen_beat(target_part, post_injury, actor)
            if worsen:
                rendered = f"{rendered} {worsen}"
        # ``apply_damage`` returns gear-drop narration (when a part
        # transitions to USELESS while holding equipment) and the
        # death tail (alive→dead). Surface both — silently dropping
        # this string is what made the burn-yourself-to-death loop
        # invisible.
        if transition:
            rendered = f"{rendered}\n{transition}"
        return rendered

    @staticmethod
    def _pick_touch_target(actor):
        """Pick a living body part to absorb a touch hit.

        Prefers hands; falls back to arms when both hands are
        destroyed (touching with a stump). Returns ``None`` when no
        living hand or arm remains — the caller should treat that
        as a symbolic touch rather than spill damage to core HP via
        the no-target path.
        """
        for query in ("hand", "arm"):
            try:
                candidates = actor.find_parts(query) or []
            except Exception:
                candidates = []
            if candidates:
                return random.choice(candidates)
        return None

    def _worsen_beat(self, part, level, actor) -> Optional[str]:
        """Short narration line when a touched part's injury level
        escalates. Lets the player feel the cumulative cost of
        repeated touches — without it, HP just silently drops while
        the flavor stays generic."""
        part_name = getattr(part, "display_name", None) or part.name
        if level == InjuryLevels.USELESS:
            return parse(
                f"@2np {part_name} blackens past use — given over to "
                f"the fire.",
                self, actor,
            )
        if level == InjuryLevels.SEVERE:
            return parse(
                f"@2np {part_name} chars deep, the meat of it raw "
                f"and red where the flame found it.",
                self, actor,
            )
        if level == InjuryLevels.MODERATE:
            return parse(
                f"@2np {part_name} blisters where the heat lingered.",
                self, actor,
            )
        if level == InjuryLevels.MINOR:
            return parse(
                f"@2np {part_name} reddens, tender to the touch now.",
                self, actor,
            )
        return None

    # ---------------------------------------------------------------
    # Presence-verb hooks (added with rpg_presence_commands cog)
    # ---------------------------------------------------------------

    def _on_sit(self, game, actor) -> Optional[str]:
        if self.is_lit:
            pool = [
                "@2 settles down beside @1d. The flames lean toward @2o, glad of the company.",
                "@2 lowers @2r onto a ring-stone, palms held out to the warmth.",
                "@2 sits with @2a knees bent toward @1d, the firelight finding the lines of @2np face.",
            ]
        elif self.is_embers:
            pool = [
                "@2 settles by the ember-bed of @1d. The glow is low and patient — companionable as a cat.",
                "@2 lowers @2r onto a warm ring-stone and lets the embers do their slow work on @2np hands.",
                "@2 sits cross-legged at the edge of @1d. The embers tick and settle, keeping @2o quiet company.",
            ]
        else:  # OUT
            pool = [
                "@2 settles down beside the cold ring of stones. The ash is grey, the warmth is gone, and the place where @1d was holds @2o anyway.",
                "@2 sits at the dead hearth of @1d. The stones are cool through @2np cloak; the silence is its own kind of sitting.",
                "@2 lowers @2r onto a ring-stone gone cold. The clearing keeps its quiet around @2np small still shape.",
            ]
        return parse(random.choice(pool), self, actor)

    def _on_rest(self, game, actor) -> Optional[str]:
        if self.is_lit:
            pool = [
                "@2 rests by @1d, eyes half-closing in the heat. The fire keeps watch in @2np stead.",
                "@2 stretches out beside @1d and lets the warmth do the work of holding @2o together.",
                "@2 settles back near @1d with a long slow exhale. The flames soften @2np shoulders one by one.",
            ]
        elif self.is_embers:
            pool = [
                "@2 rests by the ember-bed of @1d. The glow holds steady on @2np cheek and asks nothing more.",
                "@2 stretches out near @1d and lets the embers be the loudest thing in the world for a beat.",
                "@2 closes @2a eyes by the embers, breath slow, the warmth a held hand on @2np back.",
            ]
        else:  # OUT
            pool = [
                "@2 rests by the dead hearth of @1d. There is no warmth to lean into — only the shape of where the warmth was.",
                "@2 closes @2a eyes beside the cold ring of stones. The clearing holds the rest in the fire's place.",
                "@2 lets @2r settle by the ash of @1d. Cold-stones rest is rest of a different sort, but rest still.",
            ]
        return parse(random.choice(pool), self, actor)

    def _on_lean(self, game, actor) -> Optional[str]:
        if self.is_lit:
            pool = [
                "@2 leans toward the warmth of @1d, hands held open to the flame.",
                "@2 props @2a forearms on a knee and tilts @2r closer to @1d. The fire welcomes the angle.",
                "@2 leans into the heat-line of @1d. The flames lift a fraction toward @2np face.",
            ]
        elif self.is_embers:
            pool = [
                "@2 leans toward the embers of @1d, palms held a careful hand's breadth above the glow.",
                "@2 props @2r on a ring-stone and tips @2a body toward what warmth remains.",
                "@2 leans low over the ember-bed of @1d. The glow finds @2np jaw and stays there.",
            ]
        else:  # OUT
            pool = [
                "@2 leans toward the cold ring of stones. There is no warmth waiting; the lean is its own quiet ceremony.",
                "@2 props @2r on a ring-stone gone cold. The fire is not there to lean into. @2 leans anyway.",
                "@2 tilts @2r toward where @1d used to be. The ash does not stir.",
            ]
        return parse(random.choice(pool), self, actor)

    def _on_tend(self, game, actor) -> Optional[str]:
        if self.is_lit:
            pool = [
                "@2 nudges a coal back into place at the edge of @1d with the side of a stick. The fire takes the small correction without comment.",
                "@2 reaches in with a careful stick and rolls a half-burned log a quarter-turn. @1Dc settles into the new arrangement.",
                "@2 brushes a stray ember back into the ring with a flick of a twig. @1Dc accepts the tidying.",
            ]
        elif self.is_embers:
            pool = [
                "@2 stirs the ember-bed of @1d gently with a stick, coaxing the glow to spread. The embers brighten a moment in answer.",
                "@2 banks a small heap of warm ash over the brightest coals of @1d. The embers will hold longer for it.",
                "@2 turns a glowing coal with a careful twig. @1Dc sighs back a brief lift of orange light.",
            ]
        else:  # OUT
            pool = [
                "@2 brushes cold ash to one side with the edge of @2a hand. @1Dc stays cold and still — but the hearth is tidier for the gesture.",
                "@2 sweeps loose ash out of the ring of @1d, settling the dead place a little more decently.",
                "@2 squares the cooled stones of @1d with a patient hand. Nothing kindles. The care lands anyway.",
            ]
        return parse(random.choice(pool), self, actor)

    def _on_ponder(self, game, actor) -> Optional[str]:
        if self.is_lit:
            pool = [
                "@2 watches @1d, letting thoughts catch like sparks and rise.",
                "@2 stares into the flames of @1d. Shapes form, unform, almost-mean something, and don't.",
                "@2 holds @2a gaze on @1d. The fire does the thinking for @2o, in the way fire does.",
            ]
        elif self.is_embers:
            pool = [
                "@2 watches the ember-bed of @1d. The slow glow makes a slow place in @2np head for thought to settle.",
                "@2 sits with @2a thoughts beside the embers of @1d. The glow ticks and settles; so does whatever @2 was turning over.",
                "@2 considers the dim heart of @1d. The embers consider back, in their own ember way.",
            ]
        else:  # OUT
            pool = [
                "@2 looks at the cold ring of @1d. The stones hold no answer; the holding is its own.",
                "@2 ponders the ash of @1d. The fire is gone; the place where the fire was is full of what's missing.",
                "@2 stands quiet at the dead hearth of @1d, weighing something the cold stones won't quite speak to.",
            ]
        return parse(random.choice(pool), self, actor)

    def _on_bite(self, game, actor) -> Optional[str]:
        if self.is_lit:
            pool = [
                "@2 bites at @1d. The fire is delighted, and flares a hand higher in approval.",
                "@2 leans in and snaps @2a teeth at the flame of @1d. @1Dc throws a bright pop of sparks, charmed.",
                "@2 nips at the air over @1d. The fire crackles back like it's been waiting to be invited.",
            ]
        elif self.is_embers:
            pool = [
                "@2 bites at the ember-bed of @1d. The embers wake briefly, an orange wink, and settle again.",
                "@2 snaps @2a teeth playfully toward the embers. @1Dc breathes a small bright tick of acknowledgement.",
                "@2 leans in and mock-bites at the glow. The embers shift like a cat being scratched.",
            ]
        else:  # OUT
            pool = [
                "@2 bites at the cold hearth of @1d. The ash is not amused. Neither, frankly, is @2.",
                "@2 leans in and snaps @2a teeth at the dead ring of stones. The cold stones decline to participate.",
                "@2 nips at the ash where @1d used to be. The mouthful is cold and chalky and instructive.",
            ]
        return parse(random.choice(pool), self, actor)

    def _on_listen(self, game, actor) -> Optional[str]:
        if self.is_out:
            return parse(
                "@1Dc is silent, the way cold ash is silent — a "
                "settled-in sort of nothing.",
                self,
            )
        if self.is_embers:
            line = random.choice([
                "Embers tick and settle, a slow conversation between "
                "wood and air.",
                "The faint hiss of embers, the kind of sound that "
                "makes the rest of the world feel large.",
                "Soft pops from the ember-bed, like small thoughts "
                "settling.",
            ])
            return parse(line, self)
        # LIT
        line = random.choice([
            "@1Dc crackles steady, splitting wood with small sharp "
            "sounds — a fire's regular grammar.",
            "Pops and snaps from @1d, the way wood remembers being "
            "tree.",
            "The fire breathes — long draws and slow exhales of "
            "spark and heat.",
            "@1Dc whispers in its own old language: hiss, snap, "
            "settle, hiss.",
        ])
        return parse(line, self)

    # ---------------------------------------------------------------
    # $look hook
    # ---------------------------------------------------------------

    def get_look_line(self, game) -> Optional[str]:
        if self.is_out:
            return parse(
                "A circle of cold ash and blackened stones marks "
                "where @1d was.",
                self,
            )
        if self.is_embers:
            return parse(
                "@1Dc has burned down to embers, dim and patient.",
                self,
            )
        # LIT — vary by time-of-day for tone. Be explicit that the
        # fire is healthy in both cases; "crackles low" used to
        # imply state-affected which misread the daytime line as
        # rain-impacted or dying.
        tod = self._tod_flag(game)
        if tod & _NIGHT_PARTITION:
            return parse(
                "@1Dc burns brightly at the clearing's center, "
                "throwing warm light against the dark.",
                self,
            )
        return parse(
            "@1Dc burns steadily at the clearing's center, flames "
            "modest against the daylight.",
            self,
        )

    # ---------------------------------------------------------------
    # Ambience hook
    # ---------------------------------------------------------------

    def maybe_emit_ambience(self, game) -> Optional[str]:
        roll = self._ambience_roll_for_state(game)
        if random.randint(1, roll) != roll:
            return None
        pool = self._ambience_pool_for_state(game)
        if not pool:
            return None
        return parse(random.choice(pool), self)

    # ---------------------------------------------------------------
    # Weather hook
    # ---------------------------------------------------------------

    def on_weather_change(
        self, game,
        old_patterns: WeatherPatterns,
        new_patterns: WeatherPatterns,
        old_severities: Dict[WeatherPatterns, WeatherSeverities],
        new_severities: Dict[WeatherPatterns, WeatherSeverities],
    ) -> Optional[str]:
        # Only react when lit / embering. An out fire doesn't care
        # about the weather.
        if self.is_out:
            return None

        rain_started = (
            WeatherPatterns.PRECIPITATION not in old_patterns
            and WeatherPatterns.PRECIPITATION in new_patterns
        )
        rain_intensified = (
            WeatherPatterns.PRECIPITATION in old_patterns
            and WeatherPatterns.PRECIPITATION in new_patterns
            and new_severities.get(WeatherPatterns.PRECIPITATION, WeatherSeverities.LIGHT).value
            > old_severities.get(WeatherPatterns.PRECIPITATION, WeatherSeverities.LIGHT).value
        )
        if rain_started or rain_intensified:
            return self._react_to_rain(new_severities)

        wind_picked_up = (
            WeatherPatterns.WIND in new_patterns
            and (
                WeatherPatterns.WIND not in old_patterns
                or new_severities.get(WeatherPatterns.WIND, WeatherSeverities.LIGHT).value
                > old_severities.get(WeatherPatterns.WIND, WeatherSeverities.LIGHT).value
            )
        )
        if wind_picked_up:
            wind_sev = new_severities.get(WeatherPatterns.WIND)
            if wind_sev in (WeatherSeverities.HEAVY, WeatherSeverities.SEVERE):
                return parse(
                    "Embers shower from @1d, scattering across the "
                    "clearing like stars on a bad night.",
                    self,
                )
            return parse(
                "Embers lift on the breeze from @1d and drift "
                "skyward, fireflies in slow flight.",
                self,
            )

        return None

    def _react_to_rain(
        self,
        new_severities: Dict[WeatherPatterns, WeatherSeverities],
    ) -> str:
        sev = new_severities.get(WeatherPatterns.PRECIPITATION, WeatherSeverities.LIGHT)
        if sev in (WeatherSeverities.HEAVY, WeatherSeverities.SEVERE):
            # Schedule delayed extinguish — fire fights for a couple
            # ticks before going out.
            self.state["extinguish_in"] = HEAVY_RAIN_EXTINGUISH_MINUTES
            return parse(
                "Heavy rain finds @1d. It chokes, sputters, recovers, "
                "sputters again — fighting it.",
                self,
            )
        if sev == WeatherSeverities.MODERATE:
            return parse(
                "Rain begins on @1d. The flames hiss in protest "
                "but hold.",
                self,
            )
        # LIGHT
        return parse(
            "@1Dc hisses and sputters as the first drops of rain "
            "find it — but holds, for now.",
            self,
        )

    # ---------------------------------------------------------------
    # Helpers — fuel resolution
    # ---------------------------------------------------------------

    def _find_fuel_in_inventory(self, actor) -> Optional[object]:
        """Implicit-feed: scan actor's inventory for the most-
        abundant fuel item. Returns a single instance to consume,
        or ``None`` if no fuel is found."""
        candidates = self._collect_fuel_items(actor)
        if not candidates:
            return None
        # Group by name; pick the most-abundant group; return the
        # first item in that group.
        by_name: Dict[str, List[object]] = {}
        for item in candidates:
            by_name.setdefault(item.name, []).append(item)
        most_abundant_name = max(by_name.keys(), key=lambda n: len(by_name[n]))
        return by_name[most_abundant_name][0]

    def _resolve_fuel_arg(self, actor, fuel_arg: Optional[str]):
        """Explicit-feed: resolve ``fuel_arg`` against the actor's
        inventory, restricted to fuel-eligible items. Returns a
        single instance or ``None`` if no match."""
        if fuel_arg is None:
            return self._find_fuel_in_inventory(actor)
        candidates = [
            i for i in self._collect_fuel_items(actor)
            if fuel_arg.lower() in (i.name or "").lower()
        ]
        if not candidates:
            return None
        return candidates[0]

    @staticmethod
    def _collect_fuel_items(actor) -> List[object]:
        """All fuel-eligible items in the actor's inventory.
        V1 rule: an item is fuel if its name contains 'stick',
        'branch', 'log', or 'kindling'. Equipped + ★-favorited
        items are excluded — can't burn the stick in your hand,
        and the favorite flag is the player's "hands off" signal
        for any consume verb that isn't an explicit $craft / $use
        (mirrors the $sell protection). Masterwork sticks survive
        idle campfire-feeding this way.

        Inventory is dict-like (defines ``__getitem__`` keyed on
        str/ObjectId) but does NOT define ``__iter__``. Calling
        ``list(inventory)`` triggers Python's int-fallback
        iteration, which loops forever because ``__getitem__``
        returns ``None`` rather than raising IndexError on int
        keys. Use the explicit ``inventory.all()`` accessor
        instead — returns a tuple of every item.
        """
        inventory = getattr(actor, "inventory", None)
        if inventory is None:
            return []
        try:
            items_list = list(inventory.all())
        except (AttributeError, TypeError):
            return []
        fuel_keywords = ("stick", "branch", "log", "kindling")
        result = []
        for item in items_list:
            name = (getattr(item, "name", "") or "").lower()
            if not any(k in name for k in fuel_keywords):
                continue
            if getattr(item, "favorited", False):
                continue
            try:
                if actor.is_equipped(item):
                    continue
            except Exception:
                pass
            result.append(item)
        return result

    # ---------------------------------------------------------------
    # Helpers — pools
    # ---------------------------------------------------------------

    def _ambience_roll_for_state(self, game) -> int:
        if self.is_out:
            return AMBIENCE_ROLL_OUT
        if self.is_embers:
            return AMBIENCE_ROLL_EMBERS
        # LIT
        if self._tod_flag(game) & _NIGHT_PARTITION:
            return AMBIENCE_ROLL_LIT_NIGHT
        return AMBIENCE_ROLL_LIT_DAY

    def _ambience_pool_for_state(self, game) -> List[str]:
        if self.is_out:
            return [
                "A faint smell of cold ash drifts from @1d, settled "
                "into the dirt.",
            ]
        if self.is_embers:
            return [
                "@1Dc breathes a thin curl of smoke into the air.",
                "Embers shift in @1d, a single soft pop.",
                "The ember-bed of @1d glows faintly, dim as a held "
                "breath.",
            ]
        # LIT
        is_night = bool(self._tod_flag(game) & _NIGHT_PARTITION)
        base = [
            "@1Dc throws a sudden brighter flare, then settles.",
            "A pocket of sap snaps in @1d, sharp and momentary.",
            "Sparks rise from @1d in slow spirals.",
        ]
        if is_night:
            base.extend([
                "@1Dc is the warmest thing in the dark; the rest of "
                "the world stands a little farther off for it.",
                "Shadows shift in time with @1np flames, the clearing's "
                "edges breathing in and out.",
                "@1Dc is a small bright argument against the night, "
                "and winning.",
            ])
        return base

    def _gaze_pool_for_state(self, game) -> List[str]:
        if self.is_out:
            return [
                "@2 gazes at the cold circle of stones. The fire is "
                "gone, but the place where fire was remains.",
            ]
        if self.is_embers:
            return [
                "@2 watches the embers shift and settle in @1d. The "
                "small movements feel like thinking.",
                "The ember-glow of @1d catches in @2np eyes, dim and "
                "patient.",
            ]
        # LIT — vary by time-of-day
        is_night = bool(self._tod_flag(game) & _NIGHT_PARTITION)
        common = [
            "@2 gazes into @1d. Shapes form in the flames — animals, "
            "faces, old roads — and unform again.",
            "The fire holds @2np attention the way fire does, patient "
            "and absolute.",
            "@2 watches @1d burn, and for a moment forgets there's a "
            "world outside its light.",
        ]
        if is_night:
            common.append(
                "@2 stares into @1d. Beyond the firelight the dark "
                "is total, and somehow gentler for the contrast."
            )
        return common

    @staticmethod
    def _tod_flag(game) -> TimesOfDay:
        """Best-effort current time-of-day as a flag, with a clear
        default (DAY-equivalent) when the clock isn't reachable."""
        clock = getattr(game, "game_clock", None)
        if clock is None:
            return TimesOfDay.NOON
        try:
            return TimesOfDay[clock.get_time_of_day().upper()]
        except (KeyError, AttributeError):
            return TimesOfDay.NOON
