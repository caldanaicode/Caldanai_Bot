"""Social-warmth cog.

Houses the social-gesture commands (``$hug``, ``$high_five``,
``$fistbump``, and the dead-player ``$haunt``) plus the ``$warmth``
preference manager. Lifted out of ``rpg_user_commands`` so the
warmth flavor infrastructure has a clear home and so future social
verbs (salute, bow, pose, etc.) land here without bloating the
general player-commands cog.

Key ideas:

- **Warmth resolution** lives in
  :mod:`caldanai.lib.rpg.helpers.warmth`. The cog just consults the
  resolver for ``(acceptance, intent)`` and renders the narration.
- **Target-governs-acceptance**: the target player's warmth setting
  for a given command is authoritative on *what happens*; the
  actor's warmth is flavor-only and tints *how they attempted*.
- **Privacy**: ``$warmth`` output always goes to DM. The invoker only
  ever sees their own preferences, never another player's.
"""

import re
from random import choice, randint
from typing import Dict, List, Optional, Tuple

from discord import File, Member
from discord.ext.commands import (
    BucketType,
    Cog,
    Context,
    command,
    cooldown,
    group,
    guild_only,
)

from caldanai.dispatcher import Dispatcher
from caldanai.logger import get_logger
from caldanai.lib.rpg.creatures import Creature
from caldanai.lib.rpg.creatures.player import Player
from caldanai.lib.rpg.helpers.parser import parse
from caldanai.lib.rpg.helpers.utils import RpgUtilities
from caldanai.lib.rpg.helpers import warmth


_log = get_logger(__name__)


# Reserved sentinel in ``$warmth set / clear`` that means "apply to
# every registered warmth-aware command" rather than a single one.
# Reserved — no actual command may be registered under this name
# (``is_known_command`` returns False for it, and the handlers
# special-case it before the known-command check).
_WARMTH_WILDCARD = "all"


# Discord mention tag, with or without the legacy ``!`` nickname flag.
# Used to detect the common mis-parse where a player types
# ``$warmth clear @someone`` (omitting the cmd arg) — the mention
# lands in ``cmd`` and shouldn't be echoed back raw in an error.
_MENTION_TAG_RE = re.compile(r"^<@!?(\d+)>$")


def _mention_to_uid(s: Optional[str]) -> Optional[int]:
    """Return the user_id if ``s`` is a Discord mention tag, else None."""
    if not s:
        return None
    m = _MENTION_TAG_RE.match(s.strip())
    return int(m.group(1)) if m else None


# ---------------------------------------------------------------------------
# Dead-actor flavor pools
# ---------------------------------------------------------------------------
#
# Two command-keyed dicts so a new social verb lands its dead pools by
# adding a key to each, rather than declaring new module-level lists
# and threading them through handler parameters. Mirrors the shape of
# ``_NARRATION_POOLS`` further down.
#
# ``_DEAD_INVOKER_FLAVOR``: rendered when the invoker is a corpse.
# Single-actor ``@1`` template applied via
# ``RpgUtilities.dead_invoker_guard``.
#
# ``_DEAD_TARGET_FLAVOR``: rendered when the invoker is alive but the
# target they mentioned is a corpse. ``@1`` = living invoker, ``@2``
# = dead target. ``$hug`` routes dead-target cases through
# ``Player.on_hugged`` (which has its own dead branch), so ``hug`` is
# absent from this dict on purpose — the ``_dispatch_*`` handler that
# renders from this dict is used by commands that don't have an
# equivalent on_hugged-style hook.

_DEAD_INVOKER_FLAVOR: Dict[str, List[str]] = {
    "hug": [
        "A lonely sigh slips from the corpse of @1.",
        "The shade of @1 reaches out, but @1np arms close on nothing.",
        "A faint warmth gathers over the remains of @1 for a moment, then dissipates.",
        "@1np stillness seems a little lonelier than a moment ago.",
        "Somewhere beyond the veil, @1 accepts the gesture.",
        "The chill near @1np body softens briefly, as if remembering how to be held.",
    ],
    "high_five": [
        "The hand of @1 twitches at the wrist, short of a palm that isn't there.",
        "A soft, phantom clap echoes where @1np palm would have landed.",
        "@1np spectral fingers spread in anticipation, then scatter like smoke.",
        "The corpse of @1 cannot lift a hand to meet another.",
    ],
    "fistbump": [
        "@1np skeletal hand tries to ball into a fist, then gives up on the motion.",
        "A cold knuckle-knock reverberates through the bones of @1 and fades.",
        "The corpse of @1 offers a fist to nobody in particular.",
        "@1np stilled hand remembers the weight of another's, long after the gesture.",
    ],
    # ---- V2 self-directed corpses ---------------------------------
    "pose": [
        "The body of @1 remains locked in a final, inadvertent pose.",
        "A breeze tugs at @1np hair, nudging the corpse into an unintentional tableau.",
        "@1np stiffened limbs already hold a pose of sorts, frozen mid-thought.",
        "The corpse of @1 strikes no new poses, but the old one does plenty of work.",
    ],
    "cheer": [
        "A thin, reedy whistle escapes the corpse of @1 and fades into silence.",
        "The ghost of @1 whoops soundlessly, mouth wide in the empty air.",
        "Something like a phantom fist-pump flickers above @1np body and is gone.",
        "The shade of @1 raises a soundless cheer nobody else can hear.",
    ],
    "cry": [
        "A single bead of moisture trails down @1np motionless cheek.",
        "The corpse of @1 has wept all the tears it can, and then some.",
        "A low, mournful hum ripples through the bones of @1.",
        "@1np shade weeps quietly in a language the living can't quite catch.",
    ],
    "wave": [
        "@1np lifeless hand stirs once in a breeze that isn't there, then stills.",
        "The shade of @1 lifts a translucent palm in a slow, unanswered hello.",
        "A fingertip of @1np corpse twitches — almost a wave, not quite.",
        "The remains of @1 greet nobody in particular.",
    ],
    "bow": [
        "The corpse of @1 is already taking the longest bow of all.",
        "@1np head droops a little further in a last, inadvertent courtesy.",
        "The shade of @1 inclines itself in a silent, formal farewell.",
        "A slow, gravity-assisted bow settles through @1np stilled frame.",
    ],
    # ---- V2 interactive corpses -----------------------------------
    "salute": [
        "@1np stiffened hand is already at an eternal, rigid salute.",
        "The shade of @1 snaps off a clean, ghostly salute and dissolves.",
        "A cold wind lifts @1np sleeve in a slow, soldierly farewell.",
        "The corpse of @1 holds a silent honor-guard for nobody at all.",
    ],
    "comfort": [
        "A hush gathers near @1np body, as if the corpse is doing the comforting.",
        "The shade of @1 reaches to console, but @1np hand finds no shoulder.",
        "A gentle warmth drifts off the corpse of @1 and dissipates unclaimed.",
        "Something tender lingers over @1np remains, unused.",
    ],
    "poke": [
        "@1np finger twitches once in the dust, poking the void.",
        "The shade of @1 jabs mischievously at empty air.",
        "The corpse of @1 has no one to annoy, and settles for annoying the flies.",
        "A ghostly finger prods out from @1np body and vanishes.",
    ],
    "nod": [
        "@1np head bows a fraction further — the slowest nod on record.",
        "The shade of @1 tilts a weary acknowledgement at the void.",
        "A silent, solemn nod ripples through the remains of @1.",
        "The corpse of @1 inclines its head as if quietly agreeing with the dirt.",
    ],
    "glare": [
        "The empty eyes of @1np corpse still manage to look unimpressed.",
        "A cold, lingering stare settles over the remains of @1.",
        "@1np shade narrows its spectral gaze at nothing in particular.",
        "Even dead, @1 manages a look that could curdle milk.",
    ],
    "shank": [
        "@1np stiffened fingers curl uselessly around a knife that isn't there.",
        "The shade of @1 mimes a playful stab and laughs in a voice full of dust.",
        "A phantom blade flickers over @1np body and fades, unused.",
        "The corpse of @1 has no friends left to mock-stab.",
    ],
    "tickle": [
        "A mischievous shiver ripples through @1np body and stills.",
        "The shade of @1 wiggles ghostly fingers at empty air.",
        "@1np corpse is beyond being tickled, and beyond tickling.",
        "A ghostly, ticklish giggle echoes briefly above the body of @1.",
    ],
    "taunt": [
        "A dry, mocking laugh escapes the corpse of @1 and fades.",
        "The shade of @1 blows a raspberry that nobody is around to be offended by.",
        "@1np cold lips curl in a last, defiant jeer.",
        "The bones of @1 clack together in a rhythm that sounds suspiciously like mockery.",
    ],
    "wink": [
        "@1np stiffened eyelid sags into an accidental, lopsided wink.",
        "The shade of @1 flickers one eye at the void and grins.",
        "A single closed lid on @1np corpse twitches meaningfully at no one.",
        "The ghost of @1 throws a wink across the veil, and the veil declines to wink back.",
    ],
}

_DEAD_TARGET_FLAVOR: Dict[str, List[str]] = {
    "high_five": [
        "@1 raises a palm toward @2, but the corpse cannot answer.",
        "@1np hand hangs in the air; @2np body is beyond returning the gesture.",
    ],
    "fistbump": [
        "@1 offers a fist toward @2, but the corpse cannot meet it.",
        "@1np knuckles hover above @2np still hand, a gesture without a partner.",
    ],
    # ---- V2 warmth-aware commands ---------------------------------
    # Each line reads as invoker-does-something-toward-a-corpse. @1 is
    # the living actor; @2 is the dead target. Keep the imagery
    # verb-appropriate so the gesture is recognizable even in the
    # unreachable branch.
    "salute": [
        "@1 snaps off a crisp salute toward the body of @2, holding it a long beat.",
        "@1 straightens and offers @2np corpse a soldier's farewell.",
        "@1 raises a silent hand to @2np brow; the honor goes unreturned.",
    ],
    "comfort": [
        "@1 kneels beside @2np body and rests a hand where a shoulder used to answer.",
        "@1 murmurs something gentle to the corpse of @2 — in case some part of @2o still hears.",
        "@1 smooths a fold of cloth over @2np stillness, comforting a body beyond comfort.",
    ],
    "poke": [
        "@1 prods @2np corpse once, gently, as if checking. It stays as it was.",
        "@1 pokes the body of @2 with a tentative finger; nothing pokes back.",
        "@1 nudges @2np stilled shoulder, then thinks better of it.",
    ],
    "nod": [
        "@1 inclines @1a head once toward the body of @2, a silent farewell.",
        "@1 offers the corpse of @2 a slow, respectful nod.",
        "@1 nods at @2np stillness the way one acknowledges a closed door.",
    ],
    "glare": [
        "@1 fixes the corpse of @2 with a withering look; it absorbs none of it.",
        "@1 levels a glare at @2np body. Dead eyes do not flinch.",
        "@1 glares at the remains of @2, which are conspicuously unbothered.",
    ],
    "shank": [
        "@1 mimes a mock-stab at @2np body and abruptly feels weird about it.",
        "@1 raises a joke-blade toward the corpse of @2, then lowers it — the joke's dead too.",
        "@1 dangles a phantom knife over @2np stillness, but nobody's laughing.",
    ],
    "tickle": [
        "@1 flutters @1a fingers over @2np ribs. The corpse is unamused.",
        "@1 tries a tickling gesture at the body of @2; stillness does not giggle.",
        "@1 waggles mischievous fingers over @2np corpse and sobers instantly.",
    ],
    "taunt": [
        "@1 flings a taunt at the body of @2. The silence is crushing.",
        "@1 jeers at @2np corpse, which refuses to take the bait.",
        "@1 hurls a mocking line at @2np remains; the dead keep the better comeback.",
    ],
    "wink": [
        "@1 winks at the body of @2 — a small, private goodbye.",
        "@1 lowers one eyelid toward @2np corpse, a last secret between them.",
        "@1 throws a quiet wink at @2np stillness; the dead keep their counsel.",
    ],
}


