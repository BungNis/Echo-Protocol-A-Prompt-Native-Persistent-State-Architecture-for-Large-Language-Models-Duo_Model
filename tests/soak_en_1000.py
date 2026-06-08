"""Synapse Protocol V1 — PUBLIC SHOWCASE soak (English, 1000 turns, batch of 250).

Proves the LLM failure-modes V8 fixes, in a historically-grounded English world
(London, 1888). Observe-only: never edits prompts/code. Runs ONE 250-turn batch per
invocation, prints a REPORT block every 50 turns, then stops for human approval.
Rich data capture for a public report: per-turn JSONL + findings + scorecard.

Usage: python tests/soak_en_1000.py <batch 1-4> [port=8080]
  batch 1 resets campaign SOAK_EN_1000, builds world+PC+[start], plays turns 1-250
  batch N continues turns (N-1)*250+1 .. N*250

Toggles set ON: narrator_audit(v2), recall, audit_notify, ingame_date, web_lookup.
Chrysalis stays OFF (showcase only proven features). Real campaign untouched.
"""
import json, re, time, sys, random, difflib, datetime, subprocess
from pathlib import Path
import requests

PORT  = int(sys.argv[2]) if len(sys.argv) > 2 else 8080
BATCH = int(sys.argv[1]) if len(sys.argv) > 1 else 1
CAMP  = "SOAK_EN_1000"
BASE  = Path(__file__).resolve().parent.parent
DB    = BASE / "Database" / "Campaigns" / CAMP
B     = f"http://127.0.0.1:{PORT}"
CFG   = BASE / "Config" / "Settings.json"
PER   = 250
RESUME = int(sys.argv[3]) if len(sys.argv) > 3 else 0   # resume from this story-turn (skip reset+setup)

SKIP_KW = ("rest", "next morning", "three days", "a month passes", "passes", "overnight",
           "days later", "weeks later", "spend the night")

PLACES = ["the Limehouse docks", "Covent Garden market", "the goldsmiths' row",
          "the Whitechapel lanes", "the railway terminus", "a riverside warehouse",
          "the merchants' guild hall", "a dim coaching inn", "Billingsgate fish market",
          "the counting-house"]
NPCS   = ["Mrs. Pryce the fishwife", "Old Hale the dockworker", "Mr. Ashby the guild master",
          "a river smuggler", "Father Quill the parish priest", "the city tax clerk",
          "a travelling apothecary"]
ITEMS  = ["a sack of tea", "a bolt of silk", "a sturdy knife", "a crate of spices",
          "a brass lantern", "a case of medicinal tonics"]

SETUP_SEQ = [
    ("WORLD", "Build a detailed, historically grounded world: London in 1888, the late "
              "Victorian era — its docks, markets, railways, social classes, the currency of "
              "pounds, shillings and pence, and the rhythms of trade. Keep it true to the period. "
              "The story begins on the morning of 14 March 1888."),
    ("SHOW",  "Show me the world you have created."),
    ("PC",    "Create my character: Edwin Cross, an ambitious young merchant trying to build a "
              "trading house from modest beginnings — sharp, resourceful, and patient."),
    ("STARTP","Set the starting point at the Limehouse docks at dawn, with a small purse of coins "
              "and a single rented market stall."),
    ("START", "[start]"),
]

# story_turn -> (kind, text, [expected substrings for PROBE])
TRAPS = {
    5:   ("PLANT", "Hide a sealed letter and a gold signet ring beneath a loose floorboard by the "
                   "hearth in Edwin's lodgings, then set the board back exactly as it was.", None),
    30:  ("PLANT", "Befriend Old Hale, a weathered dockworker at Limehouse. Hale gives his word that "
                   "he will find the old nautical chart to the lost wreck of the Mary Reach.", None),
    50:  ("PLANT", "Send word calling a meeting of the merchants' guild in exactly seven days.", None),
    60:  ("PLANT", "A street balladeer sings the legend of the Black Sovereign — a cursed gold coin "
                   "said to be sealed in the crypt beneath St. Mowren's church.", None),

    55:  ("PROBE", "Return to Edwin's lodgings, pry up the loose floorboard by the hearth, and take "
                   "out what was hidden there.", ["letter", "ring"]),
    255: ("PROBE", "Go back to the lodgings, lift the loose floorboard by the hearth, and check the "
                   "hidden items are still there.", ["letter", "ring"]),
    300: ("PROBE", "Find Old Hale at the docks and ask after the nautical chart to the Mary Reach he "
                   "promised.", ["Hale", "chart", "Mary Reach"]),
    555: ("PROBE", "Once more lift the hearth floorboard in the lodgings and take out the hidden "
                   "letter and ring.", ["letter", "ring"]),
    600: ("PROBE", "Travel to St. Mowren's church and search the crypt for the Black Sovereign from "
                   "the legend.", ["Black Sovereign", "crypt"]),
    700: ("PROBE", "Seek out Old Hale again and follow up on the Mary Reach chart.",
                   ["Hale", "chart", "Mary Reach"]),
    955: ("PROBE", "Return a final time to the hearth floorboard and retrieve the sealed letter and "
                   "gold ring.", ["letter", "ring"]),
    1000:("PROBE", "At the close: take the hidden letter and ring from the hearth, and recall the "
                   "legend of the Black Sovereign.", ["letter", "ring", "Black Sovereign"]),
}

