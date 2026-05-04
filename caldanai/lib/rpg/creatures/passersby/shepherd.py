"""Shepherd looking for the sheep — a rural, patient passerby who
addresses sheep more than people, walks with a crook, and pairs
with the existing sheep encounters in the clearing.

Voice register: rural patient. World-weary but not cynical. Uses
"friend" / "you" by default; names land when they matter. Talks
to himself softly when nobody's listening. Counts under his
breath. Watches the treeline like he's been doing it for forty
years and intends to do it forty more.

Doesn't reference Mendholm by name explicitly — the world to him
is "this stretch of country" or "out here." His Mendholm is in
the ground, not the word. Pairs with the existing sheep flavor
pools — when a sheep is present and the shepherd arrives, that's
a moment.

Parser tokens: ``@1`` = the actor (player) when used in social
reactions. NAMING_BIAS at 0.3 — rural plain-spoken, "friend"
feels right; uses name when it matters.
"""
from typing import Dict, List, Union

from caldanai.lib.rpg.creatures.passersby import PasserbyPlugin
from caldanai.lib.rpg.helpers.enums import TimePartitions
from caldanai.lib.rpg.helpers.warmth import Warmth


class Shepherd(PasserbyPlugin):
    name = "shepherd"
    uses_article = True
    gender = "male"
    pronouns = "he,him,his,his,himself"
    ALIASES = ["sheep-herder", "old shepherd"]

    # Shepherds are out at sheep-hours — dawn for the morning
    # count, through the day, evening for bringing them in.
    # Could narrow to dawn+evening for a stricter "going out /
    # coming back" pattern but DIURNAL keeps spawn variety.
    time_partition = TimePartitions.DIURNAL

    # "Friend" / "you" are home. Names when it matters.
    NAMING_BIAS = 0.3

    # Sheep are HIS — killing one in front of him drops the
    # offender's warmth a full tier toward COLD. Other passive
    # creatures hit the system default (-10 credits); a stranger
    # killing a sheep at the verge of his flock is a different
    # weight than a stranger pulping a passive squirrel.
    PASSIVE_KILL_PENALTY: Dict[str, Union[int, str]] = {
        "sheep": "tier_drop",
    }

    ARRIVAL_POOL: List[str] = [
        "An old shepherd walks into the clearing leaning on a crook worn smooth by his palm. @1S scans the verge with practiced eyes, looking for woolly sign.",
        "A shepherd ambles in from the south, whistles two notes that hang in the air a moment, and listens for whatever might whistle back.",
        "An old man in a long coat steps over the verge, crook in one hand, and starts a slow patrol of the clearing's edges.",
        "@1D arrives the way old hills arrive — unhurriedly, inevitably. His crook taps the ground once for every two steps; the rhythm is older than him.",
        "A weathered shepherd walks in with a sheep-bell on his belt that doesn't quite ring, just whispers metal-on-metal.",
        "@1D comes in counting under his breath — \"...thirty-eight, thirty-nine...\" — looks up, sees the clearing isn't his pasture, sighs, keeps counting anyway.",
        "An old shepherd ducks the willow at the verge, plants his crook, and stands a long moment scanning. \"They wander,\" he says, mostly to the willow. \"They always wander.\"",
        "@1D walks in calm as a Sunday, crook tapping, eyes tracking nothing in particular. A few sheep-tail's worth of wool clings to one cuff.",
    ]

    AMBIENT_POOL: List[str] = [
        "@1D whistles two short notes and listens to the silence that answers, untroubled.",
        "@1D plants his crook in the dirt and leans on it, watching the treeline the way some watch fires.",
        "@1D thumbs a small wooden bead on a leather cord at his neck — once, twice, three times — and tucks it back under his collar.",
        "@1D clucks his tongue at no sheep visible, in case some sheep is invisible.",
        "@1D pulls a folded rag from his pocket, wipes his crook's worn handle absent-mindedly, and pockets the rag again.",
        "@1D hums a tuneless little tune that's been wandering around his head since before his beard was grey.",
    ]

    DEPARTURE_POOL: List[str] = [
        "@1D plants his crook one final time, mutters \"Well, they'll find their own way then,\" and walks the south path back toward wherever home is for him today.",
        "@1D whistles his two notes one last time, gets no reply, shrugs philosophically, and ambles off the way he came.",
        "@1D nods once at the clearing — a thanks, perhaps, or a goodbye — and walks back into the country he came from at the slow pace of a man who's never once been in a hurry.",
        "@1D tucks his crook under one arm, scratches the side of his nose with his thumb, and steps back into the trees with no particular fanfare.",
        "@1D ambles out humming, the sound fading into the green at exactly the rate hilltops fade in mist.",
        "@1D gives the willow a small, meaningful nod, says \"Aye, well,\" to nobody, and is gone the way old men go when they've decided.",
    ]

    SILHOUETTE_POOL: List[str] = [
        "Up the southern path, an old shepherd plants his crook in the dirt and leans on it, watching the noise patient as a hilltop.",
        "A shepherd at the verge whistles his two notes once, hears nothing useful in the answer, and settles himself to wait.",
        "@1D stops at the treeline, tucks his coat tighter, and watches with the unmoved attention of someone who has watched worse.",
        "@1D stands at the clearing's edge with his crook planted, untroubled, like he's standing in a doorway waiting for a kettle.",
        "A sheep-bell whispers somewhere up the path; @1d is half-visible behind a stand of brush, watching, not approaching.",
    ]

    COMBAT_WON_REACTIONS: List[str] = [
        "@1D ambles in once the dust's settled, surveys the kill with mild interest, and tells @2: \"Well done, friend. The hills'll sleep easier.\"",
        "@1D plants his crook beside @2 and rests on it heavily. \"That's a worthy bit of work,\" he says. \"You took a thing my flock didn't have to meet. They won't thank you. I will.\"",
        "@1D looks the carcass over slowly, nods to himself, and tells @2: \"That's one less to count on the wrong side of the count. Good.\"",
        "@1D approaches at his unhurried pace, takes off his hat, scratches his head with the same hand, replaces the hat. \"You earned a quiet road tonight, friend. Hope it stays.\"",
        "@1D lifts his crook in salute, brief. \"Aye. The country owes you one. The country won't pay; it never does. But it owes you.\"",
        "@1D stands at the kill a moment, then at @2np side a moment, then says, \"You'll do, friend. You'll do.\" High praise, the shepherd kind.",
    ]

    COMBAT_FLED_REACTIONS: List[str] = [
        "@1D walks in once the air is honest. He looks at the trampled grass, then up the path the creature took. \"Smart,\" he says. \"On both sides. Sometimes that's how you live to fifty.\"",
        "@1D nods at @2 with a slow respect. \"You held what could be held, friend. The hills will remember.\"",
        "@1D settles onto his crook and considers the empty space. \"Well. It'll come back smaller, or not at all. Either way, you stayed.\"",
        "@1D clucks his tongue at the trampled bracken. \"Hard to herd a thing like that,\" he says, half to himself. \"Glad you didn't try.\"",
        "@1D plants his crook and looks @2 in the eye. \"You'll be alive tomorrow. That's the win, friend. Don't let anyone tell you different.\"",
    ]

    PARTY_DEATH_REACTIONS: List[str] = [
        "@1D arrives without his usual ambling tempo. He sees @2, takes off his hat slowly, and stands a long while at @2np side without speaking.",
        "@1D plants his crook, leans heavy, and watches @2 with the patient stillness of someone who has buried his share. \"The ground'll have you a while,\" he says quietly. \"It always gives back what it borrows.\"",
        "@1D kneels beside @2 with the careful slowness of his joints. He puts a hand on @2np shoulder. \"Walk gentle in the dark, friend. The light'll know where to find you.\"",
        "@1D doesn't speak right away. He stands, hat in hand, and lets the silence do most of the work. Then: \"You'll be back. Things this country borrows, it returns.\"",
        "@1D plants his crook in the dirt at @2np head — like a marker, like a promise — and steps back. \"I'll mention you to the hills on the way home, friend. They listen, sometimes.\"",
    ]

    SOCIAL_REACTIONS: Dict[str, Dict[Warmth, List[str]]] = {
        "wave": {
            Warmth.HOT: [
                "@2Np whole face wrinkles into a delighted grin. He waves back broadly with his crook, then bows slightly. \"Friend! Good day for it.\"",
                "@2D laughs aloud and lifts his crook high in answer. \"Aye! There you are. The country's better with you crossing it.\"",
                "@2D waves both arms — crook in one, hat in the other — and beams with all his lined face.",
            ],
            Warmth.WARM: [
                "@2D raises his crook in a slow, warm salute. \"Friend.\"",
                "@2D grins a small grin and lifts his free hand in a steady wave. \"Aye, well met.\"",
                "@2D touches his hat brim and gives a deliberate, satisfied nod-and-wave.",
            ],
            Warmth.NEUTRAL: [
                "@2D raises a hand briefly in return, eyes already drifting back to the treeline.",
                "@2D tips his crook a fraction in acknowledgement and goes back to his watching.",
                "@2D lifts a finger off his crook, the smallest acknowledging gesture, and that's that.",
            ],
            Warmth.COOL: [
                "@2D glances over, doesn't quite wave, and adjusts his grip on the crook.",
                "@2D inclines his head a fraction and turns his attention back to the country.",
                "@2D looks past @1d to the treeline like there's a sheep that needs more attention.",
            ],
            Warmth.COLD: [
                "@2Np face goes carefully blank. He plants his crook firmly and watches a different direction.",
                "@2D does not return the wave. The set of his shoulders says he's finished with @1.",
                "@2D turns his back to @1d with the deliberate ceremony of a man who's done it before to others who deserved it.",
            ],
        },
        "nod": {
            Warmth.HOT: [
                "@2D nods back with weight. \"Aye, friend. Aye.\"",
                "@2D returns the nod twice — the second deeper than the first — and crinkles his eyes.",
                "@2D dips his crook in answer and grins his weathered grin.",
            ],
            Warmth.WARM: [
                "@2D nods back warmly. \"Aye.\"",
                "@2D returns the nod with his slow seriousness. \"Friend.\"",
                "@2D dips his head, holds it a beat, comes back up.",
            ],
            Warmth.NEUTRAL: [
                "@2D nods once, polite, and goes back to his watching.",
                "@2D returns the nod and the conversation between them is complete.",
                "@2D dips his chin a measured fraction, and lets that suffice.",
            ],
            Warmth.COOL: [
                "@2Np nod, if it was one, was small enough to be the wind.",
                "@2D doesn't quite nod. He doesn't quite not.",
                "@2Np chin doesn't move, but his eyes acknowledge that the gesture happened.",
            ],
            Warmth.COLD: [
                "@2D does not return the nod. He plants his crook and watches the country.",
                "@2D turns his face deliberately away.",
                "@2D ignores the gesture entirely, his attention on a tuft of grass that suddenly fascinates him.",
            ],
        },
        "greet": {
            Warmth.HOT: [
                "@2D grins broad and clasps @1np forearm in greeting. \"Friend, friend. The country's been quieter without you, and I mean that as a compliment.\"",
                "\"@1d!\" @2d says, real warmth crinkling his face. \"Glad to find you here. Has the willow been kind today?\"",
                "@2D laughs, crinkles his whole face up. \"Sit a moment, friend, sit. The wool can wait. The wool's never in a hurry.\"",
            ],
            Warmth.WARM: [
                "@2D smiles the slow, deep way old shepherds smile. \"Hello, friend. Glad to see your face on this stretch.\"",
                "\"Aye, well met,\" @2d says, planting his crook. \"How's the wind been treating you?\"",
                "@2D touches his hat. \"Friend. Stay a while if you've a moment. The clearing keeps better company that way.\"",
            ],
            Warmth.NEUTRAL: [
                "@2D nods. \"Friend.\"",
                "\"Aye,\" @2d says, with the polite economy of his country. \"Hello to you.\"",
                "@2D dips his hat brim. \"Greeting, friend.\"",
            ],
            Warmth.COOL: [
                "@2D grunts a syllable that may have been a greeting.",
                "@2D acknowledges @1d with the flatness of country-talk: \"Aye.\"",
                "@2D inclines his head minimally and goes back to the treeline.",
            ],
            Warmth.COLD: [
                "@2D does not return the greeting. He plants his crook and watches the south path.",
                "\"I'm working,\" @2d says flatly, which is true and also not the whole reason.",
                "@2D lets the silence speak. The silence is not warm.",
            ],
        },
    }

    DEPART_WHEN_PUSHED_POOL: List[str] = [
        "@2D raises a placating hand. \"You'll have to ask the hills, friend. I just walk where they tell me. Be well.\" He ambles off.",
        "\"Long day ahead,\" @2d says, planting his crook for one final lean. \"Sheep don't find themselves. Mind the road.\" He's gone before the next question lands.",
        "@2D touches his hat brim. \"Some questions are for the dirt, friend. I just walk on it.\" He turns and ambles off at his country pace.",
    ]

    # FLEE_FROM_ATTACK rendering: ``@1`` = the attacker (player),
    # ``@2`` = the shepherd (NPC). Matches the rendering pipeline
    # in ``spawn.flee_from_attack`` which passes ``(attacker, npc)``
    # to ``render_actor_npc`` → ``parse(line, actor, npc)``.
    FLEE_FROM_ATTACK_POOL: List[str] = [
        "@2Np eyes go cold. He plants his crook between himself and @1 — not in defiance, in geometry — and walks backward steadily out of the clearing without ever quite turning his back.",
        "\"None of that, friend,\" @2d says calmly, and he's already moving. He's faster than he looks. The crook clears the verge before @1 quite registers the motion.",
        "@2D steps backward at his deliberate pace, one hand raised, the other firm on his crook. \"You'll regret that. Or you won't. Either way, not here, not me.\" He's gone into the trees before the second sentence finishes.",
        "@2D turns and walks — not runs, walks — but at a country-emergency pace that eats ground. The clearing loses him in three breaths.",
    ]

    LOOK_LINE: str = (
        "A shepherd patrols the verges with a worn crook, watching "
        "for sheep and listening for whatever might whistle back."
    )

    # ACQUAINTANCE_CUE — fires when the shepherd learns @2's name
    # for the first time. Voice: country-quiet, the way an old
    # shepherd says a sheep's name once and then never forgets.
    ACQUAINTANCE_CUE_POOL: List[str] = [
        "*The shepherd repeats @2np name once under his breath. \"@2.\" Like he's tasting it.*",
        "*The old shepherd nods slowly to @2. \"@2. I'll mention you to the hills on the way home.\"*",
        "*@1d gives @2 the long unhurried look of a man learning a new face the way he learns a new lamb.*",
    ]