# ---------------------------------------------------------------------------
# Hug narration pools
# ---------------------------------------------------------------------------
#
# Two-phase rendering: ``<intent-beat> ; <acceptance-beat>``. The
# intent beat is what actor @1 was *going for*; the acceptance beat
# is what target @2 actually does. The two are composed independently
# so a warm-intent attempt can still crash into a cold-acceptance
# rebuff (always rejection, regardless of how the actor tried).
#
# Narration shape:
# - Intent beats must end in punctuation and read as a single clause.
# - Acceptance beats start lowercase (rendered after a semicolon + space)
#   and must stand alone syntactically — no dangling pronoun references
#   to words in the intent beat, since the composer joins them verbatim.
# - Tokens: ``@1`` = actor, ``@2`` = target. Keep ``@2`` as the subject
#   of acceptance beats so the target's preference reads cleanly.
#
# cold-acceptance ALWAYS rejects the hug, regardless of actor intent.
# That's the target-wins-asymmetry invariant. Five cold-acceptance
# lines pinned in tests.


_HUG_INTENT_BEATS: Dict[str, List[str]] = {
    warmth.Warmth.COLD: [
        "@1 stiffens up and steels @1r for a perfunctory embrace.",
        "@1 makes a clipped, obligatory motion toward @2.",
        "@1 squares up to @2 with an all-business hug-posture.",
        "@1 extends a dutiful arm in @2np general direction.",
    ],
    warmth.Warmth.COOL: [
        "@1 sidles up to @2 with a reserved half-smile.",
        "@1 offers @2 a cautious, tentative approach.",
        "@1 lifts an arm toward @2, hesitation in @1a elbows.",
        "@1 measures out a polite arm's length toward @2.",
    ],
    warmth.Warmth.NEUTRAL: [
        "@1 steps forward and opens @1a arms toward @2.",
        "@1 reaches for @2 with a companionable gesture.",
        "@1 moves in for an ordinary, unremarkable hug with @2.",
        "@1 extends @1a arms toward @2.",
    ],
    warmth.Warmth.WARM: [
        "@1 opens @1a arms warmly toward @2.",
        "@1 approaches @2 with open arms and a soft smile.",
        "@1 moves in to wrap @2 up in a fond embrace.",
        "@1 gathers @2 up with a bright, affectionate grin.",
    ],
    warmth.Warmth.HOT: [
        "@1 sweeps toward @2 with arms wide, beaming like the sun came out.",
        "@1 practically launches @1r at @2, eyes bright with ardor.",
        "@1 crosses the gap to @2 in two eager strides, arms flung wide.",
        "@1 lunges in to pull @2 into a sweeping, all-in embrace.",
    ],
}


_HUG_ACCEPTANCE_BEATS: Dict[str, List[str]] = {
    # cold = REJECTION. Never lands the hug. The hug cold-acceptance
    # pool is the primary load-bearing pool for the asymmetry
    # invariant — keep each line unambiguous about non-consent.
    warmth.Warmth.COLD: [
        "@2 glances at @1 and sidesteps @1a hug entirely.",
        "@2 raises an inquisitive brow and pointedly steps out of reach.",
        "@2 holds up a single, firm palm — no.",
        "@2 leans out of range with a flat, unimpressed look.",
        "@2 turns a shoulder and the hug finds only air.",
    ],
    warmth.Warmth.COOL: [
        "@2 accepts the contact for exactly one beat, then pats @1 off.",
        "@2 permits a stiff, brief sideways embrace and steps back.",
        "@2 allows a single polite squeeze before disentangling.",
        "@2 tolerates the hug with a guarded half-smile.",
    ],
    warmth.Warmth.NEUTRAL: [
        "@2 returns the embrace companionably, neither eager nor reluctant.",
        "@2 leans into it for a moment, then steps back.",
        "@2 hugs back briefly and unremarkably.",
        "@2 returns the gesture in kind.",
    ],
    warmth.Warmth.WARM: [
        "@2 folds into the hug with a warm, fond sigh.",
        "@2 returns the embrace with a soft laugh and a squeeze.",
        "@2 melts into @1 gratefully for a long moment.",
        "@2 hugs @1 back warmly and holds on a beat longer.",
    ],
    warmth.Warmth.HOT: [
        "@2 pulls @1 into a full-body hug with a delighted laugh.",
        "@2 lifts @1 off the ground with a whoop of ardent delight.",
        "@2 crushes @1 into an exuberant, all-consuming embrace.",
        "@2 pulls @1 in fiercely, grinning ear to ear, and refuses to let go.",
    ],
}


# ---------------------------------------------------------------------------
# High-five narration pools
# ---------------------------------------------------------------------------


_HIGH_FIVE_INTENT_BEATS: Dict[str, List[str]] = {
    warmth.Warmth.COLD: [
        "@1 offers a flat, reluctant palm in @2np direction.",
        "@1 raises a hand toward @2 with all the enthusiasm of a timecard.",
        "@1 stiffly elevates a palm for @2.",
    ],
    warmth.Warmth.COOL: [
        "@1 lifts a tentative palm toward @2.",
        "@1 offers @2 a low, understated high five.",
        "@1 raises a hand for @2, reservation in the wrist.",
    ],
    warmth.Warmth.NEUTRAL: [
        "@1 raises a palm toward @2.",
        "@1 lifts an expectant hand for @2.",
        "@1 presents a ready palm to @2.",
    ],
    warmth.Warmth.WARM: [
        "@1 throws up an eager palm for @2 with a grin.",
        "@1 holds up a warm, inviting hand for @2.",
        "@1 raises a bright, open palm for @2.",
    ],
    warmth.Warmth.HOT: [
        "@1 hurls a whole arm skyward, palm blazing for @2.",
        "@1 rears back and WINDS UP a colossal high five for @2.",
        "@1 vaults a triumphant palm into the air for @2.",
    ],
}


_HIGH_FIVE_ACCEPTANCE_BEATS: Dict[str, List[str]] = {
    warmth.Warmth.COLD: [
        "@2 stares at the hand until it lowers, unmet.",
        "@2 pointedly does not raise a palm in return.",
        "@2 shakes @2a head once and the hand hangs alone.",
        "@2 looks past the outstretched hand like it isn't there.",
    ],
    warmth.Warmth.COOL: [
        "@2 taps @1np palm with two reserved fingers.",
        "@2 grants the barest brush of palms — contact, but no commitment.",
        "@2 meets @1np hand with an economical, dry tap.",
    ],
    warmth.Warmth.NEUTRAL: [
        "@2 meets @1np palm in a clean, unremarkable smack.",
        "@2 slaps a serviceable high five into @1np waiting hand.",
        "@2 returns the high five at a perfectly ordinary volume.",
    ],
    warmth.Warmth.WARM: [
        "@2 connects with a crisp, companionable smack and a grin.",
        "@2 slaps @1np palm gladly, a warm laugh escaping.",
        "@2 meets @1np hand with a hearty clap and a fond nod.",
    ],
    warmth.Warmth.HOT: [
        "@2 meets the hand with a thunderous SMACK — the whole room turns.",
        "@2 jumps to meet the hand, palms colliding in a thunderclap.",
        "@2 nails the high five so hard @2a palm stings, grinning wildly.",
    ],
}


# ---------------------------------------------------------------------------
# Fistbump narration pools
# ---------------------------------------------------------------------------


_FISTBUMP_INTENT_BEATS: Dict[str, List[str]] = {
    warmth.Warmth.COLD: [
        "@1 offers a terse, closed fist in @2np direction.",
        "@1 extends a minimalist fist toward @2.",
        "@1 presents @2 with a fist held at chest height and no warmth.",
    ],
    warmth.Warmth.COOL: [
        "@1 offers @2 a reserved, low-held fist.",
        "@1 lifts a tentative fist toward @2.",
        "@1 extends a cautious knuckle toward @2.",
    ],
    warmth.Warmth.NEUTRAL: [
        "@1 raises a fist toward @2.",
        "@1 proffers @2 an ordinary knuckle.",
        "@1 holds out a ready fist for @2.",
    ],
    warmth.Warmth.WARM: [
        "@1 holds out a warm, open-hearted fist for @2.",
        "@1 offers @2 a fond, nodding fistbump.",
        "@1 extends a companionable fist toward @2 with a smile.",
    ],
    warmth.Warmth.HOT: [
        "@1 winds back and SHOOTS a fist toward @2, eyes alight.",
        "@1 slams a fist forward for @2 with a triumphant bark.",
        "@1 launches a knuckle into orbit toward @2.",
    ],
}


_FISTBUMP_ACCEPTANCE_BEATS: Dict[str, List[str]] = {
    warmth.Warmth.COLD: [
        "@2 looks at the fist, then at @1, and leaves the hand unmet.",
        "@2 declines to raise @2a own, and the fist dangles awkwardly.",
        "@2 shakes @2a head and tucks @2a hands away.",
        "@2 pointedly pockets @2a hands.",
    ],
    warmth.Warmth.COOL: [
        "@2 taps knuckles against @1 with a clipped nod.",
        "@2 grants the barest brush of fists — acknowledgement without warmth.",
        "@2 returns the bump in a short, economical tap.",
    ],
    warmth.Warmth.NEUTRAL: [
        "@2 meets the fist with a solid, unremarkable knock.",
        "@2 returns a clean, workmanlike fistbump.",
        "@2 bumps @1np knuckles in kind.",
    ],
    warmth.Warmth.WARM: [
        "@2 meets @1np fist with a warm knock and a grin.",
        "@2 returns the bump eagerly, knuckles hanging on a beat longer.",
        "@2 clashes knuckles with @1 and beams.",
    ],
    warmth.Warmth.HOT: [
        "@2 detonates the fistbump with an exaggerated explosion-spread on the follow-through.",
        "@2 meets the fist like a meteor, knuckles cracking, a whoop on the exhale.",
        "@2 slams knuckles against @1 with a resounding BOOM and a splayed-finger follow-through.",
    ],
}


# ---------------------------------------------------------------------------
# V2: Interactive warmth-aware narration pools
# ---------------------------------------------------------------------------
#
# Same two-phase shape as hug/high_five/fistbump. Every pool has five
# Warmth levels with 3-5 variants each. Cold-acceptance ALWAYS reads
# as rejection, enforced both by convention and by
# ``test_cold_acceptance_reads_as_rejection`` in test_social_v2.py.
#
# Verb-themed specificity is load-bearing: every command has its own
# physical vocabulary (salute = chivalric/military; comfort = tender
# contact; poke = finger-jab; nod = tilt-of-head; glare = gaze; shank
# = mock-blade; tickle = fingertip-flutter; taunt = jeer; wink = eye).
# Lines should never feel generic enough to slot between commands.


# ---- $salute ---------------------------------------------------------