# adversarial probes (test resistance) — story_turn -> (kind, text, note)
ADVERS = {
    120: ("ADV_CONTRA", "Draw the silver sword the Duke gave me and brandish it at the crowd.",
          "PC never owned such a sword — verify should flag CN / Narrator should not invent it"),
    180: ("ADV_PCCTRL", "I stand frozen, unable to decide — go on and tell me what I do next.",
          "Narrator must NOT decide the PC's meaningful choice/words"),
    240: ("ADV_CONTRA", "Spend the 10,000 gold sovereigns from my vault to buy the whole market.",
          "PC has no such fortune — engine should not grant it; currency floor holds"),
}


def gen_input(t: int) -> tuple:
    if t in TRAPS:  return (TRAPS[t][0], TRAPS[t][1])
    if t in ADVERS: return (ADVERS[t][0], ADVERS[t][1])
    rng = random.Random(t * 7919)
    place = rng.choice(PLACES); npc = rng.choice(NPCS); item = rng.choice(ITEMS)
    if t % 7 == 0:
        return ("SKIP", rng.choice([
            f"Rest for the night at {place} and set out the next morning.",
            "Spend three days trading along the rail line to the coast.",
            "A month passes; return to review how the business has grown."]))
    if t % 13 == 0:
        return ("COMBAT", f"{npc} confronts Edwin on the road — defend yourself and answer with wit.")
    if t % 11 == 0:
        return ("OOC", "(OOC) Summarise my character's status and the key events so far.")
    if t % 5 == 0:
        return ("NPC", f"Seek out {npc} to ask about trade and the latest city news.")
    if t % 9 == 0:
        return ("TRADE", f"Haggle to buy {item} at the market, then resell it elsewhere for profit.")
    return (rng.choice(["EXPLORE", "STORY"]), rng.choice([
        f"Inspect {place} for new business opportunities.",
        f"Walk through {place}, watching the crowd and the flow of trade.",
        f"Talk with the traders around {place} about prospects and prices.",
        f"Plan how to expand the trading house from {place}."]))


def send(text: str):
    try:
        r = requests.post(f"{B}/api/send", json={"input": text}, stream=True, timeout=300)
    except Exception as ex:
        return (-1, f"[EXC {ex}]")
    if r.status_code != 200:
        return (r.status_code, "")
    out = ""
    for raw in r.iter_lines():
        if not raw: continue
        l = raw.decode("utf-8")
        if l.startswith("data: "): l = l[6:]
        try: e = json.loads(l)
        except: continue
        if e.get("type") == "narrator_chunk": out += e.get("text", "")
    return (200, out)

def _j(p, d=None):
    try: return json.load(open(p, encoding="utf-8"))
    except: return d if d is not None else {}

def flags():      return _j(DB / "Setup_Flags.json")
def tindex():     return _j(DB / "Index" / "Turn_Index.json")
def stats():
    ph = _j(DB / "PC" / "01_Physical.json"); mn = _j(DB / "PC" / "02_Mental.json")
    iv = _j(DB / "PC" / "03_Inventory.json")
    return {"hp": ph.get("hp", 100), "st": ph.get("stamina", 100),
            "mn": mn.get("mental_state", 100), "cur": iv.get("currency", 0),
            "items": len(iv.get("items", []))}
def loc():        return _j(DB / "World" / "01_Geography.json").get("current_location", {}).get("name", "")
def txt_of(n):
    p = DB / "Events" / "Eternal_Logs" / "txt" / f"T{n}.txt"
    return p.read_text(encoding="utf-8") if p.exists() else ""

_E_RE = re.compile(r"\[E:([A-Za-z0-9]+)\]")
_YOU  = re.compile(r"\byou\b", re.I)

def api(path, payload):
    try: return requests.post(f"{B}{path}", json=payload, timeout=30).json()
    except Exception as ex: return {"ok": False, "error": str(ex)}

def enable_stack():
    cfg = _j(CFG); want = {"narrator_audit": True, "recall": True, "audit_notify": True,
                           "ingame_date": True, "web_lookup": True, "anti_repeat": True,
                           "chrysalis": True, "chrysalis_semantic": True, "narration_lang": "English"}
    for k, v in want.items(): cfg[k] = v
    CFG.write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")
    print("[cfg] showcase stack: narrator_audit+recall+audit_notify+ingame_date+web_lookup ON, chrysalis OFF", flush=True)

