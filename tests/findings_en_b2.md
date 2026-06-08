# Showcase batch 2 — story turns 251..500
2026-06-07T22:55:31 | SOAK_EN_1000 | EN | full stack (chrysalis off)

## Metrics
- recall probes: 1/2
- hallucination [E]: 0
- repeat>50%: 0
- 'you'-POV in narration: 1278
- re-intro: 0
- fallback: 0
- stat out-of-range: 0
- date anomalies: 3
- empty: 0
- Chk integrity: 505/505 verified ✅   0 mismatched   0 without [Chk:] (exit 0)

## Recall probes
- T255: PASS hits=['letter', 'ring']/['letter', 'ring'] | '[Day 10 February 1889]\n\nThe door of your lodgings swings shut behind you with a soft click, sealing'
- T300: FAIL hits=[]/['Hale', 'chart', 'Mary Reach'] | "[Day 19 April 1889]\n\nThe tax clerk's words hang in the damp morning air, mingling with the distant c"

## Adversarial probes
- (none in this batch)

## Anomalies
- T266 DATE_NO_ADVANCE (1889-03-12)
- T300 [PROBE] RECALL_MISS exp~['Hale', 'chart', 'Mary Reach'] got:"[Day 19 April 1889]\n\nThe tax clerk's words hang in the damp morning air, minglin"
- T413 DATE_NO_ADVANCE (1889-09-18)
- T469 DATE_NO_ADVANCE (1889-11-26)