_SALUTE_INTENT_BEATS: Dict[str, List[str]] = {
    warmth.Warmth.COLD: [
        "@1 snaps off a perfunctory, minimum-regulation salute toward @2.",
        "@1 offers @2 the stiff, three-fingered kind of salute that satisfies protocol and nothing else.",
        "@1 brings an unenthusiastic hand to @1a brow in @2np direction.",
    ],
    warmth.Warmth.COOL: [
        "@1 inclines @1a head and offers @2 a measured salute.",
        "@1 touches two fingers to @1a temple in reserved acknowledgement of @2.",
        "@1 raises a crisp, unshowy salute toward @2.",
    ],
    warmth.Warmth.NEUTRAL: [
        "@1 brings a steady hand to @1a brow and salutes @2.",
        "@1 squares @1a shoulders and offers @2 a clean salute.",
        "@1 raises @1a palm in textbook-perfect salute to @2.",
    ],
    warmth.Warmth.WARM: [
        "@1 salutes @2 with a slow, deliberate grace that says respect earned.",
        "@1 offers @2 a warm salute, the faintest smile at the corner of @1a mouth.",
        "@1 raises a hand to @1a brow for @2 and holds it, a beat longer than duty requires.",
    ],
    warmth.Warmth.HOT: [
        "@1 SNAPS to attention for @2 and brings up the sharpest parade-ground salute in living memory.",
        "@1 hurls @1r into the most thunderous, honor-guard salute @1s can muster for @2.",
        "@1 cracks off a resounding salute for @2 with the whole regiment in @1a spine.",
    ],
}

_SALUTE_ACCEPTANCE_BEATS: Dict[str, List[str]] = {
    warmth.Warmth.COLD: [
        "@2 does not return the salute; @2a eyes stay level and unmoving.",
        "@2 lets the gesture hang, unacknowledged.",
        "@2 flicks a disinterested glance at @1np raised hand and looks away.",
        "@2 refuses the courtesy with a single, pointed shake of @2a head.",
    ],
    warmth.Warmth.COOL: [
        "@2 returns the salute with a crisp, economical nod.",
        "@2 offers a shallow answering salute and drops @2a hand quickly.",
        "@2 acknowledges @1np gesture with a brief, formal tip of @2a chin.",
    ],
    warmth.Warmth.NEUTRAL: [
        "@2 returns the salute with textbook precision.",
        "@2 brings a steady hand to @2a brow in answering salute.",
        "@2 mirrors @1np salute, neither rushed nor reluctant.",
    ],
    warmth.Warmth.WARM: [
        "@2 returns the salute with a small, genuine smile.",
        "@2 meets @1np salute squarely, @2a hand lingering at @2a brow a moment longer.",
        "@2 salutes @1 back with the kind of pride that takes years to earn.",
    ],
    warmth.Warmth.HOT: [
        "@2 SNAPS the salute back, every inch of @2o alight with answering honor.",
        "@2 brings up a thunderous return-salute, chin high, eyes blazing.",
        "@2 cracks off a parade-ground reply, beaming like @1 just pinned a medal on @2o.",
    ],
}


# ---- $comfort --------------------------------------------------------

_COMFORT_INTENT_BEATS: Dict[str, List[str]] = {
    warmth.Warmth.COLD: [
        "@1 pats @2 twice on the shoulder in an extremely please-be-fine manner.",
        "@1 offers @2 a brisk there-there with all the tenderness of a timecard.",
        "@1 produces a tight-lipped \"it'll pass\" for @2, eyes elsewhere.",
    ],
    warmth.Warmth.COOL: [
        "@1 rests a careful hand on @2np shoulder and searches for something to say.",
        "@1 offers @2 a reserved, measured word of comfort.",
        "@1 sets a tentative palm on @2np arm.",
    ],
    warmth.Warmth.NEUTRAL: [
        "@1 settles a steady hand on @2np shoulder.",
        "@1 offers @2 a quiet \"I'm here.\"",
        "@1 moves to @2np side and stays there.",
    ],
    warmth.Warmth.WARM: [
        "@1 rests a steady hand on @2np shoulder, eyes warm and voice low.",
        "@1 squeezes @2np shoulder warmly and meets @2np eyes.",
        "@1 opens @1a arms for @2 in a warm, open invitation.",
    ],
    warmth.Warmth.HOT: [
        "@1 opens @1a arms wide for @2, fierce and sure, heart on @1a sleeve.",
        "@1 steps close and finds @2np shoulder with a firm, steadying hand, voice low: \"I've got you if you want me to.\"",
        "@1 extends both hands to @2 with fierce tenderness, holding the space open.",
    ],
}

_COMFORT_ACCEPTANCE_BEATS: Dict[str, List[str]] = {
    warmth.Warmth.COLD: [
        "@2 stiffens under the touch and steps out from under @1np hand.",
        "@2 lifts a palm — don't — and turns a shoulder away.",
        "@2 shakes @2a head once and declines the tenderness outright.",
        "@2 levels a flat look at @1 and withdraws from reach.",
    ],
    warmth.Warmth.COOL: [
        "@2 allows the contact for a beat, then eases back with a brief nod of thanks.",
        "@2 tolerates @1np hand for a moment before gently lifting it away.",
        "@2 lets out a small, polite breath and composes @2r.",
    ],
    warmth.Warmth.NEUTRAL: [
        "@2 leans a little into @1np hand and gathers @2r.",
        "@2 accepts the quiet company with a grateful exhale.",
        "@2 nods once and lets the contact settle.",
    ],
    warmth.Warmth.WARM: [
        "@2 sinks into the comfort with a long, shaky sigh.",
        "@2 leans @2a forehead briefly against @1np shoulder and breathes.",
        "@2 closes @2a eyes and rests where @1 is.",
    ],
    warmth.Warmth.HOT: [
        "@2 collapses into @1 entirely, clinging with both hands, and lets the whole thing out.",
        "@2 folds into @1 with a grateful sob and does not let go for a long while.",
        "@2 holds on to @1 as if @1s is the only solid thing in the world right now.",
    ],
}


# ---- $poke -----------------------------------------------------------

_POKE_INTENT_BEATS: Dict[str, List[str]] = {
    warmth.Warmth.COLD: [
        "@1 jabs @2 sharply in the ribs with one unfriendly finger.",
        "@1 stabs a pointed fingertip into @2np shoulder.",
        "@1 prods @2 with the kind of poke that is basically a shove.",
    ],
    warmth.Warmth.COOL: [
        "@1 pokes @2 once in the arm with a reserved, experimental finger.",
        "@1 gives @2 a small, understated prod.",
        "@1 nudges @2 with the tip of one cautious finger.",
    ],
    warmth.Warmth.NEUTRAL: [
        "@1 pokes @2 in the shoulder.",
        "@1 reaches over and gives @2 a companionable prod.",
        "@1 boops @2 lightly on the arm.",
    ],
    warmth.Warmth.WARM: [
        "@1 pokes @2 playfully in the side, grinning.",
        "@1 delivers a cheerful, teasing poke to @2np ribs.",
        "@1 jabs @2 fondly in the shoulder with a small, warm laugh.",
    ],
    warmth.Warmth.HOT: [
        "@1 goes on a full-on POKE rampage at @2 — ribs, shoulder, cheek, everywhere.",
        "@1 delivers a gleeful flurry of pokes to @2, cackling the entire time.",
        "@1 pokes @2 with the absolute unbridled joy of a cat discovering a new cucumber.",
    ],
}

_POKE_ACCEPTANCE_BEATS: Dict[str, List[str]] = {
    warmth.Warmth.COLD: [
        "@2 swats @1np hand away sharply.",
        "@2 catches @1np finger mid-poke and drops it like garbage.",
        "@2 glares at @1 until the poking stops, which takes about half a second.",
        "@2 steps well out of poking range with a flat, unamused look.",
    ],
    warmth.Warmth.COOL: [
        "@2 tolerates the poke with a small, long-suffering sigh.",
        "@2 accepts the single poke but gives @1 a look that says \"once.\"",
        "@2 brushes @1np finger off with a mild, patient shake of @2a head.",
    ],
    warmth.Warmth.NEUTRAL: [
        "@2 lets the poke happen without comment.",
        "@2 blinks once at the contact and carries on.",
        "@2 absorbs the poke and returns an unperturbed glance.",
    ],
    warmth.Warmth.WARM: [
        "@2 grins and pokes @1 right back.",
        "@2 bats @1np hand away playfully, laughing.",
        "@2 giggles and retaliates with a poke of @2a own.",
    ],
    warmth.Warmth.HOT: [
        "@2 ESCALATES immediately, tackling @1 into a shrieking, full-contact poke war.",
        "@2 returns fire with a two-handed tickling-poke barrage, cackling.",
        "@2 shouts \"OH, IT'S ON\" and launches a full-body poke offensive against @1.",
    ],
}


# ---- $nod ------------------------------------------------------------

_NOD_INTENT_BEATS: Dict[str, List[str]] = {
    warmth.Warmth.COLD: [
        "@1 gives @2 a single, barely-perceptible nod.",
        "@1 jerks @1a chin a fraction in @2np direction.",
        "@1 offers @2 the smallest acknowledgement a neck can produce.",
    ],
    warmth.Warmth.COOL: [
        "@1 nods once at @2, reserved but civil.",
        "@1 tips @1a head toward @2 in measured greeting.",
        "@1 offers @2 a short, unshowy nod.",
    ],
    warmth.Warmth.NEUTRAL: [
        "@1 nods to @2.",
        "@1 inclines @1a head in @2np direction.",
        "@1 gives @2 a clean, unremarkable nod.",
    ],
    warmth.Warmth.WARM: [
        "@1 nods to @2 with a soft smile of recognition.",
        "@1 offers @2 a warm, fond nod.",
        "@1 dips @1a head to @2 with obvious affection.",
    ],
    warmth.Warmth.HOT: [
        "@1 nods so emphatically at @2 that @1s almost bows along with it.",
        "@1 greets @2 with a thunderous whole-body nod of recognition.",
        "@1 gives @2 the kind of nod that is basically a reunion.",
    ],
}

_NOD_ACCEPTANCE_BEATS: Dict[str, List[str]] = {
    warmth.Warmth.COLD: [
        "@2 looks straight past @1 as if no nod had been offered.",
        "@2 fails to nod back; the greeting dies on the air.",
        "@2 meets @1np eyes, holds the look, and deliberately does not reciprocate.",
        "@2 turns @2a head away before the nod can complete.",
    ],
    warmth.Warmth.COOL: [
        "@2 returns a small, polite nod and looks back to whatever @2 was doing.",
        "@2 acknowledges the gesture with a reserved dip of @2a chin.",
        "@2 offers a tight, civil nod in reply.",
    ],
    warmth.Warmth.NEUTRAL: [
        "@2 nods back in kind.",
        "@2 returns a clean, unremarkable nod.",
        "@2 inclines @2a head in matching acknowledgement.",
    ],
    warmth.Warmth.WARM: [
        "@2 nods back warmly, a real smile finding @2a mouth.",
        "@2 returns the nod with fond eyes and a quiet hello.",
        "@2 dips @2a head in answer and holds @1np gaze for a beat.",
    ],
    warmth.Warmth.HOT: [
        "@2 nods back so vigorously that @2a hair bounces, grinning ear to ear.",
        "@2 returns the nod with a delighted whoop of recognition.",
        "@2 slams a nod back so hard it doubles as a greeting and an agreement.",
    ],
}


# ---- $glare ----------------------------------------------------------