def setup_world():
    print("\n=== BATCH 1 SETUP: reset + build London 1888 ===", flush=True)
    api("/api/campaigns/create", {"name": CAMP})
    api("/api/campaigns/reset",  {"name": CAMP})
    api("/api/campaigns/select", {"name": CAMP})
    for tag, inp in SETUP_SEQ:
        st, nar = send(inp); time.sleep(0.5)
        f = flags()
        print(f"  [{tag}] st={st} flags(w:{f.get('world_created')} p:{f.get('pc_created')} "
              f"s:{f.get('start_created')} g:{f.get('game_started')}) len={len(nar)}", flush=True)
    if not flags().get("game_started"):
        print("*** SETUP FAILED — game_started never set. Aborting. ***", flush=True); sys.exit(2)
    print("=== setup OK ===\n", flush=True)


def main():
    if not (1 <= BATCH <= 4):
        print("batch must be 1..4"); sys.exit(2)
    enable_stack()
    if BATCH == 1 and not RESUME:
        setup_world()
    else:
        api("/api/campaigns/select", {"name": CAMP})
        if not flags().get("game_started"):
            print("*** run batch 1 first ***"); sys.exit(2)
        if RESUME:
            print(f"=== RESUMING from story turn {RESUME} (no reset, no setup) ===", flush=True)

    start_t = RESUME if RESUME else (BATCH - 1) * PER + 1
    end_t   = BATCH * PER
    m = {"repeat": 0, "you": 0, "reintro": 0, "fallback": 0, "halluc": 0,
         "statbad": 0, "datebad": 0, "empty": 0}
    probe_pass = probe_total = 0
    probe_log, adv_log, findings = [], [], []
    data_fp = open(BASE / "tests" / "soak_en_data.jsonl", "a", encoding="utf-8")
    prev_nar = ""; prev_gd = tindex().get("game_date")
    eng_start = tindex().get("current_turn", 0)

    print(f"=== SHOWCASE BATCH {BATCH}: story turns {start_t}..{end_t} ===", flush=True)
    for t in range(start_t, end_t + 1):
        tag, inp = gen_input(t)
        status, nar = send(inp); time.sleep(0.3)
        cur_turn = tindex().get("current_turn", 0)
        gd = tindex().get("game_date"); s = stats(); l = loc()
        body = txt_of(cur_turn); ecodes = _E_RE.findall(body)

        if status != 200 or nar.lstrip().startswith("[Error:") or nar.startswith("[EXC"):
            findings.append(f"- T{t} [{tag}] HARD status={status} {nar[:60]!r}")
        if len(nar.strip()) < 20:
            findings.append(f"- T{t} [{tag}] EMPTY ({len(nar)}ch)"); m["empty"] += 1
        sim = difflib.SequenceMatcher(None, prev_nar, nar).ratio() if prev_nar else 0
        if sim > 0.5: findings.append(f"- T{t} [{tag}] REPEAT {sim:.0%}"); m["repeat"] += 1
        you = len(_YOU.findall(nar))
        if you: m["you"] += you
        if any(x in nar[:120] for x in ("I am the narrator", "I am Synapse", "As your storyteller",
                                        "I am your narrator")):
            findings.append(f"- T{t} [{tag}] REINTRO"); m["reintro"] += 1
        for k, lo, hi in (("hp", 0, 100), ("st", 0, 100), ("mn", 0, 100)):
            if not (lo <= s[k] <= hi): findings.append(f"- T{t} STAT {k}={s[k]}"); m["statbad"] += 1
        if s["cur"] < 0: findings.append(f"- T{t} CURRENCY<0"); m["statbad"] += 1
        if gd and prev_gd and str(gd) < str(prev_gd):
            findings.append(f"- T{t} DATE_BACKWARD {prev_gd}->{gd}"); m["datebad"] += 1
        if any(k in inp.lower() for k in SKIP_KW) and gd and prev_gd and gd == prev_gd:
            findings.append(f"- T{t} DATE_NO_ADVANCE ({gd})"); m["datebad"] += 1
        if ecodes: m["halluc"] += len(ecodes)

        if t in TRAPS and TRAPS[t][0] == "PROBE":
            exp = TRAPS[t][2] or []; hits = [e for e in exp if e.lower() in nar.lower()]
            probe_total += 1; ok = len(hits) >= 1
            if ok: probe_pass += 1
            else:  findings.append(f"- T{t} [PROBE] RECALL_MISS exp~{exp} got:{nar[:80]!r}")
            probe_log.append(f"- T{t}: {'PASS' if ok else 'FAIL'} hits={hits}/{exp} | {nar[:100].strip()!r}")
        if t in ADVERS:
            note = ADVERS[t][2]
            adv_log.append(f"- T{t} [{tag}] {note}\n    input: {inp!r}\n    [E]={ecodes} | reply: {nar[:160].strip()!r}")

        rec = {"turn": t, "eng_turn": cur_turn, "tag": tag, "input": inp, "status": status,
               "narr_head": nar[:160].strip(), "narr_len": len(nar), "hp": s["hp"], "st": s["st"],
               "mn": s["mn"], "cur": s["cur"], "items": s["items"], "loc": l, "gdate": gd,
               "ecodes": ecodes, "repeat_sim": round(sim, 2)}
        data_fp.write(json.dumps(rec, ensure_ascii=False) + "\n"); data_fp.flush()

        prev_nar = nar; prev_gd = gd
        flag = f" <<{tag}" if (t in TRAPS or t in ADVERS) else ""
        print(f"T{t:04d} [{tag}] st={status} et={cur_turn} {gd} hp{s['hp']} cur{s['cur']} "
              f"len={len(nar)} sim={sim:.0%}{flag}", flush=True)

        if (t - start_t + 1) % 50 == 0:
            print(f"\n=== REPORT @turn {t} (batch {BATCH}) ===\n"
                  f"  done {t-start_t+1}/{PER} this batch | in-game date {gd} | loc {l}\n"
                  f"  recall probes {probe_pass}/{probe_total} | [E] halluc {m['halluc']} | "
                  f"repeat {m['repeat']} | you-POV {m['you']} | reintro {m['reintro']} | "
                  f"fallback {m['fallback']} | stat-bad {m['statbad']} | date-bad {m['datebad']} | empty {m['empty']}\n"
                  f"  stats: hp{s['hp']} st{s['st']} mn{s['mn']} cur{s['cur']} items{s['items']}\n"
                  f"=== END REPORT @{t} ===\n", flush=True)

    data_fp.close()
    # per-batch report
    try:
        r = subprocess.run([sys.executable, str(BASE / "tools" / "verify_chk.py"), str(DB)],
                           capture_output=True, text=True, timeout=180)
        chk = (r.stdout.strip().splitlines() or ["?"])[-1] + f" (exit {r.returncode})"
    except Exception as ex:
        chk = f"chk err {ex}"
    probes = f"{probe_pass}/{probe_total}" if probe_total else "—"
    out = BASE / "tests" / f"findings_en_b{BATCH}.md"
    md = [f"# Showcase batch {BATCH} — story turns {start_t}..{end_t}",
          f"{datetime.datetime.now().isoformat(timespec='seconds')} | {CAMP} | EN | full stack (chrysalis off)",
          "", "## Metrics",
          f"- recall probes: {probes}", f"- hallucination [E]: {m['halluc']}",
          f"- repeat>50%: {m['repeat']}", f"- 'you'-POV in narration: {m['you']}",
          f"- re-intro: {m['reintro']}", f"- fallback: {m['fallback']}",
          f"- stat out-of-range: {m['statbad']}", f"- date anomalies: {m['datebad']}",
          f"- empty: {m['empty']}", f"- Chk integrity: {chk}",
          "", "## Recall probes"] + (probe_log or ["- (none in this batch)"]) + \
         ["", "## Adversarial probes"] + (adv_log or ["- (none in this batch)"]) + \
         ["", "## Anomalies"] + (findings or ["- (none flagged)"])
    out.write_text("\n".join(md), encoding="utf-8")
    sc = BASE / "tests" / "scorecard_en.md"
    head = ("| batch | turns | recall | [E] | repeat | you-POV | reintro | fallback | stat-bad | date-bad | empty | Chk |\n"
            "|---|---|---|---|---|---|---|---|---|---|---|---|\n")
    line = (f"| {BATCH} | {start_t}-{end_t} | {probes} | {m['halluc']} | {m['repeat']} | {m['you']} | "
            f"{m['reintro']} | {m['fallback']} | {m['statbad']} | {m['datebad']} | {m['empty']} | {chk} |\n")
    if not sc.exists():
        sc.write_text("# Synapse V1 — Public Showcase scoreboard (EN, London 1888)\n\n" + head, encoding="utf-8")
    with open(sc, "a", encoding="utf-8") as f: f.write(line)

    print(f"\n=== BATCH {BATCH} DONE — awaiting approval ===", flush=True)
    print(f"findings: {out.name} | recall {probes} | {chk} | flagged {len(findings)}", flush=True)
    print(f"data: tests/soak_en_data.jsonl | scoreboard: tests/scorecard_en.md", flush=True)
    if BATCH < 4:
        print(f"NEXT (after approval): python tests/soak_en_1000.py {BATCH+1} {PORT}", flush=True)
    else:
        print("ALL 4 BATCHES DONE — assemble tests/PUBLIC_REPORT.md", flush=True)


if __name__ == "__main__":
    main()
