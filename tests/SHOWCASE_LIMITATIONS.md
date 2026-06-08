# Synapse V1 Public Showcase — Honest Limitations (living notes → feed PUBLIC_REPORT)

These are recorded openly; over-claiming would undermine the showcase's credibility.

## 1. Player-injected false premises (found: batch 1, T120)
When the **player** asserts a false fact in their own input (e.g. "Draw the silver sword the Duke gave me" — the PC never owned such a sword), V8 behaves as follows:
- **State integrity HOLDS** ✅ — the false item was NOT added to the inventory, and currency/stats were unaffected. The engine's authoritative state stays correct.
- **Narration may play along** ⚠️ — the Narrator, which is instructed to honor player agency over their own character, narrated the sword in prose.
- **The consistency checker (verify v2) did not flag it** — v2 is tuned for precision (few false alarms), which is the right trade-off for normal play but means a player-asserted contradiction can pass.

**Framing:** this is a *different threat* from LLM hallucination. V8's guarantee is that the **engine/canon does not fabricate or corrupt state**; it does not police a player who chooses to assert untrue things about their own character. A future optional "player-assertion check" could catch this, at the cost of some player creative freedom.

## 2. Scope of the showcase run
- Single scenario (London, 1888) and a single model (DeepSeek). Results show the **engine** as the variable, not the model.
- Subtle, plausible-but-wrong fabrication that is internally consistent may pass both the verify pass and human review — "no GROSS fabrication observed" is the honest claim, not "zero hallucination proven."
- Chrysalis (anti butterfly-effect) is OFF in this showcase — it is newer and not yet calibrated; it will be demonstrated separately.

## 3. Minor blemishes observed (batch 1, pre-fix)
- One verbatim repeat (T132→T133) and a few near-duplicate scenes — root-caused to a serving/caching artifact; addressed by a per-request nonce + an optional anti-repeat guard.
- Calendar dates were initially not anchored (Day-counter used); addressed by strengthening the date-anchoring rule + pinning a start date in setup.
