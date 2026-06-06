"""Wren — an errand-runner who passes messages between the farms,
the trading-post, and the granny three valleys over. Sharp-eyed,
observational, slightly cynical-beyond-years. Has a pocketful of
small bribes (a copper coin, a sweet, a feather, a clever bird-
shaped stone) for greasing adult conversations.

Voice register: chirpy, sharp, world-wise. Drops names of unseen
adults and places casually — old Marn at the ferry-house, Master
Halrick at the granary, the granny three valleys over, the
trading-post north. Each line of hers EXPANDS Mendholm by
implication: she's how the clearing reaches the rest of the
world without us having to ship those places yet.

Repeats things she's overheard with the wrong inflection
(childlike misreading of adult speech). Knows everyone's
business. Will tell you the gossip if you bribe her with a
greeting; will tell you nothing if you've crossed her.

The first NAMED passerby — uses_article=False, name="Wren". Her
having a name (vs. the wagoneer / herbalist / shepherd, who are
generic-typed) is a meaningful design beat: she's the one Vael's
"twice a season and remembers our faces" line hangs on most
naturally. Future named passersby will follow her shape.

Parser tokens: ``@1`` = the actor (player) when used in social
reactions; the NPC referenced by name "Wren" inline. Higher
NAMING_BIAS (0.7) than the others — errand-runners use names
readily; that's their job. They still occasionally fall back to
"traveler" when she's being formal or busy.
"""
from typing import Dict, List

from caldanai.lib.rpg.creatures.passersby import PasserbyPlugin
from caldanai.lib.rpg.helpers.enums import TimePartitions
from caldanai.lib.rpg.helpers.warmth import Warmth


