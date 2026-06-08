"""Synapse Protocol V1 — Flask Web Application"""
import json
import time
import math
import hmac
import hashlib
import re
import random
import difflib
import requests as http
from datetime import datetime, timedelta
from pathlib import Path
from flask import (Flask, render_template, request, jsonify,
                   Response, redirect, url_for)

import sys
BASE = Path(__file__).parent.parent
sys.path.insert(0, str(BASE))

CFG_PATH   = BASE / "Config" / "Settings.json"
PROMPTS    = BASE / "Prompts"
SIG_PATH   = BASE / "Config" / "Signature.json"

# ─── Creator Signature / Checksum ([Chk] tracker field) ──────────────────────
# The private signature is the HMAC key behind every turn's [Chk:] value: it
# cannot be read back from output, only verified by re-computing with the key
# (tools/verify_chk.py). Doubles as a tamper/desync check — any state change
# changes [Chk]. If no signature file is present, falls back to a plain hash
# (still a working integrity check, just unsigned).

_SIG_CACHE = None

def load_signature() -> str:
    global _SIG_CACHE
    if _SIG_CACHE is None:
        try:
            if SIG_PATH.exists() and SIG_PATH.stat().st_size:
                with open(SIG_PATH, encoding="utf-8") as f:
                    _SIG_CACHE = (json.load(f).get("signature") or "").strip()
            else:
                _SIG_CACHE = ""
        except Exception:
            _SIG_CACHE = ""
    return _SIG_CACHE

def compute_chk(payload: str) -> str:
    """8-hex checksum over `payload`. HMAC-keyed by the creator signature when
    present (verifiable authorship), else a plain SHA-256 prefix (unsigned)."""
    data = payload.encode("utf-8")
    sig  = load_signature()
    if sig:
        return hmac.new(sig.encode("utf-8"), data, hashlib.sha256).hexdigest()[:8]
    return hashlib.sha256(data).hexdigest()[:8]

app = Flask(__name__)
app.secret_key = "echo_v8_secret_key"

# ─── Provider Detection ──────────────────────────────────────────────────────

_PROVIDERS = [
    ("api.deepseek.com",   "DeepSeek",    "deepseek-chat",           "deepseek"),
    ("localhost:11434",    "Ollama",      "llama3:8b",               "ollama"),
    ("127.0.0.1:11434",    "Ollama",      "llama3:8b",               "ollama"),
    ("api.openai.com",     "OpenAI",      "gpt-4o",                  "openai"),
    ("api.groq.com",       "Groq",        "llama3-70b-8192",         "groq"),
    ("openrouter.ai",      "OpenRouter",  "auto",                    "openrouter"),
    ("api.together.xyz",   "Together AI", "meta-llama/Llama-3-70b",  "openrouter"),
    ("api.mistral.ai",     "Mistral",     "mistral-large-latest",    "openai"),
    ("api.perplexity.ai",  "Perplexity",  "llama-3-sonar-large",     "openrouter"),
]

def detect_provider(url: str) -> dict:
    from urllib.parse import urlparse
    for pattern, name, model, theme in _PROVIDERS:
        if pattern in url:
            return {"name": name, "model": model, "theme": theme}
    host = urlparse(url).hostname or "custom"
    return {"name": host, "model": "unknown", "theme": "deepseek"}

# ─── Config ──────────────────────────────────────────────────────────────────

def load_cfg() -> dict:
    if not CFG_PATH.exists() or CFG_PATH.stat().st_size == 0:
        return {}
    with open(CFG_PATH, encoding="utf-8") as f:
        return json.load(f)

