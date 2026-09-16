/**
 * Message-text patterns shared by client-side filters.
 *
 * URL_RE must stay in sync with `URL_RE` in
 * `src-python/app/scripts/chat_stats/constants.py` (backend analytics use
 * the full capture; the panel only needs the boolean). In particular `?`
 * stays in the class so query strings (`?v=…`) survive matching.
 */
export const URL_RE = /https?:\/\/[^\s<>()[\]{}"',;!]+/;
