"""Generic ``WingPlugin`` -- Phase 1.B item 2.5.

The fifth base body-part plugin and the **first plugin with an active
``on_injury_change`` hook**. Wings are non-critical (you can lose them
and live) but carry both a DODGE and an ATTACK (weak buffet) debuff
similarly to legs, and -- uniquely so far -- trigger a discrete state
transition when destroyed: the creature's ``"flying"`` flag is
discarded, grounding it.

This is the flag the dragon-toes state-dependent debuff reads to
decide whether its 62 toes contribute -1 DODGE each. Grounding a
toe-variant dragon via wing destruction therefore cascades into the
full toe penalty. See the "Dragon toes" section of
``Caldanai_Bot Phase 1 - Body Parts.md``.

Design rationale
================

``health_max = "1d8"``
    Wings are slightly smaller/lighter than legs (1d10) and the
    design doc's sketch uses 1d8. We match it.

``is_critical = False``
    You can destroy a wing without killing the creature. Destruction
    drops the wing to ``InjuryLevels.USELESS`` and runs the grounded
    transition, but the creature lives (body takes only
    ``BODY_DAMAGE_FRACTION`` of the final damage, and the
    ``is_critical`` death short-circuit never fires for wings). The
    USELESS row is therefore *reachable* and needs to be a real row.

Exposure (melee/reach tucked, ranged splayed)
    - ``MELEE: 0.5`` -- a flying or even stationary creature tucks
      its wings when engaged in close combat; they are the hardest
      part to land a blade on in a melee exchange.
    - ``REACH: 0.5`` -- the design-doc sketch omitted REACH; we mirror
      MELEE (uniform 0.5) so the plugin never falls through to a
      default. Polearms and whips have the same tucked-wing problem
      as swords at knife-fight range.
    - ``THROWN: 0.7`` -- a javelin in flight has slightly better odds
      against a wing than a melee strike but still misses the broad
      side because the wing folds.
    - ``RANGED: 1.0`` -- archers *love* big spread-out wings. A
      creature mid-flight presents the wing as the single biggest,
      most exposed piece of its silhouette.

Debuffs
    - ``MINOR: DODGE -1`` -- a lightly-bruised wing wobbles slightly
      in evasive maneuvers. No ATTACK penalty; a weak buffet is still
      a weak buffet.
    - ``MODERATE: DODGE -2, ATTACK -1`` -- ATTACK penalty kicks in as
      the wing loses the snap needed for a buffet strike.
    - ``SEVERE: DODGE -3, ATTACK -2`` -- linear scaling.
    - ``USELESS: DODGE -5, ATTACK -3`` -- the wing is gone; passive
      dodge and buffet both take big hits. **Additionally, the
      ``on_injury_change`` hook below fires on the transition into
      USELESS and discards the ``"flying"`` flag.** The creature is
      grounded on the same frame its wing crumples.

    DODGE appears on every row; ATTACK skips MINOR. DEFENSE is never
    touched by wing debuffs.

``on_injury_change``
    Only the ``-> USELESS`` transition does anything: it discards
    ``"flying"`` from ``creature.flags`` (a set, so ``.discard`` is a
    no-op if the flag was never there -- safe for creatures that never
    flew in the first place) and returns a rendered flavor string via
    ``parse``. All other transitions (``NONE -> MINOR``,
    ``MINOR -> MODERATE``, etc.) are silent: they return the empty
    string and don't touch state.

Doppelganger pain cries
    One escalating flavor string per injury level, landing on "the
    imitation completes itself" for USELESS to match the design doc's
    leg example tone.
"""

from caldanai.lib.rpg.creatures.body_parts import BodyPartPlugin
from caldanai.lib.rpg.helpers.enums import InjuryLevels, Reach, Stat
from caldanai.lib.rpg.helpers.parser import parse


class WingPlugin(BodyPartPlugin):
    """Generic wing. Non-critical. DODGE + ATTACK (buffet) debuffs,
    plus an ``on_injury_change(USELESS)`` hook that grounds the
    creature by discarding the ``"flying"`` flag.

    Exposure is low in melee/reach (wings tuck away, hard to land a
    sword on) and highest at range (archers love big spread-out
    wings).
    """

    name = "wing"
    health_max = "1d8"
    is_critical = False
    exposure = {
        Reach.MELEE:  0.5,   # wings tuck away, hard to hit in melee
        Reach.REACH:  0.5,   # same; mirrors MELEE (doc sketch omitted)
        Reach.THROWN: 0.7,
        Reach.RANGED: 1.0,   # archers love big spread-out wings
    }
    debuffs = {
        InjuryLevels.MINOR:    {Stat.DODGE: -1},
        InjuryLevels.MODERATE: {Stat.DODGE: -2, Stat.ATTACK: -1},  # weak buffet
        InjuryLevels.SEVERE:   {Stat.DODGE: -3, Stat.ATTACK: -2},
        InjuryLevels.USELESS:  {Stat.DODGE: -5, Stat.ATTACK: -3},  # + grounded via on_injury_change
    }

    def on_injury_change(
        self,
        creature,
        old_level: InjuryLevels,
        new_level: InjuryLevels,
    ) -> str:
        """Ground the creature when the wing is destroyed.

        Only the transition *into* ``USELESS`` fires: we discard the
        ``"flying"`` flag (set.discard is safe on missing keys, so
        creatures that never flew are unaffected) and return a
        rendered grounded message. All other transitions are silent
        -- they return the empty string and don't touch state.
        """
        if new_level == InjuryLevels.USELESS:
            creature.flags.discard("flying")
            return parse("@1dc's wing crumples; @1s is grounded.", creature)
        return ""

