"""Constants for the chat_stats analytics pipeline.

Single source of truth for stopwords, regexes, and every tunable
magic number. No imports from the rest of the package so this module
is safe to import from anywhere (including the PyInstaller spec).
"""
from __future__ import annotations

STOPWORDS = frozenset(
    {
        "the",
        "a",
        "an",
        "and",
        "or",
        "but",
        "if",
        "then",
        "else",
        "for",
        "to",
        "of",
        "in",
        "on",
        "at",
        "by",
        "with",
        "from",
        "as",
        "is",
        "it",
        "this",
        "that",
        "these",
        "those",
        "i",
        "you",
        "he",
        "she",
        "we",
        "they",
        "them",
        "his",
        "her",
        "its",
        "our",
        "your",
        "their",
        "me",
        "him",
        "us",
        "my",
        "mine",
        "yours",
        "was",
        "were",
        "are",
        "be",
        "been",
        "being",
        "have",
        "has",
        "had",
        "do",
        "does",
        "did",
        "will",
        "would",
        "can",
        "could",
        "should",
        "not",
        "no",
        "yes",
        "so",
        "too",
        "very",
        "just",
        "like",
        "get",
        "got",
        "im",
        "dont",
        "what",
        "when",
        "where",
        "who",
        "how",
        "why",
        "all",
        "any",
        "out",
        # --- Polish ---
        "te",
        "ta",
        "ten",
        "go",
        "mu",
        "sie",
        "na",
        "co",
        "jak",
        "nie",
        "ale",
        "jest",
        "bo",
        "tak",
        "ty",
        "ja",
        "po",
        "ze",
        "dla",
        "oraz",
        "lub",
        "albo",
        "czy",
        "przy",
        "bez",
        "nad",
        "pod",
        "tylko",
        "bardzo",
        "mo",
        "ju",
        "tu",
        "tam",
        "za",
        "si",
        # --- Web ---
        "https",
        "http",
        "com",
        "www",
    }
)

# --- Regex Constants ---
# URL_RE is intentionally conservative: it truncates on ')' for Wikipedia-style
# URLs. That's an acceptable tradeoff — fixing it requires paren-balancing.
URL_RE = r"https?://[^\s<>()\[\]{}\"',;!?]+"

# NOTE: Polars' Rust regex engine does not support look-around (neither
# look-ahead `(?=...)`/`(?!...)` nor look-behind `(?<=...)`/`(?<!...)`). All
# patterns below are look-around-free. `\B` (non-word-boundary) is used to
# reject the `@` inside emails/URLs without a look-behind.
#
# Twitch usernames are ASCII (letters, digits, underscore). `\B@` means:
# match `@` where the preceding char is NOT a word character — equivalent
# to the old `(?<![A-Za-z0-9_])@`, but supported by Polars.
MENTION_RE = r"\B@[A-Za-z0-9_]+"

# Words: Unicode-aware, applied after .str.to_lowercase(). First char must be
# a letter or digit (replaces the old `(?=[\p{L}\p{N}])` look-ahead);
# remaining chars may also include apostrophes, so `don't` and `a'b` match
# but `'''` does not.
WORD_RE = r"[\p{L}\p{N}][\p{L}\p{N}']+"

# Emote names (Twitch, BTTV, FFZ, 7TV) are ASCII identifiers.
EMOTE_TOKEN_RE = r"[A-Za-z0-9_]+"
# Command names are ASCII identifiers.
COMMAND_RE = r"^[A-Za-z0-9_\-]+"

# --- Magic Numbers ---
PROGRESS_MSG_THRESHOLD = 2000
MAX_REPEAT_TEXT_LEN = 300
MAX_EMOTES_PER_MSG = 20
MIN_ALPHA_CHARS_FOR_LANG = 10
LANG_SAMPLE_SIZE = 1000
MIN_ALPHA_FOR_CAPS = 5
MAX_ANOMALIES = 50
WORDS_ZIPF_MAX_RANK = 1000  # Zipf tail deviates; fit the head only
POISSON_NORMAL_APPROX_LAMBDA = 30.0
REPLY_WINDOW_S = 300  # quote-reply recency window (5 minutes)
REPLY_TOP_N = 15
MIN_PLAUSIBLE_AVG_MESSAGE_LEN = 3.0
MAX_PLAUSIBLE_AVG_MESSAGE_LEN = 400.0
COPY_PASTE_MIN_OCCURRENCES = 3
COPY_PASTE_WINDOW_S = 60
COPY_PASTE_TOP_N = 10

LORENZ_FRACTIONS = (0.01, 0.05, 0.10, 0.25, 0.50)

BOT_MIN_MESSAGES = 50
BOT_TOP_N = 50

COHORT_MAX_WEEKS = 8

# Page-level retries handle seconds-long blips; this second line of defense
# handles the minute-long ones.
SPAN_RETRY_COOLDOWN_S = 30.0
SPAN_RETRY_TICK_S = 5.0