class Wren(PasserbyPlugin):
    name = "Wren"
    uses_article = False  # Proper-named — "Wren," not "the Wren"
    gender = "female"
    pronouns = "she,her,hers,her,herself"

    ALIASES = ["errand-runner", "messenger-child"]

    # Errand-running is daylight work — kids don't run messages
    # in the dark, even brave ones. Dawn to evening; she's
    # expected home by sundown. Halrick (whoever he is) wouldn't
    # like it if she were caught out at dusk.
    time_partition = TimePartitions.DIURNAL

    # Errand-runners use names readily — knowing names is the job.
    # Higher than the wagoneer's 0.85 because she leans even more on
    # named address; lower than 1.0 because she occasionally
    # affects formal-traveler manners when she wants something.
    NAMING_BIAS = 0.7

    # Name-drop keyword bias on the DEPARTURE_POOL. When the player
    # mentions "Marn" or "Halrick" in chat during Wren's visit, the
    # matching pool line is heavily favored at depart-time — so the
    # name-drops in lines 81-82 feel keyword-responsive rather than
    # 1-in-6 lottery draws. Both lines exist in the canonical pool
    # already; this just makes Wren actually carry the message
    # to the named adult she's heading toward.
    NAME_DROP_KEYWORDS: Dict[str, str] = {
        "marn": "Marn",
        "halrick": "Halrick",
    }

    ARRIVAL_POOL: List[str] = [
        "A girl trots into the clearing at the unhurried pace of someone running a message and willing to wait until she's noticed. A leather satchel bumps her hip; her face is sharp under a mop of dark hair.",
        "A child arrives at the verge with the official-looking gait of someone who's been on errands since she was old enough to remember addresses. @1S plants herself, surveys the adventurers, nods like she's confirming a list.",
        "@1 swings into the clearing from the south path with the brisk efficiency of a kid who's done this route a hundred times. She stops, scans, finds nothing she was specifically expecting, but settles in regardless.",
        "A messenger-child appears at the willow at the verge, satchel bouncing. @1S leans against the trunk and gives the clearing a long, professional once-over.",
        "@1 slips out of the trees at the east verge, mid-conversation with herself. \"...and Halrick said the cooper said, but the cooper was DRUNK, so —\" She trails off, sees company, smiles with all her teeth.",
        "A girl in an oversized brown coat tromps into the clearing, satchel slung crossways. The coat was somebody's father's, once. @1S has grown into the shoulders, not the length.",
        "@1 arrives at the pace of a sparrow with somewhere to be. She perches on a stump at the verge, swings her legs, and waits for the clearing to notice her professionally.",
        "A child rolls out of the brush at the south verge, having taken an off-path shortcut she's clearly not supposed to know. @1S brushes leaves off her coat with practiced indignation.",
        "@1 skips into the clearing humming something tuneless and slightly off, satchel knocking against her hip. \"...don't tell Halrick I said,\" she's muttering, \"don't tell Halrick I said...\"",
        "A girl trots in with her satchel hugged against her chest like it contains state secrets. It mostly contains a copper, two feathers, a flat stone, and a heel of bread.",
    ]

    AMBIENT_POOL: List[str] = [
        "@1 reaches into her satchel, considers her treasures one by one — copper, feather, bird-shaped stone — and tucks them all carefully back.",
        "@1 perches on a stump and counts something on her fingers under her breath. \"Three from Marn, two for the granary, one for...\" She loses her place, starts over.",
        "@1 mutters bits of an overheard adult sentence to herself with the wrong inflections, trying to remember it right. \"The CART won't go, the cart WON'T go, the cart won't GO —\"",
        "@1 kicks her heels against the stump, pulls a small bird-feather out of her pocket, twirls it, slides it back.",
        "@1 scans the clearing the way she's seen serious adults do, eyebrows lowered, lips pursed. She's clearly mimicking somebody. The somebody is not present to be embarrassed.",
        "@1 extracts a heel of dark bread from her satchel, eats it efficiently, brushes the crumbs off her coat with a satisfied air.",
    ]

    DEPARTURE_POOL: List[str] = [
        "@1 springs to her feet, slaps her satchel closed, and announces to nobody: \"Got to get to Halrick before sundown.\" She's already moving as the sentence finishes.",
        "@1 springs off the stump, slaps her satchel closed: \"Old Marn's at the ferry-house, and I'm late.\" She's already moving south.",
        "@1 hops to her feet, shoulders her satchel. \"Got to get to Marn at the ferry by sundown — he worries.\" She's already on the south path.",
        "@1 trots toward the south path, calling back over her shoulder: \"If I'm not at the ferry by sundown Marn'll send someone, and that someone will be me tomorrow.\"",
        "@1 tucks her treasures back into her satchel one by one — a small ceremony — and departs the way she came, humming.",
        "@1 bounces off the stump, salutes the clearing with one too-formal hand, and vanishes back into the brush.",
        "@1 leaves at her trotting pace, already mid-conversation with the next person she expects to see, who is half a valley away.",
        "@1 slings her satchel, gives the clearing a brisk professional nod, and is gone before her own footprints have settled.",
    ]

    SILHOUETTE_POOL: List[str] = [
        "At the verge, a small figure with a satchel skids to a halt, takes in the noise, and prudently sits behind a stump to wait.",
        "@1 peers around the trunk of the willow with wide-eyed professional caution. She's seen worse. She's seen better. She rates the situation a four out of ten and stays put.",
        "Up the south path, a girl in an oversized coat plants herself at a safe distance and watches with the unblinking attention of someone storing details to retell later.",
        "A child's silhouette at the brush-line — @1, satchel hugged tight, lips moving as she narrates the fight under her breath like a wardroom report.",
        "@1 freezes mid-trot at the verge, drops to a crouch, and watches with the stillness of a small animal that has not yet decided whether to flee.",
    ]

    # Reactive flavor for witnessing a passive-monster kill (sheep
    # today). Wren goes quiet — the kid who chirps about everything
    # has nothing to chirp about for this. Authored as starting
    # voice; revise to taste.
    PASSIVE_KILL_REACTIONS: Dict[str, List[str]] = {
        "*": [
            "@1np chirp dies. She stares at the body, then at @2, then at the body again. She doesn't say anything. She just turns and walks back the way she came — walking instead of running for the first time @2 has seen.",
            "@1np hand goes to her satchel like she's looking for something to give back, but there's nothing there. \"I won't tell Halrick this one,\" she says, quiet, almost to herself. \"He doesn't need to know everyone.\"",
            "@1 crosses to the body and touches it with two fingers, careful. She looks up at @2 with the wide-eyed grave expression she usually saves for sermons-overheard. \"That was alive,\" she says. \"I knew it was alive.\"",
            "@1 sits down on a stump heavily, satchel sagging, and stares at the body without speaking. After a long beat: \"I don't have words for this one. Old Marn would. I don't.\"",
        ],
    }

    COMBAT_WON_REACTIONS: List[str] = [
        "@1 bounds out of cover the moment the dust settles, eyes huge. \"OH. Oh. I'm telling EVERYONE. @2C! That's @2d who killed the BIG one. Halrick's going to want to hear this. Old Marn's going to want to hear this.\"",
        "@1 edges out cautiously, examines the carcass from a respectful three paces, and addresses @2d with sudden formality: \"That's a good kill, that. I'll mention you to the trading-post. They listen to me, sometimes.\"",
        "\"That,\" @1 says, emerging from her stump-shelter with all the gravity of a small judge, \"is the kind of thing the cooper said couldn't be done. The cooper was wrong. The cooper is OFTEN wrong.\" She nods sagely at @2d.",
        "@1 comes out grinning, satchel rattling. \"I saw it. I SAW the whole thing. @2D, I'm going to tell that one to Marn at the ferry-house tomorrow and he's going to call me a liar and I'm going to make him give me a sweet.\"",
        "@1 approaches @2d with the dignity she imagines a courier would use. \"News will be carried,\" she announces. \"Word will go. The granary will know. The granny three valleys over will know. The road remembers what it sees.\"",
        "@1 fishes a copper out of her satchel, considers it solemnly, and presses it into @2np hand. \"For your tally,\" she says, with great seriousness. \"Halrick gives me one when I bring good news. You should have one too.\"",
    ]

    COMBAT_FLED_REACTIONS: List[str] = [
        "@1 peeks out, sees the empty space where the creature was, and lets out a long whistle she's clearly practiced. \"That. Was. CLOSE. I'm telling old Marn that one for sure.\"",
        "@1 emerges trembling but trying to look professional about it. \"Walked off,\" she reports to @2d, like she's filing it. \"Walked off injured, probably. I'll keep an ear out at the ferry-house. People hear things.\"",
        "@1 scrambles up onto her stump for a better view of the path the creature took, narrows her eyes the way Halrick narrows his when he's thinking hard. \"It'll be back,\" she pronounces. \"Or it won't. Either way, you're alive. Halrick'd want me to mention that.\"",
        "@1 comes out of cover smoothing her coat indignantly. \"I was going to help. I was. The granny says you don't run TOWARD trouble unless you can carry it. I can't carry that.\"",
        "@1 hops off her stump and approaches @2d with cautious professional respect. \"You held,\" she says. \"That counts. The cooper says holding's the only thing that counts when the running's faster than you.\"",
    ]

    PARTY_DEATH_REACTIONS: List[str] = [
        "@1 creeps out of cover slowly, sees @2d, and goes very still in the way kids do when they suddenly understand a thing. Her satchel slips off her shoulder. She doesn't pick it up.",
        "@1 approaches @2d with a hesitant gravity that doesn't suit her usual chirp. \"I'll tell them,\" she says quietly. \"Marn. Halrick. The granny. They should know. The road should know.\"",
        "@1 kneels by @2d, pulls her best treasure from her satchel — a flat stone painted with a small careful bird — and lays it beside @2np head. \"For the road back,\" she says, repeating something she's heard adults say without quite knowing what it means.",
        "@1 doesn't say anything at first. She just stands at @2np side, satchel forgotten, eyes wet but stubborn. Finally: \"I'm going to mention you to everyone I run for tomorrow. Just so they know.\"",
        "@1 removes a small dried flower from her satchel — saved from somewhere, for someone — and lays it on @2np chest. \"Old Marn'll keep a place,\" she says. \"He always does. Mendholm mends. The granny says.\"",
    ]

    SOCIAL_REACTIONS: Dict[str, Dict[Warmth, List[str]]] = {
        "wave": {
            Warmth.HOT: [
                "@2 waves both arms back, satchel flying. \"@1d! Halrick was just asking about you yesterday! The cooper says hi too, probably!\"",
                "@2 bounces on her toes and waves with the hand not currently holding her satchel. \"There you are! I was going to LOOK for you if I didn't see you today!\"",
                "\"@1!\" @2 calls, beaming. She launches off her stump and waves with both hands, satchel and all.",
            ],
            Warmth.WARM: [
                "@2 waves back warmly. \"Hi @1! Old Marn says hello — he always says hello when I tell him about you.\"",
                "@2 grins and lifts a hand in answer. \"@1d. I knew you'd be around here today. The wind was right.\"",
                "@2 nods with professional satisfaction and waves. \"Knew you'd be passing.\"",
            ],
            Warmth.NEUTRAL: [
                "@2 returns the wave briskly, all business. \"Traveler.\"",
                "@2 acknowledges the wave with a small efficient flutter of her hand and goes back to her satchel.",
                "@2 raises a finger off her satchel in returned greeting, polite-runner style.",
            ],
            Warmth.COOL: [
                "@2 glances up, doesn't quite wave, and pretends to be very absorbed in her satchel-contents.",
                "@2 gives @1d the smallest possible acknowledging gesture and turns away.",
                "@2 narrows her eyes a touch and busies herself counting feathers.",
            ],
            Warmth.COLD: [
                "@2 turns her face deliberately toward the south path. The wave goes unanswered. She is, suddenly, very busy.",
                "@2 closes her satchel pointedly and pretends to be checking the sky for messenger-birds.",
                "@2 doesn't return the wave. She mutters something under her breath that sounds suspiciously like the cooper's least-flattering opinions.",
            ],
        },
        "nod": {
            Warmth.HOT: [
                "@2 nods back with the gravity of a small ambassador, then breaks into a grin she can't contain. \"@1!\"",
                "@2 returns the nod twice, satisfied. \"Aye, @1. The road's been kind today.\"",
                "@2 nods so hard her satchel rattles, and salutes for good measure.",
            ],
            Warmth.WARM: [
                "@2 returns the nod with measured warmth. \"Traveler. Halrick'd be glad to know I saw you well.\"",
                "@2 dips her head and smiles. \"@1d.\"",
                "@2 nods, slow and serious in a way she's clearly imitating from someone older.",
            ],
            Warmth.NEUTRAL: [
                "@2 nods once, all-business runner-style, and turns back to her satchel.",
                "@2 returns the nod, brisk, and resumes her watching.",
                "@2 bobs her head efficiently and moves on.",
            ],
            Warmth.COOL: [
                "@2 returns a tiny, perfunctory nod, and looks pointedly elsewhere.",
                "@2 inclines her head a fraction without meeting @1np eyes.",
                "@2Np nod, if it was one, was so small the wind might have done it.",
            ],
            Warmth.COLD: [
                "@2 stares at the ground and does not nod.",
                "@2 turns her face deliberately south and counts the trees on the horizon.",
                "@2Np jaw sets, and she pretends to consult an imaginary list. She does not nod.",
            ],
        },
        "greet": {
            Warmth.HOT: [
                "\"@1d!\" @2 explodes, scrambling off her stump. \"Halrick was JUST asking, and old Marn said you'd come through, and I told him he was wrong but he WASN'T, and —\" She runs out of breath.",
                "@2 beams, plants both hands on her hips. \"There you are! Sit down. I have NEWS. The cooper got drunk again and the ferry-house has new ropes and the granny says hello.\"",
                "\"@1!\" @2 sings. \"Tell me everything. EVERYTHING. I'll trade you. I have a copper. I have a feather. The feather's better, actually.\"",
            ],
            Warmth.WARM: [
                "@2 tips an imaginary hat with all the gravity of a small magistrate. \"Hello, @1. Halrick says good things about you.\"",
                "\"@1d,\" @2 says, smiling. \"Old Marn'll be glad to hear I crossed your path.\"",
                "@2 nods deeply. \"Greetings, traveler. Roads be kind to you.\" She's clearly imitating Halrick. The imitation is excellent.",
            ],
            Warmth.NEUTRAL: [
                "@2 returns the greeting briskly. \"Traveler.\" She means well; she's just on the clock.",
                "\"Hello,\" @2 says efficiently, already half-checking her satchel.",
                "@2 tips her chin and offers a polite-runner \"Aye.\"",
            ],
            Warmth.COOL: [
                "@2 mumbles something that might have been a greeting and pretends to need to count her feathers.",
                "@2 acknowledges the greeting with the smallest professional possible \"Mm,\" and turns to her satchel.",
                "@2Np response is the kind of greeting Halrick would call \"polite enough.\" Just barely.",
            ],
            Warmth.COLD: [
                "@2 does not return the greeting. She slings her satchel and looks pointedly down the south path, suddenly remembering somewhere she needs to be.",
                "@2 fixes her gaze on a fixed point in the middle distance. The greeting doesn't land. She doesn't pick it up.",
                "\"Working,\" @2 says flatly, and resumes counting feathers with the air of someone rewriting an unfavorable rumor in her head.",
            ],
        },
        "thank": {
            Warmth.HOT: [
                "@2 puffs up so fast her satchel rattles. \"Halrick says a thank-you well-given is worth a copper, @1d, and I've never heard him wrong.\" She salutes for emphasis.",
                "@2 beams, plants both hands on her hips. \"Old Marn says you don't count thanks, you remember them. I'll remember.\" She nods like she's just sworn an oath.",
                "@2 dips into a too-formal little bow she's clearly copied from somebody. \"The granny says a thank-you is the smallest coin and the longest spent. So. Spent.\"",
            ],
            Warmth.WARM: [
                "@2 nods with the gravity of a small ambassador. \"Halrick says you take thanks like coin: count it, pocket it, don't spend it twice. I'll keep it, @1d.\"",
                "@2 ducks her head, suddenly shy. \"Aye, traveler. Old Marn says the road remembers a kindness longer than a slight. So.\" She shrugs, satisfied.",
                "@2 tips an imaginary hat. \"Greetings noted and gratitude accepted. The granny says that's how it's done.\"",
            ],
            Warmth.NEUTRAL: [
                "@2 nods professionally. \"Noted, traveler.\" She's clearly imitating somebody important.",
                "@2 returns the thanks with a brisk \"Aye,\" already half-back to her satchel.",
                "@2 dips her chin once. \"Right. Mind the road.\"",
            ],
            Warmth.COOL: [
                "@2 narrows her eyes a touch. \"What for?\" she says, suspicious of unsolicited credit.",
                "@2 turns the thank-you over like she's checking it for trick-coins. \"Mm,\" she says, and goes back to her feathers.",
                "@2 shrugs, unconvinced. \"Halrick says don't trust thanks you didn't earn. I'm thinking.\"",
            ],
            Warmth.COLD: [
                "@2 doesn't answer. She bends over her satchel and counts feathers with great deliberation.",
                "@2 fixes her eyes on the south path. \"I'm working,\" she mutters, and that's the whole reply.",
                "@2 closes her satchel pointedly. The thanks goes in the pile of things she's chosen not to hear.",
            ],
        },
        "ponder": {
            Warmth.HOT: [
                "@2 perches on her stump beside @1d and drops to a confidential whisper: \"You think slower than the cooper. That's a compliment. The cooper doesn't think at all.\"",
                "@2 mimics @1np stance with great seriousness, hand on chin. \"Old Marn says the people worth knowing are the ones who pause. So we're pausing. I'm pausing.\"",
                "@2 settles cross-legged at @1np feet, satchel hugged. \"Halrick goes still like that before he says something good. I'll wait. I'm patient. I can be patient.\"",
            ],
            Warmth.WARM: [
                "@2 plants herself nearby and watches @1d with quiet interest. \"You've got a thinking-face. The granny says those are the faces worth bothering.\"",
                "@2 nods sagely from her stump. \"Aye. Thinking's good. Halrick says ponder costs no copper. Ponder away.\"",
                "@2 settles in to wait @1d out, satchel in lap, eyes wide and patient.",
            ],
            Warmth.NEUTRAL: [
                "@2 glances over briefly. \"Halrick says ponder costs no copper.\" She returns to counting feathers.",
                "@2 acknowledges the moment with a brief professional nod and goes back to her satchel.",
                "@2 perches on her stump and minds her own business while @1d minds @1np.",
            ],
            Warmth.COOL: [
                "@2 makes a great show of not watching @1d, counting feathers with elaborate concentration.",
                "@2 turns her stump a fraction so her back is mostly to @1d.",
                "@2 tips her chin up at the sky, suddenly fascinated by clouds.",
            ],
            Warmth.COLD: [
                "@2 doesn't look up. She is, suddenly, very busy with the contents of her satchel.",
                "@2 fixes her eyes on the south path and counts the trees on the horizon, lips moving.",
                "@2 closes her satchel with a small definitive snap and pretends to listen for messenger-birds.",
            ],
        },
        "tend": {
            Warmth.HOT: [
                "@2 stands very still for the gesture, satchel held flat. When @1d is done she beams. \"Old Marn does that. He'd like you.\"",
                "@2 ducks her head obligingly while @1d works, and offers a small ceremonial \"Thanks, that,\" when it's done. \"Halrick'd want me looking proper.\"",
                "@2 grins crookedly. \"Aye. Going to tell the granny somebody fussed over me proper. She'll make a face, but she'll like it.\"",
            ],
            Warmth.WARM: [
                "@2 holds still and lets @1d adjust the strap, watching with quiet curiosity. \"Aye. Thanks, traveler. Old Marn does that, sometimes.\"",
                "@2 dips her head obediently, satchel up. \"Mm. The granny says a kept-tidy runner is a trusted runner. So. Tidied.\"",
                "@2 accepts the gesture with grave practical thanks. \"Right. That'll do me to the ferry-house.\"",
            ],
            Warmth.NEUTRAL: [
                "@2 lifts her satchel to make the strap easier to reach, brisk and professional. \"Aye. Thanks.\"",
                "@2 holds still for the gesture, says \"Right,\" and is back to her satchel-counting before @1d's hands have lowered.",
                "@2 nods once. \"Halrick says a runner who can't fix her own straps doesn't run far. But — aye. Thanks.\"",
            ],
            Warmth.COOL: [
                "@2 steps back a half-pace, satchel pulled close. \"I've got it, traveler. Thanks.\" The thanks is doing a lot of work.",
                "@2 twists her shoulder out of easy reach. \"Mm. I can do mine.\"",
                "@2 fends @1np hand off with a quick small motion. \"It's fine. It's fine.\"",
            ],
            Warmth.COLD: [
                "@2 jerks her satchel away and steps clear. \"DON'T,\" she says, sharp as a struck flint, and watches @1d with wide unhappy eyes.",
                "@2 twists clean out of reach. \"Halrick says don't let strangers handle the bag. So.\" She glares, satchel hugged to her chest.",
                "@2 steps back two full paces. \"My satchel,\" she says firmly, the way an adult might say \"my house.\" \"Mine.\"",
            ],
        },
    }

    # DEPART_WHEN_PUSHED — convention matches future on_pushed
    # wiring: ``@1`` = the actor (player), ``@2`` = Wren (NPC).
    DEPART_WHEN_PUSHED_POOL: List[str] = [
        "@2 shoulders her satchel professionally. \"I have to be at the ferry-house before sundown — old Marn's expecting me, traveler, you understand.\" She's already moving.",
        "\"Halrick wouldn't like it if I was late,\" @2 announces, slinging her satchel and already half-out of the clearing. \"Roads be kind to you, @1.\"",
        "@2 raises a placating hand. \"That's grown-up business, that is. I run things between hands; I don't open the parcels.\" She slips out the south path at her trotting pace.",
    ]

    # FLEE_FROM_ATTACK rendering: ``@1`` = the attacker (player),
    # ``@2`` = Wren (NPC).
    FLEE_FROM_ATTACK_POOL: List[str] = [
        "@2 shrieks once — a high small bird-cry — and is gone. She vanishes into the south brush so fast her satchel doesn't quite catch up; a feather drifts to the ground in her wake.",
        "@2 turns and runs without looking back, satchel banging against her hip, voice trailing back: \"I'M TELLING. I'M TELLING HALRICK. I'M TELLING EVERYONE.\" The trees swallow her.",
        "@2 bolts. The copper coin she fishes from her pocket as she runs is dropped behind her — a panicked offering, like that might buy mercy. It clinks on a stone and rolls into the bracken.",
        "@2 doesn't say anything. She's just GONE — a small comet of brown coat and flying satchel, the south brush sealing behind her like she was never there at all. Only the dropped feather marks the spot.",
    ]

    LOOK_LINE: str = (
        "A girl named Wren waits at the verge with the unhurried "
        "purpose of someone running a message and willing to be "
        "noticed when she's good and ready."
    )

    # ACQUAINTANCE_CUE — fires when Wren learns @2's name for the
    # first time. Voice: chirpy, sharp-eyed, the kind of kid who
    # files a name immediately and tells someone else about it.
    ACQUAINTANCE_CUE_POOL: List[str] = [
        "*Wren writes @2np name in a tiny notebook with great seriousness, then puts the notebook away like a state secret.*",
        "*\"@2,\" Wren repeats, satisfied. \"Got it. Old Marn'll want to know I crossed paths with @2.\"*",
        "*Wren's eyes flick to @2 the way an errand-runner's eyes flick — that's a face she'll know on the road from now on.*",
    ]
