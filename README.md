# Synapse Protocol V1

**Durable long‑term memory, verifiable state, and consistency for LLM applications — demonstrated over a 1000‑turn run.**

![license](https://img.shields.io/badge/license-MIT-blue) ![python](https://img.shields.io/badge/python-3.10%2B-blue) ![status](https://img.shields.io/badge/status-V1-green)

Synapse is an **engine that wraps a language model and fixes the failure modes that show up over long interactions** — forgetting past the context window, drifting on numbers and state, hallucinating, repeating, and losing the thread. It does this by *taking those jobs away from the model*. The model writes; a deterministic engine owns memory, math, state, and canon.

Interactive fiction (an AI "game master") is used as the **testbed**, because a long roleplay session stresses *every* one of these failure modes at once. The ideas generalize to any long‑running LLM app — agents, assistants, simulations.

---

## The problem

LLMs are excellent at language and terrible at *bookkeeping over time*:

- **They forget.** Anything past the context window is gone — bigger context only delays the cliff.
- **They drift.** Ask a model to track HP, money, dates, or inventory across hundreds of turns and the numbers wander.
- **They hallucinate.** A detail invented once gets treated as true later and compounds.
- **They repeat and lose persona** as sessions grow long.

These are not prompt‑engineering bugs; they are structural. You cannot reliably *prompt* a model into not forgetting.

## The approach

Synapse runs **two cores over the same model**, and moves every fragile job out of the model and into the engine:

```
                 ┌──────────────────────────────────────────────┐
   player input  │                  ENGINE                       │
   ───────────►  │  ┌────────────┐      apply (deterministic)    │
                 │  │  AUDITOR    │  ── stat math, inventory,     │
                 │  │ (logic core)│     currency, location, date, │
                 │  │  temp 0.1   │     events/laws ──►  PERSISTENT DB
                 │  │  JSON only  │                         │ (signed [Chk])
                 │  └─────┬──────┘                          │
                 │        │ director's briefing             │ recall + worldbook
                 │        ▼                                 ▼
                 │  ┌────────────┐   reads memory/canon, writes prose
   story  ◄──────│  │  NARRATOR   │  ◄──────────────────────────────
                 │  │(language core)│  temp 0.8, streams                  │
                 │  └────────────┘                                       │
                 └──────────────────────────────────────────────────────┘
```

- **Auditor** (logic): reads the turn, computes state changes as *deltas*, updates the database, and hands the Narrator a briefing. Outputs strict JSON, never prose.
- **Narrator** (language): writes the story from the briefing + the relevant slice of memory. Never touches numbers or state.
- **The engine** does the arithmetic, persists everything to disk, signs each turn, and decides *which* slice of the permanent record to show next.

> The model can't drift on what it no longer owns.

---

## 🎯 What it solves

| Classic LLM failure (long sessions) | How Synapse handles it | Evidence (1000‑turn run) |
|---|---|---|
| **Forgetting / limited context** | Permanent disk store + two‑lane recall (recency + relevance) surfaces old facts on demand | A hidden object planted at turn 5 was retrieved on cue at **+50, +250, +550, +950 turns** (4/4) |
| **Numeric / state drift** | Engine applies signed deltas and clamps; the model never does math | **0** out‑of‑range states; currency tracked live 0 → ~9,400 |
| **Tampering / desync** | Every turn's state carries an HMAC checksum (`[Chk]`) | **1005 / 1005 turns verified** |
| **Hallucination** | A second core audits the prose against canon (detect + self‑correct); optional *Chrysalis* quarantine keeps one‑off claims out of permanent canon until confirmed | 0 gross fabrications flagged (see honest caveat in the report) |
| **Repetition** | Per‑request nonce + an anti‑repeat guard that regenerates a verbatim repeat | **4 / 1000** near‑duplicates, **0** verbatim |
| **Persona / identity drift** | Bounded, role‑scoped prompts per core | **0** re‑introductions |
| **Instruction/language adherence** | Hard language lock; consistency auditor | **0** stray‑language characters across 1000 turns |
| **Time / world coherence** | Engine‑advanced calendar, events, timers, laws, NPC state | calendar held forward over ~3.7 in‑game years |

---

## 📊 Proof

A reproducible **1000‑turn capability run** (a Victorian‑London world, 250 turns × 4) with full per‑turn logs. Headlines: long‑range recall 4/4 on hidden objects, state integrity 1005/1005, live economy, stable calendar, zero crashes/fallbacks.

**Read the full report — including honest limitations — in [`tests/PUBLIC_REPORT.md`](tests/PUBLIC_REPORT.md).**

Every turn, verbatim — player input, unabridged narration, and the signed tracker — is in [`tests/FULL_TRANSCRIPT.md`](tests/FULL_TRANSCRIPT.md) (nothing summarized).

Limitations are stated openly there: a precision‑tuned auditor is *not* a proof of zero hallucination; recall of abstract named details is softer than recall of concrete objects/places; results are from one scenario and one model (the **engine** is the variable, not the model).

Reproduce:
```bash
python tests/soak_en_1000.py <batch 1-4>     # 250 turns per batch on a dedicated campaign
```

---

## 🧪 Why roleplay is the testbed

A single roleplay session demands, simultaneously: long‑term memory, exact numeric state, an economy, many NPCs with persistent relationships, an advancing clock/calendar, a coherent world, and free‑form natural language. That makes it a brutal, all‑at‑once stress test for the failure modes above — which is exactly why it's the proving ground. **Synapse is the engine; the game is the demonstration.**

---

## 🚀 Quick start

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp Config/Settings.json.example Config/Settings.json     # then add your API key(s)
./run_web.sh                                             # → http://127.0.0.1:8080
```
Works with **DeepSeek**, any **OpenAI‑compatible** endpoint, or **OpenRouter** — set the URL + key in `Config/Settings.json`. (Optional creator signature for `[Chk]`: copy `Config/Signature.json.example` → `Config/Signature.json`.)

---

## ⚙️ Configuration (`Config/Settings.json`)

| Key | What it does |
|---|---|
| `primary` / `secondary` | the two cores' provider `url`, `api_key`, `model` |
| `recall` | two‑lane long‑term memory retrieval (default on) |
| `narrator_audit` | second core verifies prose vs. canon (catches hallucination; +1 call/turn) |
| `audit_notify` | surface the auditor's reason inline (debugging) |
| `anti_repeat` | buffer + regenerate a turn that repeats the previous one verbatim |
| `narration_lang` | hard‑lock the output language (e.g. `"English"`); empty = follow the player |
| `ingame_date` | maintain an ISO calendar (for dated/historical worlds) |
| `web_lookup` | ground real/historical worlds via an encyclopedia lookup |
| `chrysalis` / `chrysalis_semantic` | anti‑drift canon quarantine: new facts stay *provisional* until confirmed, else fade |

---

## 🎮 Usage

Three‑page flow: **Settings → Loading → Game.** To start a story, describe in plain language: a **world**, then a **character**, then a **starting point** — then type `[start]`. In‑session commands: `[pause]` / `[resume]`. The engine writes a permanent, signed `.txt` archive of every turn under `Database/Campaigns/<name>/Events/Eternal_Logs/txt/`.

## 📁 Project layout

`web/app.py` — the engine · `Prompts/{Auditor,Narrator}/Core.txt` — the two cores' prompts · `tools/verify_chk.py` — log signature verifier · `tests/` — soak harness + the 1000‑turn report.

## 🗺️ Roadmap

- Tighten abstract/long‑range recall (NPC verbal promises)
- Calibrate Chrysalis (anti‑butterfly canon quarantine) and a stricter contradiction‑drop
- Multi‑scenario and head‑to‑head benchmarks
- Generalize the engine pattern beyond interactive fiction (agents/assistants)

## 🤝 Contributing

Issues and PRs welcome. The test harness in `tests/` is the place to add new scenarios or failure‑mode probes.

## ⚠️ Security

Never commit `Config/Settings.json`, `Config/Keys/`, or `Config/Signature.json` (already in `.gitignore`). Rotate any key that has ever touched disk before publishing.

## 📄 License

MIT — see [`LICENSE`](LICENSE).

*Two cores over one model. The model writes; the engine remembers.*
