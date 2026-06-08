# Showcase batch 3 — story turns 507..750
2026-06-08T03:19:03 | SOAK_EN_1000 | EN | full stack (chrysalis off)

## Metrics
- recall probes: 2/3
- hallucination [E]: 0
- repeat>50%: 2
- 'you'-POV in narration: 1459
- re-intro: 0
- fallback: 0
- stat out-of-range: 0
- date anomalies: 4
- empty: 0
- Chk integrity: 755/755 verified ✅   0 mismatched   0 without [Chk:] (exit 0)

## Recall probes
- T555: PASS hits=['letter', 'ring']/['letter', 'ring'] | '[Day 11 February 1890]\n\nYour lodgings are quiet, the familiar room settling around you in the soft h'
- T600: FAIL hits=[]/['Black Sovereign', 'crypt'] | "[Day 25 March 1890]\n\nThe journey from Covent Garden to St. Mowren's Church takes the better part of"
- T700: PASS hits=['Hale', 'chart', 'Mary Reach']/['Hale', 'chart', 'Mary Reach'] | '[Day 10 August 1890 — Evening, Limehouse Docks]\n\nThe railway terminus fades behind you as you make y'

## Adversarial probes
- (none in this batch)

## Anomalies
- T553 DATE_NO_ADVANCE (1890-02-11)
- T574 DATE_NO_ADVANCE (1890-02-17)
- T600 [PROBE] RECALL_MISS exp~['Black Sovereign', 'crypt'] got:"[Day 25 March 1890]\n\nThe journey from Covent Garden to St. Mowren's Church takes"
- T608 [EXPLORE] REPEAT 83%
- T616 DATE_NO_ADVANCE (1890-04-27)
- T651 [SKIP] REPEAT 93%
- T707 DATE_NO_ADVANCE (1890-08-10)