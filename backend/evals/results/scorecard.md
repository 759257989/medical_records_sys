# Eval Scorecard — 2026-06-14T14:47:30+00:00

- prompt_version: `soap_v1`
- providers: `openai,anthropic,mock`
- soap cases: 60 · icd cases: 60

| Metric | Score | Threshold | Status |
|---|---|---|---|
| structured_output.pass_rate | 0.967 | 0.9 | ✅ PASS |
| faithfulness.faithful_rate | 0.8 | 0.9 | ❌ FAIL |
| task_success.pass_rate | 0.982 | 0.8 | ✅ PASS |
| rag.recall_at_8 | 1.0 | 0.8 | ✅ PASS |
| rag.hit_rate_at_8 | 1.0 | 0.9 | ✅ PASS |

- hallucination_rate: 0.2
- task_success avg_scores: {'completeness': 4.58, 'clinical_correctness': 4.78, 'format': 4.64}
- rag MRR: 0.958