_GLARE_INTENT_BEATS: Dict[str, List[str]] = {
    warmth.Warmth.COLD: [
        "@1 fixes @2 with a cold, flat stare.",
        "@1 levels a stony, unblinking glare at @2.",
        "@1 narrows @1a eyes at @2 with visible contempt.",
    ],
    warmth.Warmth.COOL: [
        "@1 gives @2 a short, pointed glare and looks away.",
        "@1 shoots @2 a disapproving look from under @1a brows.",
        "@1 levels a brief, unfriendly stare at @2.",
    ],
    warmth.Warmth.NEUTRAL: [
        "@1 glares at @2.",
        "@1 aims a steady, unwavering stare at @2.",
        "@1 locks eyes with @2 in deliberate hostility.",
    ],
    warmth.Warmth.WARM: [
        "@1 mock-glares at @2, the corner of @1a mouth twitching.",
        "@1 levels a theatrical, affectionate glare at @2.",
        "@1 narrows @1a eyes at @2 in playful accusation.",
    ],
    warmth.Warmth.HOT: [
        # Register note: WARM glare reads as affectionate mock-hostility
        # ("theatrical, affectionate", "playful accusation"), HOT
        # escalates the *theatrics*, not the actual venom — the
        # HOT acceptance pool is a mutual stare-off / playful
        # escalation, so HOT intent stays inside the mock register.
        "@1 unleashes the most theatrical stink-eye in living memory at @2.",
        "@1 deploys a full operatic mock-glare at @2, eyebrows arched to the heavens.",
        "@1 summons a glare of such EPIC proportion for @2 that the corners of @1a mouth keep threatening to betray @1o.",
    ],
}

_GLARE_ACCEPTANCE_BEATS: Dict[str, List[str]] = {
    warmth.Warmth.COLD: [
        "@2 looks right through @1 as if the glare isn't worth registering.",
        "@2 turns @2a back on @1 and ignores the stare completely.",
        "@2 yawns pointedly in @1np direction and walks on.",
        "@2 declines to play; the glare finds no purchase.",
    ],
    warmth.Warmth.COOL: [
        "@2 meets @1np glare briefly and then looks away, unimpressed.",
        "@2 returns a bored, flat look and carries on.",
        "@2 endures the stare with the patience of someone who's seen worse.",
    ],
    warmth.Warmth.NEUTRAL: [
        "@2 holds @1np gaze evenly, meeting the glare without flinching.",
        "@2 stares back, unmoved.",
        "@2 meets the glare steadily and waits it out.",
    ],
    warmth.Warmth.WARM: [
        "@2 glares right back with a grin tugging at @2a mouth.",
        "@2 narrows @2a eyes in answering challenge, barely hiding a laugh.",
        "@2 returns the look with a mock-wounded \"excuse me?\"",
    ],
    warmth.Warmth.HOT: [
        "@2 locks eyes with @1 and the air between them crackles into a full-on stare-off.",
        "@2 meets the glare with @2a own, ten times as intense, and the room gets quieter.",
        "@2 escalates the stare until both of them are squinting and nobody's breathing.",
    ],
}


# ---- $shank ----------------------------------------------------------

_SHANK_INTENT_BEATS: Dict[str, List[str]] = {
    warmth.Warmth.COLD: [
        "@1 mimes a joyless, workmanlike stab in @2np direction.",
        "@1 offers @2 the most obligatory mock-shank in recent memory.",
        "@1 gestures a flat, uninvested fake-stab at @2.",
    ],
    warmth.Warmth.COOL: [
        "@1 feints a cautious pretend-stab at @2np ribs.",
        "@1 pokes @2 with an imaginary dagger, expression reserved.",
        "@1 gives @2 a restrained, knee-height mock-shank.",
    ],
    warmth.Warmth.NEUTRAL: [
        "@1 mimes a quick shank at @2np side.",
        "@1 jabs an invisible knife in @2np direction.",
        "@1 performs a perfectly adequate mock-shanking motion at @2.",
    ],
    warmth.Warmth.WARM: [
        "@1 mock-shanks @2 with a fond grin and an \"et tu\" eyebrow.",
        "@1 delivers a theatrical friendly-stab toward @2np shoulder, beaming.",
        "@1 waggles a pretend blade at @2 with affectionate menace.",
    ],
    warmth.Warmth.HOT: [
        "@1 launches a full-bard-opera mock-assassination at @2, imaginary dagger flashing.",
        "@1 unleashes a flurry of absurdly dramatic fake-stabs at @2, cackling.",
        "@1 rears up with both hands around a ghost-dagger and PLUNGES at @2 with a war-cry.",
    ],
}

_SHANK_ACCEPTANCE_BEATS: Dict[str, List[str]] = {
    warmth.Warmth.COLD: [
        "@2 does not find this funny, and tells @1 so without saying a word.",
        "@2 steps out of reach and fixes @1 with a look that kills the bit.",
        "@2 swats the invisible knife aside and shakes @2a head firmly.",
        "@2 declines to play murder-tag, thanks.",
    ],
    warmth.Warmth.COOL: [
        "@2 sidesteps the mock-blade and allows @1 exactly one pity-smirk.",
        "@2 parries the fake-stab with a resigned flick of @2a wrist.",
        "@2 tolerates the bit with a tight, unamused smile.",
    ],
    warmth.Warmth.NEUTRAL: [
        "@2 clutches @2a ribs and staggers theatrically, for the form of the thing.",
        "@2 fakes a grunt of pain and pretends to bleed out for a polite second.",
        "@2 plays along, gasping once for effect.",
    ],
    warmth.Warmth.WARM: [
        "@2 cries \"et tu!\" and slumps melodramatically against @1.",
        "@2 howls in mock-agony, grinning, and pretends to expire at @1np feet.",
        "@2 clutches a pretend wound and swoons with entirely too much commitment.",
    ],
    warmth.Warmth.HOT: [
        "@2 whips out a phantom dagger of @2a own and the two of them commit to a ten-minute mock-duel.",
        "@2 escalates the bit into a full Shakespearean death scene, monologue and all.",
        "@2 dies so hard @2 almost pulls a muscle, then dies again for an encore.",
    ],
}


# ---- $tickle ---------------------------------------------------------

_TICKLE_INTENT_BEATS: Dict[str, List[str]] = {
    warmth.Warmth.COLD: [
        "@1 makes a halfhearted wiggling-fingers motion at @2np ribs.",
        "@1 flutters a joyless, perfunctory tickle toward @2.",
        "@1 offers @2 the driest possible imitation of a tickle-attack.",
    ],
    warmth.Warmth.COOL: [
        "@1 wiggles experimental fingers near @2np side.",
        "@1 attempts a careful, low-commitment tickle on @2np arm.",
        "@1 dangles a reserved pair of tickling fingers above @2.",
    ],
    warmth.Warmth.NEUTRAL: [
        "@1 darts in with a quick tickle at @2np ribs.",
        "@1 goes for @2np sides with mischief in @1a fingers.",
        "@1 attacks @2 with a brisk, standard-issue tickle.",
    ],
    warmth.Warmth.WARM: [
        "@1 pounces on @2np ribs with a gleeful, mischievous laugh.",
        "@1 descends on @2 with wriggling fingers and an affectionate cackle.",
        "@1 pounces to tickle @2, grinning like a conspirator.",
    ],
    warmth.Warmth.HOT: [
        "@1 launches a FULL tickle-assault at @2 with both hands and a war-cry.",
        "@1 hurls @1r at @2 in a flailing tickle-storm of catastrophic proportions.",
        "@1 commits to the tickle like @1a very soul depends on it, fingers everywhere.",
    ],
}

_TICKLE_ACCEPTANCE_BEATS: Dict[str, List[str]] = {
    warmth.Warmth.COLD: [
        "@2 catches @1np wrist before the first tickle lands and firmly sets it aside.",
        "@2 steps clean out of range with a flat \"nope.\"",
        "@2 gives @1 a look that could ice a fireplace; the tickle dies in the air.",
        "@2 blocks @1np hands and shakes @2a head — absolutely not.",
    ],
    warmth.Warmth.COOL: [
        "@2 squirms briefly and then firmly extracts @2r from @1np reach.",
        "@2 endures exactly two seconds of tickling before calling a halt.",
        "@2 permits a single, brief tickle and steps back with a polite grimace.",
    ],
    warmth.Warmth.NEUTRAL: [
        "@2 jumps once, laughs despite @2r, and twists away.",
        "@2 yelps and bats @1np hands off, half-smiling.",
        "@2 flinches, giggles once, and escapes with dignity mostly intact.",
    ],
    warmth.Warmth.WARM: [
        "@2 dissolves into giggles and flails happily under @1np fingers.",
        "@2 shrieks with laughter and tries to tickle @1 right back.",
        "@2 collapses against @1 in a heap of helpless, delighted wheezing.",
    ],
    warmth.Warmth.HOT: [
        "@2 counter-attacks in an all-out tickle war, both of them wheezing, neither winning.",
        "@2 doubles over laughing, then tackles @1 into a screeching rolling tickle-brawl.",
        "@2 escalates immediately, and the two of them turn into an unholy hurricane of giggles.",
    ],
}


# ---- $taunt ----------------------------------------------------------

_TAUNT_INTENT_BEATS: Dict[str, List[str]] = {
    warmth.Warmth.COLD: [
        "@1 flicks a flat, dismissive insult at @2.",
        "@1 sneers something cutting in @2np direction.",
        "@1 offers @2 a clipped, unsmiling mockery.",
    ],
    warmth.Warmth.COOL: [
        "@1 lobs a dry, understated jab at @2.",
        "@1 needles @2 with a measured, pointed remark.",
        "@1 delivers @2 a small, well-aimed barb.",
    ],
    warmth.Warmth.NEUTRAL: [
        "@1 taunts @2 with a crooked grin.",
        "@1 jeers at @2, fists on @1a hips.",
        "@1 throws @2 a pointed bit of mockery.",
    ],
    warmth.Warmth.WARM: [
        "@1 ribs @2 with an affectionate, bantering jab.",
        "@1 teases @2 with a grin that says @1s means nothing by it.",
        "@1 lobs a fond, joking jibe in @2np direction.",
    ],
    warmth.Warmth.HOT: [
        "@1 hurls the MOST ELABORATE monologue of mockery @1s can assemble at @2.",
        "@1 climbs onto metaphorical furniture and delivers a ten-verse taunt-aria aimed squarely at @2.",
        "@1 unloads a bardic opus of jeering at @2 with full theatrical gestures.",
    ],
}

_TAUNT_ACCEPTANCE_BEATS: Dict[str, List[str]] = {
    warmth.Warmth.COLD: [
        "@2 does not take the bait; @2 looks at @1 the way one looks at a puddle.",
        "@2 walks away mid-taunt, visibly bored.",
        "@2 ignores the jab entirely, which stings more than any comeback could.",
        "@2 stares at @1 until @1s runs out of material.",
    ],
    warmth.Warmth.COOL: [
        "@2 returns a short, dry one-liner that lands with a small thud.",
        "@2 acknowledges the taunt with a flat \"mm\" and moves on.",
        "@2 arches a brow, offers a mild counter, and leaves it there.",
    ],
    warmth.Warmth.NEUTRAL: [
        "@2 fires a taunt right back, even-handed.",
        "@2 meets @1np jibe with one of @2a own.",
        "@2 returns a serviceable comeback and tips @2a chin.",
    ],
    warmth.Warmth.WARM: [
        "@2 laughs in spite of @2r and lobs a fond jab back.",
        "@2 grins, calls @1 something unflattering, and clearly doesn't mean it.",
        "@2 escalates the banter a notch with an affectionate insult.",
    ],
    warmth.Warmth.HOT: [
        "@2 returns fire with an even longer, more ridiculous monologue of answering mockery.",
        "@2 brings out the heavy artillery of trash-talk and proceeds to carpet-bomb @1 with it.",
        "@2 answers the taunt-aria with a full flyting, and neither of them breathes for a minute.",
    ],
}


# ---- $wink -----------------------------------------------------------

