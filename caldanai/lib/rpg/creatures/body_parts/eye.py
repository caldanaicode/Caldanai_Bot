"""Generic ``EyePlugin`` -- Phase 1.B item 2.7.

The seventh base body-part plugin and a non-critical part common to
nearly every creature in the bestiary. Eyes are small, hard-to-hit
targets with an outsized combat impact: they drive aim. Injuring or
destroying an eye debuffs ``Stat.HIT`` (the creature's attack-roll
accuracy), not ``Stat.ATTACK`` (raw power), because even a blinded
creature can still swing hard -- it just can't target well.

Eyes are also the canonical "explicit targeting" part. The exposure
table is dramatically lower than every other part (0.1 to 0.3 versus
0.5 to 1.0 elsewhere), which keeps random attack routing from landing
on an eye all that often. The intended play pattern is ``attack
@dragon eye`` -- a deliberate, tactical gouge that trades hit chance
for a very large payoff if it lands.

Design rationale
================

``health_max = "1d4"``
    Eyes are the smallest base part in the plugin set. ``1d4`` is the
    smallest sane dice string and matches the biological reality that
    eyes explode under any serious hit. By contrast, arms and heads
    are ``1d8``, legs are ``1d10``, and torso is ``2d10``.

``is_critical = False``
    Blinding a creature does not kill it. Even a creature with every
    eye destroyed still has limbs, internal organs, and a working
    nervous system. Under the current ``Creature.apply_damage``
    routing, non-critical parts drain the body by
    ``BODY_DAMAGE_FRACTION`` (0.5) of the damage dealt and do NOT
    fire the critical-part death short-circuit. The USELESS debuff row
    is therefore reachable and needs to be a real, balanced row.

Exposure (uniformly low across every reach)
    - ``MELEE: 0.1`` -- hitting a specific eye with a sword is
      unlikely unless you're deliberately gouging. Most melee swings
      land on arms, torso, or legs long before they reach an eye.
    - ``REACH: 0.1`` -- polearms have the same geometric problem. The
      extra reach doesn't help you hit a specific eye; it just lets
      you hit from further away.
    - ``THROWN: 0.2`` -- slightly higher than melee. A thrown dagger
      or javelin follows a cleaner trajectory than a swung weapon and
      can occasionally catch a face, but throwers still aim
      center-mass so eye hits remain rare.
    - ``RANGED: 0.3`` -- the highest reach band for eyes. Archers and
      crossbow users can line up a deliberate head-shot over distance.
      Ranged is still dramatically lower than torso (1.0) or arms
      (0.6) -- an eye is a small target no matter how much time you
      have to aim -- but it's the one reach where eye-hits happen with
      any regularity.

    All four reach keys are populated explicitly so the plugin never
    falls through to a default. **All four values are <= 0.3**, and
    ``test_exposure_uniformly_low`` pins this invariant so any future
    accidental bump past 0.3 trips the test suite.

Debuffs (HIT-only, non-linear)
    - ``MINOR: HIT -1`` -- a watering or slightly irritated eye
      affects aim marginally.
    - ``MODERATE: HIT -2`` -- swelling and blurred vision start
      compounding the accuracy hit.
    - ``SEVERE: HIT -4`` -- a ruptured or nearly-blinded eye. The
      scaling jumps past linear (-3 would be linear from -1/-2).
    - ``USELESS: HIT -8`` -- fully destroyed / blind. The jump from
      SEVERE to USELESS is *intentionally* larger than the linear
      extension (linear would be -6; this is -8). A creature with no
      functional eyes should be a sitting duck in combat, and the
      non-linear cliff at USELESS encodes the qualitative difference
      between "severely injured eye" and "blind". Two destroyed eyes
      aggregate to HIT -16, which should be enough to make any
      attack-roll contest effectively hopeless.

    **Contract pin**: HIT is the *only* stat the base eye touches.

    - **No ATTACK debuff.** Eyes affect aim, not raw attack power.
      Keeping ATTACK out of the eye debuff table preserves the
      conceptual split the design doc draws between ATTACK (how hard
      you swing) and HIT (whether you connect).
    - **No DEFENSE debuff.** DEFENSE is the arm's SEVERE niche (parry
      loss); eyes have nothing to do with blocking.
    - **No DODGE debuff.** DODGE is the tail and leg niche (balance
      and footwork). While real-world blindness intuitively would hurt
      dodging, the base eye plugin keeps its contract tight so it
      composes cleanly without double-booking the dodge penalty that
      other parts already own. Creatures that want blindness to hurt
      dodge can subclass or compose additional parts.

Multi-eye composition
    Creatures with more than one eye (most creatures: 2; cyclops: 1;
    spiders: 8) compose by calling ``BodyPart.make("eye",
    name="left eye")`` once per eye, each with a unique name. The
    item 1.8 ``Creature.get_part(name)`` helper then resolves each eye
    by name for explicit targeting, and stat aggregation sums debuffs
    across every eye. A two-eyed creature with both eyes destroyed
    aggregates to HIT -16.

Doppelganger pain cries
    One flavor string per injury level, escalating from a mysterious
    teary blink to a pupil-blown sinking into the socket. The design
    doc wants per-part doppelganger cries on every base part.
"""

from caldanai.lib.rpg.creatures.body_parts import BodyPartPlugin
from caldanai.lib.rpg.helpers.enums import InjuryLevels, Reach, Stat


class EyePlugin(BodyPartPlugin):
    """Generic eye. Non-critical. HIT-only debuffs (aim organ).

    Eyes are small, hard-to-hit targets with an outsized combat impact.
    They drive aim, so injuring one debuffs ``Stat.HIT`` (attack-roll
    accuracy), not ``Stat.ATTACK`` (raw power). The exposure table is
    uniformly low (all values <= 0.3) because eyes are tiny targets;
    the intended play pattern is explicit targeting (``attack @dragon
    eye``) rather than random routing.

    The USELESS HIT debuff (-8) is deliberately steeper than a linear
    extension of the MINOR/MODERATE/SEVERE scale (-1/-2/-4). A fully
    blinded creature should be qualitatively different from one with
    merely severely injured eyes -- this is the tactical payoff that
    makes eye-gouging worth the low hit chance.

    Creatures with multiple eyes compose by calling
    ``BodyPart.make("eye", name="left eye")`` once per eye; each
    instance contributes its own debuff row to
    ``get_stat_modifier_total(Stat.HIT)``.
    """

    name = "eye"
    health_max = "1d4"
    is_critical = False
    exposure = {
        Reach.MELEE:  0.1,
        Reach.REACH:  0.1,
        Reach.THROWN: 0.2,
        Reach.RANGED: 0.3,
    }
    debuffs = {
        InjuryLevels.MINOR:    {Stat.HIT: -1},
        InjuryLevels.MODERATE: {Stat.HIT: -2},
        InjuryLevels.SEVERE:   {Stat.HIT: -4},
        InjuryLevels.USELESS:  {Stat.HIT: -8},
    }

    def get_doppelganger_pain_cry(self, level: InjuryLevels) -> str:
        return {
            InjuryLevels.MINOR: (
                "@1 blinks rapidly as one eye clouds over with "
                "unexplained tears."
            ),
            InjuryLevels.MODERATE: (
                "@1 squints hard, @1a eye going bloodshot and swollen "
                "in an instant."
            ),
            InjuryLevels.SEVERE: (
                "@1 claps @1a hand to @1a face as the eye beneath it "
                "splits open without warning."
            ),
            InjuryLevels.USELESS: (
                "@1's eye sinks deep into its socket, pupil blown "
                "black as the imitation blinds it."
            ),
        }.get(level, "")