def save_cfg(data: dict):
    CFG_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(CFG_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

# ─── Setup Flags & Commands ──────────────────────────────────────────────────

_FLAGS_DEFAULT = {
    "world_created": False, "pc_created": False, "start_created": False,
    "game_started":  False, "game_paused": False,
    "world_data": {}, "pc_data": {}, "start_data": {},
}

# Short deterministic reply for a bare stop command; resume keyword is "เล่นต่อ".
PAUSE_MSG = 'หยุดแล้ว — พิมพ์ "เล่นต่อ" เมื่อพร้อมกลับเข้าเล่นต่อ'
# Briefing cue when the Auditor INFERS a stop ("หยุด" + off-topic): pause, then answer in OOC.
PAUSE_INFER_CUE = ('PAUSED_BY_INFERENCE: the player asked to stop the game. '
                   'Confirm briefly that the game is paused ("หยุดแล้ว"), then answer their '
                   'out-of-character message plainly (if any). Tell them to type "เล่นต่อ" to resume. '
                   'Do NOT narrate story, advance time, or move NPCs.')

def flags_path(db: Path) -> Path:
    """Per-campaign setup flags — isolated so one campaign's setup never leaks into another."""
    return db / "Setup_Flags.json"

def load_flags(db: Path) -> dict:
    fp = flags_path(db)
    if fp.exists() and fp.stat().st_size:
        try:
            with open(fp, encoding="utf-8") as f:
                return {**_FLAGS_DEFAULT, **json.load(f)}
        except Exception:
            pass
    return dict(_FLAGS_DEFAULT)

def save_flags(db: Path, flags: dict):
    fp = flags_path(db)
    fp.parent.mkdir(parents=True, exist_ok=True)
    with open(fp, "w", encoding="utf-8") as f:
        json.dump(flags, f, ensure_ascii=False, indent=2)

def detect_command(player_input: str, flags: dict) -> str | None:
    """Return command result and mutate flags. None if not a command."""
    s = player_input.strip()
    # accept either [start] or a bare whole-message keyword (start / เริ่ม), but not a keyword inside a sentence
    core = s[1:-1] if (s.startswith("[") and s.endswith("]")) else s
    cmd = core.strip().lower()
    if cmd in ("start", "เริ่มเกม", "เริ่ม"):
        if flags.get("world_created") and flags.get("pc_created") and flags.get("start_created"):
            flags["game_started"] = True
            return "start_game"
        missing = []
        if not flags.get("world_created"): missing.append("world")
        if not flags.get("pc_created"):    missing.append("character")
        if not flags.get("start_created"): missing.append("starting point")
        return "cannot_start:" + ",".join(missing)
    # Bare stop word → instant pause (other languages / "หยุด"+off-topic handled by Auditor inference)
    if cmd in ("pause", "stop", "หยุดเกม", "หยุด", "พัก", "พอ"):
        flags["game_paused"] = True
        return "pause"
    if cmd in ("resume", "เล่นต่อ", "เล่น", "ต่อ", "play"):
        flags["game_paused"] = False
        return "resume"
    return None

def get_db(cfg: dict = None) -> Path:
    if cfg is None:
        cfg = load_cfg()
    db_str = cfg.get("db_path", "")
    return Path(db_str) if db_str else BASE / "Database"

def get_model_info(cfg: dict) -> tuple:
    pri_cfg = cfg.get("primary", {})
    sec_cfg = cfg.get("secondary", {})
    pri = detect_provider(pri_cfg.get("url", ""))
    sec = detect_provider(sec_cfg.get("url", ""))
    if "model" in pri_cfg: pri["model"] = pri_cfg["model"]
    if "model" in sec_cfg: sec["model"] = sec_cfg["model"]
    pri.update({"url": pri_cfg.get("url",""), "api_key": pri_cfg.get("api_key","")})
    sec.update({"url": sec_cfg.get("url",""), "api_key": sec_cfg.get("api_key","")})
    return pri, sec

# ─── DB Utilities ────────────────────────────────────────────────────────────

def load_json(path: Path):
    if not path.exists() or path.stat().st_size == 0:
        return {}
    with open(path, encoding="utf-8") as f:
        return json.load(f)

def save_json(path: Path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

def clamp(val, lo=0, hi=100) -> int:
    return int(max(lo, min(hi, val)))

def load_state(db: Path) -> dict:
    return {
        "geography":  load_json(db / "World" / "01_Geography.json"),
        "history":    load_json(db / "World" / "05_History.json"),
        "laws":       load_json(db / "World" / "06_Active_Laws.json"),
        "physical":   load_json(db / "PC"    / "01_Physical.json"),
        "mental":     load_json(db / "PC"    / "02_Mental.json"),
        "inventory":  load_json(db / "PC"    / "03_Inventory.json"),
        "politics":   load_json(db / "World" / "02_Politics.json"),
        "economy":    load_json(db / "World" / "03_Economy.json"),
        "tech":       load_json(db / "World" / "04_Magic_Tech.json"),
        "worldbook":  load_worldbook(db),
        "npcs":       _load_npcs(db),
        "provisional": load_provisional(db).get("entries", []),
    }

def _load_npcs(db: Path) -> list:
    npc_dir = db / "NPCs"
    if not npc_dir.exists():
        return []
    result = []
    for folder in sorted(npc_dir.iterdir()):
        if folder.is_dir():
            profile = load_json(folder / "Profile.json")
            rel     = load_json(folder / "Relationships.json")
            if profile:
                result.append({**profile, "relationship": rel})
    return result

def load_index(db: Path) -> dict:
    idx = load_json(db / "Index" / "Turn_Index.json")
    return idx or {"current_turn": 0, "current_date": "", "history": []}

# ─── In-game date (toggle cfg["ingame_date"]) ────────────────────────────────

def fmt_date(s: str) -> str:
    try:
        return datetime.fromisoformat(s).strftime("%d/%m/%Y")
    except Exception:
        return s

def advance_date(date_str: str, days: int = 0, hours: int = 0) -> str:
    try:
        dt = datetime.fromisoformat(date_str) + timedelta(days=days, hours=hours)
        return dt.date().isoformat() if not hours else dt.isoformat(timespec="hours")
    except Exception:
        return date_str   # unparseable (e.g. just a year) → keep as-is, no precise advance

def apply_date(auditor_out: dict, index: dict, cfg: dict):
    """Maintain the in-game date. The simple Day-counter (game_day) ALWAYS tracks elapsed STORY days — it works even when the calendar toggle is off, and never advances on OOC/meta turns (the day must not climb just because turns pass). The ISO calendar (game_date) is the opt-in ingame_date feature; explicit date anchors it, time_passed advances it."""
    tp = auditor_out.get("time_passed") or {}
    try:    days = int(tp.get("days", 0) or 0)
    except (TypeError, ValueError): days = 0
    try:    hours = int(tp.get("hours", 0) or 0)
    except (TypeError, ValueError): hours = 0
    if auditor_out.get("is_ooc"):     # off-topic/OOC/meta turns pass NO in-game time
        days = hours = 0
    index["game_day"] = max(0, int(index.get("game_day", 0) or 0) + days)
    clock = int(index.get("game_clock", 480) or 480)   # in-game time-of-day (min), starts 08:00
    index["game_clock"] = (clock + hours * 60) % 1440  # advances by elapsed hours (sleep/skip), wraps daily
    if not cfg.get("ingame_date"):
        return
    ed  = (auditor_out.get("explicit_date") or "").strip()[:10]   # trim any time suffix → YYYY-MM-DD
    cur = (index.get("game_date") or "")[:10]
    ok  = bool(re.fullmatch(r"\d{4}-\d{2}-\d{2}", ed))            # well-formed calendar date only
    if ed and ok and (not cur or ed >= cur):                     # anchor ONLY if valid & not backward
        index["game_date"] = ed
    elif cur and (days or hours):                                # else advance by elapsed time (date-only)
        index["game_date"] = advance_date(cur, days, hours)[:10]

# ─── Wikipedia grounding (toggle cfg["web_lookup"]) ───────────────────────────

_WIKI_UA = {"User-Agent": "SynapseProtocolV1/1.0 (interactive fiction engine)"}

def wiki_lookup(query: str, langs=("th", "en"), chars: int = 1500) -> str:
    """Fetch a Wikipedia intro extract for grounding a real/historical world. Network-guarded — returns '' on any failure (never breaks the turn)."""
    if not query:
        return ""
    for lang in langs:
        try:
            r = http.get(f"https://{lang}.wikipedia.org/w/api.php", params={
                "action": "query", "format": "json", "prop": "extracts",
                "exintro": 1, "explaintext": 1,
                "generator": "search", "gsrsearch": query, "gsrlimit": 1,
            }, headers=_WIKI_UA, timeout=8)
            r.raise_for_status()
            for p in (r.json().get("query", {}).get("pages", {}) or {}).values():
                ex = (p.get("extract") or "").strip()
                if ex:
                    return ex[:chars]
        except Exception:
            continue
    return ""

def get_recent_history(index: dict, n: int = 5) -> str:
    hist = index.get("history", [])[-n:]
    if not hist:
        return "No prior events."
    return " | ".join(f"T{h['turn']}:{h['summary']}" for h in hist)

# ─── Recall: relevance retrieval over the permanent archive ──────────────────
# Data is permanent on disk; the working context is a ~50% budget window. Instead
# of filling that window purely by recency, reserve part for the most RELEVANT
# older turns (lexical TF-IDF over the per-turn archive) so distant facts can
# return on demand without overflowing context. Pure-Python, no extra deps.

_STOP = set(("the a an of to and or is are was were be been in on at it this that "
             "i you he she we they my your his her its our their").split())
_ASCII_RE = re.compile(r"[a-z0-9]{2,}")
_THAI_RE  = re.compile(r"[฀-๿]+")

def _tokenize(text: str) -> list:
    """ASCII word tokens + Thai character trigrams. Thai (and other space-less
    scripts) don't delimit words with spaces, so whole-run tokens never overlap;
    overlapping trigrams give meaningful lexical similarity instead."""
    if not text:
        return []
    out = [t for t in _ASCII_RE.findall(text.lower()) if t not in _STOP]
    for run in _THAI_RE.findall(text):
        if len(run) <= 3:
            out.append(run)
        else:
            out.extend(run[i:i + 3] for i in range(len(run) - 2))
    return out

def recall_index_path(db: Path) -> Path:
    return db / "Index" / "Recall_Index.json"

def build_query(player_input: str, state: dict) -> tuple:
    """(terms, npc_ids, loc) describing what the current turn is 'about'."""
    loc  = state.get("geography", {}).get("current_location", {}).get("id", "")
    npcs = [_safe_name(str(n.get("npc_id") or n.get("name") or ""))
            for n in state.get("npcs", []) if isinstance(n, dict)]
    return (_tokenize(player_input), [x for x in npcs if x], loc)

def update_recall_index(db: Path, turn: int, date: str, game_date: str,
                        player_input: str, narrator_out: str, auditor_out: dict):
    """Append/replace this turn's lightweight term entry (incremental — never rescans)."""
    p   = recall_index_path(db)
    idx = load_json(p) or {"turns": []}
    text = " ".join([player_input or "", narrator_out or "",
                     json.dumps(auditor_out.get("turn_summary", {}) or {}, ensure_ascii=False)])
    terms = {}
    for tok in _tokenize(text):
        terms[tok] = terms.get(tok, 0) + 1
    npc_ids = [_safe_name(str(n.get("npc_id") or n.get("name") or ""))
               for n in (auditor_out.get("directors_briefing", {}) or {}).get("npc_profiles", []) or []
               if isinstance(n, dict)]
    loc = load_json(db / "World" / "01_Geography.json").get("current_location", {}).get("id", "")
    entry = {"turn": turn, "date": date, "game_date": game_date or "",
             "terms": terms, "npc_ids": [x for x in npc_ids if x], "loc": loc or ""}
    idx["turns"] = [e for e in idx.get("turns", []) if e.get("turn") != turn] + [entry]
    save_json(p, idx)

def _score_turns(q_terms, q_npcs, q_loc, turns, exclude):
    if not turns:
        return []
    N  = len(turns)
    df = {}
    for t in turns:
        for term in t.get("terms", {}):
            df[term] = df.get(term, 0) + 1
    qset, qn = set(q_terms), set(q_npcs)
    scored = []
    for t in turns:
        if t.get("turn") in exclude:
            continue
        terms = t.get("terms", {})
        s = sum(math.log((N + 1) / (df.get(qt, 0) + 1)) + 1.0 for qt in qset if qt in terms)
        s += 5.0 * len(qn & set(t.get("npc_ids", [])))     # shared NPC = strong signal
        if q_loc and t.get("loc") == q_loc:
            s += 3.0                                        # same location
        if s > 0:
            scored.append((s, t))
    scored.sort(key=lambda x: -x[0])
    return scored

def _turn_snippet(db: Path, turn: int, cap: int = 420) -> str:
    f = db / "Events" / "Eternal_Logs" / "txt" / f"T{turn}.txt"
    if not f.exists():
        return ""
    return f.read_text(encoding="utf-8")[:cap].strip()

def recall_block(db: Path, q_terms, q_npcs, q_loc, budget_chars: int,
                 exclude: set, k: int, snippet_chars: int = 420) -> tuple:
    """Top relevant older turns (excluding `exclude`), chronological, within budget.
    Returns (text_block, set_of_turn_ids)."""
    if budget_chars < 200:
        return "", set()
    turns  = (load_json(recall_index_path(db)) or {}).get("turns", [])
    scored = _score_turns(q_terms, q_npcs, q_loc, turns, exclude)
    picked, used = [], 0
    for _, t in (scored[:k] if k else scored):
        snip = _turn_snippet(db, t["turn"], snippet_chars)
        if not snip:
            continue
        tag   = f" {t['game_date']}" if t.get("game_date") else ""
        block = f"[T{t['turn']}{tag}] {snip}\n"
        if used + len(block) > budget_chars and picked:
            break
        picked.append((t["turn"], block)); used += len(block)
    if not picked:
        return "", set()
    picked.sort(key=lambda x: x[0])
    return "[RECALLED — older relevant turns]\n" + "".join(b for _, b in picked), {p[0] for p in picked}

# Per-provider context window (tokens). Override per-campaign via cfg["context_tokens"].
_CTX_TOKENS = {"deepseek":64000, "openai":128000, "groq":8000, "openrouter":128000, "ollama":8000}

def history_budget_chars(pri: dict, cfg: dict) -> int:
    """Char budget for the Narrator's history ≈ fill_ratio of the model's context window. Approximate (≈2 chars/token, leans to not overflow); tune via cfg."""
    ctx   = int(cfg.get("context_tokens") or _CTX_TOKENS.get(pri.get("theme", ""), 32000))
    ratio = float(cfg.get("history_fill_ratio", 0.5))
    return max(2000, int(ctx * ratio * 2))

def build_history(db: Path, budget_chars: int, query: tuple = None, cfg: dict = None) -> str:
    """Two-lane history within the budget: a recency lane (recent turns, always
    kept for continuity) plus a relevance lane (older turns most relevant to the
    current query). When recall is off / no query, it's a pure recency window —
    identical to the previous behaviour."""
    cfg = cfg or {}
    log_dir = db / "Events" / "Eternal_Logs"
    if not log_dir.exists():
        return ""
    recall_on     = bool(cfg.get("recall", True)) and query is not None
    recency_ratio = float(cfg.get("recall_recency_ratio", 0.5)) if recall_on else 1.0
    recency_budget = max(800, int(budget_chars * recency_ratio))

    turns = []
    for f in sorted(log_dir.glob("*.json")):
        turns += load_json(f).get("turns", [])
    turns.sort(key=lambda t: t.get("turn_id", 0))

    picked, total, recent_ids = [], 0, set()
    for t in reversed(turns):
        block = f"[T{t.get('turn_id')}] player: {t.get('player_input','')}\nnarrator: {t.get('narrator_output','')}\n"
        if total + len(block) > recency_budget and picked:
            break
        picked.append(block); total += len(block); recent_ids.add(t.get("turn_id"))
    recency = "\n".join(reversed(picked))

    if not recall_on:
        return recency

    q_terms, q_npcs, q_loc = query
    recalled, _ = recall_block(db, q_terms, q_npcs, q_loc,
                               budget_chars - total, recent_ids, int(cfg.get("recall_k", 6)),
                               int(cfg.get("recall_snippet_chars", 1200)))
    return (recalled + "\n" + recency).strip() if recalled else recency

def build_history_messages(db: Path, budget_chars: int, query: tuple = None, cfg: dict = None):
    """Recent turns as REAL chat-role messages (user=player_input, assistant=narrator_output) so the
    model takes turns properly and replies to the latest input — instead of one flat transcript blob it
    continues mid-scene (the structural cause of the '1-turn-late' feel). Returns (messages, recalled_text);
    older relevant turns come back as a context block (non-contiguous → can't be clean conversation)."""
    cfg = cfg or {}
    log_dir = db / "Events" / "Eternal_Logs"
    if not log_dir.exists():
        return [], ""
    recall_on     = bool(cfg.get("recall", True)) and query is not None
    recency_ratio = float(cfg.get("recall_recency_ratio", 0.5)) if recall_on else 1.0
    recency_budget = max(800, int(budget_chars * recency_ratio))
    turns = []
    for f in sorted(log_dir.glob("*.json")):
        turns += load_json(f).get("turns", [])
    turns.sort(key=lambda t: t.get("turn_id", 0))
    picked, total, recent_ids = [], 0, set()
    for t in reversed(turns):
        cost = len(t.get("player_input", "") or "") + len(t.get("narrator_output", "") or "")
        if total + cost > recency_budget and picked:
            break
        picked.append(t); total += cost; recent_ids.add(t.get("turn_id"))
    picked.reverse()
    msgs = []
    for t in picked:
        p = (t.get("player_input", "") or "").strip()
        n = (t.get("narrator_output", "") or "").strip()
        if p: msgs.append({"role": "user", "content": p})
        if n: msgs.append({"role": "assistant", "content": n})
    recalled = ""
    if recall_on:
        q_terms, q_npcs, q_loc = query
        recalled, _ = recall_block(db, q_terms, q_npcs, q_loc,
                                   budget_chars - total, recent_ids, int(cfg.get("recall_k", 4)))
    return msgs, recalled

def get_last_scene(db: Path, chars: int = 600) -> str:
    """Full narrator text of the previous turn (truncated) so the Narrator keeps scene continuity."""
    today = datetime.now().strftime("%Y-%m-%d")
    lp = db / "Events" / "Eternal_Logs" / f"{today}.json"
    if not lp.exists():
        return ""
    turns = load_json(lp).get("turns", [])
    if not turns:
        return ""
    return (turns[-1].get("narrator_output", "") or "")[:chars]

def ingame_date_str(idx: dict) -> str:
    """In-game date ONLY (never the real-world date): the calendar date when set, else a Day counter."""
    gd = (idx.get("game_date") or "").strip()
    return fmt_date(gd) if gd else f"Day {int(idx.get('game_day', 0) or 0) + 1}"

def ingame_time_str(idx: dict) -> str:
    clk = int(idx.get("game_clock", 480) or 480)
    return f"{clk // 60:02d}:{clk % 60:02d}"

def get_stats(db: Path) -> dict:
    phys = load_json(db / "PC" / "01_Physical.json")
    mn   = load_json(db / "PC" / "02_Mental.json")
    inv  = load_json(db / "PC" / "03_Inventory.json")
    idx  = load_index(db)
    geo  = load_json(db / "World" / "01_Geography.json")
    laws = load_json(db / "World" / "06_Active_Laws.json")
    fx   = [e for e in phys.get("status_effects", []) if e]
    return {
        "turn":     idx.get("current_turn", 0),
        "hp":       phys.get("hp", 100),
        "stamina":  phys.get("stamina", 100),
        "mental":   mn.get("mental_state", 100),
        "location": geo.get("current_location", {}).get("name", "—"),
        "gdate":    ingame_date_str(idx),                 # in-game date (Day N or calendar)
        "gtime":    ingame_time_str(idx),                 # in-game clock HH:MM
        "fx":       "|".join(fx),                         # status effects ("" when none)
        "items":    len(inv.get("items", [])),
        "currency": inv.get("currency", 0),
        "pc":       (mn.get("profile", {}) or {}).get("name", ""),
        "laws":     len([l for l in laws.get("laws",[]) if l.get("is_active",True)]),
        "undo":     len(list_snapshots(db)),
    }

# ─── MOST Encoder ────────────────────────────────────────────────────────────

def encode_most(state: dict, index: dict) -> str:
    geo  = state["geography"]
    phys = state["physical"]
    mn   = state["mental"]
    inv  = state["inventory"]
    laws = state["laws"].get("laws", [])
    npcs = relevant_npcs(state["npcs"], index.get("current_turn", 0))   # footer shows the bounded working set; full NPC set stays on disk

    loc  = geo.get("current_location", {}).get("id", "unknown")
    t    = ingame_time_str(index).replace(":", "")   # in-game clock (HHMM), not wall-clock
    date = index.get("current_date") or datetime.now().strftime("%Y-%m-%d")
    hp   = phys.get("hp", 100)
    st   = phys.get("stamina", 100)
    mn_v = mn.get("mental_state", 100)
    fx   = "|".join(phys.get("status_effects", [])) or "none"

    items = inv.get("items", [])
    inv_s = "|".join(i.get("id", i.get("name","?")) + (f" ×{i.get('qty',1)}" if i.get("qty",1) > 1 else "")
                     for i in items) or "none"

    npc_parts = []
    for n in npcs:
        rel = n.get("relationship", {})
        npc_parts.append(f"{n.get('npc_id','?')}/rel:{rel.get('rel_type','neutral')}|trs:{rel.get('trust',5)}")

    law_ids = [l.get("law_id","?") for l in laws if l.get("is_active", True)]

    gd = index.get("game_date")
    base = (f"[W:loc:{loc}|t:{t}|date:{gd or ('Day' + str(int(index.get('game_day', 0) or 0) + 1))}]"
            f"[P:hp:{hp}|st:{st}|mn:{mn_v}|fx:{fx}|cur:{inv.get('currency',0)}]"
            f"[I:{inv_s}]"
            f"[N:{' '.join(npc_parts) or 'none'}]"
            f"[L:{','.join(law_ids) or 'none'}]"
            + (f"[D:{fmt_date(gd)}]" if gd else ""))
    # Signed checksum over everything before it — verifiable + tamper-evident.
    return base + f"[Chk:{compute_chk(base)}]"

def decode_most(s: str) -> dict:
    """Parse a MOST tracker string into readable fields for the tracker window."""
    groups = dict(re.findall(r"\[([A-Za-z]+):(.*?)\]", s or ""))
    def kv(body):
        d = {}
        for part in body.split("|"):
            if ":" in part:
                k, v = part.split(":", 1); d[k] = v
        return d
    w = kv(groups.get("W", "")); p = kv(groups.get("P", ""))
    return {
        "location":  w.get("loc", ""), "time": w.get("t", ""), "date": w.get("date", ""),
        "hp":        p.get("hp", ""), "stamina": p.get("st", ""), "mental": p.get("mn", ""),
        "fx":        p.get("fx", ""), "currency": p.get("cur", ""),
        "inventory": groups.get("I", ""), "npcs": groups.get("N", ""), "laws": groups.get("L", ""),
        "chk":       groups.get("Chk", ""), "error": groups.get("E", ""),
    }

# ─── Prompts ─────────────────────────────────────────────────────────────────

def read_prompt(path: Path) -> str:
    if path.exists() and path.stat().st_size > 0:
        return path.read_text(encoding="utf-8").strip()
    return ""

# ─── Auditor ─────────────────────────────────────────────────────────────────

_REQUIRED = {"intent","action_success","stat_changes","flag_changes",
             "most_updated","directors_briefing","turn_summary"}

def call_auditor(player_input: str, most: str, state: dict,
                 history: str, sec: dict, flags: dict,
                 due_events: list = None, active_events: list = None,
                 prior_error: str = "") -> dict | None:
    geo  = state["geography"]
    laws = [l for l in state["laws"].get("laws", []) if l.get("is_active", True)][-25:]  # bounded working window
    pol = state.get("politics", {}); eco = state.get("economy", {}); tech = state.get("tech", {})
    def _npc_brief(x):
        r = x.get("relationship", {}) or {}
        return (f"{x.get('npc_id')}({x.get('name') or x.get('descriptor','?')}"
                f"|known:{x.get('name_known')}|mood:{x.get('mood','') or '?'}"
                f"|rel:{r.get('rel_type','neutral')}|trust:{r.get('trust',5)}|aff:{r.get('affection',5)}"
                f"|goal:{x.get('goal','') or '?'}|knows:{x.get('knowledge','')})")
    npc_roster = "; ".join(_npc_brief(x) for x in state.get("npcs", []) if isinstance(x, dict)) or "none"
    facts = [str(f) for f in (state.get("mental", {}).get("known_facts") or []) if str(f).strip()][-12:]
    known_facts = " · ".join(facts) or "none"
    world_ctx = (
        f"Location: {geo.get('current_location',{}).get('description','unknown')} | "
        f"Era: {state['history'].get('era','')} | "
        f"World: {state['history'].get('world_name','')} | "
        f"Reputation: {pol.get('pc_reputation',{})} | "
        f"Economy: {eco.get('economic_state','')} | "
        f"Tech: {tech.get('tech_level','')} | "
        f"NPCs: {npc_roster} | "
        f"PC_known_facts: {known_facts} | "
        f"Ref: {(state['history'].get('web_context','') or 'none')[:600]}"
    )
    canon = render_canon((state.get("worldbook") or {}).get("entries", []), 2500)
    if canon:
        world_ctx += " | Canon (authoritative world facts):\n" + canon
    prov = state.get("provisional") or []                  # Chrysalis Phase 2: let the Auditor confirm/contradict
    if prov:
        digest = "; ".join(f"[{e.get('id')}] {e.get('text','')}" for e in prov[-20:] if isinstance(e, dict))
        if digest:
            world_ctx += (" | Provisional (UNCONFIRMED facts — in canon_review.confirm put ids the scene "
                          "restates/is consistent with, .contradict put ids it conflicts with):\n" + digest)
    if prior_error:                                       # V7-style error recovery: steer a correction
        world_ctx += (f" | PriorTurnError: {prior_error} — the previous turn was flagged for this; "
                      f"steer the scene to correct it and do not repeat it")
    user_msg = json.dumps({
        "player_input": player_input, "most_current": most,
        "active_laws": laws, "world_context": world_ctx,
        "recent_history": history, "flags_json": flags,
        "due_events": due_events or [], "active_events": active_events or [],
    }, ensure_ascii=False)

    payload = {
        "model": sec["model"], "temperature": 0.1,
        "messages": [
            {"role": "system", "content": read_prompt(PROMPTS/"Auditor"/"Core.txt")},
            {"role": "user",   "content": user_msg},
        ],
        "response_format": {"type": "json_object"}, "stream": False,
    }
    headers = {"Authorization": f"Bearer {sec['api_key']}"} if sec.get("api_key") else {}

    for attempt in range(3):
        try:
            r = http.post(sec["url"], json=payload, headers=headers, timeout=30)
            r.raise_for_status()
            out = json.loads(r.json()["choices"][0]["message"]["content"])
            if _REQUIRED.issubset(out.keys()):
                return out
        except Exception:
            if attempt < 2:
                time.sleep(1)
    return None

# ─── Verify: Auditor checks the Narrator (V7-style [E]) ──────────────────────

_VERIFY_REQUIRED = {"error_code", "severity"}

def verify_narration(narrator_text: str, state: dict, sec: dict,
                     auditor_out: dict = None, player_input: str = "") -> dict | None:
    """Post-narration consistency pass: the Auditor (logic core) checks the
    Narrator's prose against canonical state and returns an error_code/violations.
    Non-blocking — the engine records the result; it never rewrites the prose.
    Verify_v2: also receives the turn's INTENT (player command + planned scene) so a
    player-driven move is not mistaken for a contradiction; currency is in canon."""
    if not (narrator_text or "").strip():
        return None
    geo  = state.get("geography", {})
    npc_facts = "; ".join(
        f"{n.get('npc_id')}(name_known:{n.get('name_known')}|knows:{n.get('knowledge','')})"
        for n in state.get("npcs", []) if isinstance(n, dict)
    ) or "none"
    laws = [l.get("law_id", "?") for l in state.get("laws", {}).get("laws", []) if l.get("is_active", True)]
    inv_obj = state.get("inventory", {})
    inv  = "|".join(i.get("id", i.get("name", "?")) for i in inv_obj.get("items", [])) or "none"
    canon = {
        "location":    geo.get("current_location", {}).get("description", "")
                       or geo.get("current_location", {}).get("name", ""),
        "npc_facts":   npc_facts,
        "active_laws": laws,
        "inventory":   inv,
        "currency":    inv_obj.get("currency", 0),
    }
    brief  = (auditor_out or {}).get("directors_briefing", {}) or {}
    intent = {
        "player_action": brief.get("player_last_action") or (player_input or ""),
        "scene_intent":  brief.get("scene_context", ""),
    }
    user_msg = json.dumps({"narrator_text": narrator_text[:4000], "canon": canon, "intent": intent},
                          ensure_ascii=False)
    payload = {
        "model": sec["model"], "temperature": 0.1,
        "messages": [
            {"role": "system", "content": read_prompt(PROMPTS/"Auditor"/"Verify_v2.txt")},
            {"role": "user",   "content": user_msg},
        ],
        "response_format": {"type": "json_object"}, "stream": False,
    }
    headers = {"Authorization": f"Bearer {sec['api_key']}"} if sec.get("api_key") else {}
    for attempt in range(2):
        try:
            r = http.post(sec["url"], json=payload, headers=headers, timeout=20)
            r.raise_for_status()
            out = json.loads(r.json()["choices"][0]["message"]["content"])
            if _VERIFY_REQUIRED.issubset(out.keys()):
                return out
        except Exception:
            if attempt < 1:
                time.sleep(1)
    return None

# ─── Apply Changes ───────────────────────────────────────────────────────────

def apply_changes(auditor_out: dict, db: Path):
    if auditor_out.get("stat_changes"):
        _apply_stats(auditor_out["stat_changes"], db)
    inv_ch = auditor_out.get("inventory_changes", {}) or {}
    if inv_ch.get("remove") or inv_ch.get("add"):
        _apply_inventory(inv_ch, db)
    cur_delta = inv_ch.get("currency") or auditor_out.get("currency_change") or 0   # hybrid: nested first, fallback top-level (precedence avoids double-count)
    if cur_delta:
        _apply_currency(cur_delta, db)
    if auditor_out.get("new_law"):
        _apply_law(auditor_out["new_law"], db)

def _apply_stats(changes: dict, db: Path):
    pp = db / "PC" / "01_Physical.json"
    mp = db / "PC" / "02_Mental.json"
    phys = load_json(pp); mn = load_json(mp)
    m = {"hp":(phys,"hp"),"st":(phys,"stamina"),"mn":(mn,"mental_state")}
    cp = cm = False
    for k, d in changes.items():
        if k in m:
            obj, f = m[k]; obj[f] = clamp(obj.get(f,100)+d)
            if obj is phys: cp=True
            else: cm=True
    if cp: save_json(pp, phys)
    if cm: save_json(mp, mn)

def _apply_inventory(inv_ch: dict, db: Path):
    path = db/"PC"/"03_Inventory.json"
    inv  = load_json(path)
    # heal pre-existing duplicates: collapse same-id entries, summing qty (auto-migration)
    merged, order = {}, []
    for it in inv.get("items", []):
        key = it.get("id") or it.get("name")
        if key in merged: merged[key]["qty"] = merged[key].get("qty",1) + it.get("qty",1)
        else: merged[key] = dict(it); merged[key].setdefault("qty",1); order.append(key)
    items = [merged[k] for k in order]
    idx = {(it.get("id") or it.get("name")): it for it in items}
    for rem in inv_ch.get("remove",[]):                 # remove = decrement qty by 1, drop entry at 0
        it = idx.get(rem)
        if it:
            it["qty"] = it.get("qty",1) - 1
            if it["qty"] <= 0: items = [x for x in items if x is not it]; idx.pop(rem, None)
    for add in inv_ch.get("add",[]):                    # add = qty+1 if owned, else new entry
        it = idx.get(add)
        if it: it["qty"] = it.get("qty",1) + 1
        else:
            new = {"id":add,"name":add,"qty":1,"condition":"good"}; items.append(new); idx[add] = new
    inv["items"] = items; save_json(path, inv)

def _apply_currency(delta, db: Path):
    """Apply a SIGNED currency delta to the PC's balance (engine keeps the running total; floor 0)."""
    path = db/"PC"/"03_Inventory.json"
    inv  = load_json(path)
    try: d = int(delta)
    except (TypeError, ValueError): return
    inv["currency"] = max(0, inv.get("currency", 0) + d)
    save_json(path, inv)

def _apply_law(law: dict, db: Path):
    path = db/"World"/"06_Active_Laws.json"
    data = load_json(path); laws = data.get("laws",[])
    law.setdefault("is_active", True); laws.append(law)
    data["laws"] = laws; save_json(path, data)

def apply_knowledge(auditor_out: dict, db: Path):
    """Accumulate what the PC learned (turn_summary.new_knowledge) into mental.known_facts — a persistent
    story variable fed back to the Auditor each turn so learned facts aren't forgotten. Deduped, bounded."""
    facts = (auditor_out.get("turn_summary", {}) or {}).get("new_knowledge") or []
    facts = [str(f).strip() for f in facts if str(f).strip()]
    if not facts:
        return
    mp = db / "PC" / "02_Mental.json"; m = load_json(mp)
    known = list(m.get("known_facts") or [])
    seen  = set(known)
    for f in facts:
        if f not in seen:
            known.append(f); seen.add(f)
    m["known_facts"] = known[-30:]            # keep the most recent 30
    save_json(mp, m)

def apply_setup(uf: dict, db: Path):
    """Persist setup data (world/pc/start, manual or auto-created) into the campaign DB."""
    wd = uf.get("world_data") or {}
    if wd:
        hp = db/"World"/"05_History.json"; h = load_json(hp)
        for k in ("world_name", "era", "backstory"):
            if wd.get(k): h[k] = wd[k]
        save_json(hp, h)
    sd = uf.get("start_data") or {}
    if sd:
        gp = db/"World"/"01_Geography.json"; g = load_json(gp)
        loc = g.get("current_location") or {}
        name  = sd.get("location_name") or sd.get("name")
        desc  = sd.get("location_description") or sd.get("description")
        biome = (sd.get("biome") or "").strip().lower()
        if name:  loc["name"] = name
        if desc:  loc["description"] = desc
        if biome: loc["biome"] = biome          # so the start area runs its own encounter table
        loc.setdefault("id", "start")
        g["current_location"] = loc
        save_json(gp, g)
    pd = uf.get("pc_data") or {}
    if pd:
        mp = db/"PC"/"02_Mental.json"; m = load_json(mp)
        m["profile"] = {k: pd[k] for k in ("name", "description") if pd.get(k)}
        save_json(mp, m)

def apply_world(wu: dict, db: Path):
    """Persist in-game world deltas (reputation/faction/economy/tech) to the existing World DB files."""
    if not wu:
        return
    rep = wu.get("reputation") or {}
    nf  = wu.get("new_faction")
    if rep or (isinstance(nf, dict) and nf.get("name")):
        pp = db/"World"/"02_Politics.json"; pol = load_json(pp)
        pcrep = pol.get("pc_reputation", {})
        for fac, d in rep.items():
            try: pcrep[fac] = clamp(pcrep.get(fac, 50) + int(d))
            except (TypeError, ValueError): pass
        pol["pc_reputation"] = pcrep
        if isinstance(nf, dict) and nf.get("name"):
            facs = pol.get("factions", [])
            names = {f.get("name") if isinstance(f, dict) else f for f in facs}
            if nf["name"] not in names:
                facs.append(nf)
            pol["factions"] = facs
        save_json(pp, pol)
    es = wu.get("economy_state"); note = wu.get("market_note")
    if es or note:
        ep = db/"World"/"03_Economy.json"; eco = load_json(ep)
        if es: eco["economic_state"] = es
        if note: eco["market_notes"] = (eco.get("market_notes", "") + " | " + note).strip(" |")
        save_json(ep, eco)
    tl = wu.get("tech_level")
    if tl:
        tp = db/"World"/"04_Magic_Tech.json"; tch = load_json(tp)
        tch["tech_level"] = tl
        save_json(tp, tch)

# ─── World Canon (Worldbook) ─────────────────────────────────────────────────
# The lore the player builds during world-creation (and genuine world shifts in
# play) is distilled into a permanent, compact canon. Unlike recall (lexical,
# truncated, evictable) the canon is injected always-on into BOTH cores every
# turn — so world facts never fall out of context or get cut to a snippet.

WORLDBOOK_CAP = 200   # keep the newest N canon entries (older lore stays in the .txt logs)

def load_worldbook(db: Path) -> dict:
    wb = load_json(db / "World" / "00_Worldbook.json")
    if not isinstance(wb, dict) or not isinstance(wb.get("entries"), list):
        return {"entries": []}
    return wb

def save_worldbook(db: Path, wb: dict):
    save_json(db / "World" / "00_Worldbook.json", wb)

def _canon_norm(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "")).strip().lower()

def add_canon_entries(db: Path, items: list, turn: int, source: str = "build"):
    """Append distilled lore lines to the worldbook (dedup by normalized text)."""
    if not items:
        return
    wb   = load_worldbook(db)
    ents = wb.get("entries", [])
    seen = {_canon_norm(e.get("text", "")) for e in ents if isinstance(e, dict)}
    nid  = max([int(str(e.get("id", "0")).lstrip("wb") or 0) for e in ents
                if isinstance(e, dict)] or [0])
    for it in items:
        if isinstance(it, dict):
            topic, text = (it.get("topic") or "").strip(), (it.get("text") or "").strip()
        else:
            topic, text = "", str(it).strip()
        norm = _canon_norm(text)
        if not norm or norm in seen:
            continue
        seen.add(norm)
        nid += 1
        ents.append({"id": f"wb{nid}", "topic": topic, "text": text,
                     "turn": turn, "source": source})
    wb["entries"] = ents[-WORLDBOOK_CAP:]
    save_worldbook(db, wb)

def apply_canon(auditor_out: dict, db: Path, turn: int, game_started: bool, chrysalis: bool = False):
    """Capture world canon from the Auditor's turn_summary. Pre-game (world-building)
    keeps everything; in-play keeps only genuine world_changes (new_knowledge already
    feeds mental.known_facts via apply_knowledge). Chrysalis: in-play facts go to the
    PROVISIONAL pool first (promoted only once confirmed) instead of straight to canon."""
    ts = auditor_out.get("turn_summary", {}) or {}
    items = []
    for wc in (ts.get("world_changes") or []):
        if str(wc).strip():
            items.append({"topic": "world", "text": str(wc).strip()})
    if not game_started:
        for nk in (ts.get("new_knowledge") or []):
            if str(nk).strip():
                items.append({"topic": "lore", "text": str(nk).strip()})
        note = (ts.get("important_notes") or "").strip()
        if note:
            items.append({"topic": "note", "text": note})
        add_canon_entries(db, items, turn, source="build")          # vetted setup → permanent
    elif chrysalis:
        add_provisional(db, items, turn, source="play")             # quarantine until confirmed
    else:
        add_canon_entries(db, items, turn, source="play")           # legacy: straight to canon

def format_canon(db: Path, budget_chars: int = 2500) -> str:
    """Compact always-on canon block from disk (used by the Narrator call site)."""
    return render_canon(load_worldbook(db).get("entries", []), budget_chars)

def render_canon(ents: list, budget_chars: int = 2500) -> str:
    """Compact always-on canon block, grouped by topic, newest-first within budget."""
    if not ents:
        return ""
    groups: dict = {}
    for e in reversed(ents):                      # newest first
        if not isinstance(e, dict):
            continue
        groups.setdefault(e.get("topic") or "world", []).append(e.get("text", "").strip())
    lines, used = [], 0
    for topic, texts in groups.items():
        head = f"[{topic}]"
        if used + len(head) > budget_chars and lines:
            break
        lines.append(head); used += len(head) + 1
        for t in texts:
            row = f"- {t}"
            if used + len(row) > budget_chars and lines:
                return "\n".join(lines)
            lines.append(row); used += len(row) + 1
    return "\n".join(lines)

# ─── Chrysalis: provisional canon quarantine (anti butterfly-effect) ──────────
PROVISIONAL_CAP = 60   # bound the quarantine pool (raw turn .txt keeps the full truth regardless)

def load_provisional(db: Path) -> dict:
    pv = load_json(db / "World" / "00_Worldbook_Provisional.json")
    if not isinstance(pv, dict) or not isinstance(pv.get("entries"), list):
        return {"entries": []}
    return pv

def save_provisional(db: Path, pv: dict):
    save_json(db / "World" / "00_Worldbook_Provisional.json", pv)

def add_provisional(db: Path, items: list, turn: int, source: str = "play"):
    """Stage in-play facts as provisional. Recurrence (same normalized text) bumps hits;
    facts already in permanent canon are skipped."""
    if not items:
        return
    pv   = load_provisional(db); ents = pv.get("entries", [])
    perm = {_canon_norm(e.get("text", "")) for e in load_worldbook(db).get("entries", []) if isinstance(e, dict)}
    by_norm = {e.get("norm"): e for e in ents if isinstance(e, dict)}
    nid = max([int(str(e.get("id", "0")).lstrip("pv") or 0) for e in ents if isinstance(e, dict)] or [0])
    for it in items:
        text  = (it.get("text") if isinstance(it, dict) else str(it)).strip()
        topic = (it.get("topic") if isinstance(it, dict) else "") or ""
        norm  = _canon_norm(text)
        if not norm or norm in perm:
            continue
        if norm in by_norm:                                   # recurrence → confirm signal
            e = by_norm[norm]; e["hits"] = e.get("hits", 1) + 1; e["last_seen_turn"] = turn
        else:
            nid += 1
            e = {"id": f"pv{nid}", "topic": topic, "text": text, "norm": norm,
                 "first_turn": turn, "last_seen_turn": turn, "hits": 1, "source": source}
            ents.append(e); by_norm[norm] = e
    pv["entries"] = ents[-PROVISIONAL_CAP:]
    save_provisional(db, pv)

def promote_and_expire_provisional(db: Path, turn: int, player_input: str, cfg: dict):
    """Each turn: promote provisional facts that are confirmed (repeated >=hits, or the
    player engaged with them); fade out stale ones. Faded facts remain in the raw turn log."""
    pv = load_provisional(db); ents = pv.get("entries", [])
    if not ents:
        return
    hits_need = int(cfg.get("chrysalis_hits", 2))
    window    = int(cfg.get("chrysalis_window", 12))
    overlap_t = float(cfg.get("chrysalis_touch_overlap", 0.5))
    p_tok     = set(_tokenize(player_input or ""))
    keep, promote = [], []
    for e in ents:
        if not isinstance(e, dict):
            continue
        touched = False
        if p_tok:
            et = set(_tokenize(e.get("text", "")))
            if et and len(p_tok & et) / min(len(p_tok), len(et)) >= overlap_t:
                touched = True
        if e.get("hits", 1) >= hits_need or touched:
            promote.append(e)
        elif turn - e.get("first_turn", turn) > window:
            continue                                          # fade (still in raw log)
        else:
            keep.append(e)
    if promote:
        add_canon_entries(db, [{"topic": e.get("topic", ""), "text": e.get("text", "")} for e in promote],
                          turn, source="play")
    pv["entries"] = keep
    save_provisional(db, pv)

def render_provisional(db: Path, budget_chars: int = 600) -> str:
    """Compact provisional block (tagged unverified) so the Narrator keeps continuity."""
    ents = load_provisional(db).get("entries", [])
    if not ents:
        return ""
    lines, used = ["[ชั่วคราว/ยังไม่ยืนยัน]"], 0
    for e in reversed(ents):
        row = f"- {e.get('text','').strip()}"
        if used + len(row) > budget_chars and len(lines) > 1:
            break
        lines.append(row); used += len(row) + 1
    return "\n".join(lines) if len(lines) > 1 else ""

def apply_canon_review(db: Path, review: dict, turn: int, cfg: dict):
    """Chrysalis Phase 2: act on the Auditor's semantic confirm/contradict tags — PROVISIONAL
    entries ONLY (never touches permanent canon). id-validated and capped per turn."""
    if not isinstance(review, dict):
        return
    cap     = int(cfg.get("chrysalis_review_cap", 5))
    confirm = [str(x) for x in (review.get("confirm") or [])][:cap]
    contra  = [str(x) for x in (review.get("contradict") or [])][:cap]
    if not confirm and not contra:
        return
    pv = load_provisional(db); ents = pv.get("entries", [])
    if not ents:
        return
    by_id    = {e.get("id"): e for e in ents if isinstance(e, dict)}
    promote  = [by_id[i] for i in confirm if i in by_id]          # ignore ids not in the list (guards hallucinated ids)
    promo_ids = {p.get("id") for p in promote}
    drop_ids  = {i for i in contra if i in by_id} - promo_ids     # confirm wins ties
    if promote:
        add_canon_entries(db, [{"topic": e.get("topic", ""), "text": e.get("text", "")} for e in promote],
                          turn, source="play")
    pv["entries"] = [e for e in ents if e.get("id") not in promo_ids and e.get("id") not in drop_ids]
    save_provisional(db, pv)

def _pregame_transcript(db: Path, cap: int = 16000) -> str:
    """All player+narrator text so far, tail-capped — the raw lore the player built before [start]."""
    log_dir = db / "Events" / "Eternal_Logs"
    turns = []
    for f in sorted(log_dir.glob("*.json")):
        turns += load_json(f).get("turns", [])
    turns.sort(key=lambda t: t.get("turn_id", 0))
    parts = []
    for t in turns:
        p = (t.get("player_input", "") or "").strip()
        n = (t.get("narrator_output", "") or "").strip()
        if p: parts.append("PLAYER: " + p)
        if n: parts.append("NARRATOR: " + n)
    text = "\n".join(parts)
    return text[-cap:] if len(text) > cap else text

def compile_worldbook(db: Path, sec: dict) -> bool:
    """One-shot distillation of all pre-game world-building turns into the Worldbook +
    structured World files (politics/magic_tech/laws). Network-guarded — on any failure
    the incremental worldbook is kept and [start] proceeds normally. Returns True on success."""
    transcript = _pregame_transcript(db)
    sys = read_prompt(PROMPTS / "Auditor" / "Compile.txt")
    if not transcript.strip() or not sys:
        return False
    payload = {
        "model": sec["model"], "temperature": 0.2,
        "messages": [
            {"role": "system", "content": sys},
            {"role": "user",   "content": json.dumps({"pregame_transcript": transcript}, ensure_ascii=False)},
        ],
        "response_format": {"type": "json_object"}, "stream": False,
    }
    headers = {"Authorization": f"Bearer {sec['api_key']}"} if sec.get("api_key") else {}
    out = None
    for attempt in range(2):
        try:
            r = http.post(sec["url"], json=payload, headers=headers, timeout=60)
            r.raise_for_status()
            out = json.loads(r.json()["choices"][0]["message"]["content"])
            break
        except Exception:
            if attempt < 1:
                time.sleep(1)
    if not isinstance(out, dict):
        return False
    turn = load_index(db).get("current_turn", 0)
    # Worldbook — append compiled canon (dedup keeps prior incremental entries)
    wb_items = [{"topic": (e.get("topic") or "world"), "text": (e.get("text") or "").strip()}
                for e in (out.get("worldbook") or [])
                if isinstance(e, dict) and (e.get("text") or "").strip()]
    add_canon_entries(db, wb_items, turn, source="compile")
    # Structured merge — only fill empties / append genuinely new items
    facs = [f for f in ((out.get("politics") or {}).get("factions") or [])
            if isinstance(f, dict) and f.get("name")]
    if facs:
        pp = db / "World" / "02_Politics.json"; pol = load_json(pp)
        pol.setdefault("factions", [])
        have = {f.get("name") for f in pol["factions"] if isinstance(f, dict)}
        for f in facs:
            if f["name"] not in have:
                pol["factions"].append(f)
        save_json(pp, pol)
    mt = out.get("magic_tech") or {}
    if mt.get("tech_level") or mt.get("magic_rules"):
        tp = db / "World" / "04_Magic_Tech.json"; tch = load_json(tp)
        if mt.get("tech_level") and not tch.get("tech_level"):
            tch["tech_level"] = mt["tech_level"]
        cur = tch.get("magic_rules", [])
        for rule in (mt.get("magic_rules") or []):
            if rule and rule not in cur:
                cur.append(rule)
        tch["magic_rules"] = cur
        save_json(tp, tch)
    laws_in = [l for l in (out.get("laws") or []) if (l.get("text") if isinstance(l, dict) else str(l)).strip()]
    if laws_in:
        lp = db / "World" / "06_Active_Laws.json"; lw = load_json(lp); lw.setdefault("laws", [])
        have = {_canon_norm(l.get("text", "")) if isinstance(l, dict) else _canon_norm(str(l)) for l in lw["laws"]}
        base = len(lw["laws"])
        for i, l in enumerate(laws_in, 1):
            txt = (l.get("text") if isinstance(l, dict) else str(l)).strip()
            if _canon_norm(txt) in have:
                continue
            lw["laws"].append({"law_id": f"L{base + i}", "text": txt, "is_active": True})
        save_json(lp, lw)
    return True

def _slug(name: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "_", (name or "").lower()).strip("_")
    return s[:24]

# ─── Location random encounters (engine rolls the dice; player keeps ≥70% quiet) ─
ENC_CAP      = 30   # hard ceiling on any location's encounter chance (always ≥70% quiet)
ENC_COOLDOWN = 3    # minimum turns between encounters so they stay rare

# Preset biome tables: chance(%) + weighted entries (weight, level, cue). Auditor may override per location.
BIOME_ENCOUNTERS = {
    "forest":     {"chance": 25, "table": [
        (50, "ambient", "สัตว์เล็กวิ่งตัดหน้า (กระต่าย/กระรอก/นก)"),
        (28, "minor",   "ฝูงสัตว์กินพืชหากินอยู่ใกล้ ๆ (กวาง/หมูป่า)"),
        (16, "threat",  "สัตว์นักล่าปรากฏตัวและจับจ้องมา (หมาป่า/หมี)"),
        (6,  "rare",    "สิ่งผิดธรรมชาติหรือสัตว์เวทปรากฏ")]},
    "town":       {"chance": 12, "table": [
        (45, "ambient", "ผู้คนพลุกพล่าน พ่อค้าเร่ร้องขายของ"),
        (30, "minor",   "คนแปลกหน้าเข้ามาทักหรือเสนอข่าว/งาน"),
        (18, "threat",  "นักล้วงกระเป๋าหรือนักเลงจ้องหาเรื่อง"),
        (7,  "rare",    "เหตุชุลมุนในที่สาธารณะ (วิวาท/ประกาศสำคัญ)")]},
    "road":       {"chance": 18, "table": [
        (45, "ambient", "นักเดินทางหรือขบวนเกวียนสวนทางมา"),
        (30, "minor",   "พ่อค้าเร่/ผู้แสวงบุญขอร่วมทางหรือแลกข่าว"),
        (20, "threat",  "โจรปล้นทางหรือด่านเก็บส่วยซุ่มอยู่"),
        (5,  "rare",    "ซากปรักหักพังหรือของถูกทิ้งข้างทาง")]},
    "dungeon":    {"chance": 30, "table": [
        (35, "ambient", "เสียงหรือร่องรอยบ่งบอกว่ามีบางสิ่งอยู่ลึกเข้าไป"),
        (25, "minor",   "กับดักเก่าหรืออุปสรรคทางกายภาพ"),
        (30, "threat",  "สัตว์ประหลาดหรือผู้พิทักษ์เฝ้าอยู่"),
        (10, "rare",    "ห้องลับหรือสมบัติที่ถูกซ่อน")]},
    "wilderness": {"chance": 22, "table": [
        (45, "ambient", "สัตว์ป่าผ่านมาในระยะไกล"),
        (28, "minor",   "สภาพอากาศหรือภูมิประเทศเปลี่ยน (ลำธาร/หน้าผา/พายุ)"),
        (20, "threat",  "สัตว์นักล่าหรือสิ่งมีชีวิตอันตราย"),
        (7,  "rare",    "ผู้รอดชีวิต/ค่ายพักร้าง/สิ่งลึกลับ")]},
    "water":      {"chance": 15, "table": [
        (50, "ambient", "ฝูงปลาหรือนกน้ำ หรือกระแสน้ำเปลี่ยน"),
        (30, "minor",   "เรือลำอื่นหรือชาวประมงผ่านมา"),
        (15, "threat",  "สัตว์น้ำอันตรายหรือคลื่นลมแรง"),
        (5,  "rare",    "ซากเรือหรือสิ่งลอยมาตามน้ำ")]},
    "indoor":     {"chance": 8,  "table": [
        (55, "ambient", "เสียงหรือความเคลื่อนไหวเล็กน้อยในอาคาร"),
        (30, "minor",   "ผู้คนอื่นในสถานที่เข้ามาปฏิสัมพันธ์"),
        (12, "threat",  "ผู้ไม่หวังดีหรือเหตุไม่คาดฝันในอาคาร"),
        (3,  "rare",    "การค้นพบบางสิ่งที่ซ่อนอยู่")]},
    "default":    {"chance": 15, "table": [
        (55, "ambient", "ความเคลื่อนไหวเล็กน้อยในสภาพแวดล้อม"),
        (30, "minor",   "ผู้คนหรือสัตว์ผ่านเข้ามาในระยะ"),
        (12, "threat",  "บางสิ่งที่อาจเป็นภัยปรากฏ"),
        (3,  "rare",    "สิ่งผิดปกติที่น่าสนใจ")]},
}

def roll_encounter(loc: dict, index: dict, turn: int) -> str | None:
    """Engine-side dice for a location random encounter. Returns a Narrator cue or None. Honors a per-location chance (capped at ENC_CAP so the player keeps ≥70% quiet) and a cooldown so encounters stay rare. The Auditor only picks the biome/odds and narrates the result — it never decides whether one fires."""
    if not isinstance(loc, dict):
        return None
    preset = BIOME_ENCOUNTERS.get((loc.get("biome") or "default").lower(), BIOME_ENCOUNTERS["default"])
    chance = loc.get("enc_chance")
    if not isinstance(chance, int):
        chance = preset["chance"]
    chance = max(0, min(ENC_CAP, chance))
    if chance <= 0:
        return None
    last = index.get("last_encounter_turn")
    if isinstance(last, int) and turn - last < ENC_COOLDOWN:
        return None
    if random.randint(1, 100) > chance:                    # ≥70% of the time: nothing — player drives
        return None
    table = list(preset["table"]) + [tuple(x) for x in (loc.get("enc_table") or [])
                                     if isinstance(x, (list, tuple)) and len(x) == 3]
    total = sum(w for w, _, _ in table if isinstance(w, int))
    if total <= 0:
        return None
    r = random.randint(1, total); acc = 0
    for w, level, text in table:
        if not isinstance(w, int):
            continue
        acc += w
        if r <= acc:
            index["last_encounter_turn"] = turn
            return (f"RANDOM_ENCOUNTER[{level}]: {text} — แทรกเข้าฉากอย่างเป็นธรรมชาติ "
                    f"ผู้เล่นยังเป็นคนเลือกว่าจะตอบสนองอย่างไร")
    return None

def apply_location(loc_update: dict, db: Path):
    """Move the PC to a new current_location when the story relocates them, and remember it in known_locations (no duplicates). Reuses an existing id for a place already visited so the MOST tracker's loc: stays stable for recall."""
    if not isinstance(loc_update, dict):
        return
    name = (loc_update.get("name") or loc_update.get("location_name") or "").strip()
    if not name:                                          # nothing moved this turn
        return
    desc  = (loc_update.get("description") or loc_update.get("location_description") or "").strip()
    biome = (loc_update.get("biome") or "").strip().lower()
    enc_chance = loc_update.get("enc_chance") if isinstance(loc_update.get("enc_chance"), int) else None
    enc_table  = loc_update.get("enc_table")  if isinstance(loc_update.get("enc_table"), list)  else None
    gp = db / "World" / "01_Geography.json"; g = load_json(gp)
    known = g.get("known_locations") or []
    match = next((k for k in known if isinstance(k, dict) and k.get("name") == name), None)
    if match:
        loc_id = match.get("id") or _slug(name) or f"loc{len(known)+1}"
        if desc:  match["description"] = desc
        entry = match
    else:
        loc_id = (loc_update.get("id") or "").strip() or _slug(name) or f"loc{len(known)+1}"
        existing_ids = {k.get("id") for k in known if isinstance(k, dict)}
        if loc_id in existing_ids:                        # avoid id collision for a genuinely new place
            loc_id = f"loc{len(known)+1}"
        entry = {"id": loc_id, "name": name, "description": desc}
        known.append(entry)
    if biome:                 entry["biome"]      = biome          # encounter table to use for this area
    if enc_chance is not None: entry["enc_chance"] = max(0, min(ENC_CAP, enc_chance))
    if enc_table  is not None: entry["enc_table"]  = enc_table
    cur = g.get("current_location") or {}
    g["current_location"] = {
        "id": loc_id, "name": name,
        "description": desc or cur.get("description", ""),
        "biome":      entry.get("biome", ""),
        "enc_chance": entry.get("enc_chance"),
        "enc_table":  entry.get("enc_table"),
        "connected_to": cur.get("connected_to", []) if cur.get("id") == loc_id else [],
    }
    g["known_locations"] = known
    save_json(gp, g)

def relevant_npcs(npcs: list, turn: int, window: int = 12, cap: int = 12) -> list:
    """Curated working window: NPCs seen within `window` turns, most-recent first, capped. The full set stays on disk (data permanent); this only bounds what the prompt shows."""
    recent = [n for n in npcs if isinstance(n, dict) and turn - n.get("last_seen_turn", -9999) <= window]
    recent.sort(key=lambda n: n.get("last_seen_turn", -9999), reverse=True)
    return recent[:cap]

def apply_npcs(npcs: list, db: Path, turn: int):
    """Persist NPCs permanently (merge, never delete). name_known is sticky; knowledge = the NPC's current limited memory, which the Auditor may shrink (in-world forgetting). The permanent .txt/JSON log keeps the full truth."""
    if not npcs:
        return
    base = db / "NPCs"
    for n in npcs:
        if not isinstance(n, dict):
            continue
        nid = _safe_name(str(n.get("npc_id") or n.get("name") or n.get("descriptor") or ""))
        if not nid:
            continue
        folder = base / nid
        folder.mkdir(parents=True, exist_ok=True)
        prof = load_json(folder / "Profile.json")
        was_known = bool(prof.get("name_known")) and bool(prof.get("name"))
        prof.update({
            "npc_id":     nid,
            "name":       prof["name"] if was_known else (n.get("name") or prof.get("name", "")),
            "descriptor": n.get("descriptor", prof.get("descriptor", "")),
            "name_known": was_known or bool(n.get("name_known")),
            "mood":       n.get("mood", prof.get("mood", "")),
            "goal":       n.get("goal", prof.get("goal", "")),
            "intent":     n.get("intent", ""),
            "knowledge":  n.get("knowledge", prof.get("knowledge", "")),
            "last_seen_turn": turn,
        })
        save_json(folder / "Profile.json", prof)
        rel = load_json(folder / "Relationships.json")
        rel.update({
            "rel_type":  n.get("relation",  rel.get("rel_type", "neutral")),
            "trust":     n.get("trust",     rel.get("trust", 5)),
            "affection": n.get("affection", rel.get("affection", 5)),
        })
        save_json(folder / "Relationships.json", rel)

def enrich_npc_profiles(briefing: dict, db: Path):
    """Fill each in-scene NPC profile the Auditor sent with the FULL stored state from disk
    (name/mood/relation/trust/affection/knowledge) so the Narrator always gets continuous personality,
    even when the Auditor emitted a thin profile. Runs after apply_npcs, so disk already holds this turn's merge."""
    profs = briefing.get("npc_profiles") or []
    base  = db / "NPCs"
    for p in profs:
        if not isinstance(p, dict):
            continue
        nid = _safe_name(str(p.get("npc_id") or p.get("name") or p.get("descriptor") or ""))
        if not nid:
            continue
        stored = load_json(base / nid / "Profile.json")
        rel    = load_json(base / nid / "Relationships.json")
        if stored:
            for k in ("descriptor", "mood", "goal", "knowledge"):
                if not p.get(k) and stored.get(k):
                    p[k] = stored[k]
            if stored.get("name_known") and stored.get("name"):   # sticky name once learned
                p["name_known"] = True
                p["name"] = stored["name"]
        if rel:
            p.setdefault("relation", rel.get("rel_type", "neutral"))
            if p.get("trust") is None:     p["trust"]     = rel.get("trust", 5)
            if p.get("affection") is None: p["affection"] = rel.get("affection", 5)

def tick_events(db: Path) -> list:
    """Decrement turn-based timers on active events. Return the events that fired (turns_left<=0) this turn."""
    p = db / "Events" / "World_Chronicles.json"; wc = load_json(p)
    active = wc.get("active_events", [])
    due = []
    for ev in active:
        tl = ev.get("turns_left")
        if isinstance(tl, int):
            ev["turns_left"] = tl - 1
            if ev["turns_left"] <= 0:
                due.append(ev)
    wc["active_events"] = active
    save_json(p, wc)
    return due

def apply_events(eu: dict, due: list, db: Path, turn: int):
    """Add new events; resolve/expire events by moving active->archived (permanent, never deleted)."""
    p = db / "Events" / "World_Chronicles.json"; wc = load_json(p)
    active   = wc.get("active_events", [])
    archived = wc.get("archived_events", [])
    for ev in (eu.get("new") or []):
        if not isinstance(ev, dict) or not ev.get("text"):
            continue
        ev.setdefault("id", _safe_name(ev["text"])[:18] + f"_{turn}")
        ev.setdefault("status", "active"); ev.setdefault("created_turn", turn)
        active.append(ev)
    resolve = set(eu.get("resolve") or [])
    due_ids = {e.get("id") for e in due}
    move    = resolve | due_ids
    still = []
    for ev in active:
        if ev.get("id") in move:
            ev["status"] = "resolved" if ev.get("id") in resolve else "expired"
            ev["closed_turn"] = turn
            archived.append(ev)
        else:
            still.append(ev)
    wc["active_events"] = still; wc["archived_events"] = archived
    save_json(p, wc)

# ─── Narrator Stream ─────────────────────────────────────────────────────────

def narrate(auditor_out: dict, player_input: str, history_messages: list, recalled: str,
            pri: dict, flags: dict, turn: int, tracker: str = "", canon: str = "", extra_system: str = "", lang: str = ""):
    """Yield narrator text deltas (plain strings). Caller wraps into SSE.
    Story-so-far is sent as real user/assistant turns (history_messages); the model then replies to the
    final user message (the current input + this turn's directives) as the NEXT turn — no transcript-continuation lag."""
    if not pri.get("api_key") or pri["api_key"].startswith("YOUR_"):
        yield "[Narrator: API key not configured]"
        return

    final_user = json.dumps({                          # the CURRENT turn — what the model must respond to
        "directors_briefing":    auditor_out.get("directors_briefing", {}),
        "player_original_input": player_input,
        "flags_json":            flags,
        "turn_number":           turn,
        "tracker":               tracker,
        "_n":                    f"{turn}:{int(time.time()*1000)}",   # per-request nonce — defeats any identical-completion caching
    }, ensure_ascii=False)

    messages = [{"role": "system", "content": read_prompt(PROMPTS/"Narrator"/"Core.txt")}]
    if canon:
        messages.append({"role": "system", "content":
            "[WORLD CANON — authoritative, always true; honor it in narration]\n" + canon})
    if recalled:
        messages.append({"role": "system", "content": "[RECALLED older relevant turns — context only, already happened]\n" + recalled})
    messages += (history_messages or [])               # story so far, as real turns (already shown)
    if lang:
        messages.append({"role": "system", "content":
            f"[LANGUAGE] Narrate STRICTLY in {lang}. Every word of the story output must be in {lang}, "
            f"regardless of any other instruction, example, or the language of the system prompt."})
    if extra_system:
        messages.append({"role": "system", "content": extra_system})
    messages.append({"role": "user", "content": final_user})

    payload = {
        "model": pri["model"], "temperature": 0.8,
        "messages": messages,
        "stream": True,
    }
    headers = {"Authorization": f"Bearer {pri['api_key']}"}

    try:
        with http.post(pri["url"], json=payload, headers=headers, stream=True, timeout=60) as r:
            r.raise_for_status()
            for raw in r.iter_lines():
                if not raw: continue
                line = raw.decode("utf-8")
                if line.startswith("data: "): line = line[6:]
                if line.strip() == "[DONE]": break
                try:
                    delta = json.loads(line)["choices"][0]["delta"].get("content","")
                    if delta:
                        yield delta
                except Exception:
                    pass
    except Exception as e:
        yield f"[Error: {e}]"

# ─── Logger ──────────────────────────────────────────────────────────────────

def write_turn_txt(turn: int, player_input: str, narrator_out: str, db: Path, error_code: str = ""):
    """Permanent per-turn .txt: raw player + narrator text with the MOST tracker at the very END (V7 style), for precise retrieval. The tracker carries [Chk:] (signed checksum) and, when the verify pass flagged the turn, [E:] (error code) — both after the signed payload so the checksum stays verifiable."""
    txt_dir = db / "Events" / "Eternal_Logs" / "txt"
    txt_dir.mkdir(parents=True, exist_ok=True)
    tracker = encode_most(load_state(db), load_index(db))   # end-of-turn state (apply_* already ran)
    if error_code:
        tracker += f"[E:{error_code}]"
    body = (
        f"=== TURN {turn} | {datetime.now().isoformat(timespec='seconds')} ===\n"
        f"[PLAYER]\n{player_input}\n\n"
        f"[NARRATOR]\n{narrator_out}\n\n"
        f"[TRACKER]\n{tracker}\n"
    )
    (txt_dir / f"T{turn}.txt").write_text(body, encoding="utf-8")

def log_turn(turn: int, player_input: str, most: str,
             auditor_out: dict, narrator_out: str, index: dict, db: Path, error_code: str = ""):
    today    = datetime.now().strftime("%Y-%m-%d")
    log_dir  = db / "Events" / "Eternal_Logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    log_path = log_dir / f"{today}.json"

    entry = {
        "turn_id": turn, "timestamp": datetime.now().isoformat(),
        # end-of-turn tracker (post-apply) — consistent with the .txt log and the narration's date,
        # not the pre-turn `most` (which lagged a turn behind on day-skips)
        "player_input": player_input, "most_snapshot": encode_most(load_state(db), index),
        "auditor_output": auditor_out, "narrator_output": narrator_out,
        "laws_changed": [auditor_out["new_law"]] if auditor_out.get("new_law") else [],
    }
    log_data = load_json(log_path) if log_path.exists() else {"turns": []}
    log_data.setdefault("turns", []).append(entry)
    save_json(log_path, log_data)

    summary = auditor_out.get("turn_summary",{}).get("player_action") or player_input[:80]
    index.setdefault("history",[]).append({"turn":turn,"date":today,"summary":summary})
    index["history"]      = index["history"][-200:]
    index["current_turn"] = turn + 1
    index["current_date"] = today
    save_json(db/"Index"/"Turn_Index.json", index)

    write_turn_txt(turn, player_input, narrator_out, db, error_code)
    update_recall_index(db, turn, today, index.get("game_date", ""),
                        player_input, narrator_out, auditor_out)

def _make_fallback(player_input: str, most: str) -> dict:
    return {
        "intent": player_input, "action_success": True, "failure_reason": None,
        "stat_changes": {}, "flag_changes": {},
        "inventory_changes": {"remove":[],"add":[]},
        "new_law": None, "most_updated": most,
        "directors_briefing": {
            "scene_context":"Auditor offline — narrate from player input.",
            "npc_states":[],"tone":"calm",
            "player_last_action":player_input,"suggested_focus":"","npc_profiles":[],
        },
        "turn_summary": {
            "player_action":player_input,"key_dialogue":[],"emotional_impact":{},
            "world_changes":[],"new_knowledge":[],"important_notes":"[FALLBACK]",
        },
    }

# ─── Routes ──────────────────────────────────────────────────────────────────

@app.route("/")
def index():
    return redirect(url_for("setup"))

@app.route("/setup")
def setup():
    cfg = load_cfg()
    return render_template("settings.html", cfg=cfg)

@app.route("/loading")
def loading():
    cfg = load_cfg()
    pri, sec = get_model_info(cfg)
    return render_template("loading.html", pri=pri, sec=sec)

@app.route("/game")
def game():
    cfg = load_cfg()
    pri, sec = get_model_info(cfg)
    db  = get_db(cfg)
    stats = get_stats(db)
    return render_template("game.html", pri=pri, sec=sec, stats=stats, theme=pri["theme"])

# ─── API ─────────────────────────────────────────────────────────────────────

@app.route("/api/detect", methods=["POST"])
def api_detect():
    url = request.get_json(force=True).get("url","")
    return jsonify(detect_provider(url))

@app.route("/api/save-settings", methods=["POST"])
def api_save_settings():
    d = request.get_json(force=True)
    old = load_cfg()
    cfg = {
        "primary":   {"url": d.get("pri_url",""), "api_key": d.get("pri_key","")},
        "secondary": {"url": d.get("sec_url",""), "api_key": d.get("sec_key","")},
        "db_path":   old.get("db_path",""),
        "history_turns": int(d.get("history_turns", 5)),
        "auto_save": {
            "enabled":     bool(d.get("as_enabled", False)),
            "every_turns": int(d.get("as_turns", 5)),
            "keep_files":  int(d.get("as_keep",  5)),
        },
    }
    if d.get("pri_model"): cfg["primary"]["model"]   = d["pri_model"]
    if d.get("sec_model"): cfg["secondary"]["model"] = d["sec_model"]
    cfg["ingame_date"] = bool(d.get("ingame_date", False))
    cfg["web_lookup"]  = bool(d.get("web_lookup", False))
    for k in ("web_source", "history_fill_ratio", "context_tokens"):  # preserve advanced keys not in the form
        if k in old:
            cfg[k] = old[k]
    save_cfg(cfg)
    return jsonify({"ok": True})

# ─── Campaigns ────────────────────────────────────────────────────────────────

def campaigns_root() -> Path:
    p = BASE / "Database" / "Campaigns"
    p.mkdir(parents=True, exist_ok=True)
    return p

def _campaign_stats(folder: Path, active_db: Path) -> dict:
    idx  = load_json(folder / "Index" / "Turn_Index.json")
    turns = idx.get("current_turn", 0)
    size  = sum(f.stat().st_size for f in folder.rglob("*") if f.is_file())
    return {
        "name":     folder.name,
        "turns":    turns,
        "size_mb":  round(size / 1024 / 1024, 1),
        "active":   folder.resolve() == active_db.resolve(),
    }

def _init_campaign(path: Path):
    defaults = {
        "World/01_Geography.json":   {"current_location":{"id":"start","name":"","description":"","connected_to":[]},"known_locations":[]},
        "World/02_Politics.json":    {"factions":[],"active_conflicts":[],"pc_reputation":{}},
        "World/03_Economy.json":     {"economic_state":"stable","trade_goods":[],"market_notes":""},
        "World/04_Magic_Tech.json":  {"tech_level":"","available_tech":[],"magic_rules":[]},
        "World/05_History.json":     {"world_name":"","era":"","backstory":"","major_past_events":[]},
        "World/06_Active_Laws.json": {"laws":[]},
        "World/00_Worldbook.json":   {"entries":[]},
        "PC/01_Physical.json":       {"hp":100,"stamina":100,"injuries":[],"status_effects":[],"posture":"standing"},
        "PC/02_Mental.json":         {"mental_state":100,"stress_triggers":[],"known_facts":[]},
        "PC/03_Inventory.json":      {"items":[],"equipped":{},"currency":0},
        "Events/World_Chronicles.json": {"major_events":[]},
        "Index/Turn_Index.json":     {"current_turn":0,"current_date":"","history":[]},
    }
    for rel, data in defaults.items():
        fp = path / rel
        fp.parent.mkdir(parents=True, exist_ok=True)
        if not fp.exists():
            with open(fp, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)

# ─── Turn snapshots (undo / rewind) ──────────────────────────────────────────
SNAP_DIR = "Snapshots"
SNAP_MAX = 20   # how many turns back the player can rewind

def _snap_root(db: Path) -> Path:
    return db / SNAP_DIR

def list_snapshots(db: Path) -> list:
    """Turn numbers that currently have a checkpoint, ascending."""
    root = _snap_root(db)
    if not root.exists():
        return []
    return sorted(int(p.name[1:]) for p in root.iterdir()
                  if p.is_dir() and p.name.startswith("T") and p.name[1:].isdigit())

def snapshot_turn(db: Path, turn: int, keep: int = SNAP_MAX):
    """Full checkpoint of the campaign BEFORE `turn` mutates anything — the undo target. Copies every state item except the Snapshots folder itself, then prunes to the last `keep` checkpoints (ring buffer)."""
    import shutil
    root = _snap_root(db); root.mkdir(parents=True, exist_ok=True)
    dest = root / f"T{turn}"
    if dest.exists():
        shutil.rmtree(dest, ignore_errors=True)
    dest.mkdir(parents=True, exist_ok=True)
    for item in db.iterdir():
        if item.name == SNAP_DIR:
            continue
        tgt = dest / item.name
        shutil.copytree(item, tgt) if item.is_dir() else shutil.copy2(item, tgt)
    for old in list_snapshots(db)[:-keep] if keep > 0 else []:
        shutil.rmtree(root / f"T{old}", ignore_errors=True)

def restore_snapshot(db: Path, turn: int) -> bool:
    """Restore the campaign to the checkpoint taken before `turn`, discarding that turn and any later ones — like loading a save. Returns True on success."""
    import shutil
    src = _snap_root(db) / f"T{turn}"
    if not src.is_dir():
        return False
    for item in db.iterdir():                       # wipe current state (keep the Snapshots folder)
        if item.name == SNAP_DIR:
            continue
        shutil.rmtree(item, ignore_errors=True) if item.is_dir() else item.unlink(missing_ok=True)
    for item in src.iterdir():                      # copy the checkpoint back
        tgt = db / item.name
        shutil.copytree(item, tgt) if item.is_dir() else shutil.copy2(item, tgt)
    for t in list_snapshots(db):                    # drop this checkpoint and any newer (no redo)
        if t >= turn:
            shutil.rmtree(_snap_root(db) / f"T{t}", ignore_errors=True)
    return True

@app.route("/api/campaigns")
def api_campaigns_list():
    import shutil
    cfg     = load_cfg()
    root    = campaigns_root()
    active  = get_db(cfg)
    folders = sorted([f for f in root.iterdir() if f.is_dir()])
    camps   = [_campaign_stats(f, active) for f in folders]
    total_b = sum(f.stat().st_size for d in folders for f in d.rglob("*") if f.is_file())
    _, _, free = shutil.disk_usage(str(root))
    return jsonify({
        "campaigns": camps,
        "count":     len(camps),
        "total_mb":  round(total_b / 1024 / 1024, 1),
        "free_gb":   round(free / 1024 / 1024 / 1024, 1),
    })

@app.route("/api/campaigns/create", methods=["POST"])
def api_campaigns_create():
    name = request.get_json(force=True).get("name","").strip()
    if not name:
        return jsonify({"ok":False,"error":"Name required"}), 400
    path = campaigns_root() / name
    if path.exists():
        return jsonify({"ok":False,"error":"Already exists"}), 400
    _init_campaign(path)
    return jsonify({"ok":True})

@app.route("/api/campaigns/delete", methods=["POST"])
def api_campaigns_delete():
    import shutil
    name = request.get_json(force=True).get("name","").strip()
    path = campaigns_root() / name
    if not path.exists():
        return jsonify({"ok":False,"error":"Not found"}), 404
    shutil.rmtree(str(path))
    cfg = load_cfg()
    if cfg.get("db_path","") == str(path):
        cfg["db_path"] = ""
        save_cfg(cfg)
    return jsonify({"ok":True})

@app.route("/api/campaigns/rename", methods=["POST"])
def api_campaigns_rename():
    d    = request.get_json(force=True)
    old  = (d.get("old","")).strip()
    new  = (d.get("new","")).strip()
    root = campaigns_root()
    old_p, new_p = root/old, root/new
    if not old_p.exists(): return jsonify({"ok":False,"error":"Not found"}), 404
    if new_p.exists():     return jsonify({"ok":False,"error":"Name taken"}), 400
    old_p.rename(new_p)
    cfg = load_cfg()
    if cfg.get("db_path","") == str(old_p):
        cfg["db_path"] = str(new_p)
        save_cfg(cfg)
    return jsonify({"ok":True})

@app.route("/api/campaigns/select", methods=["POST"])
def api_campaigns_select():
    name = request.get_json(force=True).get("name","").strip()
    cfg  = load_cfg()
    cfg["db_path"] = str(campaigns_root() / name) if name else ""
    save_cfg(cfg)
    return jsonify({"ok":True})

# ─── Key Vault ───────────────────────────────────────────────────────────────

def keys_dir(slot: str = "") -> Path:
    sub = slot if slot in ("primary", "secondary") else ""
    p   = BASE / "Config" / "Keys" / sub if sub else BASE / "Config" / "Keys"
    p.mkdir(parents=True, exist_ok=True)
    return p

def _safe_name(name: str) -> str:
    return "".join(c for c in name if c.isalnum() or c in " _-").strip().replace(" ", "_")

@app.route("/api/keys")
def api_keys_list():
    slot = request.args.get("slot", "")
    keys = []
    for f in sorted(keys_dir(slot).glob("*.json")):
        try:
            d = load_json(f)
            if d.get("name"):
                keys.append(d)
        except Exception:
            pass
    return jsonify({"keys": keys})

@app.route("/api/keys/save", methods=["POST"])
def api_keys_save():
    d    = request.get_json(force=True)
    name = d.get("name","").strip()
    slot = d.get("slot","").strip()
    if not name:
        return jsonify({"ok":False,"error":"Name required"}), 400
    path = keys_dir(slot) / f"{_safe_name(name)}.json"
    save_json(path, {
        "name":     name,
        "slot":     slot,
        "provider": d.get("provider",""),
        "url":      d.get("url",""),
        "api_key":  d.get("api_key",""),
        "model":    d.get("model",""),
    })
    return jsonify({"ok":True})

@app.route("/api/keys/delete", methods=["POST"])
def api_keys_delete():
    d    = request.get_json(force=True)
    name = d.get("name","").strip()
    slot = d.get("slot","").strip()
    for f in keys_dir(slot).glob("*.json"):
        if load_json(f).get("name") == name:
            f.unlink()
            return jsonify({"ok":True})
    return jsonify({"ok":False,"error":"Not found"}), 404

@app.route("/api/keys/rename", methods=["POST"])
def api_keys_rename():
    d        = request.get_json(force=True)
    old_name = d.get("old","").strip()
    new_name = d.get("new","").strip()
    slot     = d.get("slot","").strip()
    if not old_name or not new_name:
        return jsonify({"ok":False,"error":"Names required"}), 400
    kdir = keys_dir(slot)
    for f in kdir.glob("*.json"):
        data = load_json(f)
        if data.get("name") == old_name:
            data["name"] = new_name
            f.unlink()
            save_json(kdir / f"{_safe_name(new_name)}.json", data)
            return jsonify({"ok":True})
    return jsonify({"ok":False,"error":"Not found"}), 404

@app.route("/api/campaigns/reset", methods=["POST"])
def api_campaigns_reset():
    import shutil
    name = request.get_json(force=True).get("name","").strip()
    path = campaigns_root() / name
    if not path.exists():
        return jsonify({"ok":False,"error":"Not found"}), 404
    for item in list(path.iterdir()):
        shutil.rmtree(str(item)) if item.is_dir() else item.unlink()
    _init_campaign(path)
    return jsonify({"ok":True})

@app.route("/api/browse", methods=["POST"])
def api_browse():
    try:
        import tkinter as tk
        from tkinter import filedialog
        root = tk.Tk(); root.withdraw(); root.wm_attributes("-topmost", 1)
        folder = filedialog.askdirectory(title="Select Database Folder")
        root.destroy()
        return jsonify({"path": folder or ""})
    except Exception as e:
        return jsonify({"path":"","error": str(e)})

@app.route("/api/check")
def api_check():
    cfg = load_cfg()
    db  = get_db(cfg)
    pri, sec = get_model_info(cfg)

    def generate():
        steps = [
            ("config",    "Loading config",
             lambda: bool(cfg)),
            ("providers", f"Detecting providers",
             lambda: bool(pri["name"] and sec["name"])),
            ("prompts",   "Loading prompts",
             lambda: bool(read_prompt(PROMPTS/"Auditor"/"Core.txt"))),
            ("auditor",   f"Connecting to Auditor  ({sec['name']})",
             lambda: _ping(sec["url"])),
            ("narrator",  f"Connecting to Narrator ({pri['name']})",
             lambda: bool(pri.get("api_key") and not pri["api_key"].startswith("YOUR_"))),
            ("database",  "Loading database",
             lambda: campaigns_root().exists() and (
                 (db / "PC" / "01_Physical.json").exists()
                 or any(campaigns_root().iterdir())
             )),
        ]
        total = len(steps)
        for i, (key, label, fn) in enumerate(steps):
            try: ok = fn()
            except Exception: ok = False
            pct = int((i+1)/total*100)
            yield f"data: {json.dumps({'step':key,'label':label,'ok':ok,'pct':pct})}\n\n"
            time.sleep(0.5)
        yield f"data: {json.dumps({'step':'done','pct':100,'pri':pri,'sec':sec})}\n\n"

    return Response(generate(), mimetype="text/event-stream",
                    headers={"Cache-Control":"no-cache","X-Accel-Buffering":"no"})

def _ping(url: str) -> bool:
    try:
        base = url.split("/v1/")[0] if "/v1/" in url else url
        r = http.get(base, timeout=3)
        return r.status_code < 500
    except Exception:
        return False

@app.route("/api/send", methods=["POST"])
def api_send():
    player_input = request.get_json(force=True).get("input","").strip()
    if not player_input:
        return jsonify({"error":"empty"}), 400

    cfg      = load_cfg()
    db       = get_db(cfg)
    pri, sec = get_model_info(cfg)

    state    = load_state(db)
    index    = load_index(db)
    turn     = index.get("current_turn", 0)
    prior_error = index.get("last_error", "")            # V7-style: last turn's flag, fed back for correction
    state["npcs"] = relevant_npcs(state["npcs"], turn)   # curated working window (full set stays on disk)
    most     = encode_most(state, index)
    history  = get_recent_history(index, cfg.get("history_turns", 5))
    query    = build_query(player_input, state)
    if cfg.get("recall", True):                          # give the Auditor a relevant slice of the past too
        _rb, _ = recall_block(db, query[0], query[1], query[2],
                              int(cfg.get("recall_auditor_chars", 2000)), set(),
                              int(cfg.get("recall_k", 6)),
                              int(cfg.get("recall_snippet_chars", 1200)))
        if _rb:
            history = _rb + "\n[RECENT]\n" + history
    active_events = sorted(load_json(db/"Events"/"World_Chronicles.json").get("active_events", []),
                           key=lambda e: e.get("turns_left") if isinstance(e.get("turns_left"), int) else 9999)[:15]
    flags    = load_flags(db)

    snapshot_turn(db, turn)     # checkpoint BEFORE this turn mutates anything → the undo target

    def generate():
        yield f"data: {json.dumps({'type':'auditor_start','turn':turn})}\n\n"

        fixed_response = None   # when set, skip the Narrator LLM and emit this text verbatim

        # 1. Command detection ([start]/[pause]/[resume] + Thai aliases)
        cmd_result = detect_command(player_input, flags)
        if cmd_result:
            save_flags(db, flags)
            if cmd_result == "start_game":
                if not flags.get("worldbook_compiled"):   # distill all pre-game lore into permanent canon (once)
                    try:
                        if compile_worldbook(db, sec):
                            flags["worldbook_compiled"] = True
                            save_flags(db, flags)
                    except Exception:
                        pass                               # never let canon compilation block [start]
                briefing = {"scene_context": "Game starting", "tone": "calm", "is_ooc": False, "npc_profiles": []}
            elif cmd_result.startswith("cannot_start"):
                missing = cmd_result.split(":", 1)[1] if ":" in cmd_result else "world,character,starting point"
                briefing = {"scene_context": f"Cannot start. Missing: {missing}", "tone": "calm", "is_ooc": True, "npc_profiles": []}
            elif cmd_result == "pause":
                briefing = {"scene_context": "Game paused", "tone": "calm", "is_ooc": True, "npc_profiles": []}
                fixed_response = PAUSE_MSG          # bare "หยุด" → short, deterministic, no LLM
            elif cmd_result == "resume":
                briefing = {"scene_context": "Game resumed", "tone": "calm", "is_ooc": False, "npc_profiles": []}
            else:
                briefing = {"scene_context": "", "tone": "calm", "is_ooc": True, "npc_profiles": []}
            auditor_out = {
                "directors_briefing": briefing,
                "is_ooc":         briefing.get("is_ooc", True),
                "intent":         player_input,
                "action_success": True,
                "new_law":        None,
            }
            yield f"data: {json.dumps({'type':'auditor_ok', 'new_law': None})}\n\n"
        else:
            # 2. Normal flow: Auditor (secondary model, multi-provider)
            due_events = tick_events(db) if flags.get("game_started") else []
            auditor_out = call_auditor(player_input, most, state, history, sec, flags, due_events, active_events, prior_error)
            if not auditor_out:
                auditor_out = _make_fallback(player_input, most)
                yield f"data: {json.dumps({'type':'auditor_fail'})}\n\n"
            elif auditor_out.get("request_pause") and flags.get("game_started") and not flags.get("game_paused"):
                # AI inferred a stop ("หยุด"/stop + off-topic) → pause now, answer in OOC, no state changes.
                flags["game_paused"] = True
                save_flags(db, flags)
                auditor_out["is_ooc"] = True
                br = auditor_out.setdefault("directors_briefing", {})
                br.update({"is_ooc": True, "npc_profiles": [], "scene_context": PAUSE_INFER_CUE})
                yield f"data: {json.dumps({'type':'auditor_ok', 'new_law': None})}\n\n"
            else:
                if auditor_out.get("updated_flags"):
                    # game_started/game_paused are command-only (set by detect_command), never by the Auditor
                    safe = {k: v for k, v in auditor_out["updated_flags"].items()
                            if k not in ("game_started", "game_paused")}
                    if safe:
                        flags.update(safe)
                        save_flags(db, flags)
                apply_changes(auditor_out, db)
                apply_setup(auditor_out.get("updated_flags") or {}, db)
                apply_canon(auditor_out, db, turn, flags.get("game_started", False), bool(cfg.get("chrysalis")))
                if cfg.get("chrysalis"):
                    promote_and_expire_provisional(db, turn, player_input, cfg)
                    if cfg.get("chrysalis_semantic"):
                        apply_canon_review(db, auditor_out.get("canon_review") or {}, turn, cfg)
                apply_world(auditor_out.get("world_updates") or {}, db)
                if flags.get("game_started") and not auditor_out.get("is_ooc"):
                    apply_knowledge(auditor_out, db)   # accumulate learned facts → mental.known_facts
                if flags.get("game_started") and not auditor_out.get("is_ooc"):
                    apply_location(auditor_out.get("location_update") or {}, db)
                    # Engine rolls a rare area encounter — only on calm exploration/travel/idle turns
                    _br = auditor_out.get("directors_briefing", {}) or {}
                    if auditor_out.get("allow_encounter", True) and _br.get("tone") != "tense":
                        _loc = load_json(db/"World"/"01_Geography.json").get("current_location", {})
                        _cue = roll_encounter(_loc, index, turn)
                        if _cue:
                            _br.setdefault("signals", []).append(_cue)
                            auditor_out["directors_briefing"] = _br
                apply_npcs(auditor_out.get("directors_briefing", {}).get("npc_profiles") or [], db, turn)
                apply_events(auditor_out.get("event_updates") or {}, due_events, db, turn)
                apply_date(auditor_out, index, cfg)
                if cfg.get("web_lookup") and cfg.get("web_source", "wikipedia") == "wikipedia" and auditor_out.get("wiki_query"):
                    _hp = db / "World" / "05_History.json"; _h = load_json(_hp)
                    if not _h.get("web_context"):                       # fetch once, at setup
                        _ref = wiki_lookup(auditor_out["wiki_query"])
                        if _ref:
                            _h["web_context"] = _ref; save_json(_hp, _h)
                yield f"data: {json.dumps({'type':'auditor_ok', 'new_law': auditor_out.get('new_law')})}\n\n"

        # 3. Narrator (primary model, multi-provider) — stream deltas
        briefing = auditor_out.get("directors_briefing", {})
        briefing["is_ooc"] = auditor_out.get("is_ooc", False)
        if flags.get("game_started") and not briefing.get("is_ooc"):
            enrich_npc_profiles(briefing, db)             # give the Narrator full, continuous NPC personality
        if prior_error and not briefing.get("is_ooc"):    # surface last turn's flag so the Narrator self-corrects
            briefing.setdefault("signals", []).append(f"PRIOR_ERROR {prior_error}: correct it this turn, do not repeat")

        narr_msgs, recalled = build_history_messages(db, history_budget_chars(pri, cfg), query, cfg)
        tracker   = encode_most(load_state(db), index)   # fresh (post-apply, incl. game_date) so the Narrator can read [D:]
        canon     = format_canon(db, int(cfg.get("canon_budget_chars", 2500)))  # always-on world facts
        if cfg.get("chrysalis"):                                                # + provisional (tagged unverified)
            _prov = render_provisional(db, int(cfg.get("chrysalis_prov_budget", 600)))
            if _prov:
                canon = (canon + "\n" + _prov).strip()
        narrator_full = ""
        if fixed_response is not None:                   # deterministic reply (bare stop) — skip the LLM
            narrator_full = fixed_response
            yield f"data: {json.dumps({'type':'narrator_chunk','text':fixed_response})}\n\n"
        elif cfg.get("anti_repeat"):                     # buffer → guard verbatim repeat → emit (no live stream)
            prev_scene = get_last_scene(db, 4000)
            def _gen(extra=""):
                b = ""
                for d in narrate(auditor_out, player_input, narr_msgs, recalled, pri, flags, turn, tracker, canon, extra, lang=cfg.get("narration_lang", "")):
                    b += d
                return b
            narrator_full = _gen()
            if prev_scene and difflib.SequenceMatcher(None, prev_scene, narrator_full).ratio() >= 0.95:
                narrator_full = _gen("[ANTI-REPEAT] Your previous attempt repeated the last turn almost verbatim. "
                                     "Write a DIFFERENT continuation that responds to THIS turn's input and director's briefing.")
            yield f"data: {json.dumps({'type':'narrator_chunk','text':narrator_full})}\n\n"
        else:
            for delta in narrate(auditor_out, player_input, narr_msgs, recalled, pri, flags, turn, tracker, canon, lang=cfg.get("narration_lang", "")):
                narrator_full += delta
                yield f"data: {json.dumps({'type':'narrator_chunk','text':delta})}\n\n"

        # 4. Verify pass (Auditor checks Narrator) — non-blocking, stamps [E:] for next turn
        err_code = ""
        if cfg.get("narrator_audit") and cmd_result is None and flags.get("game_started") and not auditor_out.get("is_ooc"):
            v = verify_narration(narrator_full, load_state(db), sec, auditor_out, player_input)
            if v:
                err_code = (v.get("error_code") or "").strip()
                if cfg.get("audit_notify") and v.get("severity") == "hard":
                    details = "; ".join(x.get("detail", "") for x in (v.get("violations") or []) if x.get("detail"))
                    if details:
                        note = "\n\n---\n[ตรวจสอบ] " + details[:240]
                        narrator_full += note
                        yield f"data: {json.dumps({'type':'narrator_chunk','text':note})}\n\n"
        index["last_error"] = err_code                    # cleared (="") on clean / OOC / command turns

        # 5. Finalize turn
        log_turn(turn, player_input, most, auditor_out, narrator_full, index, db, err_code)
        yield f"data: {json.dumps({'type':'done','stats':get_stats(db)})}\n\n"

    return Response(generate(), mimetype="text/event-stream",
                    headers={"Cache-Control":"no-cache","X-Accel-Buffering":"no"})

@app.route("/api/history")
def api_history():
    cfg = load_cfg()
    db  = get_db(cfg)
    today    = datetime.now().strftime("%Y-%m-%d")
    log_path = db/"Events"/"Eternal_Logs"/f"{today}.json"
    if not log_path.exists():
        return jsonify({"turns":[]})
    turns = load_json(log_path).get("turns",[])[-20:]
    return jsonify({"turns": [
        {"turn": t.get("turn_id",0),
         "player": t.get("player_input",""),
         "narrator": t.get("narrator_output","")}
        for t in turns
    ]})

@app.route("/api/state")
def api_state():
    cfg = load_cfg()
    return jsonify(get_stats(get_db(cfg)))

@app.route("/api/tracker")
def api_tracker():
    """Previous turn's tracker (raw MOST string + decoded fields + turn summary) for the slide-out tracker window."""
    cfg = load_cfg(); db = get_db(cfg)
    today    = datetime.now().strftime("%Y-%m-%d")
    log_path = db/"Events"/"Eternal_Logs"/f"{today}.json"
    turns    = load_json(log_path).get("turns", []) if log_path.exists() else []
    if not turns:
        return jsonify({"empty": True})
    last = turns[-1]
    raw  = last.get("most_snapshot", "")
    return jsonify({
        "empty":   False,
        "turn":    last.get("turn_id", 0),
        "player":  last.get("player_input", ""),
        "raw":     raw,
        "decoded": decode_most(raw),
        "summary": last.get("auditor_output", {}).get("turn_summary", {}) or {},
    })

@app.route("/api/undo", methods=["POST"])
def api_undo():
    """Rewind one turn: restore the checkpoint taken before the most recent turn, discarding it — like loading a save. Repeatable up to SNAP_MAX turns back."""
    cfg = load_cfg()
    db  = get_db(cfg)
    snaps = list_snapshots(db)
    if not snaps:
        return jsonify({"ok": False, "error": "ไม่มีเทิร์นให้ย้อน"}), 400
    last = max(snaps)                                  # checkpoint = state before the latest turn
    if not restore_snapshot(db, last):
        return jsonify({"ok": False, "error": "restore failed"}), 500
    today    = datetime.now().strftime("%Y-%m-%d")
    log_path = db/"Events"/"Eternal_Logs"/f"{today}.json"
    turns    = load_json(log_path).get("turns",[])[-20:] if log_path.exists() else []
    return jsonify({
        "ok":          True,
        "undone_turn": last,
        "undo_left":   len(list_snapshots(db)),
        "stats":       get_stats(db),
        "turns": [
            {"turn": t.get("turn_id",0),
             "player": t.get("player_input",""),
             "narrator": t.get("narrator_output","")}
            for t in turns
        ],
    })