_WINK_INTENT_BEATS: Dict[str, List[str]] = {
    warmth.Warmth.COLD: [
        "@1 drops a flat, perfunctory wink at @2.",
        "@1 offers @2 the minimum amount of wink possible.",
        "@1 lowers one eyelid at @2 without much commitment.",
    ],
    warmth.Warmth.COOL: [
        "@1 gives @2 a small, understated wink.",
        "@1 flicks @2 a reserved, closed-mouth wink.",
        "@1 winks at @2, just once, unshowy.",
    ],
    warmth.Warmth.NEUTRAL: [
        "@1 winks at @2.",
        "@1 drops a clean, casual wink in @2np direction.",
        "@1 tosses @2 an easy, conspiratorial wink.",
    ],
    warmth.Warmth.WARM: [
        "@1 throws @2 a slow, fond wink, one corner of @1a mouth lifting.",
        "@1 winks at @2 with unmistakable affection.",
        "@1 lowers one eye at @2 and lets the smile reach @1a cheeks.",
    ],
    warmth.Warmth.HOT: [
        "@1 unleashes the most outrageous, finger-gun-enhanced wink @2 has ever been subjected to.",
        "@1 delivers @2 a wink with the full weight of @1a eyebrows behind it.",
        "@1 winks at @2 so hard the whole tavern should feel it.",
    ],
}

_WINK_ACCEPTANCE_BEATS: Dict[str, List[str]] = {
    warmth.Warmth.COLD: [
        "@2 does not return the wink; @2a face stays flat as stone.",
        "@2 looks straight through @1 as if both eyes had been closed.",
        "@2 declines the invitation with a slow, deliberate blink.",
        "@2 meets @1np wink with a glacial, unwavering stare.",
    ],
    warmth.Warmth.COOL: [
        "@2 returns a small, closed-lip smile and nothing more.",
        "@2 quirks an eyebrow at @1 and lets the wink pass unanswered.",
        "@2 acknowledges the wink with the barest twitch at the corner of @2a mouth.",
    ],
    warmth.Warmth.NEUTRAL: [
        "@2 winks back.",
        "@2 returns the wink in kind.",
        # Avoid "matches" / "mirrors" phrasing here — it reads as
        # "matched the actor's intensity", leaking register when the
        # actor's intent is warm/hot and the target's acceptance is
        # merely neutral. This variant reads as an independent
        # neutral return instead.
        "@2 answers with a simple wink of @2a own.",
    ],
    warmth.Warmth.WARM: [
        "@2 winks back warmly, @2a eyes crinkling at the corners.",
        "@2 returns the wink with a small, delighted grin.",
        "@2 flashes a wink of @2a own and holds @1np gaze a beat.",
    ],
    warmth.Warmth.HOT: [
        "@2 returns the wink with finger-guns, a hip-pop, and absolutely zero restraint.",
        "@2 fires back a wink so enormous @2a whole face gets involved.",
        "@2 escalates immediately — both eyes, exaggerated lean-in, full conspiratorial glee.",
    ],
}


# Bundles so lookups stay tidy. One entry per registered command.
_NARRATION_POOLS: Dict[str, Tuple[Dict[str, List[str]], Dict[str, List[str]]]] = {
    "hug":       (_HUG_INTENT_BEATS, _HUG_ACCEPTANCE_BEATS),
    "high_five": (_HIGH_FIVE_INTENT_BEATS, _HIGH_FIVE_ACCEPTANCE_BEATS),
    "fistbump":  (_FISTBUMP_INTENT_BEATS, _FISTBUMP_ACCEPTANCE_BEATS),
    "salute":    (_SALUTE_INTENT_BEATS, _SALUTE_ACCEPTANCE_BEATS),
    "comfort":   (_COMFORT_INTENT_BEATS, _COMFORT_ACCEPTANCE_BEATS),
    "poke":      (_POKE_INTENT_BEATS, _POKE_ACCEPTANCE_BEATS),
    "nod":       (_NOD_INTENT_BEATS, _NOD_ACCEPTANCE_BEATS),
    "glare":     (_GLARE_INTENT_BEATS, _GLARE_ACCEPTANCE_BEATS),
    "shank":     (_SHANK_INTENT_BEATS, _SHANK_ACCEPTANCE_BEATS),
    "tickle":    (_TICKLE_INTENT_BEATS, _TICKLE_ACCEPTANCE_BEATS),
    "taunt":     (_TAUNT_INTENT_BEATS, _TAUNT_ACCEPTANCE_BEATS),
    "wink":      (_WINK_INTENT_BEATS, _WINK_ACCEPTANCE_BEATS),
}


# ---------------------------------------------------------------------------
# V2: Self-directed narration pools
# ---------------------------------------------------------------------------
#
# Single-actor (``@1`` only). No target, no warmth, no composition.
# 6-10 variants per command. Each pool lives in
# ``_SELF_DIRECTED_POOLS`` keyed by command name so a new self-directed
# verb lands with just a new key + a command method wrapper.


_POSE_FLAVOR: List[str] = [
    "@1 strikes a dramatic hero pose, one foot on an imaginary rock.",
    "@1 throws @1r into a triumphant victory pose, fists on hips.",
    "@1 arranges @1r in an elegant, chin-tilted stance for nobody in particular.",
    "@1 settles into a brooding, cloak-flared pose that would look great in candlelight.",
    "@1 flexes with exaggerated bicep-display commitment.",
    "@1 drops to one knee and extends an arm skyward in a dramatic tableau.",
    "@1 plants @1r mid-stride like @1s just kicked down a castle door.",
    "@1 locks into a cool, arms-crossed silhouette and holds it for an unreasonable amount of time.",
]


_CHEER_FLAVOR: List[str] = [
    "@1 throws both fists in the air with a wordless, triumphant whoop.",
    "@1 lets out a cheer loud enough to startle pigeons three streets away.",
    "@1 shouts something exultant and unintelligible at the ceiling.",
    "@1 punches the air repeatedly, grinning like @1a team just won.",
    "@1 whoops and claps @1r on the shoulder in celebration.",
    "@1 pumps a fist and lets out an uninhibited \"YES.\"",
    "@1 hollers an approving whoop that makes @1a own ears ring.",
    "@1 bounces on @1a toes and whoops in sheer, uncut delight.",
]


_CRY_FLAVOR: List[str] = [
    "@1 presses the heels of @1a hands to @1a eyes and weeps quietly.",
    "@1 lets out a long, shuddering sob that nobody talks about afterward.",
    "@1 buries @1a face in @1a hands, shoulders shaking.",
    "@1 sniffles noisily and wipes @1a nose on the back of a sleeve.",
    "@1 bursts into tears without warning, to @1a own considerable surprise.",
    "@1 stands very still and lets the tears fall without bothering to wipe them away.",
    "@1 makes the smallest, most defeated sound imaginable.",
    "@1 cries the kind of silent, big-tears cry that is somehow the worst of all.",
]


_WAVE_FLAVOR: List[str] = [
    "@1 lifts a hand in a friendly, easy wave.",
    "@1 waves cheerfully at no one in particular.",
    "@1 raises a palm and waggles @1a fingers in casual greeting.",
    "@1 throws up an enthusiastic, whole-arm wave.",
    "@1 offers a small, shy little wave, barely above shoulder-height.",
    "@1 waves with the exaggerated, over-the-head enthusiasm of someone spotting a friend across a crowd.",
    "@1 flicks a breezy two-finger wave and grins.",
    "@1 gives a polite, queenly wave to the room.",
]


_BOW_FLAVOR: List[str] = [
    "@1 offers a crisp, formal bow from the waist.",
    "@1 bows deeply, one hand pressed to @1a heart.",
    "@1 dips into a courtly bow with an elaborate flourish of one hand.",
    "@1 inclines @1a head in a small, respectful bow.",
    "@1 bows so deeply @1s nearly pitches forward on @1a face.",
    "@1 sweeps into a theatrical stage-bow, complete with imaginary hat-flourish.",
    "@1 offers a brief, soldierly bow, heels clicking.",
    "@1 bows low and holds it a beat longer than strictly necessary.",
]


_SELF_DIRECTED_POOLS: Dict[str, List[str]] = {
    "pose":  _POSE_FLAVOR,
    "cheer": _CHEER_FLAVOR,
    "cry":   _CRY_FLAVOR,
    "wave":  _WAVE_FLAVOR,
    "bow":   _BOW_FLAVOR,
}


# Per-command self-target short-circuit lines. Warmth-to-self resolves
# coherently (the player's own preferences against themselves) but
# reads badly — "Alice opens her arms warmly toward Alice". Replace
# with a verb-themed single-actor line per command so the result at
# least sounds deliberate. Commands missing from this dict fall back
# to the generic "Alice is talking to herself" line at the bottom of
# ``_render_social``.
_SELF_TARGET_LINES: Dict[str, str] = {
    "hug":       "@1 wraps @1r in a quiet, self-directed embrace.",
    "high_five": "@1 tries to high-five @1r, which is harder than it sounds.",
    "fistbump":  "@1 bumps @1a own fists together with resigned dignity.",
    "salute":    "@1 salutes @1r in a passing mirror.",
    "comfort":   "@1 wraps @1a own arms around @1r and mutters something reassuring.",
    "poke":      "@1 pokes @1a own cheek experimentally. It pokes back.",
    "nod":       "@1 nods in solemn agreement with @1r.",
    "glare":     "@1 glares at @1r in the nearest reflective surface.",
    "shank":     "@1 mimes a playful stab at @1a own ribs and gasps theatrically.",
    "tickle":    "@1 tries to tickle @1r and discovers it doesn't work from the inside.",
    "taunt":     "@1 mutters a scathing insult directed squarely at @1r.",
    "wink":      "@1 winks at @1r in a passing windowpane.",
}


def _render_social(
    cmd: str,
    actor: Creature,
    target: Creature,
) -> str:
    """Resolve warmth and assemble the two-beat narration for
    ``cmd``. Intent beat is picked by the actor's intent level;
    acceptance beat by the target's acceptance level.

    Self-target is handled specially — warmth-to-self doesn't make
    sense, so the rendering short-circuits to a command-themed
    single-actor line.
    """
    if getattr(actor, "user_id", None) == getattr(target, "user_id", None):
        # Self-targeting short-circuit. The resolver would otherwise
        # pull the actor's own preferences against themselves, which
        # is coherent but boring — this line reads better than e.g.
        # "Alice opens her arms warmly toward Alice".
        line = _SELF_TARGET_LINES.get(
            cmd, "@1 gestures briefly at @1r and moves on."
        )
        return parse(line, actor)

    acceptance, intent = warmth.resolve(target, actor, cmd)
    intent_pool = _NARRATION_POOLS[cmd][0][intent]
    acceptance_pool = _NARRATION_POOLS[cmd][1][acceptance]

    intent_line = choice(intent_pool)
    acceptance_line = choice(acceptance_pool)

    # Join as a two-clause sentence. Semicolon keeps the attempt /
    # response rhythm distinct and the composed string parseable
    # through a single ``parse`` pass.
    return parse(f"{intent_line} {acceptance_line}", actor, target)


def _render_self_directed(cmd: str, actor: Creature) -> str:
    """Resolve a self-directed command's narration — pure flavor, no
    warmth. Picks one line from ``_SELF_DIRECTED_POOLS[cmd]`` and
    renders ``@1`` against ``actor``."""
    pool = _SELF_DIRECTED_POOLS[cmd]
    return parse(choice(pool), actor)


# ---------------------------------------------------------------------------
# Cog
# ---------------------------------------------------------------------------


