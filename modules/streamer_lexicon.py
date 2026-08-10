"""
Streamer culture lexicon for clip scoring.

Layered data for the profiler:
  CATCHPHRASE_REGISTRY   per-streamer hooks with tier, boost, and clip-boundary role
  IDIOM_NORMALIZER       multi-word idioms collapsed to semantic-class tokens before scoring
  CROSS_CULTURAL_SLANG   single-word slang tagged by semantic class
  SEMANTIC_BOOST_MAP     flat dict consumed by clip_engine.get_semantic_boost (drop-in)
  HAZARD_PHRASES         strings that mark high-risk segments (handled in clip_hazards.py)

Tiers: peak=0.22, strong=0.14, mild=0.06.
Boundary roles:
  payoff   catchphrase is the punchline, clip should END shortly after
  lead-in  catchphrase precedes the peak, buffer N seconds for the payoff
  endpoint speaker is wrapping/leaving the segment, natural cut here
"""

PEAK = 0.22
STRONG = 0.14
MILD = 0.06

# Per-streamer catchphrases.
# Tuning per user: Peak = Plaqueboymax, Bruce, iShowSpeed, HotShotAaron, Sonwabile.
# Strong = Kai Cenat, YourRage, FlightReacts, Carter Efe, Shank Comic.
CATCHPHRASE_REGISTRY = {
    # --- Peak-tier streamers ---
    "plaqueboymax": {
        "tier": "peak",
        "phrases": {
            "iceman reaction brrrr": {"boost": PEAK, "role": "payoff"},
            "iceman reaction": {"boost": PEAK, "role": "payoff"},
            "5$tar": {"boost": PEAK, "role": "lead-in"},
            "five star": {"boost": PEAK, "role": "lead-in"},
            "5star cypher": {"boost": PEAK, "role": "lead-in"},
            "5star trivia": {"boost": PEAK, "role": "lead-in"},
            "cax": {"boost": PEAK, "role": "payoff"},
            "smell my breath": {"boost": PEAK, "role": "payoff"},
            "fent dance": {"boost": PEAK, "role": "payoff"},
            "hair dye lady": {"boost": PEAK, "role": "payoff"},
            "sped": {"boost": STRONG, "role": "payoff"},
            "zesty": {"boost": STRONG, "role": "payoff"},
        },
        "collaborators": ["tae", "morgan", "ron"],
    },
    "brucedropemoff": {
        "tier": "peak",
        "phrases": {
            "deo": {"boost": PEAK, "role": "lead-in"},
            "dropemoff": {"boost": PEAK, "role": "lead-in"},
            "drop em off": {"boost": PEAK, "role": "lead-in"},
        },
        "hazard_phrases": ["dyk is over", "dyk over", "drop your knees over"],
    },
    "ishowspeed": {
        "tier": "peak",
        "phrases": {
            "cristo ronaldo sewey": {"boost": PEAK, "role": "payoff"},
            "ronaldo sewey": {"boost": PEAK, "role": "payoff"},
            "sewey": {"boost": STRONG, "role": "payoff"},
            "siu": {"boost": STRONG, "role": "payoff"},
        },
        "acoustic_signature": "barking",
    },
    "hotshotaaron": {
        "tier": "peak",
        "phrases": {
            "hsn": {"boost": PEAK, "role": "lead-in"},
            "hotshotnation": {"boost": PEAK, "role": "lead-in"},
            "hotshot nation": {"boost": PEAK, "role": "lead-in"},
            "try not to laugh": {"boost": PEAK, "role": "lead-in"},
            "reuniting with adonis": {"boost": PEAK, "role": "payoff"},
            "motion will make you": {"boost": STRONG, "role": "payoff"},
        },
    },
    "sonwabile": {
        "tier": "peak",
        "phrases": {
            "rizzler bear": {"boost": PEAK, "role": "payoff"},
            "adambe": {"boost": PEAK, "role": "lead-in"},
            "team adambe": {"boost": PEAK, "role": "lead-in"},
            "tokoloshe": {"boost": PEAK, "role": "payoff"},
            "spreading humours": {"boost": STRONG, "role": "lead-in"},
        },
        "acoustic_signature": "horror_scream",
    },

    # --- Strong-tier streamers ---
    "kai_cenat": {
        "tier": "strong",
        "phrases": {
            "word to my mother": {"boost": STRONG, "role": "lead-in", "buffer_sec": 3},
            "chop cheese": {"boost": STRONG, "role": "payoff"},
            "bacon egg and cheese": {"boost": STRONG, "role": "payoff"},
            "let me get a what": {"boost": STRONG, "role": "lead-in", "buffer_sec": 2},
            "like what like how": {"boost": STRONG, "role": "lead-in", "buffer_sec": 2},
            "say cheese": {"boost": STRONG, "role": "payoff"},
            "w strokes": {"boost": MILD, "role": "payoff"},
        },
        "visual_signature": "frozen_grin",
    },
    "yourrage": {
        "tier": "strong",
        "phrases": {
            "yrg": {"boost": STRONG, "role": "lead-in"},
            "yourragegaming": {"boost": STRONG, "role": "lead-in"},
            "gazer": {"boost": STRONG, "role": "payoff"},
            "my knee": {"boost": STRONG, "role": "payoff"},
            "my shoulder": {"boost": STRONG, "role": "payoff"},
            "my knees": {"boost": STRONG, "role": "payoff"},
            "my shoulders": {"boost": STRONG, "role": "payoff"},
        },
        "hazard_phrases": ["bruce", "deo"],  # post-DYK schism mentions
    },
    "flightreacts": {
        "tier": "strong",
        "phrases": {
            "look at curry man": {"boost": STRONG, "role": "payoff"},
            "by june": {"boost": STRONG, "role": "lead-in"},
            "irish spring green green": {"boost": STRONG, "role": "payoff"},
        },
        "acoustic_signature": "dolphin_laugh",
    },
    "carter_efe": {
        "tier": "strong",
        "phrases": {
            "machala": {"boost": STRONG, "role": "lead-in"},
            "wizkid fc": {"boost": STRONG, "role": "lead-in"},
            "open your mouth": {"boost": STRONG, "role": "payoff"},
            "shoot gun": {"boost": MILD, "role": "payoff"},  # theatrical, hazard-flagged
            "two gun shooting": {"boost": MILD, "role": "payoff"},
        },
        "hazard_phrases": ["shoot gun", "two gun shooting"],  # theatrical-vs-real check
    },
    "shank_comic": {
        "tier": "strong",
        "phrases": {
            "lit gang": {"boost": STRONG, "role": "lead-in"},
            "money is my set": {"boost": STRONG, "role": "payoff"},
            "i ain't losing no money": {"boost": STRONG, "role": "payoff"},
            "we on smoke baby": {"boost": STRONG, "role": "payoff"},
            "we on smoke": {"boost": STRONG, "role": "payoff"},
            "you don't have questions about god": {"boost": STRONG, "role": "payoff"},
        },
    },
}


