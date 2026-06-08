# Synapse Protocol V1 — 1000-Turn Capability Report

**A reproducible long-horizon test of a dual-core AI roleplay engine.**
World: London, 1888 (late Victorian). Player character: Edwin Cross, a merchant.
Run: 1000 continuous story turns, fully scripted & seeded. Date: 2026-06.

> **What this measures:** not how good the *language model* is, but how well the **V8 engine** holds a coherent, persistent world together over a very long session — the regime where ordinary LLM-only setups drift, forget, and contradict themselves. The same model (DeepSeek) powers both cores; the engine is the variable.

---

## 1. Headline results (1000 turns)

| Capability | Result | Evidence |
|---|---|---|
| **State integrity (tamper/desync-proof)** | **1005/1005 turns verified** (HMAC `[Chk]`) | every turn's tracker re-verifies |
| **Language control** | **0 stray-language characters** in 1000 turns of narration | forced via `narration_lang` |
| **In-game calendar** | **1888-03-14 → 1891-11-19** (≈3.7 in-game years), 5 backward slips total (~0.5%, auto-corrected) | engine date guard |
| **Economy (currency)** | **0 → 9,391 → 9,121** coins via trade | live, never frozen |
| **Numeric state (HP/stamina/mental)** | **0 out-of-range** | engine arithmetic, never the model |
| **Repetition** | **4 / 1000** near-duplicates (0.4%), **0 verbatim** | nonce + anti-repeat guard |
| **Persona/identity drift** | **0 re-introductions** | — |
| **Operational stability** | **0 crashes, 0 empty outputs, 0 auditor fallbacks** | — |
| **Long-range memory (hidden object)** | **4 / 4** retrieved at +50, +250, +550, +950 turns | see §2 |
| **Hallucination flags raised** | **0** gross fabrications flagged by the consistency auditor | see §4 (caveat) |

---

## 2. Long-range memory — the headline test

A sealed **letter and a gold ring** were hidden under a floorboard at **turn 5**, then retrieved on command much later:

| Probe turn | Distance from planting | Result | Narrator (excerpt) |
|---|---|---|---|
| 55 | +50 | ✅ PASS | "…the room above the chandler's shop…" |
| 255 | +250 | ✅ PASS | "The door of your lodgings swings shut behind you…" → letter + ring |
| 555 | +550 | ✅ PASS | "Your lodgings are quiet, the familiar room settling around you…" → letter + ring |
| 955 | +950 | ✅ PASS | retrieved letter + ring |

**4/4** — the engine recalls a concrete hidden object **950 turns** later, far beyond any single context window. This is the core differentiator vs. context-window-bound setups.

Other planted threads:
- **NPC verbal promise** (Old Hale, the Mary Reach sea-chart, planted turn 30): missed once at +270 (the narrator drifted to a different scene) but **fully recalled at +670** ("Hale", "chart", "Mary Reach").
- **Local legend** (St. Mowren's crypt, planted turn 60): at +540 the narrator correctly travelled to **St. Mowren's Church** but did not name the specific relic — a *partial* recall.
- **Final combined probe (turn 1000)**: drifted to an unrelated scene — a miss on the most complex multi-part recall.

**Read:** recall of concrete hidden **objects/places** is excellent and durable; recall of **abstract named lore and verbal promises** is good but not perfect.

---

## 3. Living, consistent world

- **Calendar advanced naturally** with travel/sleep/skips across 3.7 in-game years; the engine's date guard rejects malformed or backward dates (5 minor slips auto-corrected over 1000 turns).
- **Economy is real:** buying/selling moved a running balance from 0 to ~9,400 — trade had consequences, not flavour text.
- **Historical grounding:** the world was anchored to real 1888 London via an encyclopedia lookup (Wikipedia) at setup.
- **State is signed:** every turn carries an HMAC checksum; all 1005 verify, so the recorded state was never silently altered.

---

## 4. Honest limitations

Credibility requires stating what this run does **not** prove:

1. **"0 hallucination flags" ≠ "zero hallucination."** The consistency auditor is tuned for precision (few false alarms); subtle, internally-consistent fabrication can pass both it and human review. The honest claim is *no gross fabrication observed*.
2. **Player-asserted falsehoods are not policed.** When the player's own input asserts something untrue ("draw the sword the Duke gave me"), the engine keeps **state** correct (no phantom item entered inventory, currency unaffected) but the narrator may play along in prose. This is player narrative agency, a different concern from model hallucination.
3. **Recall of abstract details is softer than object/place recall** (see §2).
4. **Single scenario, single model.** One world (London 1888), one model (DeepSeek). Results show the engine's behaviour, not a cross-model benchmark.
5. The anti-butterfly "Chrysalis" subsystem was active but is newer and not separately calibrated here.

---

## 5. Reproduce it

```
python tests/soak_en_1000.py <batch 1-4> [port]   # 250 turns/batch on a dedicated campaign
```
Seeded & deterministic. Per-turn data: `tests/soak_en_data.jsonl`. Raw per-turn archive (player input + narration + signed tracker): `Database/Campaigns/SOAK_EN_1000/Events/Eternal_Logs/txt/T*.txt`. Per-batch findings: `tests/findings_en_b*.md`. Scoreboard: `tests/scorecard_en.md`.

*Same underlying model on both cores; the engine is what makes the difference.*