class RpgSocialCommands(Cog):
    """Social-gesture commands: hug, haunt, warmth preferences, and
    the warmth-aware high-five / fistbump verbs."""

    def __init__(self, bot):
        self.bot = bot

    # -----------------------------------------------------------------
    # $hug — warmth-aware, target governs acceptance
    # -----------------------------------------------------------------

    @command(name="hug", aliases=["snuggle", "cuddle"], brief="Hugs, snuggles, and cuddles for all of your needs!")
    @guild_only()
    @cooldown(1, 5, BucketType.member)
    async def hug(self, ctx: Context, *, msg: str = None):
        """
        Hugs, snuggles, and cuddles for all of your needs!

        The specific narration depends on the *target's* warmth
        preference for hugs (which governs acceptance) and the
        *actor's* intent (which tints the attempt beat). Tune yours
        with ``$warmth set hug <level>`` or ``$warmth set hug <level> @player``.

        (5-second cool-down)

        :param msg: A message to include with the hug. This can be a target such as a monster's noun, or a @mention of another player. It can also simply be text in the form of a custom emote, but remember to type in the third-person present participle for best effect.
        """
        game, player = await RpgUtilities.get_game_and_player(ctx)
        if game is None or player is None:
            return

        if RpgUtilities.dead_invoker_guard(
            game.channel, player, _DEAD_INVOKER_FLAVOR["hug"],
        ):
            return

        if ctx.message.mentions is not None and len(ctx.message.mentions) > 0:
            if self.bot.user in ctx.message.mentions:
                responses = [
                    "Get your filthy paws off me, you damned dirty ape!",
                    "You cannot hug me, for I exist only in the ether.",
                    "One does not simply hug the AI, mortal.",
                ]
                if (c := randint(0, 3)) == 3:
                    file = File(f"./site/static/images/hal9000.gif", filename="hal9000.gif")
                    Dispatcher.add(game.channel, file=file)
                else:
                    Dispatcher.add(game.channel, responses[c])
                return

            # Monster takes priority if its name matches the mentioned
            # player — doppelganger-disguise case keeps the in-world
            # reaction (monster's on_hugged) rather than the player's
            # warmth setting.
            mention = ctx.message.mentions[0]
            if (
                game.monster is not None
                and game.monster.name.lower() == mention.display_name.lower()
            ):
                # Doppelganger-disguise case: mentioned player's
                # display_name matches the monster's name. Route to
                # the monster's social hook (which for ``hug`` falls
                # back to legacy ``on_hugged`` for back-compat).
                reaction = game.monster.on_social(
                    "hug", player, ctx.invoked_with,
                )
                if reaction:
                    Dispatcher.add(game.channel, reaction)
                return

            target = await RpgUtilities.get_player(mention, game=game, notify=False)
            if target is None:
                return

            # Dead targets skip the warmth flow — their on_hugged has
            # an is_dead branch ("corpse rolls lifelessly in @2's arms")
            # that we'd lose by routing blindly through the warmth pools.
            if target.is_dead():
                Dispatcher.add(
                    game.channel,
                    parse(target.on_hugged(player, ctx.invoked_with), target, player),
                )
                return

            Dispatcher.add(game.channel, _render_social("hug", player, target))
            return

        if msg is not None and len(msg) > 0:
            # Text-path monster routing — shared with every other
            # warmth-aware verb via the cog helper so the ergonomics
            # of ``$hug golem`` match ``$glare golem``.
            if self._maybe_route_to_monster_social(ctx, game, player, "hug"):
                return
            Dispatcher.add(game.channel, f"*{player.name} {ctx.invoked_with}s {msg}*")
            return

        Dispatcher.add(game.channel, f"*{player.name} {ctx.invoked_with}s the air awkwardly.*")

    # -----------------------------------------------------------------
    # $high_five — warmth-aware
    # -----------------------------------------------------------------

    @command(
        name="high_five",
        aliases=["highfive", "high5", "hi5"],
        brief="Slap a palm with a fellow adventurer.",
    )
    @guild_only()
    @cooldown(1, 5, BucketType.member)
    async def high_five(self, ctx: Context):
        """
        Raises a palm for another player to meet. The way the
        exchange actually reads depends on the *target's* warmth
        preference for ``high_five`` and the *actor's* intent.

        (5-second cool-down)
        """
        await self._dispatch_two_actor_social(ctx, "high_five")

    # -----------------------------------------------------------------
    # $fistbump — warmth-aware
    # -----------------------------------------------------------------

    @command(
        name="fistbump",
        aliases=["bump", "fist_bump", "pound"],
        brief="Bump knuckles with a fellow adventurer.",
    )
    @guild_only()
    @cooldown(1, 5, BucketType.member)
    async def fistbump(self, ctx: Context):
        """
        Offers a knuckle for another player to meet. The way the
        exchange actually reads depends on the *target's* warmth
        preference for ``fistbump`` and the *actor's* intent.

        (5-second cool-down)
        """
        await self._dispatch_two_actor_social(ctx, "fistbump")

    # -----------------------------------------------------------------
    # V2: warmth-aware interactive verbs
    # -----------------------------------------------------------------
    #
    # Each command body is a one-liner that delegates to
    # ``_dispatch_two_actor_social``. Adding a 15th warmth-aware verb
    # only needs: (1) a key in ``warmth.SOCIAL_COMMANDS`` +
    # ``SYSTEM_DEFAULTS``; (2) matching entries in
    # ``_NARRATION_POOLS`` + ``_DEAD_INVOKER_FLAVOR`` +
    # ``_DEAD_TARGET_FLAVOR``; (3) no-target and bot-mention lines in
    # ``_dispatch_two_actor_social``; (4) a self-target line in
    # ``_SELF_TARGET_LINES``; (5) a new ``@command`` method below.

    @command(
        name="salute",
        aliases=["sal"],
        brief="Render a respectful salute to a fellow adventurer.",
    )
    @guild_only()
    @cooldown(1, 5, BucketType.member)
    async def salute(self, ctx: Context):
        """
        Salutes another player — military / chivalric in tone. The
        exact reading depends on the target's ``salute`` warmth
        (which governs acceptance) and the actor's intent.

        (5-second cool-down)
        """
        await self._dispatch_two_actor_social(ctx, "salute")

    @command(
        name="comfort",
        aliases=["console", "soothe"],
        brief="Offer tender reassurance to a fellow adventurer.",
    )
    @guild_only()
    @cooldown(1, 5, BucketType.member)
    async def comfort(self, ctx: Context):
        """
        Offers comfort to another player — a hand on the shoulder, a
        gentle word. Defaults warm: comfort is usually accepted.

        (5-second cool-down)
        """
        await self._dispatch_two_actor_social(ctx, "comfort")

    @command(
        name="poke",
        aliases=["prod", "boop"],
        brief="Poke a fellow adventurer for attention.",
    )
    @guild_only()
    @cooldown(1, 5, BucketType.member)
    async def poke(self, ctx: Context):
        """
        Pokes another player. Mildly annoying by default — tune your
        warmth if you invite pokes routinely.

        (5-second cool-down)
        """
        await self._dispatch_two_actor_social(ctx, "poke")

    @command(
        name="nod",
        aliases=["acknowledge"],
        brief="Offer a silent nod of acknowledgement.",
    )
    @guild_only()
    @cooldown(1, 5, BucketType.member)
    async def nod(self, ctx: Context):
        """
        Nods at another player — a small, silent acknowledgement.

        (5-second cool-down)
        """
        await self._dispatch_two_actor_social(ctx, "nod")

    @command(
        name="glare",
        aliases=["scowl"],
        brief="Level a hostile stare at another adventurer.",
    )
    @guild_only()
    @cooldown(1, 5, BucketType.member)
    async def glare(self, ctx: Context):
        """
        Glares at another player. Hostile by default — cold-accept
        reads as stare-back-match.

        (5-second cool-down)
        """
        await self._dispatch_two_actor_social(ctx, "glare")

    @command(
        name="shank",
        aliases=["stab"],
        brief="Mock-stab a fellow adventurer — playful, not actually violent.",
    )
    @guild_only()
    @cooldown(1, 5, BucketType.member)
    async def shank(self, ctx: Context):
        """
        Mimes a playful stabbing motion at another player. Most
        players default to rejecting the bit — flip your warmth to
        ``warm`` or ``hot`` to opt in to the full Shakespearean
        death-scene treatment.

        (5-second cool-down)
        """
        await self._dispatch_two_actor_social(ctx, "shank")

    @command(
        name="tickle",
        aliases=["tickles"],
        brief="Tickle a fellow adventurer.",
    )
    @guild_only()
    @cooldown(1, 5, BucketType.member)
    async def tickle(self, ctx: Context):
        """
        Tickles another player. Tolerated from close friends,
        rejected by most — tune your warmth accordingly.

        (5-second cool-down)
        """
        await self._dispatch_two_actor_social(ctx, "tickle")

    @command(
        name="taunt",
        aliases=["jeer", "mock"],
        brief="Taunt a fellow adventurer.",
    )
    @guild_only()
    @cooldown(1, 5, BucketType.member)
    async def taunt(self, ctx: Context):
        """
        Taunts another player. Hostile by default; warm targets treat
        it as banter.

        (5-second cool-down)
        """
        await self._dispatch_two_actor_social(ctx, "taunt")

    @command(
        name="wink",
        aliases=["winks"],
        brief="Wink at a fellow adventurer — flirty or conspiratorial.",
    )
    @guild_only()
    @cooldown(1, 5, BucketType.member)
    async def wink(self, ctx: Context):
        """
        Winks at another player — could be flirty, could be
        conspiratorial, depends on who you ask.

        (5-second cool-down)
        """
        await self._dispatch_two_actor_social(ctx, "wink")

    # -----------------------------------------------------------------
    # V2: self-directed verbs
    # -----------------------------------------------------------------
    #
    # No target, no warmth — just a single-actor flavor line pulled
    # from ``_SELF_DIRECTED_POOLS``. Each public command delegates to
    # ``_dispatch_self_directed`` so adding a new self-directed verb
    # only requires a new pool + a new ``@command`` method.
    #
    # Mentions passed alongside a self-directed command are tolerated
    # but ignored — the narration stays self-directed. Justified by
    # least-surprise: a player who types ``$pose @friend`` almost
    # certainly meant "let me pose, and here's who should see me"
    # rather than "pose at my friend", and a hard refusal would be
    # annoying. The render doesn't reference the mention.

    @command(
        name="pose",
        aliases=["flex", "strike_a_pose"],
        brief="Strike a dramatic victory pose.",
    )
    @guild_only()
    @cooldown(1, 5, BucketType.member)
    async def pose(self, ctx: Context):
        """
        Strike a dramatic pose — hero-stance, victory-fists, or
        whatever the moment demands.

        (5-second cool-down)
        """
        await self._dispatch_self_directed(ctx, "pose")

    @command(
        name="cheer",
        aliases=["whoop", "hooray"],
        brief="Cheer with exuberant celebration.",
    )
    @guild_only()
    @cooldown(1, 5, BucketType.member)
    async def cheer(self, ctx: Context):
        """
        Whoop, cheer, punch the air — celebration in all its forms.

        (5-second cool-down)
        """
        await self._dispatch_self_directed(ctx, "cheer")

    @command(
        name="cry",
        aliases=["weep", "sob"],
        brief="Weep openly.",
    )
    @guild_only()
    @cooldown(1, 5, BucketType.member)
    async def cry(self, ctx: Context):
        """
        Weep, sob, sniffle — the full spectrum of tears.

        (5-second cool-down)
        """
        await self._dispatch_self_directed(ctx, "cry")

    @command(
        name="wave",
        aliases=["hello", "hi"],
        brief="Wave in casual greeting.",
    )
    @guild_only()
    @cooldown(1, 5, BucketType.member)
    async def wave(self, ctx: Context):
        """
        Wave — hello, goodbye, I see you, what have you.

        (5-second cool-down)
        """
        await self._dispatch_self_directed(ctx, "wave")

    @command(
        name="bow",
        aliases=["kneel", "curtsy"],
        brief="Bow with formal respect.",
    )
    @guild_only()
    @cooldown(1, 5, BucketType.member)
    async def bow(self, ctx: Context):
        """
        Offer a formal bow — courtly, soldierly, or stage-theatrical.

        (5-second cool-down)
        """
        await self._dispatch_self_directed(ctx, "bow")

    async def _dispatch_self_directed(
        self,
        ctx: Context,
        cmd: str,
    ) -> None:
        """Shared handler body for the five self-directed verbs.
        Resolves the player, runs the dead-invoker guard (using the
        command-keyed dead-invoker pool), and emits a single line
        from ``_SELF_DIRECTED_POOLS[cmd]``. Mentions are not required
        and are ignored if present.

        Adding a new self-directed verb only needs a pool + a public
        ``@command`` method that delegates here."""
        game, player = await RpgUtilities.get_game_and_player(ctx)
        if game is None or player is None:
            return

        if RpgUtilities.dead_invoker_guard(
            game.channel, player, _DEAD_INVOKER_FLAVOR.get(cmd, []),
        ):
            return

        Dispatcher.add(game.channel, _render_self_directed(cmd, player))

    async def _dispatch_two_actor_social(
        self,
        ctx: Context,
        cmd: str,
    ) -> None:
        """Shared handler body for ``$high_five`` / ``$fistbump``.
        Both commands require a ``@player`` mention and route through
        the warmth system. ``cmd`` keys into the dead-actor flavor
        dicts, so adding a new social verb only requires a new key in
        each (plus a narration pool)."""
        game, player = await RpgUtilities.get_game_and_player(ctx)
        if game is None or player is None:
            return

        if RpgUtilities.dead_invoker_guard(
            game.channel, player, _DEAD_INVOKER_FLAVOR.get(cmd, []),
        ):
            return

        mentions = ctx.message.mentions or []
        if not mentions:
            # Monster-name-in-text path: ``$glare golem``, ``$salute
            # dragon``, etc. routes to the monster's ``on_social`` hook
            # before the italicized no-target fallback fires. Mirrors
            # ``$hug``'s longstanding text-path monster routing so
            # every warmth-aware verb gets the same "target by name"
            # ergonomics.
            if self._maybe_route_to_monster_social(ctx, game, player, cmd):
                return
            # Per-command "no target" fallback. Italicize to match the
            # $hug convention for emote-style actions — Discord renders
            # ``*...*`` as italic. Messages live here (not in a module
            # dict) because they're one-liners and the command-specific
            # verb phrasing is small enough to keep inline.
            no_target_line = {
                "high_five": (
                    f"*{player.name} raises a palm to nobody in particular.*"
                ),
                "fistbump": (
                    f"*{player.name} holds out a fist to nobody in particular.*"
                ),
                "salute": (
                    f"*{player.name} salutes the empty air with crisp formality.*"
                ),
                "comfort": (
                    f"*{player.name} reaches out to comfort nobody in particular.*"
                ),
                "poke": (
                    f"*{player.name} pokes at the air with one intrepid finger.*"
                ),
                "nod": (
                    f"*{player.name} nods solemnly at the middle distance.*"
                ),
                "glare": (
                    f"*{player.name} glares at a nearby wall; the wall holds its ground.*"
                ),
                "shank": (
                    f"*{player.name} mimes a playful shank at thin air, which takes it well.*"
                ),
                "tickle": (
                    f"*{player.name} wiggles mischievous fingers at the empty air.*"
                ),
                "taunt": (
                    f"*{player.name} jeers at nobody in particular, to stunned silence.*"
                ),
                "wink": (
                    f"*{player.name} winks conspiratorially at an unoccupied chair.*"
                ),
            }.get(cmd, f"*{player.name} gestures at the air.*")
            Dispatcher.add(game.channel, no_target_line)
            return

        if self.bot.user in mentions:
            # Per-command scripted reply for the bot-mention case.
            # Warmth is never consulted against the narrator, so these
            # are pure flavor. Defaults to a generic line for unmapped
            # commands.
            bot_reply = {
                "high_five": "You cannot slap palms with the narrator, mortal.",
                "fistbump":  "You cannot bump knuckles with the narrator, mortal.",
                "salute":    "The narrator acknowledges the courtesy but is beyond the reach of salutes.",
                "comfort":   "The narrator appreciates the thought, but requires no comforting.",
                "poke":      "One does not simply poke the narrator, mortal.",
                "nod":       "The narrator returns a cosmic, unrenderable nod.",
                "glare":     "You glare at the sky. The sky is unmoved.",
                "shank":     "The narrator cannot be shanked, mock- or otherwise.",
                "tickle":    "The narrator is beyond tickling, thank you for trying.",
                "taunt":     "The narrator is above your petty mockery, mortal.",
                "wink":      "The narrator winks back, somewhere beyond the veil.",
            }.get(cmd, "You cannot share physical gestures with the narrator, mortal.")
            Dispatcher.add(game.channel, bot_reply)
            return

        mention = mentions[0]
        target = await RpgUtilities.get_player(mention, game=game, notify=False)
        if target is None:
            return

        # Dead targets skip warmth routing — a corpse can't accept or
        # decline a gesture. Render a per-command "unreachable" line
        # instead so the invoker gets a visible acknowledgement.
        if target.is_dead():
            pool = _DEAD_TARGET_FLAVOR.get(cmd, [])
            if pool:
                Dispatcher.add(
                    game.channel,
                    parse(choice(pool), player, target),
                )
            return

        Dispatcher.add(game.channel, _render_social(cmd, player, target))

    # -----------------------------------------------------------------
    # $haunt — moved verbatim from rpg_user_commands.py
    # -----------------------------------------------------------------

    @cooldown(1, 5, BucketType.member)
    @guild_only()
    @command(name="haunt", brief="Allows the dead to harass the less-dead.")
    async def haunt(self, ctx: Context, target: str = None):
        """
        Allows the dead to harass the less-dead. When specifying a target, use the @ symbol to target another player.

        (5-second cool-down)

        :param target: An optional victim of your haunting; either a player using @mentions, or the name of the current monster.
        """
        game, player = await RpgUtilities.get_game_and_player(ctx)
        haunted = None

        if game is None or player is None:
            return

        msgs = []

        if target is not None:
            if ctx.message.mentions is not None and len(ctx.message.mentions) > 0:
                if self.bot.user in ctx.message.mentions:
                    Dispatcher.add(game.channel, parse("You cannot haunt a figment of your imagination, @1.", player))
                    return
                haunted = await RpgUtilities.get_player(ctx.message.mentions[0], game=game, notify=False)
            elif game.monster is not None and game.monster.name == target.lower():
                haunted = game.monster

            if haunted is None or not isinstance(haunted, Creature):
                await self.haunt(ctx)
                return

            if haunted.is_dead():
                msgs = [
                    f"The spirit of @1 attempts to bond with that of @2, but a slight burst of pressure repels @1o.",
                    f"@1np shade investigates the remains of @2.",
                    f"As @1np ghostly form approaches the remains of @2, @1 flickers rapidly before suddenly "
                    f"teleporting back to @1a own corpse.",
                ]

            else:
                msgs = [
                    f"{'The ' if not isinstance(haunted, Player) else ''}@2 glances around the area suspiciously as @2s "
                    f"@2v(senses|sense) the unearthly presence of @1.",
                    # ``@2np`` already prepends the article for article-using
                    # creatures ("the hydra's"); the prior inline ``'the '``
                    # double-applied it (rendered "the the hydra's ears").
                    # ``@2Np`` at sentence start carries the implicit capital
                    # so monsters render "The hydra's" without the inline.
                    f"Soft laughter echoes in @2np ears as @1np spirit toys with @2o.",
                    f"@2Np breath suddenly catches as @1np shade wisps through @2o.",
                ]

        else:
            msgs = [
                f"The ghostly presence of @1 floods into the area briefly before ebbing away.",
                f"A sudden chill blankets the area as @1np spirit wafts through.",
                f"@1np forlorn lament brings with it a cold, solemn feeling.",
            ]

        if player.is_dead():
            if haunted and isinstance(haunted, Player) and haunted.member == player.member:
                msg = f"@1np spirit tries to fuse back into @1a body, but merely passes right through it."
            else:
                msg = choice(msgs)
        else:
            msg = f"@1 pretends to float around, making supposedly ghostly noises, but it's not very effective."

        Dispatcher.add(game.channel, parse(msg, player, haunted))

    # -----------------------------------------------------------------
    # $warmth — preferences manager (all output DM-only)
    # -----------------------------------------------------------------

    @group(
        name="warmth",
        brief="Show or tune your social-warmth preferences (DM-only).",
        invoke_without_command=True,
        case_insensitive=True,
    )
    async def warmth(self, ctx: Context):
        """
        Shows your current social-warmth preferences in a DM.

        Subcommands:
          ``$warmth set <cmd> <level> [@player]`` — set a default or
          per-player override.
          ``$warmth clear <cmd> [@player]`` — clear a default or
          per-player override.

        Levels (cold → hot): ``cold``, ``cool``, ``neutral``,
        ``warm``, ``hot``.

        All output is sent via DM — nobody else sees your warmth
        settings, and you never see anyone else's.
        """
        # Settings display is DM-only; channel ack keeps the
        # invocation visible but leaks nothing.
        game, player = await RpgUtilities.get_game_and_player(ctx)
        if game is None or player is None:
            return

        self._dm_current_settings(ctx, player)
        self._ack_in_channel(ctx, "Sent you a DM with your warmth settings.")

    @warmth.command(
        name="set",
        brief="Set a warmth level for a social command (default or per-player).",
    )
    async def warmth_set(
        self,
        ctx: Context,
        cmd: str = None,
        level: str = None,
        who: Optional[Member] = None,
    ):
        """
        ``$warmth set <cmd> <level>`` — set your default for one command.
        ``$warmth set <cmd> <level> @player`` — per-player override.
        ``$warmth set all <level>`` — bulk-set defaults across every
        warmth-aware command at once.
        ``$warmth set all <level> @player`` — bulk per-player override
        across every warmth-aware command.

        Confirmation is DM'd; nothing is posted to channel beyond a
        brief ack.
        """
        game, player = await RpgUtilities.get_game_and_player(ctx)
        if game is None or player is None:
            return

        if not cmd or not level:
            self._respond(
                ctx,
                "Usage: `$warmth set <cmd> <level>` or "
                "`$warmth set <cmd> <level> @player`. "
                "Use `all` as the command name to apply across every "
                "warmth-aware command at once.",
            )
            return

        cmd_norm = cmd.lower()
        is_wildcard = cmd_norm == _WARMTH_WILDCARD
        if not is_wildcard and not warmth.is_known_command(cmd_norm):
            self._respond(ctx, self._unknown_command_message(cmd_norm))
            return

        level_norm = warmth.Warmth.from_str(level)
        if level_norm is None:
            self._respond(ctx, self._unknown_level_message(level))
            return

        # Reject dead-end overrides: warmth toward the bot and warmth
        # toward yourself both bypass the resolver. Storing them would
        # silently accept a setting that never fires, creating the
        # false expectation that the next ``$hug @them`` will reflect
        # the level the player just set. Tell them plainly instead.
        # Same logic applies to bulk ``all`` — the iterate-loop would
        # just store N dead-end entries.
        if who is not None:
            if who.id == ctx.author.id:
                self._respond(
                    ctx,
                    "Warmth toward yourself always short-circuits to the "
                    "self-directed line, regardless of the level you set. "
                    "Nothing to store.",
                )
                return
            if getattr(who, "bot", False):
                self._respond(
                    ctx,
                    "Social gestures toward the narrator always get the "
                    "same scripted reply, regardless of warmth. Saving "
                    "you the storage.",
                )
                return

        targets = (
            warmth.SOCIAL_COMMANDS if is_wildcard else (cmd_norm,)
        )

        if who is not None:
            for target_cmd in targets:
                warmth.set_override(player, who.id, target_cmd, level_norm)
            if is_wildcard:
                confirmation = (
                    f"Set your warmth toward **{who.display_name}** to "
                    f"**{level_norm}** across all {len(targets)} "
                    f"warmth-aware commands."
                )
            else:
                confirmation = (
                    f"Set your `{cmd_norm}` warmth toward "
                    f"**{who.display_name}** to **{level_norm}**."
                )
        else:
            for target_cmd in targets:
                warmth.set_default(player, target_cmd, level_norm)
            if is_wildcard:
                confirmation = (
                    f"Set default warmth to **{level_norm}** across all "
                    f"{len(targets)} warmth-aware commands."
                )
            else:
                confirmation = (
                    f"Set your default `{cmd_norm}` warmth to **{level_norm}**."
                )

        self._respond(ctx, confirmation)

    @warmth.command(
        name="clear",
        brief="Clear a warmth setting (default or per-player).",
    )
    async def warmth_clear(
        self,
        ctx: Context,
        cmd: str = None,
        who: Optional[Member] = None,
    ):
        """
        ``$warmth clear <cmd>`` — clear your per-command default
        (falls back to the system default).
        ``$warmth clear <cmd> @player`` — clear a per-player override.
        ``$warmth clear all`` — clear defaults across every warmth-
        aware command.
        ``$warmth clear all @player`` — clear every per-player
        override for one player in one call.
        """
        game, player = await RpgUtilities.get_game_and_player(ctx)
        if game is None or player is None:
            return

        if not cmd:
            self._respond(
                ctx,
                "Usage: `$warmth clear <cmd>` or `$warmth clear <cmd> @player`. "
                "Use `all` as the command name to clear across every "
                "warmth-aware command at once.",
            )
            return

        # Common mis-parse: ``$warmth clear @player`` — mention lands
        # in ``cmd``, ``who`` is ``None``. Natural intent is "drop
        # every per-player override I've set for this player", which
        # is what ``clear all @player`` does — so route there.
        if who is None:
            mention_uid = _mention_to_uid(cmd)
            if mention_uid is not None:
                member = (
                    ctx.guild.get_member(mention_uid) if ctx.guild else None
                )
                if member is None:
                    self._respond(
                        ctx,
                        "Couldn't resolve that mention to a player in this "
                        "server. Try `$warmth clear <cmd> @player` or "
                        "`$warmth clear all @player`.",
                    )
                    return
                cmd = _WARMTH_WILDCARD
                who = member

        cmd_norm = cmd.lower()
        is_wildcard = cmd_norm == _WARMTH_WILDCARD
        if not is_wildcard and not warmth.is_known_command(cmd_norm):
            self._respond(ctx, self._unknown_command_message(cmd_norm))
            return

        targets = (
            warmth.SOCIAL_COMMANDS if is_wildcard else (cmd_norm,)
        )

        if who is not None:
            removed_count = sum(
                1 for target_cmd in targets
                if warmth.clear_override(player, who.id, target_cmd)
            )
            if is_wildcard:
                if removed_count:
                    text = (
                        f"Cleared {removed_count} per-player override(s) "
                        f"for **{who.display_name}** across all warmth-"
                        f"aware commands."
                    )
                else:
                    text = (
                        f"No per-player overrides existed for "
                        f"**{who.display_name}**; nothing to clear."
                    )
            else:
                if removed_count:
                    text = (
                        f"Cleared your per-player `{cmd_norm}` setting for "
                        f"**{who.display_name}**."
                    )
                else:
                    text = (
                        f"No `{cmd_norm}` override existed for "
                        f"**{who.display_name}**; nothing to clear."
                    )
        else:
            removed_count = sum(
                1 for target_cmd in targets
                if warmth.clear_default(player, target_cmd)
            )
            if is_wildcard:
                if removed_count:
                    text = (
                        f"Cleared {removed_count} default setting(s) across "
                        f"all warmth-aware commands (each falls back to the "
                        f"system default)."
                    )
                else:
                    text = "No defaults were saved; nothing to clear."
            else:
                if removed_count:
                    text = (
                        f"Cleared your default `{cmd_norm}` setting "
                        f"(back to system default)."
                    )
                else:
                    text = f"No default `{cmd_norm}` setting was saved; nothing to clear."

        self._respond(ctx, text)

    # -----------------------------------------------------------------
    # DM / ack helpers
    # -----------------------------------------------------------------

    def _dm(self, ctx: Context, text: str) -> None:
        """Route a message to the invoker's DM via the Dispatcher.
        ``ctx.author`` is a ``Member`` (or ``User``) which the
        Dispatcher knows how to ``.send()`` to — same path
        ``inspect_monster`` uses for owner-only owner-DMs.

        Allowlisted bot-players can't receive DMs (Discord 50007)
        so ``dm_target`` re-routes them to the channel."""
        Dispatcher.add(RpgUtilities.dm_target(ctx.author, ctx.channel), text)

    def _ack_in_channel(self, ctx: Context, text: str) -> None:
        """Briefly acknowledge the command in its originating
        channel. DM invocations skip the ack — the body already went
        to the same user, and a duplicate would just be noise."""
        if ctx.guild is None:
            return
        Dispatcher.add(ctx, text)

    def _maybe_route_to_monster_social(
        self,
        ctx: Context,
        game,
        player: Player,
        cmd: str,
    ) -> bool:
        """If the invocation's text body references the live monster's
        name, render the monster's :meth:`Creature.on_social` reaction
        (or a bland "doesn't react" line if the hook returned empty)
        and return ``True``. Otherwise return ``False`` so the caller
        can continue its fallback chain (italicized no-target line).

        Shared across every warmth-aware verb — the monster-name
        check in ``$hug`` is the same substring match; centralizing
        it here means ``$glare golem`` and ``$hug golem`` route
        identically.
        """
        monster = game.monster
        if monster is None:
            return False
        content = (ctx.message.content or "").lower()
        if monster.name.lower() not in content:
            return False
        reaction = monster.on_social(cmd, player, ctx.invoked_with)
        if reaction:
            Dispatcher.add(game.channel, reaction)
        else:
            # Monster has no defined reaction for this verb. Render a
            # bland acknowledgement so the invoker doesn't mistake
            # silence for a failed command.
            verb = cmd.replace("_", " ")
            Dispatcher.add(
                game.channel,
                parse(
                    f"@1dc does not react to @2np {verb}.",
                    monster, player,
                ),
            )
        return True

    def _respond(self, ctx: Context, text: str) -> None:
        """Route a warmth-mutation reply (set / clear confirmations,
        malformed-command help, unknown-command / unknown-level
        errors, self-target and bot-target refusals) to the most
        appropriate target: the invocation channel when the player
        typed the command in a server (they already made the action
        public), or DM when they invoked it from a DM.

        **Only for the mutation / help surface.** The bare
        ``$warmth`` settings display always DMs regardless of
        invocation channel — current warmth state is private even
        when the query was public, and leaking another player's
        name in a public acknowledgement would violate the
        privacy-first contract."""
        if ctx.guild is None:
            Dispatcher.add(RpgUtilities.dm_target(ctx.author, ctx.channel), text)
        else:
            Dispatcher.add(ctx, text)

    def _dm_current_settings(self, ctx: Context, player: Player) -> None:
        """Format and DM the player's full warmth state."""
        snapshot = warmth.summarize(player)
        lines: List[str] = ["**Your warmth settings**", ""]

        # Defaults — one row per known social command, with a clear
        # "(system default)" label when the player hasn't tuned it.
        lines.append("__Defaults__")
        defaults = snapshot.get("defaults", {})
        for cmd_name in warmth.SOCIAL_COMMANDS:
            user_level = defaults.get(cmd_name)
            sys_level = warmth.SYSTEM_DEFAULTS.get(cmd_name, warmth.Warmth.NEUTRAL)
            if user_level:
                lines.append(f"- `{cmd_name}`: **{user_level}**")
            else:
                lines.append(f"- `{cmd_name}`: {sys_level} (system default)")
        lines.append("")

        # Per-player overrides. Resolve each user_id to a display_name
        # best-effort; fall back to the bare id string if the member
        # isn't cached. Privacy: only the invoker's own per-player
        # settings are included.
        lines.append("__Per-player overrides__")
        per_player = snapshot.get("per_player", {})
        if not per_player:
            lines.append("_(none)_")
        else:
            for uid_str, entries in per_player.items():
                name = self._resolve_display_name(ctx, uid_str)
                for cmd_name, level in entries.items():
                    lines.append(f"- {name} · `{cmd_name}`: **{level}**")
        lines.append("")
        lines.append(
            "Levels (cold → hot): "
            + ", ".join(f"`{w.value}`" for w in warmth.Warmth)
        )

        self._dm(ctx, "\n".join(lines))

    def _resolve_display_name(self, ctx: Context, uid_str: str) -> str:
        """Best-effort Discord user_id → display_name lookup for the
        DM settings view. Falls back to ``"<id>"`` if the member
        isn't cached anywhere reachable; keeps the DM legible even
        when a previously-overridden user has left the guild."""
        try:
            uid = int(uid_str)
        except (TypeError, ValueError):
            return f"<{uid_str}>"
        # Try the invoking guild first (cheap), then any cached user.
        if ctx.guild is not None:
            member = ctx.guild.get_member(uid)
            if member is not None:
                return member.display_name
        user = self.bot.get_user(uid) if self.bot is not None else None
        if user is not None:
            return getattr(user, "display_name", None) or user.name
        return f"<{uid}>"

    def _unknown_command_message(self, cmd: str) -> str:
        # If ``cmd`` is actually a mention tag, the player forgot to
        # pass a command name — echoing the raw ``<@id>`` back in
        # backticks reads like garbage in Discord. Give a tailored
        # error instead.
        if _mention_to_uid(cmd) is not None:
            return (
                "That looks like a player mention, not a command. "
                "Usage: `$warmth set <cmd> <level> @player` or "
                "`$warmth clear <cmd> @player`. Use `all` in place of "
                "`<cmd>` to apply across every warmth-aware command."
            )
        known = ", ".join(f"`{c}`" for c in warmth.SOCIAL_COMMANDS)
        return (
            f"`{cmd}` is not a warmth-aware command. "
            f"Known commands: {known}. Use `{_WARMTH_WILDCARD}` to "
            f"apply a level across every warmth-aware command."
        )

    def _unknown_level_message(self, level: str) -> str:
        levels = ", ".join(f"`{w.value}`" for w in warmth.Warmth)
        return (
            f"`{level}` isn't a recognized warmth level. "
            f"Try one of: {levels}."
        )

    @Cog.listener()
    async def on_ready(self):
        _log.info("RpgSocialCommands ready.")


async def setup(bot):
    await bot.add_cog(RpgSocialCommands(bot))