# Multi-word idioms collapsed to semantic-class tokens before any further scoring.
# Whisper often mangles these; the normalized token gives the classifier a
# stable feature even when the surface text varies.
IDIOM_NORMALIZER = {
    # South African idioms
    "is not make sure": "__DISAPPROVAL__",
    "same whatsapp group": "__SIMILAR__",
    "id photo": "__HYGIENE_INSULT__",
    # Kai Cenat NY intensifiers
    "word to my mother": "__NY_INTENSIFIER__",
    "like what like how": "__NY_INTENSIFIER__",
    # Suspicion class — semantic equivalents across regions
    "k-leg": "__SUSPICIOUS__",
    "k leg": "__SUSPICIOUS__",
    "no cap": "__SUSPICIOUS__",
    "cap": "__SUSPICIOUS__",
    # Namibian shock + boundary
    "atata-taah": "__SHOCK_PEAK__",
    "atata taah": "__SHOCK_PEAK__",
    "zimbuka": "__SEGMENT_END__",
    # Nigerian Pidgin
    "wetin dey happen": "__CONFUSION__",
    "wahala": "__TENSION__",
    "abeg": "__DISMISSAL__",
}


# Single-word slang tagged by semantic class. All four regions weighted equally
# per user preference; on conflict, the highest semantic_weight wins.
CROSS_CULTURAL_SLANG = {
    # --- Namibian / Namlish ---
    "atata-taah": {"class": "shock_peak",   "weight": 0.20, "region": "nam"},
    "zimbuka":    {"class": "segment_end",  "weight": 0.00, "region": "nam"},  # boundary, no boost
    "praating":   {"class": "low_volume_segment", "weight": 0.00, "region": "nam"},
    "papura":     {"class": "comedic_downtime",   "weight": 0.08, "region": "nam"},
    "aweh":       {"class": "ambiguous_excite",   "weight": 0.05, "region": "nam"},  # intonation-dependent
    "mxm":        {"class": "frustration",  "weight": 0.10, "region": "nam"},
    "etse":       {"class": "drama",        "weight": 0.12, "region": "nam"},
    "verra":      {"class": "greeting",     "weight": 0.03, "region": "nam"},
    "smaak":      {"class": "positive_vibe","weight": 0.06, "region": "nam"},
    "nxa":        {"class": "approval",     "weight": 0.06, "region": "nam"},
    "mos":        {"class": "punctuation",  "weight": 0.00, "region": "nam"},
    "neh":        {"class": "punctuation",  "weight": 0.00, "region": "nam"},

    # --- American AAVE / W/L ---
    "motion":     {"class": "status_topic", "weight": 0.10, "region": "us"},
    "rizz":       {"class": "charisma",     "weight": 0.10, "region": "us"},
    "glaze":      {"class": "accusation",   "weight": 0.10, "region": "us"},
    "glazing":    {"class": "accusation",   "weight": 0.10, "region": "us"},
    "cap":        {"class": "suspicion",    "weight": 0.08, "region": "us"},
    "no cap":     {"class": "emphasis",     "weight": 0.06, "region": "us"},
    "sped":       {"class": "insult_play",  "weight": 0.10, "region": "us"},
    "zesty":      {"class": "insult_play",  "weight": 0.10, "region": "us"},
    "5$tar":      {"class": "community_id", "weight": 0.20, "region": "us"},
    "deo":        {"class": "community_id", "weight": 0.20, "region": "us"},
    "yrg":        {"class": "community_id", "weight": 0.18, "region": "us"},

    # --- South African ---
    "eish":       {"class": "rant_prelude", "weight": 0.10, "region": "sa"},
    "yoh":        {"class": "rant_prelude", "weight": 0.10, "region": "sa"},
    "robot":      {"class": "irl_context",  "weight": 0.00, "region": "sa"},  # disambiguator only
    "nyuku":      {"class": "lifestyle",    "weight": 0.06, "region": "sa"},
    "moreki":     {"class": "lifestyle",    "weight": 0.06, "region": "sa"},

    # --- Nigerian Pidgin ---
    "wahala":     {"class": "tension",      "weight": 0.10, "region": "ng"},
    "comot":      {"class": "aggression",   "weight": 0.10, "region": "ng"},
    "k-leg":      {"class": "suspicion",    "weight": 0.10, "region": "ng"},
    "abeg":       {"class": "dismissal",    "weight": 0.08, "region": "ng"},
    "vex":        {"class": "anger_prelude","weight": 0.10, "region": "ng"},
    "machala":    {"class": "community_id", "weight": 0.18, "region": "ng"},

    # --- Carry-overs from the legacy SEMANTIC_BOOST_MAP so existing behavior
    # is preserved (these were already wired into the engine) ---
    "jawn":       {"class": "person",       "weight": 0.12, "region": "us"},
    "hun":        {"class": "person",       "weight": 0.12, "region": "us"},
    "bunda":      {"class": "relationship", "weight": 0.08, "region": "nam"},
    "goon":       {"class": "person",       "weight": 0.06, "region": "nam"},
    "ngl":        {"class": "confession",   "weight": 0.08, "region": "us"},
    "fr":         {"class": "emphasis",     "weight": 0.06, "region": "us"},
    "ong":        {"class": "emphasis",     "weight": 0.06, "region": "us"},
    "lowkey":     {"class": "admission",    "weight": 0.06, "region": "us"},
    "deadass":    {"class": "sincerity",    "weight": 0.08, "region": "us"},
    "gg":         {"class": "acknowledgment","weight": 0.05, "region": "us"},
    "gooner":     {"class": "shock_disgust","weight": 0.10, "region": "us"},
    "beat my meat":   {"class": "explicit_shock", "weight": 0.12, "region": "us"},
    "stroke my shi":  {"class": "explicit_shock", "weight": 0.12, "region": "us"},
    "etche":      {"class": "wtf_questionable", "weight": 0.10, "region": "nam"},
    "jrrr":       {"class": "wtf_reaction", "weight": 0.10, "region": "nam"},
    "tah":        {"class": "extreme_shock","weight": 0.09, "region": "nam"},
    "yeses":      {"class": "insane_reaction", "weight": 0.10, "region": "nam"},
    "5":          {"class": "person",       "weight": 0.04, "region": "us"},
}


