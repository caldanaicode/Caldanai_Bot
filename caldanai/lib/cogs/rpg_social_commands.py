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
from caldanai.lib.rpg.helpers.converters import (
    CreatureConverter, FuzzyMemberConverter,
)
from caldanai.lib.rpg.helpers.fuzzy_resolve import fuzzy_resolve
from caldanai.lib.rpg.creatures import Creature
from caldanai.lib.rpg.creatures.player import Player
from caldanai.lib.rpg.helpers.parser import parse
from caldanai.lib.rpg.helpers.utils import RpgUtilities
from caldanai.lib.rpg.helpers.verb_dispatch import dispatch_expressive_verb
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
    "greet": [
        "The shade of @1 mouths a hello that doesn't quite reach the air.",
        "@1np corpse greets the long road instead.",
        "A faint sigh slips from @1 — the shape of a hello, lost.",
        "The remains of @1 try the introduction, but the introduction won't take.",
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
    "thank": [
        "The shade of @1 mouths a quiet thanks the air won't quite carry.",
        "A faint warmth gathers above the corpse of @1 — gratitude with no breath behind it.",
        "@1np stilled lips shape \"thank you\" once, soundless, and settle again.",
        "Something gentle ripples off the body of @1 — the shape of a thank-you, unsent.",
    ],
    # ---- Presence-verb dead-invoker pools ------------------------
    # Voice = a corpse attempting the presence-action: poignant,
    # ghostly, the gesture outliving the body. @1 = the dead invoker
    # (no article — players are named). Per-verb tone:
    # - lean: corpse propped, finally at rest against something
    # - sit: settled where they fell, the way the dirt holds them
    # - rest: the stillness that cannot deepen further
    # - ponder: the thought that doesn't finish
    # - tend: a last attempt at small care that doesn't land
    # - bite: emotion-neutral (per `project_verb_adverb_coloring.md`);
    #   teeth set in death, a fidget-shape that outlives the fidget
    "lean":   [
        "The body of @1 lists slowly sideways and finds something to rest against.",
        "@1 leans where @1 fell, propped at last against the dirt that holds @1o.",
        "The corpse of @1 settles into a final lean, weight given over entirely.",
        "@1np shoulder finds the ground and stays there, the lean become permanent.",
    ],
    "sit":    [
        "The corpse of @1 is already sat, and shows no sign of getting up.",
        "@1 sits where @1 came down, the dirt holding @1o the way the dirt does.",
        "The body of @1 settles a fraction lower, taking its place among the still things.",
        "@1np remains keep their seat without ceremony.",
    ],
    "rest":   [
        "The corpse of @1 is at rest, and the rest goes no deeper than this.",
        "@1np stillness can't deepen — @1 has rested all the way through.",
        "The body of @1 holds the kind of quiet only the dead carry.",
        "@1 lies where @1 lies, beyond troubling.",
    ],
    "ponder": [
        "@1np eyes hold a thought the body can no longer finish.",
        "The corpse of @1 stares at something a long way past the ceiling.",
        "@1 considers the dark with the slow patience of a body done with hurry.",
        "The shade of @1 turns a question over once and lets it lie.",
    ],
    "tend":   [
        "@1np hand twitches toward a buckle that doesn't need straightening anymore.",
        "The corpse of @1 lifts a finger half an inch, as if to fix something, and stops.",
        "A small gesture of caretaking flickers across @1np stilled hand and fades.",
        "@1np fingers curl in the dust the way they used to curl around someone else's sleeve.",
    ],
    "bite":   [
        "@1np teeth are set, the jaw closed in a fidget the body forgot to release.",
        "The corpse of @1 has its lip caught in its teeth and won't be letting go.",
        "@1np jaw clicks shut once in the cold and stays that way.",
        "A last small bite-shape holds in @1np mouth, neither finished nor undone.",
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
    "thank": [
        "@1 kneels by @2np body and says \"thank you\" the way one says it to a closed door — quiet, complete, meant.",
        "@1 lays a hand on @2np stilled shoulder and offers @2o a thanks the dark can carry the rest of the way.",
        "@1 murmurs a final \"thank you\" to the corpse of @2, soft enough that only the dirt hears.",
    ],
    # ---- Presence-verb dead-target pools -------------------------
    # Voice = a living actor performing the presence-action toward
    # a corpse: tender, final, the body still present in some
    # functional way (still sittable-near, still leanable-against,
    # still a thing one can ponder). @1 = living actor; @2 = dead
    # target. Per-verb tone:
    # - lean: actor leans on or near the body, a vigil-shape
    # - sit: actor sits beside the corpse, the way you keep watch
    # - rest: actor rests by them, the held quiet two bodies make
    # - ponder: actor considers them — a last thought offered
    # - tend: actor brushes hair from forehead, smooths a sleeve;
    #   small caretaking that lands gently on the still
    # - bite: emotion-neutral (per `project_verb_adverb_coloring.md`);
    #   actor catches their own lip in their teeth, looking at @2
    "lean":   [
        "@1 leans against the dirt beside @2np body and lets the silence stand.",
        "@1 sets a shoulder near @2np and holds the lean a long while.",
        "@1 rests @1a back against the same ground that holds @2 and stays there.",
    ],
    "sit":    [
        "@1 sits down beside the body of @2 and keeps the watch.",
        "@1 settles in the dirt next to @2np remains, neither speaking nor leaving.",
        "@1 takes a place beside @2np stillness and stays.",
    ],
    "rest":   [
        "@1 rests beside the body of @2, the quiet two bodies make holding.",
        "@1 lays @1r down within reach of @2np remains and lets the dark have them both for a while.",
        "@1 keeps a still, breathing watch beside @2np corpse.",
    ],
    "ponder": [
        "@1 looks down at the body of @2 a long time, holding a thought @1s won't say.",
        "@1 considers @2np stillness the way one considers a closed letter.",
        "@1 stands over the corpse of @2 and turns something over carefully in @1a head.",
    ],
    "tend":   [
        "@1 brushes hair from @2np forehead with the back of one careful knuckle.",
        "@1 smooths a fold in @2np sleeve, settling the cloth the way @2 might have liked.",
        "@1 closes @2np eyes with two fingers and lets @1a hand linger a beat.",
    ],
    "bite":   [
        "@1 catches @1a own lip in @1a teeth, eyes on the body of @2.",
        "@1 sets @1a jaw, looking at @2np stillness and not looking away.",
        "@1 holds @1a own thumb between @1a teeth and watches @2np corpse for a long beat.",
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
        "@2 holds on to @1 as if @1s @1v(is|are) the only solid thing in the world right now.",
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
        "@1 teases @2 with a grin that says @1s @1v(means|mean) nothing by it.",
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
        "@2 stares at @1 until @1s @1v(runs|run) out of material.",
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


# ---- $thank ---------------------------------------------------------
#
# Voice: gratitude is sincere by default; the warmth tiers tune *how*
# the actor expressed it (HOT = effusive, public; WARM = heartfelt;
# NEUTRAL = polite; COOL = perfunctory; COLD = grudging / sarcastic)
# and *how* the target received it (HOT = embraces it back, makes a
# moment of it; WARM = accepts warmly; NEUTRAL = acknowledges; COOL =
# brushes off; COLD = rejects / refuses). @1 = actor (intent), @2 =
# target.

_THANK_INTENT_BEATS: Dict[str, List[str]] = {
    warmth.Warmth.COLD: [
        "@1 thanks @2 through gritted teeth, the words doing the work and nothing more.",
        "@1 mutters a flat \"thanks\" in @2np general direction without quite looking at @2o.",
        "@1 offers @2 the most begrudging acknowledgement a thank-you can carry.",
        "@1 says \"thanks\" to @2 in the tone people reserve for a debt they didn't want to owe.",
    ],
    warmth.Warmth.COOL: [
        "@1 offers @2 a perfunctory thanks and a small, formal nod.",
        "@1 thanks @2 in the brisk economy of someone with somewhere else to be.",
        "@1 produces a short, polite \"my thanks\" for @2 and leaves it there.",
        "@1 dispatches a clipped acknowledgement of thanks toward @2.",
    ],
    warmth.Warmth.NEUTRAL: [
        "@1 thanks @2.",
        "@1 inclines @1a head and says \"thank you\" to @2 plainly.",
        "@1 offers @2 a clean, unembellished word of thanks.",
        "@1 catches @2np eye and says \"thanks for that\" with no fuss.",
    ],
    warmth.Warmth.WARM: [
        "@1 thanks @2 with quiet sincerity, the kind that lands.",
        "@1 meets @2np eyes and says \"truly — thank you,\" voice low and warm.",
        "@1 lays a hand briefly on @2np shoulder and offers @2o a heartfelt thanks.",
        "@1 thanks @2 with the unhurried weight of someone who means each word.",
    ],
    warmth.Warmth.HOT: [
        "@1 thanks @2 with both hands and a long bow, loud enough that the whole clearing turns.",
        "@1 throws @1a arms wide and declares @2np kindness to anyone within earshot.",
        "@1 grips @2np shoulders, beaming, and tells @2o exactly how much it meant.",
        "@1 sweeps @2 into a thanks so effusive @1s nearly forgets to breathe between sentences.",
    ],
}

_THANK_ACCEPTANCE_BEATS: Dict[str, List[str]] = {
    warmth.Warmth.COLD: [
        "@2 doesn't acknowledge it; the gratitude lands on stone.",
        "@2 looks past @1 as if no thanks had been offered at all.",
        "@2 turns a shoulder and the thank-you finds nowhere to settle.",
        "@2 shakes @2a head once — \"don't\" — and walks @2a attention elsewhere.",
    ],
    warmth.Warmth.COOL: [
        "@2 brushes the thanks off with a small, quick \"don't make it a thing.\"",
        "@2 waves @1np gratitude aside with a tight, unembarrassed gesture.",
        "@2 nods once, briskly, and changes the subject before @1 can extend it.",
    ],
    warmth.Warmth.NEUTRAL: [
        "@2 inclines @2a head in acknowledgement.",
        "@2 nods and says \"of course\" the way one ticks off a small completed thing.",
        "@2 returns a short, even \"any time\" and lets the moment close.",
    ],
    warmth.Warmth.WARM: [
        "@2 smiles and waves it off, warm and easy. \"Glad to.\"",
        "@2 meets @1np eyes and says \"truly — any time,\" and means it.",
        "@2 clasps @1np forearm briefly. \"Don't mention it. Or do. Either way, glad of it.\"",
    ],
    warmth.Warmth.HOT: [
        "@2 lights up and clasps @1np hand in both of @2a own, holding on a long beat.",
        "@2 sweeps @1 into a quick fierce embrace and announces to nobody in particular that @1 is good people.",
        "@2 grips @1np shoulders, eyes bright, and gives the thanks back twice as warm.",
        "@2 throws @2a arm around @1 and makes a whole moment of it, refusing to let @1 minimize the gesture.",
    ],
}


# ---- Presence verbs ($lean / $sit / $rest / $ponder / $tend / $bite)
#
# Per-warmth-tier intent + acceptance beats for each of the 6
# presence verbs (10 dicts; pools below). Voice rules:
#
# - Presence verbs share a "low-energy occupying space" register
#   (per `caldanai/lib/cogs/rpg_presence_commands.py` docstring).
#   The intent beat captures HOW the actor performed the gesture
#   toward @2; the acceptance beat captures HOW @2 received it.
# - **Emotion-neutral by default for $bite, $lean, $rest, $ponder**
#   (per `project_verb_adverb_coloring.md`). Stick to physical
#   action + observable detail; let warmth-tier do the tonal work
#   without painting emotion adverbs onto the line.
# - $tend / $sit can carry mild affection at HOT/WARM (small care,
#   companionable settling). $bite is the awkward one — stays
#   physical-fidget across all tiers; HOT/WARM reads as playful,
#   COOL/COLD reads as performed-aggression-or-rejection.
# - Match the intent/acceptance asymmetry from existing pools:
#   intent = actor's projected gesture; acceptance = target's
#   independent response. Never echo the actor's tier in the
#   acceptance line.
# - Rendering convention: ``@1`` = actor, ``@2`` = target. Use
#   ``@1np`` / ``@2a`` for possessives, etc. Italic asterisks are
#   the social-cog convention but presence beats may run
#   non-italic (match existing $hug et al. shape — they're not
#   italic).

_LEAN_INTENT_BEATS: Dict[str, List[str]] = {
    warmth.Warmth.COLD: [
        "@1 leans against the far wall, well clear of @2.",
        "@1 props a shoulder against the nearest surface that isn't @2.",
        "@1 angles @1r away from @2 and leans into nothing in particular.",
        "@1 picks a lean that puts @2 squarely behind @1np shoulder.",
    ],
    warmth.Warmth.COOL: [
        "@1 leans at arm's length from @2, weight on one foot.",
        "@1 sets a shoulder against the wall a measured pace from @2.",
        "@1 leans nearby with @1a arms folded and @1a eyes on the middle distance.",
        "@1 settles into a lean that keeps @2 in @1a peripheral vision.",
    ],
    warmth.Warmth.NEUTRAL: [
        "@1 leans against the same wall as @2.",
        "@1 props @1r near @2 and lets the lean settle.",
        "@1 takes up a lean within easy speaking distance of @2.",
        "@1 sets @1a back against something solid alongside @2.",
    ],
    warmth.Warmth.WARM: [
        "@1 leans in close enough to @2 that @1np shoulder almost brushes @2np.",
        "@1 settles into a lean beside @2 with the easy posture of company.",
        "@1 props @1r against the same beam as @2, shoulder a hand's width away.",
        "@1 leans toward @2 the way one leans into a familiar quiet.",
    ],
    warmth.Warmth.HOT: [
        "@1 sets @1a shoulder flush against @2np and lets the weight of the lean carry through.",
        "@1 leans into @2 with the unconsidered familiarity of long company.",
        "@1 props @1r against @2 the way one leans against a wall — and stays.",
        "@1 lets @1a head come to rest against @2np shoulder without hesitation.",
    ],
}

_LEAN_ACCEPTANCE_BEATS: Dict[str, List[str]] = {
    warmth.Warmth.COLD: [
        "@2 shifts a half-pace clear and the lean has nothing to land against.",
        "@2 straightens off the wall and walks @2a lean elsewhere.",
        "@2 stiffens and the air between them gets pointedly wider.",
        "@2 turns a shoulder away and the contact does not happen.",
    ],
    warmth.Warmth.COOL: [
        "@2 holds @2a ground without closing the gap.",
        "@2 keeps @2a own lean and lets @1np stand on its own.",
        "@2 acknowledges the proximity with the smallest tilt of @2a head.",
        "@2 stays put — neither leaning in nor pulling away.",
    ],
    warmth.Warmth.NEUTRAL: [
        "@2 lets the lean be what it is.",
        "@2 stays leaned where @2 was and the moment holds.",
        "@2 makes no particular accommodation, and no particular refusal.",
        "@2 keeps @2a stance and the two leans share the wall.",
    ],
    warmth.Warmth.WARM: [
        "@2 settles a fraction closer, the lean shared between them.",
        "@2 lets @2a own weight come to rest against @1np shoulder.",
        "@2 angles toward @1 just enough that the leans meet.",
        "@2 leans back into @1np quiet and lets it stand.",
    ],
    warmth.Warmth.HOT: [
        "@2 leans back into @1np weight without thinking about it.",
        "@2 settles @2a head against @1np shoulder and breathes out.",
        "@2 sinks into the shared lean and stays there a long, unhurried while.",
        "@2 catches @1np shoulder with @2a own and lets the lean become a held thing.",
    ],
}

_SIT_INTENT_BEATS: Dict[str, List[str]] = {
    warmth.Warmth.COLD: [
        "@1 picks a seat well across the room from @2.",
        "@1 sits down with @1a back to @2.",
        "@1 chooses a place on the bench that puts a careful gap between @1r and @2.",
        "@1 finds a seat at the far edge of the firelight, @2 left to the other side.",
    ],
    warmth.Warmth.COOL: [
        "@1 sits within reach of @2 without closing the gap.",
        "@1 takes a seat one place removed from @2.",
        "@1 lowers @1r onto the bench with a deliberate hand-span between @1r and @2.",
        "@1 settles into a seat near enough to talk, far enough not to.",
    ],
    warmth.Warmth.NEUTRAL: [
        "@1 sits down beside @2.",
        "@1 takes the seat next to @2 and lets the silence be silence.",
        "@1 settles onto the bench alongside @2.",
        "@1 lowers @1r into the place beside @2 without ceremony.",
    ],
    warmth.Warmth.WARM: [
        "@1 sits beside @2 and lets the moment hold.",
        "@1 settles in close enough to @2 that the warmth of the bench is shared.",
        "@1 takes the seat at @2np elbow and breathes out.",
        "@1 lowers @1r beside @2 with the easy slowness of company kept often.",
    ],
    warmth.Warmth.HOT: [
        "@1 plants @1r shoulder-to-shoulder with @2 and breathes out.",
        "@1 drops onto the bench so close to @2 that their knees knock and stay touching.",
        "@1 sits down against @2np side and lets @1a weight come to rest there.",
        "@1 takes the seat against @2np shoulder the way kin takes a seat against kin.",
    ],
}

_SIT_ACCEPTANCE_BEATS: Dict[str, List[str]] = {
    warmth.Warmth.COLD: [
        "@2 stands and finds reason to be elsewhere.",
        "@2 gathers @2a things and moves to the far end of the bench.",
        "@2 rises, brushes off, and crosses the room.",
        "@2 turns @2a back and the seat beside goes unanswered.",
    ],
    warmth.Warmth.COOL: [
        "@2 acknowledges the company with the smallest tilt of @2a head.",
        "@2 keeps @2a seat and @2a own counsel.",
        "@2 nods once at the new neighbor and goes back to what held @2o.",
        "@2 stays put without comment, neither welcoming nor objecting.",
    ],
    warmth.Warmth.NEUTRAL: [
        "@2 makes room on the bench without comment.",
        "@2 shifts a fraction to give @1 a clean place to sit.",
        "@2 stays where @2 is and the two seats sit alongside.",
        "@2 acknowledges the seat-taking with a small, even nod.",
    ],
    warmth.Warmth.WARM: [
        "@2 settles deeper into @2a own seat, the silence between them companionable.",
        "@2 leans a fraction toward @1, glad of the company.",
        "@2 lets the shoulders nearly touch and stays there.",
        "@2 angles @2a knees toward @1np in the unhurried language of welcome.",
    ],
    warmth.Warmth.HOT: [
        "@2 leans into the shared seat, quiet as old habit.",
        "@2 hooks an elbow over @1np shoulder and stays put a long while.",
        "@2 lets @2a weight rest against @1np side and breathes out.",
        "@2 settles into the bench like the bench was always meant to hold both of them.",
    ],
}

_REST_INTENT_BEATS: Dict[str, List[str]] = {
    warmth.Warmth.COLD: [
        "@1 picks a place to rest with @2 well outside @1np line of sight.",
        "@1 settles in to rest with @2 pointedly to @1np back.",
        "@1 lays @1r down at the far edge of the firelight from @2.",
        "@1 takes @1a rest where @2 is just a shape in the dark.",
    ],
    warmth.Warmth.COOL: [
        "@1 rests within sight of @2, not within reach.",
        "@1 lays @1r down a measured distance from @2 and keeps one eye half-open.",
        "@1 takes @1a rest with @2 across the firelight, neither close nor strange.",
        "@1 settles for a rest at the edge of @2np pace.",
    ],
    warmth.Warmth.NEUTRAL: [
        "@1 rests near @2, eyes half-closing.",
        "@1 lays @1r down within hearing of @2 and lets @1a breath even out.",
        "@1 settles in for a rest beside @2np spot.",
        "@1 takes @1a rest at the same fire as @2.",
    ],
    warmth.Warmth.WARM: [
        "@1 rests near @2 the way one rests where one is safe.",
        "@1 lays @1r down within arm's length of @2 and lets @1a guard ease.",
        "@1 settles into rest with @2 close enough to hear breathing.",
        "@1 takes @1a rest beside @2 and the held quiet welcomes both.",
    ],
    warmth.Warmth.HOT: [
        "@1 lets @1r go fully unguarded near @2 — the trust whole.",
        "@1 lays @1r down against @2np side and the breathing slows immediately.",
        "@1 rests with @1a head a hand's width from @2np and sleeps the deep sleep of safety.",
        "@1 settles into rest with @2np presence the only watch needed.",
    ],
}

_REST_ACCEPTANCE_BEATS: Dict[str, List[str]] = {
    warmth.Warmth.COLD: [
        "@2 keeps @2a back to @1 and does not soften.",
        "@2 stays awake, listening, with @2a hand near @2a hilt.",
        "@2 holds @2a own watch and offers no quiet in return.",
        "@2 turns @2a face away and the rest is taken alone.",
    ],
    warmth.Warmth.COOL: [
        "@2 stays alert the way one stays alert near a stranger at rest.",
        "@2 keeps half an eye open and lets @1 sleep light.",
        "@2 doesn't rest in answer, but doesn't make a thing of @1np resting either.",
        "@2 stays seated with @2a back straight and the quiet kept careful.",
    ],
    warmth.Warmth.NEUTRAL: [
        "@2 lets @1 rest, untroubled.",
        "@2 keeps a small steady watch while @1 settles.",
        "@2 makes no fuss of @1np resting and no fuss of @2a own.",
        "@2 stays as @2 was, the rest a private thing held in the same room.",
    ],
    warmth.Warmth.WARM: [
        "@2 keeps a quiet watch while @1 rests, the trust returning.",
        "@2 settles into @2a own rest a hand's width from @1np.",
        "@2 lets the watch shift to @2a shoulders and breathes out.",
        "@2 stays close while @1 sleeps, breathing in the same slow rhythm.",
    ],
    warmth.Warmth.HOT: [
        "@2 rests in answer, the two of them holding the quiet between them.",
        "@2 lays @2a head against @1np and the both of them go under at once.",
        "@2 settles fully unguarded beside @1, the trust returned in full.",
        "@2 sleeps with @2a hand resting on @1np forearm, breathing slow.",
    ],
}

_PONDER_INTENT_BEATS: Dict[str, List[str]] = {
    warmth.Warmth.COLD: [
        "@1 considers @2 as one considers a closed door.",
        "@1 looks at @2 with the flat attention reserved for problems.",
        "@1 weighs @2 in @1a head and arrives at nothing flattering.",
        "@1 turns a long, unsmiling thought over about @2.",
    ],
    warmth.Warmth.COOL: [
        "@1 ponders @2 at a measured remove.",
        "@1 watches @2 from across the firelight, a thought held at arm's length.",
        "@1 considers @2 the way one considers an unopened note.",
        "@1 turns @2 over in @1a thinking and keeps the conclusion to @1r.",
    ],
    warmth.Warmth.NEUTRAL: [
        "@1 ponders the space near @2 for a long beat.",
        "@1 looks at @2 a moment longer than is purely casual.",
        "@1 holds a quiet thought about @2 and lets it sit.",
        "@1 turns a half-formed question over in @1a head, eyes on @2.",
    ],
    warmth.Warmth.WARM: [
        "@1 ponders @2 with the soft attention of someone holding a thought about them.",
        "@1 watches @2 a while, a small private consideration settling behind @1a eyes.",
        "@1 turns a kind thought over about @2 and keeps it to @1r.",
        "@1 holds @1a gaze on @2 the way one holds a pleasant memory.",
    ],
    warmth.Warmth.HOT: [
        "@1 looks at @2 long enough that the looking itself becomes the thought.",
        "@1 ponders @2 with the slow certainty of knowing them through.",
        "@1 watches @2 the way one watches kin do the small ordinary things.",
        "@1 holds @2 in @1a thinking unhurried, the thought already half a memory.",
    ],
}

_PONDER_ACCEPTANCE_BEATS: Dict[str, List[str]] = {
    warmth.Warmth.COLD: [
        "@2 doesn't return the look.",
        "@2 keeps @2a face turned and offers nothing back.",
        "@2 lets the consideration pass straight through without registering.",
        "@2 holds @2a own counsel and the look finds no purchase.",
    ],
    warmth.Warmth.COOL: [
        "@2 lets the consideration pass without acknowledging it.",
        "@2 catches the look out of the corner of @2a eye and keeps moving.",
        "@2 notices and chooses not to.",
        "@2 keeps @2a own thoughts and gives @1 no opening into them.",
    ],
    warmth.Warmth.NEUTRAL: [
        "@2 lets @1 think, untroubled by being seen.",
        "@2 catches the look once and goes back to what held @2o.",
        "@2 stays as @2 was, neither inviting the thought nor refusing it.",
        "@2 returns the gaze briefly and lets it close.",
    ],
    warmth.Warmth.WARM: [
        "@2 meets the look briefly, accepts it, lets it go.",
        "@2 catches @1np eye and a small smile passes between them.",
        "@2 returns the look long enough to be seen back.",
        "@2 lets the thought land, lets @1 keep it.",
    ],
    warmth.Warmth.HOT: [
        "@2 holds @1np gaze with the unhurried recognition of being known.",
        "@2 returns the look the way old kin return a look — already in on the thought.",
        "@2 lets @1 think, and lets @1 see @2 thinking the same thing back.",
        "@2 meets @1np eyes and the silence between them does the rest.",
    ],
}

_TEND_INTENT_BEATS: Dict[str, List[str]] = {
    warmth.Warmth.COLD: [
        "@1 reaches to tend @2 and stops short of touching.",
        "@1 makes the gesture of caretaking but lets the hand fall before it lands.",
        "@1 lifts a hand toward @2np cloak and thinks better of it.",
        "@1 starts to fix something on @2 and pulls back, hand half-curled.",
    ],
    warmth.Warmth.COOL: [
        "@1 offers @2 a small, careful caretaking gesture from a distance.",
        "@1 reaches across the space to flick a leaf off @2np shoulder, hand barely there.",
        "@1 nudges @2np strap straight with the back of one knuckle.",
        "@1 picks at a stray thread on @2np sleeve and lets the hand withdraw.",
    ],
    warmth.Warmth.NEUTRAL: [
        "@1 tends to a strap on @2np shoulder, brief and practical.",
        "@1 fixes a buckle on @2np pack with quiet efficiency.",
        "@1 straightens @2np collar with two fingers and steps back.",
        "@1 picks a burr from @2np sleeve and flicks it aside.",
    ],
    warmth.Warmth.WARM: [
        "@1 brushes a smudge of dirt from @2np cheek with the back of one wrist.",
        "@1 settles @2np hood for @2o with both hands, careful at the cloth.",
        "@1 picks a leaf out of @2np hair, taking the time to do it gently.",
        "@1 smooths @2np collar with the unhurried hand of someone glad to.",
    ],
    warmth.Warmth.HOT: [
        "@1 takes the edge of @2np cloak and resettles it for @2o, unhurried.",
        "@1 sits @2 down and works a knot out of @2np shoulder with both thumbs.",
        "@1 takes @2np hand and turns it over, tending a scrape without asking.",
        "@1 fusses with @2np collar and hair and sleeve in the practiced order of long care.",
    ],
}

_TEND_ACCEPTANCE_BEATS: Dict[str, List[str]] = {
    warmth.Warmth.COLD: [
        "@2 steps clear before the gesture lands.",
        "@2 turns @2a shoulder away and the hand finds nothing.",
        "@2 lifts a palm — \"don't\" — and the caretaking stops.",
        "@2 brushes the reach aside and keeps moving.",
    ],
    warmth.Warmth.COOL: [
        "@2 lets the gesture happen without quite welcoming it.",
        "@2 holds still for the fix and goes back to what held @2o.",
        "@2 tolerates the small caretaking with a brief, neutral nod.",
        "@2 allows the touch a beat, then steps a half-pace clear.",
    ],
    warmth.Warmth.NEUTRAL: [
        "@2 holds still for the moment of caretaking, then nods @1 off.",
        "@2 lets the small fix happen and offers a quiet \"thanks.\"",
        "@2 stays put for the gesture and goes on with @2a evening.",
        "@2 accepts the small care plainly and moves on.",
    ],
    warmth.Warmth.WARM: [
        "@2 lets @1 do the small thing, the gesture received the way it was meant.",
        "@2 leans into the touch a fraction and lets the cloth be set right.",
        "@2 catches @1np wrist and squeezes once in thanks before letting go.",
        "@2 stays still and lets the caretaking land, fond.",
    ],
    warmth.Warmth.HOT: [
        "@2 lets @1 tend without comment, the way old kin lets old kin.",
        "@2 closes @2a eyes and lets @1 work the knot out, unhurried.",
        "@2 sets @2a hand over @1np a moment in the middle of it, and lets the work continue.",
        "@2 lets @1 fuss the whole circuit — collar, hair, cuffs — and breathes out at the end.",
    ],
}

_BITE_INTENT_BEATS: Dict[str, List[str]] = {
    warmth.Warmth.COLD: [
        "@1 nips at the air sharply in @2np direction.",
        "@1 clicks @1a teeth shut once toward @2.",
        "@1 bares @1a teeth in a brief, pointed snap aimed at @2.",
        "@1 makes a sharp little bite-shape in the air between @1r and @2.",
    ],
    warmth.Warmth.COOL: [
        "@1 catches @1a own lip and looks at @2 sidelong.",
        "@1 sets @1a teeth in @1a own knuckle, eyes flicking to @2.",
        "@1 worries the inside of @1a cheek and glances at @2.",
        "@1 nibbles the edge of @1a thumb and watches @2 from the corner of @1a eye.",
    ],
    warmth.Warmth.NEUTRAL: [
        "@1 nips at the air near @2.",
        "@1 catches @1a own thumb between @1a teeth, half-attentive to @2.",
        "@1 chews the inside of @1a lip, eyes on @2.",
        "@1 makes a small, idle bite-shape in @2np general direction.",
    ],
    warmth.Warmth.WARM: [
        "@1 catches @1a own thumb in @1a teeth, eyes on @2.",
        "@1 mock-bites at the air a hand's width from @2np shoulder.",
        "@1 nips lightly at @1a own lip and glances at @2.",
        "@1 makes a small play-bite shape in @2np direction.",
    ],
    warmth.Warmth.HOT: [
        "@1 mock-snaps in @2np direction with the easy threat of long companionship.",
        "@1 nips at the air a finger-width from @2np ear and shows teeth.",
        "@1 clacks @1a teeth shut at @2 in the long-running joke between them.",
        "@1 bares @1a teeth in @2np direction the way kin bares teeth at kin — full play.",
    ],
}

_BITE_ACCEPTANCE_BEATS: Dict[str, List[str]] = {
    warmth.Warmth.COLD: [
        "@2 turns @2a face fully aside; the gesture finds nothing to land on.",
        "@2 steps a half-pace clear and gives the snap nowhere to go.",
        "@2 levels a flat look at @1 and the bite-shape dies in the air.",
        "@2 doesn't dignify it, and the snap goes unanswered.",
    ],
    warmth.Warmth.COOL: [
        "@2 lets it pass without engaging.",
        "@2 catches the gesture out of the corner of @2a eye and ignores it.",
        "@2 stays unbothered and goes back to what held @2o.",
        "@2 acknowledges the snap with the smallest dry blink.",
    ],
    warmth.Warmth.NEUTRAL: [
        "@2 raises an eyebrow, unbothered.",
        "@2 catches the snap and lets it land on nothing in particular.",
        "@2 huffs once through @2a nose and stays where @2 is.",
        "@2 acknowledges the gesture with a small, even tilt of @2a head.",
    ],
    warmth.Warmth.WARM: [
        "@2 huffs a small dry laugh.",
        "@2 swats at @1np shoulder, the corner of @2a mouth twitching up.",
        "@2 returns the bite-shape lazily — a slow chew on @2a own lip.",
        "@2 catches @1np eye and shakes @2a head.",
    ],
    warmth.Warmth.HOT: [
        "@2 mock-snaps back, the play long since established between them.",
        "@2 clacks @2a teeth at @1 twice in answer and grins.",
        "@2 catches @1np shoulder and pretend-bites at it, both of them laughing.",
        "@2 nips at the air a finger-width from @1np jaw, fully in on the joke.",
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
    "thank":     (_THANK_INTENT_BEATS, _THANK_ACCEPTANCE_BEATS),
    # Presence verbs (V2 warmth-aware, 2026-05-06 — see
    # `project_presence_verbs_with_target.md`).
    "lean":      (_LEAN_INTENT_BEATS, _LEAN_ACCEPTANCE_BEATS),
    "sit":       (_SIT_INTENT_BEATS, _SIT_ACCEPTANCE_BEATS),
    "rest":      (_REST_INTENT_BEATS, _REST_ACCEPTANCE_BEATS),
    "ponder":    (_PONDER_INTENT_BEATS, _PONDER_ACCEPTANCE_BEATS),
    "tend":      (_TEND_INTENT_BEATS, _TEND_ACCEPTANCE_BEATS),
    "bite":      (_BITE_INTENT_BEATS, _BITE_ACCEPTANCE_BEATS),
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
# Per-command italic-fallback when the player invokes bare with
# no target / mention. Wrapped as a single-element ``self_directed_pool``
# by :meth:`_dispatch_warmth_aware_verb` and rendered through the
# dispatcher's parser pipeline — values use parser tokens (``@1``)
# rather than Python format strings.
_BARE_NO_TARGET_TEMPLATES: Dict[str, str] = {
    "high_five": "*@1 raises a palm to nobody in particular.*",
    "fistbump":  "*@1 holds out a fist to nobody in particular.*",
    "salute":    "*@1 salutes the empty air with crisp formality.*",
    "comfort":   "*@1 reaches out to comfort nobody in particular.*",
    "poke":      "*@1 pokes at the air with one intrepid finger.*",
    "nod":       "*@1 nods solemnly at the middle distance.*",
    "glare":     "*@1 glares at a nearby wall; the wall holds its ground.*",
    "shank":     "*@1 mimes a playful shank at thin air, which takes it well.*",
    "tickle":    "*@1 wiggles mischievous fingers at the empty air.*",
    "taunt":     "*@1 jeers at nobody in particular, to stunned silence.*",
    "wink":      "*@1 winks conspiratorially at an unoccupied chair.*",
    "thank":     "*@1 murmurs a quiet thanks to no one in particular.*",
}


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
    "thank":     "@1 thanks @1r quietly for whatever it was. The thanks holds.",
    # Presence verbs — self-target short-circuit. Emotion-neutral
    # per `project_verb_adverb_coloring.md`; bare-self-directed
    # pools in rpg_presence_commands.py already carry richer
    # texture, so these are deliberately spare.
    "lean":      "@1 leans against @1a own arm a moment.",
    "sit":       "@1 sits down where @1s is.",
    "rest":      "@1 rests for a beat, eyes half-closing.",
    "ponder":    "@1 ponders the middle distance.",
    "tend":      "@1 tends to a strap on @1a own coat.",
    "bite":      "@1 worries at @1a lower lip.",
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
        # $hug carries unique fallbacks for the bare and bad-token
        # cases ($hug with no args → "hugs the air awkwardly"; $hug
        # arbitrary-text → narrates the text as the gesture object).
        # Doppelganger-disguise routing (mentioned player's
        # display_name matches an active monster's name) is handled
        # by the unified resolver; bot-mention scripted reply,
        # dead-target on_hugged path, and warmth-aware render are
        # handled by the wrapper + Player.handle_verb.
        await self._dispatch_warmth_aware_verb(
            ctx, "hug",
            msg=msg,
            bare_template="*@1 hugs the air awkwardly.*",
            bad_token_template="*{name} hugs {target}*",
        )

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
    async def high_five(self, ctx: Context, *, msg: str = None):
        """
        Raises a palm for another player or NPC to meet. The way the
        exchange reads depends on the *target's* warmth preference
        for ``high_five`` and the *actor's* intent.

        Bare ``$high_five`` is self-directed. ``$high_five @player``
        routes via @-mention. ``$high_five <token>`` (e.g. a passerby
        name or active monster) routes through the verb-dispatch
        chain — falls through to the "doesn't react" miss line if
        the responder doesn't carry a ``high_five`` reaction.

        (5-second cool-down)

        :param msg: A target name to high-five, or omit for self-
            directed.
        """
        await self._dispatch_warmth_aware_verb(ctx, "high_five", msg=msg)

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
    async def fistbump(self, ctx: Context, *, msg: str = None):
        """
        Offers a knuckle for another player or NPC to meet. The way
        the exchange reads depends on the *target's* warmth
        preference for ``fistbump`` and the *actor's* intent.

        Bare ``$fistbump`` is self-directed. ``$fistbump @player``
        routes via @-mention. ``$fistbump <token>`` (passerby /
        monster) routes through the verb-dispatch chain.

        (5-second cool-down)

        :param msg: A target name to bump, or omit for self-directed.
        """
        await self._dispatch_warmth_aware_verb(ctx, "fistbump", msg=msg)

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
    async def salute(self, ctx: Context, *, msg: str = None):
        """
        Salutes another player or NPC — military / chivalric in tone.
        The exact reading depends on the target's ``salute`` warmth
        (which governs acceptance) and the actor's intent.

        Bare ``$salute`` is self-directed. ``$salute @player`` routes
        via @-mention. ``$salute <token>`` (passerby / monster) routes
        through the verb-dispatch chain.

        (5-second cool-down)

        :param msg: A target name to salute, or omit for self-directed.
        """
        await self._dispatch_warmth_aware_verb(ctx, "salute", msg=msg)

    @command(
        name="comfort",
        aliases=["console", "soothe"],
        brief="Offer tender reassurance to a fellow adventurer.",
    )
    @guild_only()
    @cooldown(1, 5, BucketType.member)
    async def comfort(self, ctx: Context, *, msg: str = None):
        """
        Offers comfort to another player or NPC — a hand on the
        shoulder, a gentle word. Defaults warm: comfort is usually
        accepted.

        Bare ``$comfort`` is self-directed. ``$comfort @player``
        routes via @-mention. ``$comfort <token>`` (passerby /
        monster) routes through the verb-dispatch chain.

        (5-second cool-down)

        :param msg: A target name to comfort, or omit for self-directed.
        """
        await self._dispatch_warmth_aware_verb(ctx, "comfort", msg=msg)

    @command(
        name="poke",
        aliases=["prod", "boop"],
        brief="Poke a fellow adventurer for attention.",
    )
    @guild_only()
    @cooldown(1, 5, BucketType.member)
    async def poke(self, ctx: Context, *, msg: str = None):
        """
        Pokes another player or NPC. Mildly annoying by default —
        tune your warmth if you invite pokes routinely.

        Bare ``$poke`` is self-directed. ``$poke @player`` routes via
        @-mention. ``$poke <token>`` (passerby / monster) routes
        through the verb-dispatch chain.

        (5-second cool-down)

        :param msg: A target name to poke, or omit for self-directed.
        """
        await self._dispatch_warmth_aware_verb(ctx, "poke", msg=msg)

    @command(
        name="nod",
        aliases=["acknowledge"],
        brief="Offer a silent nod of acknowledgement.",
    )
    @guild_only()
    @cooldown(1, 5, BucketType.member)
    async def nod(self, ctx: Context, *, msg: str = None):
        """
        Nods at another player or NPC — a small, silent acknowledgement.

        Bare ``$nod`` is self-directed. ``$nod @player`` routes via
        @-mention. ``$nod <passerby>`` (e.g. ``$nod wagoneer``) routes
        to the present NPC's warmth-keyed reaction pool.

        (5-second cool-down)

        :param msg: A passerby's name to nod at, or omit to nod at
            no one in particular.
        """
        await self._dispatch_warmth_aware_verb(ctx, "nod", msg=msg)

    @command(
        name="glare",
        aliases=["scowl"],
        brief="Level a hostile stare at another adventurer.",
    )
    @guild_only()
    @cooldown(1, 5, BucketType.member)
    async def glare(self, ctx: Context, *, msg: str = None):
        """
        Glares at another player or NPC. Hostile by default —
        cold-accept reads as stare-back-match.

        Bare ``$glare`` is self-directed. ``$glare @player`` routes
        via @-mention. ``$glare <token>`` (e.g. ``$glare bandit``)
        routes through the verb-dispatch chain — monsters without a
        ``glare`` SOCIAL_REACTION fall through to the bland
        "doesn't react" miss line.

        (5-second cool-down)

        :param msg: A target name to glare at, or omit for self-directed.
        """
        await self._dispatch_warmth_aware_verb(ctx, "glare", msg=msg)

    @command(
        name="shank",
        aliases=["stab"],
        brief="Mock-stab a fellow adventurer — playful, not actually violent.",
    )
    @guild_only()
    @cooldown(1, 5, BucketType.member)
    async def shank(self, ctx: Context, *, msg: str = None):
        """
        Mimes a playful stabbing motion at another player or NPC.
        Most players default to rejecting the bit — flip your warmth
        to ``warm`` or ``hot`` to opt in to the full Shakespearean
        death-scene treatment.

        Bare ``$shank`` is self-directed. ``$shank @player`` routes
        via @-mention. ``$shank <token>`` (passerby / monster) routes
        through the verb-dispatch chain.

        (5-second cool-down)

        :param msg: A target name to shank, or omit for self-directed.
        """
        await self._dispatch_warmth_aware_verb(ctx, "shank", msg=msg)

    @command(
        name="tickle",
        aliases=["tickles"],
        brief="Tickle a fellow adventurer.",
    )
    @guild_only()
    @cooldown(1, 5, BucketType.member)
    async def tickle(self, ctx: Context, *, msg: str = None):
        """
        Tickles another player or NPC. Tolerated from close friends,
        rejected by most — tune your warmth accordingly.

        Bare ``$tickle`` is self-directed. ``$tickle @player`` routes
        via @-mention. ``$tickle <token>`` (passerby / monster) routes
        through the verb-dispatch chain.

        (5-second cool-down)

        :param msg: A target name to tickle, or omit for self-directed.
        """
        await self._dispatch_warmth_aware_verb(ctx, "tickle", msg=msg)

    @command(
        name="taunt",
        aliases=["jeer", "mock"],
        brief="Taunt a fellow adventurer.",
    )
    @guild_only()
    @cooldown(1, 5, BucketType.member)
    async def taunt(self, ctx: Context, *, msg: str = None):
        """
        Taunts another player or NPC. Hostile by default; warm
        targets treat it as banter.

        Bare ``$taunt`` is self-directed. ``$taunt @player`` routes
        via @-mention. ``$taunt <token>`` (passerby / monster) routes
        through the verb-dispatch chain.

        (5-second cool-down)

        :param msg: A target name to taunt, or omit for self-directed.
        """
        await self._dispatch_warmth_aware_verb(ctx, "taunt", msg=msg)

    @command(
        name="wink",
        aliases=["winks"],
        brief="Wink at a fellow adventurer — flirty or conspiratorial.",
    )
    @guild_only()
    @cooldown(1, 5, BucketType.member)
    async def wink(self, ctx: Context, *, msg: str = None):
        """
        Winks at another player or NPC — could be flirty, could be
        conspiratorial, depends on who you ask.

        Bare ``$wink`` is self-directed. ``$wink @player`` routes via
        @-mention. ``$wink <token>`` (passerby / monster) routes
        through the verb-dispatch chain.

        (5-second cool-down)

        :param msg: A target name to wink at, or omit for self-directed.
        """
        await self._dispatch_warmth_aware_verb(ctx, "wink", msg=msg)

    @command(
        name="thank",
        aliases=["thanks", "ty"],
        brief="Offer thanks to another player or NPC.",
    )
    @guild_only()
    @cooldown(1, 5, BucketType.member)
    async def thank(self, ctx: Context, *, msg: str = None):
        """
        Thank another player, monster, or passerby. WARM by default —
        most targets accept gratitude graciously, though a player who
        prefers stoicism can tune ``$warmth set thank cool``.

        (5-second cool-down)

        :param msg: Either a target (a passerby's name, a monster's
            noun) or a @mention of another player. Bare ``$thank``
            offers a quiet, self-directed thanks.
        """
        await self._dispatch_warmth_aware_verb(ctx, "thank", msg=msg)

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
    async def wave(self, ctx: Context, *, target: str = None):
        """
        Wave — hello, goodbye, I see you, what have you.

        Bare ``$wave`` is self-directed (the player waves at the
        clearing). ``$wave <passerby>`` (e.g. ``$wave wagoneer``)
        routes to the present NPC's warmth-keyed reaction pool.
        ``$wave <unknown>`` falls back to a self-directed line with
        a "(at no one in particular)" tag so the gesture isn't
        silently dropped.

        (5-second cool-down)

        :param target: A passerby's name to wave at, or omit to
            wave at no one in particular.
        """
        # $wave deliberately ignores Discord mentions — players
        # naturally type "$wave @Caels" but the gesture stays
        # self-directed (mention is audience-acknowledgement, not
        # a verb target). Bypass the warmth-wrapper's mention
        # extraction by calling dispatch_expressive_verb directly
        # with mention=None.
        game, player = await RpgUtilities.get_game_and_player(ctx)
        if game is None or player is None:
            return
        if RpgUtilities.dead_invoker_guard(
            game.channel, player, _DEAD_INVOKER_FLAVOR.get("wave", []),
        ):
            return
        await dispatch_expressive_verb(
            ctx, "wave",
            target_token=target,
            mention=None,
            self_directed_pool=_SELF_DIRECTED_POOLS["wave"],
            bad_token_template="*{name} waves at no one in particular.*",
        )

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

    @command(
        name="greet",
        aliases=["introduce"],
        brief="Greet a passerby and introduce yourself.",
    )
    @guild_only()
    @cooldown(1, 5, BucketType.member)
    async def greet(self, ctx: Context, *, target: str = None):
        """
        Greet a present passerby NPC. The first greet is the
        explicit introduction — the NPC learns what to call you.
        Subsequent greets render with full acquaintance, the way
        people who know each other meet on the road.

        (5-second cool-down)

        :param target: A passerby's name (e.g. ``$greet wagoneer``).
        """
        # $greet has a special silhouette-too-far line: when the
        # target token matches a pending-silhouette NPC (visible
        # in $look but at distance), render "too far off" rather
        # than the standard "introduces to nobody" italic. Run the
        # silhouette check INLINE before falling into the wrapper
        # so the dispatch chain doesn't accidentally render the
        # wrong fallback when the silhouette doesn't claim the verb.
        game, player = await RpgUtilities.get_game_and_player(ctx)
        if game is None or player is None:
            return
        if target:
            from caldanai.lib.rpg.helpers.resolvers import (
                resolve_pending_silhouette,
            )
            silhouette = resolve_pending_silhouette(game, target.split(None, 1)[0])
            if silhouette is not None:
                Dispatcher.add(
                    game.channel,
                    parse(
                        "@1Dc is too far off across the clearing to hear; "
                        "wait until @1s approaches.",
                        silhouette,
                    ),
                )
                return

        await self._dispatch_warmth_aware_verb(
            ctx, "greet",
            msg=target,
            bare_template="*@1 introduces @1r to nobody in particular.*",
            bad_token_template="*{name} introduces {name} to nobody in particular.*",
        )

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

    async def _dispatch_warmth_aware_verb(
        self,
        ctx: Context,
        cmd: str,
        *,
        msg: Optional[str] = None,
        bare_template: Optional[str] = None,
        self_directed_pool: Optional[List[str]] = None,
        bad_token_template: Optional[str] = None,
    ) -> None:
        """Cog-side wrapper for warmth-aware social verbs.

        Thin layer over :func:`dispatch_expressive_verb` — extracts
        a Discord ``@mention`` from the message (forwarding text as
        ``msg`` when no mention is present) and supplies the per-cmd
        bare-no-target template. Bot-mention routing and
        doppelganger-disguise checks live inside the dispatcher's
        unified mention path.

        ``msg`` is the raw text token / target (passed via
        ``$hug <text>`` or ``$wave <text>``). Used as the fuzzy
        text-target for NPC / monster routing when no @mention is
        present.

        ``bare_template`` is a parser-token-formatted line used
        when both no mention and no text are supplied. Defaults
        from :data:`_BARE_NO_TARGET_TEMPLATES` keyed by ``cmd``.

        ``bad_token_template`` (Python ``str.format`` with
        ``{name}``/``{verb}``/``{target}`` placeholders) is the
        line shown when text is supplied but no responder claimed
        the verb. Defaults to the dispatcher's standard "nothing
        here by the name X" miss line.
        """
        # Bot-mention handling and doppelganger-disguise routing
        # both happen inside :func:`dispatch_expressive_verb`'s
        # mention path now (BotResponder for bot, monster for the
        # disguise case). The cog wrapper just extracts the first
        # mention from the message and forwards.
        mentions = ctx.message.mentions or []
        mention = mentions[0] if mentions else None
        target_token = None if mention else msg

        # Bare-invocation pool. Caller's explicit
        # ``self_directed_pool`` wins (used by $wave for its
        # multi-line texture pool). Otherwise wrap a single
        # ``bare_template`` line — falls back to the per-cmd
        # default in :data:`_BARE_NO_TARGET_TEMPLATES`.
        bare_pool = self_directed_pool
        if bare_pool is None:
            if bare_template is None:
                bare_template = _BARE_NO_TARGET_TEMPLATES.get(cmd)
            if bare_template is not None:
                bare_pool = [bare_template]

        await dispatch_expressive_verb(
            ctx, cmd,
            target_token=target_token,
            mention=mention,
            dead_invoker_pool=_DEAD_INVOKER_FLAVOR.get(cmd, []),
            self_directed_pool=bare_pool,
            bad_token_template=bad_token_template,
        )

    # -----------------------------------------------------------------
    # $haunt — moved verbatim from rpg_user_commands.py
    # -----------------------------------------------------------------

    @cooldown(1, 5, BucketType.member)
    @guild_only()
    @command(name="haunt", brief="Allows the dead to harass the less-dead.")
    async def haunt(self, ctx: Context, target: str = None):
        """
        Allows the dead to harass the less-dead. When specifying a target, use the @ symbol to target another player or a fuzzy monster name (e.g. ``$haunt hyd`` against a hexed hydra).

        (5-second cool-down)

        :param target: An optional victim of your haunting; either a player using @mentions, or the name (or fuzzy prefix) of the current monster.
        """
        game, player = await RpgUtilities.get_game_and_player(ctx)
        if game is None or player is None:
            return

        # Bot-mention reject stays at the call site: identifying the
        # bot user is haunt-specific UX, not converter logic. Pre-
        # checking here keeps the "figment of your imagination" line
        # out of the converter layer entirely.
        mentions = ctx.message.mentions or []
        if target is not None and self.bot.user in mentions:
            Dispatcher.add(
                game.channel,
                parse("You cannot haunt a figment of your imagination, @1.", player),
            )
            return

        # ``CreatureConverter`` resolves either an active monster or
        # a fellow player from one string. ``prefer="monster"`` (the
        # default) matches the in-fiction priority: a ghost haunts a
        # creature in scene before a name-collision player.
        # ``$haunt @Caels`` flows through the same call — mention
        # syntax misses MonsterConverter and hits PlayerConverter's
        # mention fast-path. On full miss we fall through to the
        # no-target ambient pool below — silent fall-through is the
        # dispatcher's whole point and the UX the BadArgument-raising
        # shape couldn't support.
        haunted = None
        if target:
            haunted = await fuzzy_resolve(ctx, target, CreatureConverter)

        if haunted is not None:
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
        who: FuzzyMemberConverter = None,
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
        who: FuzzyMemberConverter = None,
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

    @Cog.listener()
    async def on_message(self, message):
        """Acquaintance-by-mention learning event for any present
        passerby NPC. When an in-channel message ``<@!id>``-mentions
        another *registered player* on a channel that has a passerby
        present (or pending in silhouette), the NPC learns that
        player's name. Pure mention parsing — no fuzzy-name detection
        from prose.

        Filtered to channels with a Game routed to them, so the
        per-message overhead in non-game channels is one ``dict.get``
        miss. Self-authored messages and bot messages are skipped
        outright; they don't count as "another player addressed me
        by name."

        For each newly-acquainted player, dispatches one line from
        the NPC's ACQUAINTANCE_CUE_POOL — surfaces the otherwise-
        silent learning channel so the player sees evidence the NPC
        now knows their name.
        """
        if message.author.bot:
            return
        if message.guild is None:
            return
        # Lazy imports avoid pulling the rpg package into the cog
        # module-load path. Both modules are cheap to import after
        # the bot's already running.
        from caldanai.lib.rpg import Game
        from caldanai.lib.rpg.creatures.passersby.spawn import overhear_mentions

        game = Game.for_channel(message.channel.id)
        if game is None:
            return
        npc = game.passerby or game.pending_silhouette
        if npc is None:
            return
        try:
            newly_acquainted = overhear_mentions(game, message)
        except Exception:
            _log.exception("overhear_mentions raised; ignoring")
            return

        # Per-player cue dispatch — one italicized line per newly-
        # learned face. Resolves the player object from the game's
        # roster so the parser can render @2 with the right name +
        # pronouns. Silently skips if the player isn't resolvable
        # (race condition: player left between mention-overhear and
        # cue-dispatch).
        cue_pool = getattr(npc, "ACQUAINTANCE_CUE_POOL", [])
        if not cue_pool:
            return
        for player_id in newly_acquainted:
            learned_player = game.player_manager.players.get(player_id)
            if learned_player is None:
                continue
            Dispatcher.add(
                game.channel,
                parse(choice(cue_pool), npc, learned_player),
            )


async def setup(bot):
    await bot.add_cog(RpgSocialCommands(bot))
