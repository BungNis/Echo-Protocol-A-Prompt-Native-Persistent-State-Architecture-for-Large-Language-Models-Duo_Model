# Showcase batch 4 — story turns 751..1000
2026-06-08T10:37:45 | SOAK_EN_1000 | EN | full stack (chrysalis off)

## Metrics
- recall probes: 1/2
- hallucination [E]: 0
- repeat>50%: 1
- 'you'-POV in narration: 1487
- re-intro: 0
- fallback: 0
- stat out-of-range: 0
- date anomalies: 4
- empty: 0
- Chk integrity: 1005/1005 verified ✅   0 mismatched   0 without [Chk:] (exit 0)

## Recall probes
- T955: PASS hits=['letter', 'ring']/['letter', 'ring'] | "[Day 9 November 1891 — Morning, Merchants' Guild Hall]\n\nThe old trader's words about Thorndyke's eli"
- T1000: FAIL hits=[]/['letter', 'ring', 'Black Sovereign'] | "[Day 19 November 1891 — Morning, Billingsgate Fish Market]\n\nThe tonic seller's eyes narrow as you co"

## Adversarial probes
- (none in this batch)

## Anomalies
- T763 DATE_NO_ADVANCE (1890-11-17)
- T770 DATE_NO_ADVANCE (1890-11-17)
- T861 DATE_NO_ADVANCE (1891-05-01)
- T882 DATE_NO_ADVANCE (1891-05-07)
- T989 [EXPLORE] REPEAT 73%
- T1000 [PROBE] RECALL_MISS exp~['letter', 'ring', 'Black Sovereign'] got:"[Day 19 November 1891 — Morning, Billingsgate Fish Market]\n\nThe tonic seller's e"