# Drop-in replacement for the legacy SEMANTIC_BOOST_MAP in clip_engine.py.
# Same shape: {slang: (meaning_label, value)}.
# Built by merging single-word slang + every per-streamer catchphrase, so the
# engine's substring-matching code picks up streamer-specific hooks for free.
def _build_semantic_boost_map():
    merged = {}
    for term, meta in CROSS_CULTURAL_SLANG.items():
        if meta["weight"] > 0:
            merged[term.lower()] = (meta["class"], meta["weight"])

    for streamer, data in CATCHPHRASE_REGISTRY.items():
        for phrase, meta in data.get("phrases", {}).items():
            key = phrase.lower()
            new_val = meta["boost"]
            # Highest-boost wins on conflict.
            if key in merged and merged[key][1] >= new_val:
                continue
            merged[key] = (f"{streamer}:{meta.get('role', 'phrase')}", new_val)
    return merged


SEMANTIC_BOOST_MAP = _build_semantic_boost_map()


# Phrases that should trigger the hazard soft-flag (see modules/clip_hazards.py).
# These don't penalize score by themselves — they're metadata for the UI / user review.
HAZARD_PHRASES = {
    "dyk_schism": [
        "dyk is over", "dyk over", "drop your knees over",
    ],
    "theatrical_violence": [
        "shoot gun", "two gun shooting", "i'll kill you",
    ],
    "intoxication_hint": [
        "i'm drunk", "i'm fucked up", "i'm zooted", "i'm cooked",
        "i'm faded", "i'm lit fr",
    ],
    "political_debate": [
        "trump", "biden", "election", "republican", "democrat",
        "abortion", "israel", "palestine", "gaza", "ukraine", "russia",
    ],
    "dmca_risk_audio_marker": [
        # Phrases that strongly imply background commercial music with no reaction.
        "just listening", "let me put this song", "playing in background",
    ],
}


def lookup_catchphrase(text: str):
    """
    Return list of (streamer, phrase, meta) tuples for every catchphrase
    detected in `text`. Useful for UI surfacing and clip-boundary hints.
    """
    if not text:
        return []
    lower = text.lower()
    hits = []
    for streamer, data in CATCHPHRASE_REGISTRY.items():
        for phrase, meta in data.get("phrases", {}).items():
            if phrase.lower() in lower:
                hits.append((streamer, phrase, meta))
    return hits


def normalize_idioms(text: str) -> str:
    """
    Replace known multi-word idioms with stable semantic-class tokens.
    Call this before any tokenization-based scoring so Whisper variants
    collapse to a single feature.
    """
    if not text:
        return text
    out = text
    lower = out.lower()
    for idiom, token in IDIOM_NORMALIZER.items():
        if idiom in lower:
            # Case-insensitive substitution; preserve token in upper-case form.
            idx = lower.find(idiom)
            while idx != -1:
                out = out[:idx] + token + out[idx + len(idiom):]
                lower = out.lower()
                idx = lower.find(idiom, idx + len(token))
    return out
