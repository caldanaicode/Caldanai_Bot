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
from caldanai.lib.rpg.helpers.warmth import Warmth


class Wren(PasserbyPlugin):
    name = "Wren"
    uses_article = False  # Proper-named — "Wren," not "the Wren"
    gender = "female"
    pronouns = "she,her,hers,her,herself"

    ALIASES = ["errand-runner", "messenger-child"]

    # Errand-runners use names readily — knowing names is the job.
    # Higher than the wagoneer's 0.85 because she leans even more on
    # named address; lower than 1.0 because she occasionally
    # affects formal-traveler manners when she wants something.
    NAMING_BIAS = 0.7

    ARRIVAL_POOL: List[str] = [
        "A girl trots into the clearing at the unhurried pace of someone running a message and willing to wait until she's noticed. A leather satchel bumps her hip; her face is sharp under a mop of dark hair.",
        "A child arrives at the verge with the official-looking gait of someone who's been on errands since she was old enough to remember addresses. She plants herself, surveys the adventurers, nods like she's confirming a list.",
        "Wren swings into the clearing from the south path with the brisk efficiency of a kid who's done this route a hundred times. She stops, scans, finds nothing she was specifically expecting, but settles in regardless.",
        "A messenger-child appears at the willow at the verge, satchel bouncing. She leans against the trunk and gives the clearing a long, professional once-over.",
        "Wren slips out of the trees at the east verge, mid-conversation with herself. \"...and Halrick said the cooper said, but the cooper was DRUNK, so —\" She trails off, sees company, smiles with all her teeth.",
        "A girl in an oversized brown coat tromps into the clearing, satchel slung crossways. The coat was somebody's father's, once. She's grown into the shoulders, not the length.",
        "Wren arrives at the pace of a sparrow with somewhere to be. She perches on a stump at the verge, swings her legs, and waits for the clearing to notice her professionally.",
        "A child rolls out of the brush at the south verge, having taken an off-path shortcut she's clearly not supposed to know. She brushes leaves off her coat with practiced indignation.",
        "Wren skips into the clearing humming something tuneless and slightly off, satchel knocking against her hip. \"...don't tell Halrick I said,\" she's muttering, \"don't tell Halrick I said...\"",
        "A girl trots in with her satchel hugged against her chest like it contains state secrets. It mostly contains a copper, two feathers, a flat stone, and a heel of bread.",
    ]

    AMBIENT_POOL: List[str] = [
        "Wren reaches into her satchel, considers her treasures one by one — copper, feather, bird-shaped stone — and tucks them all carefully back.",
        "She perches on a stump and counts something on her fingers under her breath. \"Three from Marn, two for the granary, one for...\" She loses her place, starts over.",
        "Wren mutters bits of an overheard adult sentence to herself with the wrong inflections, trying to remember it right. \"The CART won't go, the cart WON'T go, the cart won't GO —\"",
        "She kicks her heels against the stump, pulls a small bird-feather out of her pocket, twirls it, slides it back.",
        "Wren scans the clearing the way she's seen serious adults do, eyebrows lowered, lips pursed. She's clearly mimicking somebody. The somebody is not present to be embarrassed.",
        "She extracts a heel of dark bread from her satchel, eats it efficiently, brushes the crumbs off her coat with a satisfied air.",
    ]

    DEPARTURE_POOL: List[str] = [
        "Wren springs to her feet, slaps her satchel closed, and announces to nobody: \"Got to get to Halrick before sundown.\" She's already moving as the sentence finishes.",
        "She stretches dramatically, the way she's seen old men do, and trots back toward the south path. \"Tell Marn I came through!\" she calls back over her shoulder, to nobody specifically.",
        "Wren tucks her treasures back into her satchel one by one — a small ceremony — and departs the way she came, humming.",
        "She bounces off the stump, salutes the clearing with one too-formal hand, and vanishes back into the brush.",
        "Wren leaves at her trotting pace, already mid-conversation with the next person she expects to see, who is half a valley away.",
        "She slings her satchel, gives the clearing a brisk professional nod, and is gone before her own footprints have settled.",
    ]

    SILHOUETTE_POOL: List[str] = [
        "At the verge, a small figure with a satchel skids to a halt, takes in the noise, and prudently sits behind a stump to wait.",
        "Wren peers around the trunk of the willow with wide-eyed professional caution. She's seen worse. She's seen better. She rates the situation a four out of ten and stays put.",
        "Up the south path, a girl in an oversized coat plants herself at a safe distance and watches with the unblinking attention of someone storing details to retell later.",
        "A child's silhouette at the brush-line — Wren, satchel hugged tight, lips moving as she narrates the fight under her breath like a wardroom report.",
        "She freezes mid-trot at the verge, drops to a crouch, and watches with the stillness of a small animal that has not yet decided whether to flee.",
    ]

    COMBAT_WON_REACTIONS: List[str] = [
        "Wren bounds out of cover the moment the dust settles, eyes huge. \"OH. Oh. I'm telling EVERYONE. @2! That's @2 who killed the BIG one. Halrick's going to want to hear this. Old Marn's going to want to hear this.\"",
        "She edges out cautiously, examines the carcass from a respectful three paces, and addresses @2 with sudden formality: \"That's a good kill, that. I'll mention you to the trading-post. They listen to me, sometimes.\"",
        "\"That,\" Wren says, emerging from her stump-shelter with all the gravity of a small judge, \"is the kind of thing the cooper said couldn't be done. The cooper was wrong. The cooper is OFTEN wrong.\" She nods sagely at @2.",
        "She comes out grinning, satchel rattling. \"I saw it. I SAW the whole thing. @2d, I'm going to tell that one to Marn at the ferry-house tomorrow and she's going to call me a liar and I'm going to make her give me a sweet.\"",
        "Wren approaches @2 with the dignity she imagines a courier would use. \"News will be carried,\" she announces. \"Word will go. The granary will know. The granny three valleys over will know. The road remembers what it sees.\"",
        "She fishes a copper out of her satchel, considers it solemnly, and presses it into @2np hand. \"For your tally,\" she says, with great seriousness. \"Halrick gives me one when I bring good news. You should have one too.\"",
    ]

    COMBAT_FLED_REACTIONS: List[str] = [
        "Wren peeks out, sees the empty space where the creature was, and lets out a long whistle she's clearly practiced. \"That. Was. CLOSE. I'm telling old Marn that one for sure.\"",
        "She emerges trembling but trying to look professional about it. \"Walked off,\" she reports to @2, like she's filing it. \"Walked off injured, probably. I'll keep an ear out at the ferry-house. People hear things.\"",
        "Wren scrambles up onto her stump for a better view of the path the creature took, narrows her eyes the way Halrick narrows his when he's thinking hard. \"It'll be back,\" she pronounces. \"Or it won't. Either way, you're alive. Halrick'd want me to mention that.\"",
        "She comes out of cover smoothing her coat indignantly. \"I was going to help. I was. The granny says you don't run TOWARD trouble unless you can carry it. I can't carry that.\"",
        "Wren hops off her stump and approaches @2 with cautious professional respect. \"You held,\" she says. \"That counts. The cooper says holding's the only thing that counts when the running's faster than you.\"",
    ]

    PARTY_DEATH_REACTIONS: List[str] = [
        "Wren creeps out of cover slowly, sees @2, and goes very still in the way kids do when they suddenly understand a thing. Her satchel slips off her shoulder. She doesn't pick it up.",
        "She approaches @2 with a hesitant gravity that doesn't suit her usual chirp. \"I'll tell them,\" she says quietly. \"Marn. Halrick. The granny. They should know. The road should know.\"",
        "Wren kneels by @2, pulls her best treasure from her satchel — a flat stone painted with a small careful bird — and lays it beside @2np head. \"For the road back,\" she says, repeating something she's heard adults say without quite knowing what it means.",
        "She doesn't say anything at first. She just stands at @2's side, satchel forgotten, eyes wet but stubborn. Finally: \"I'm going to mention you to everyone I run for tomorrow. Just so they know.\"",
        "Wren removes a small dried flower from her satchel — saved from somewhere, for someone — and lays it on @2np chest. \"Old Marn'll keep a place,\" she says. \"She always does. Mendholm mends. The granny says.\"",
    ]

    SOCIAL_REACTIONS: Dict[str, Dict[Warmth, List[str]]] = {
        "wave": {
            Warmth.HOT: [
                "Wren waves both arms back, satchel flying. \"@1d! Halrick was just asking about you yesterday! The cooper says hi too, probably!\"",
                "She bounces on her toes and waves with the hand not currently holding her satchel. \"There you are! I was going to LOOK for you if I didn't see you today!\"",
                "\"@1!\" Wren calls, beaming. She launches off her stump and waves with both hands, satchel and all.",
            ],
            Warmth.WARM: [
                "Wren waves back warmly. \"Hi @1! Old Marn says hello — she always says hello when I tell her about you.\"",
                "She grins and lifts a hand in answer. \"@1d. I knew you'd be around here today. The wind was right.\"",
                "Wren nods with professional satisfaction and waves. \"Knew you'd be passing.\"",
            ],
            Warmth.NEUTRAL: [
                "Wren returns the wave briskly, all business. \"Traveler.\"",
                "She acknowledges the wave with a small efficient flutter of her hand and goes back to her satchel.",
                "Wren raises a finger off her satchel in returned greeting, polite-runner style.",
            ],
            Warmth.COOL: [
                "Wren glances up, doesn't quite wave, and pretends to be very absorbed in her satchel-contents.",
                "She gives @1np the smallest possible acknowledging gesture and turns away.",
                "Wren narrows her eyes a touch and busies herself counting feathers.",
            ],
            Warmth.COLD: [
                "Wren turns her face deliberately toward the south path. The wave goes unanswered. She is, suddenly, very busy.",
                "She closes her satchel pointedly and pretends to be checking the sky for messenger-birds.",
                "Wren doesn't return the wave. She mutters something under her breath that sounds suspiciously like the cooper's least-flattering opinions.",
            ],
        },
        "nod": {
            Warmth.HOT: [
                "Wren nods back with the gravity of a small ambassador, then breaks into a grin she can't contain. \"@1!\"",
                "She returns the nod twice, satisfied. \"Aye, @1. The road's been kind today.\"",
                "Wren nods so hard her satchel rattles, and salutes for good measure.",
            ],
            Warmth.WARM: [
                "Wren returns the nod with measured warmth. \"Traveler. Halrick'd be glad to know I saw you well.\"",
                "She dips her head and smiles. \"@1d.\"",
                "Wren nods, slow and serious in a way she's clearly imitating from someone older.",
            ],
            Warmth.NEUTRAL: [
                "Wren nods once, all-business runner-style, and turns back to her satchel.",
                "She returns the nod, brisk, and resumes her watching.",
                "Wren bobs her head efficiently and moves on.",
            ],
            Warmth.COOL: [
                "Wren returns a tiny, perfunctory nod, and looks pointedly elsewhere.",
                "She inclines her head a fraction without meeting @1np eyes.",
                "Wren's nod, if it was one, was so small the wind might have done it.",
            ],
            Warmth.COLD: [
                "Wren stares at the ground and does not nod.",
                "She turns her face deliberately south and counts the trees on the horizon.",
                "Wren's jaw sets, and she pretends to consult an imaginary list. She does not nod.",
            ],
        },
        "greet": {
            Warmth.HOT: [
                "\"@1d!\" Wren explodes, scrambling off her stump. \"Halrick was JUST asking, and old Marn said you'd come through, and I told her she was wrong but she WASN'T, and —\" She runs out of breath.",
                "She beams, plants both hands on her hips. \"There you are! Sit down. I have NEWS. The cooper got drunk again and the ferry-house has new ropes and the granny says hello.\"",
                "\"@1!\" Wren sings. \"Tell me everything. EVERYTHING. I'll trade you. I have a copper. I have a feather. The feather's better, actually.\"",
            ],
            Warmth.WARM: [
                "Wren tips an imaginary hat with all the gravity of a small magistrate. \"Hello, @1. Halrick says good things about you.\"",
                "\"@1d,\" she says, smiling. \"Old Marn'll be glad to hear I crossed your path.\"",
                "Wren nods deeply. \"Greetings, traveler. Roads be kind to you.\" She's clearly imitating Halrick. The imitation is excellent.",
            ],
            Warmth.NEUTRAL: [
                "Wren returns the greeting briskly. \"Traveler.\" She means well; she's just on the clock.",
                "\"Hello,\" she says efficiently, already half-checking her satchel.",
                "Wren tips her chin and offers a polite-runner \"Aye.\"",
            ],
            Warmth.COOL: [
                "Wren mumbles something that might have been a greeting and pretends to need to count her feathers.",
                "She acknowledges the greeting with the smallest professional possible \"Mm,\" and turns to her satchel.",
                "Wren's response is the kind of greeting Halrick would call \"polite enough.\" Just barely.",
            ],
            Warmth.COLD: [
                "Wren does not return the greeting. She slings her satchel and looks pointedly down the south path, suddenly remembering somewhere she needs to be.",
                "She fixes her gaze on a fixed point in the middle distance. The greeting doesn't land. She doesn't pick it up.",
                "\"Working,\" Wren says flatly, and resumes counting feathers with the air of someone rewriting an unfavorable rumor in her head.",
            ],
        },
    }

    DEPART_WHEN_PUSHED_POOL: List[str] = [
        "Wren shoulders her satchel professionally. \"I have to be at the ferry-house before sundown — old Marn's expecting me, traveler, you understand.\" She's already moving.",
        "\"Halrick wouldn't like it if I was late,\" Wren announces, slinging her satchel and already half-out of the clearing. \"Roads be kind to you, @1.\"",
        "She raises a placating hand. \"That's grown-up business, that is. I run things between hands; I don't open the parcels.\" She slips out the south path at her trotting pace.",
    ]

    FLEE_FROM_ATTACK_POOL: List[str] = [
        "Wren shrieks once — a high small bird-cry — and is gone. She vanishes into the south brush so fast her satchel doesn't quite catch up; a feather drifts to the ground in her wake.",
        "She turns and runs without looking back, satchel banging against her hip, voice trailing back: \"I'M TELLING. I'M TELLING HALRICK. I'M TELLING EVERYONE.\" The trees swallow her.",
        "Wren bolts. The copper coin she fishes from her pocket as she runs is dropped behind her — a panicked offering, like that might buy mercy. It clinks on a stone and rolls into the bracken.",
        "She doesn't say anything. She's just GONE — a small comet of brown coat and flying satchel, the south brush sealing behind her like she was never there at all. Only the dropped feather marks the spot.",
    ]

    LOOK_LINE: str = (
        "A girl named Wren waits at the verge with the unhurried "
        "purpose of someone running a message and willing to be "
        "noticed when she's good and ready."
    )
