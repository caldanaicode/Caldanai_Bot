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
from typing import Dict, List

from caldanai.lib.rpg.creatures.passersby import PasserbyPlugin
from caldanai.lib.rpg.helpers.warmth import Warmth


class Shepherd(PasserbyPlugin):
    name = "shepherd"
    uses_article = True
    gender = "male"
    pronouns = "he,him,his,his,himself"
    ALIASES = ["sheep-herder", "old shepherd"]

    # "Friend" / "you" are home. Names when it matters.
    NAMING_BIAS = 0.3

    ARRIVAL_POOL: List[str] = [
        "An old shepherd walks into the clearing leaning on a crook worn smooth by his palm. He scans the verge with practiced eyes, looking for woolly sign.",
        "A shepherd ambles in from the south, whistles two notes that hang in the air a moment, and listens for whatever might whistle back.",
        "An old man in a long coat steps over the verge, crook in one hand, and starts a slow patrol of the clearing's edges.",
        "The shepherd arrives the way old hills arrive — unhurriedly, inevitably. His crook taps the ground once for every two steps; the rhythm is older than him.",
        "A weathered shepherd walks in with a sheep-bell on his belt that doesn't quite ring, just whispers metal-on-metal.",
        "The old shepherd comes in counting under his breath — \"...thirty-eight, thirty-nine...\" — looks up, sees the clearing isn't his pasture, sighs, keeps counting anyway.",
        "An old shepherd ducks the willow at the verge, plants his crook, and stands a long moment scanning. \"They wander,\" he says, mostly to the willow. \"They always wander.\"",
        "He walks in calm as a Sunday, crook tapping, eyes tracking nothing in particular. A few sheep-tail's worth of wool clings to one cuff.",
    ]

    AMBIENT_POOL: List[str] = [
        "The shepherd whistles two short notes and listens to the silence that answers, untroubled.",
        "He plants his crook in the dirt and leans on it, watching the treeline the way some watch fires.",
        "The old shepherd thumbs a small wooden bead on a leather cord at his neck — once, twice, three times — and tucks it back under his collar.",
        "He clucks his tongue at no sheep visible, in case some sheep is invisible.",
        "The shepherd pulls a folded rag from his pocket, wipes his crook's worn handle absent-mindedly, and pockets the rag again.",
        "He hums a tuneless little tune that's been wandering around his head since before his beard was grey.",
    ]

    DEPARTURE_POOL: List[str] = [
        "The shepherd plants his crook one final time, mutters \"Well, they'll find their own way then,\" and walks the south path back toward wherever home is for him today.",
        "He whistles his two notes one last time, gets no reply, shrugs philosophically, and ambles off the way he came.",
        "The old shepherd nods once at the clearing — a thanks, perhaps, or a goodbye — and walks back into the country he came from at the slow pace of a man who's never once been in a hurry.",
        "He tucks his crook under one arm, scratches the side of his nose with his thumb, and steps back into the trees with no particular fanfare.",
        "The shepherd ambles out humming, the sound fading into the green at exactly the rate hilltops fade in mist.",
        "He gives the willow a small, meaningful nod, says \"Aye, well,\" to nobody, and is gone the way old men go when they've decided.",
    ]

    SILHOUETTE_POOL: List[str] = [
        "Up the southern path, an old shepherd plants his crook in the dirt and leans on it, watching the noise patient as a hilltop.",
        "A shepherd at the verge whistles his two notes once, hears nothing useful in the answer, and settles himself to wait.",
        "The old shepherd stops at the treeline, tucks his coat tighter, and watches with the unmoved attention of someone who has watched worse.",
        "He stands at the clearing's edge with his crook planted, untroubled, like he's standing in a doorway waiting for a kettle.",
        "A sheep-bell whispers somewhere up the path; the shepherd is half-visible behind a stand of brush, watching, not approaching.",
    ]

    COMBAT_WON_REACTIONS: List[str] = [
        "The shepherd ambles in once the dust's settled, surveys the kill with mild interest, and tells @2: \"Well done, friend. The hills'll sleep easier.\"",
        "He plants his crook beside @2 and rests on it heavily. \"That's a worthy bit of work,\" he says. \"You took a thing my flock didn't have to meet. They won't thank you. I will.\"",
        "The old shepherd looks the carcass over slowly, nods to himself, and tells @2: \"That's one less to count on the wrong side of the count. Good.\"",
        "He approaches at his unhurried pace, takes off his hat, scratches his head with the same hand, replaces the hat. \"You earned a quiet road tonight, friend. Hope it stays.\"",
        "The shepherd lifts his crook in salute, brief. \"Aye. The country owes you one. The country won't pay; it never does. But it owes you.\"",
        "He stands at the kill a moment, then at @2's side a moment, then says, \"You'll do, friend. You'll do.\" High praise, the shepherd kind.",
    ]

    COMBAT_FLED_REACTIONS: List[str] = [
        "The shepherd walks in once the air is honest. He looks at the trampled grass, then up the path the creature took. \"Smart,\" he says. \"On both sides. Sometimes that's how you live to fifty.\"",
        "He nods at @2 with a slow respect. \"You held what could be held, friend. The hills will remember.\"",
        "The old shepherd settles onto his crook and considers the empty space. \"Well. It'll come back smaller, or not at all. Either way, you stayed.\"",
        "He clucks his tongue at the trampled bracken. \"Hard to herd a thing like that,\" he says, half to himself. \"Glad you didn't try.\"",
        "The shepherd plants his crook and looks @2 in the eye. \"You'll be alive tomorrow. That's the win, friend. Don't let anyone tell you different.\"",
    ]

    PARTY_DEATH_REACTIONS: List[str] = [
        "The shepherd arrives without his usual ambling tempo. He sees @2, takes off his hat slowly, and stands a long while at @2np side without speaking.",
        "He plants his crook, leans heavy, and watches @2 with the patient stillness of someone who has buried his share. \"The ground'll have you a while,\" he says quietly. \"It always gives back what it borrows.\"",
        "The old shepherd kneels beside @2 with the careful slowness of his joints. He puts a hand on @2np shoulder. \"Walk gentle in the dark, friend. The light'll know where to find you.\"",
        "He doesn't speak right away. He stands, hat in hand, and lets the silence do most of the work. Then: \"You'll be back. Things this country borrows, it returns.\"",
        "The shepherd plants his crook in the dirt at @2np head — like a marker, like a promise — and steps back. \"I'll mention you to the hills on the way home, friend. They listen, sometimes.\"",
    ]

    SOCIAL_REACTIONS: Dict[str, Dict[Warmth, List[str]]] = {
        "wave": {
            Warmth.HOT: [
                "The shepherd's whole face wrinkles into a delighted grin. He waves back broadly with his crook, then bows slightly. \"Friend! Good day for it.\"",
                "He laughs aloud and lifts his crook high in answer. \"Aye! There you are. The country's better with you crossing it.\"",
                "The old shepherd waves both arms — crook in one, hat in the other — and beams with all his lined face.",
            ],
            Warmth.WARM: [
                "The shepherd raises his crook in a slow, warm salute. \"Friend.\"",
                "He grins a small grin and lifts his free hand in a steady wave. \"Aye, well met.\"",
                "The old shepherd touches his hat brim and gives a deliberate, satisfied nod-and-wave.",
            ],
            Warmth.NEUTRAL: [
                "The shepherd raises a hand briefly in return, eyes already drifting back to the treeline.",
                "He tips his crook a fraction in acknowledgement and goes back to his watching.",
                "The old shepherd lifts a finger off his crook, the smallest acknowledging gesture, and that's that.",
            ],
            Warmth.COOL: [
                "The shepherd glances over, doesn't quite wave, and adjusts his grip on the crook.",
                "He inclines his head a fraction and turns his attention back to the country.",
                "The old shepherd looks past @1np to the treeline like there's a sheep that needs more attention.",
            ],
            Warmth.COLD: [
                "The shepherd's face goes carefully blank. He plants his crook firmly and watches a different direction.",
                "He does not return the wave. The set of his shoulders says he's finished with @1.",
                "The old shepherd turns his back to @1np with the deliberate ceremony of a man who's done it before to others who deserved it.",
            ],
        },
        "nod": {
            Warmth.HOT: [
                "The shepherd nods back with weight. \"Aye, friend. Aye.\"",
                "He returns the nod twice — the second deeper than the first — and crinkles his eyes.",
                "The old shepherd dips his crook in answer and grins his weathered grin.",
            ],
            Warmth.WARM: [
                "The shepherd nods back warmly. \"Aye.\"",
                "He returns the nod with his slow seriousness. \"Friend.\"",
                "The old shepherd dips his head, holds it a beat, comes back up.",
            ],
            Warmth.NEUTRAL: [
                "The shepherd nods once, polite, and goes back to his watching.",
                "He returns the nod and the conversation between them is complete.",
                "The old shepherd dips his chin a measured fraction, and lets that suffice.",
            ],
            Warmth.COOL: [
                "The shepherd's nod, if it was one, was small enough to be the wind.",
                "He doesn't quite nod. He doesn't quite not.",
                "The old shepherd's chin doesn't move, but his eyes acknowledge that the gesture happened.",
            ],
            Warmth.COLD: [
                "The shepherd does not return the nod. He plants his crook and watches the country.",
                "He turns his face deliberately away.",
                "The old shepherd ignores the gesture entirely, his attention on a tuft of grass that suddenly fascinates him.",
            ],
        },
        "greet": {
            Warmth.HOT: [
                "The shepherd grins broad and clasps @1np forearm in greeting. \"Friend, friend. The country's been quieter without you, and I mean that as a compliment.\"",
                "\"@1d!\" the shepherd says, real warmth crinkling his face. \"Glad to find you here. Has the willow been kind today?\"",
                "He laughs, crinkles his whole face up. \"Sit a moment, friend, sit. The wool can wait. The wool's never in a hurry.\"",
            ],
            Warmth.WARM: [
                "The shepherd smiles the slow, deep way old shepherds smile. \"Hello, friend. Glad to see your face on this stretch.\"",
                "\"Aye, well met,\" he says, planting his crook. \"How's the wind been treating you?\"",
                "The old shepherd touches his hat. \"Friend. Stay a while if you've a moment. The clearing keeps better company that way.\"",
            ],
            Warmth.NEUTRAL: [
                "The shepherd nods. \"Friend.\"",
                "\"Aye,\" he says, with the polite economy of his country. \"Hello to you.\"",
                "The old shepherd dips his hat brim. \"Greeting, friend.\"",
            ],
            Warmth.COOL: [
                "The shepherd grunts a syllable that may have been a greeting.",
                "He acknowledges @1np with the flatness of country-talk: \"Aye.\"",
                "The old shepherd inclines his head minimally and goes back to the treeline.",
            ],
            Warmth.COLD: [
                "The shepherd does not return the greeting. He plants his crook and watches the south path.",
                "\"I'm working,\" he says flatly, which is true and also not the whole reason.",
                "The old shepherd lets the silence speak. The silence is not warm.",
            ],
        },
    }

    DEPART_WHEN_PUSHED_POOL: List[str] = [
        "The shepherd raises a placating hand. \"You'll have to ask the hills, friend. I just walk where they tell me. Be well.\" He ambles off.",
        "\"Long day ahead,\" the shepherd says, planting his crook for one final lean. \"Sheep don't find themselves. Mind the road.\" He's gone before the next question lands.",
        "The old shepherd touches his hat brim. \"Some questions are for the dirt, friend. I just walk on it.\" He turns and ambles off at his country pace.",
    ]

    FLEE_FROM_ATTACK_POOL: List[str] = [
        "The shepherd's eyes go cold. He plants his crook between himself and @2 — not in defiance, in geometry — and walks backward steadily out of the clearing without ever quite turning his back.",
        "\"None of that, friend,\" the shepherd says calmly, and he's already moving. He's faster than he looks. The crook clears the verge before @2 quite registers the motion.",
        "The old shepherd steps backward at his deliberate pace, one hand raised, the other firm on his crook. \"You'll regret that. Or you won't. Either way, not here, not me.\" He's gone into the trees before the second sentence finishes.",
        "He turns and walks — not runs, walks — but at a country-emergency pace that eats ground. The clearing loses him in three breaths.",
    ]

    LOOK_LINE: str = (
        "A shepherd patrols the verges with a worn crook, watching "
        "for sheep and listening for whatever might whistle back."
    )
