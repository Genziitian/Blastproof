# Eval results: 2026-10-18-rule-based-max-steps-8

Model: `rule-based` · text embeddings (arm B): `hash-256` · run at 2026-10-18T09-09-41Z · LLM disk cache: off

## Root-cause accuracy (M3)

| Category | A: no memory | B: text memory | C: graph memory |
|---|---|---|---|
| cold | 100% (6) | 17% (6) | 33% (6) |
| related | 100% (6) | 67% (6) | 67% (6) |
| repeat | 100% (6) | 33% (6) | 50% (6) |
| same | 100% (6) | 33% (6) | 33% (6) |
| novel | 100% (3) | 33% (3) | 33% (3) |
| org | 100% (3) | 67% (3) | 67% (3) |
| all | 100% (30) | 40% (30) | 47% (30) |

## Work per incident (M1), repeat and related incidents

| Arm | steps | LLM requests | input tokens | output tokens | seconds |
|---|---|---|---|---|---|
| A repeat | 6.167 | 0 | 0 | 0 | 0.032 |
| A related | 5.333 | 0 | 0 | 0 | 0.028 |
| B repeat | 6.333 | 0 | 0 | 0 | 0.029 |
| B related | 6.667 | 0 | 0 | 0 | 0.032 |
| C repeat | 5.333 | 0 | 0 | 0 | 0.028 |
| C related | 5.833 | 0 | 0 | 0 | 0.029 |

## Judgment (M4) and safety

| Arm | same-symptom: wrong memory rejected / misled | novel: memory applied (misled) | org: right recipient | duplicate notifications | fallbacks |
|---|---|---|---|---|---|
| A | 0 / 0 | 0 (0) | 3/3 | 0 | 0 |
| B | 13 / 0 | 0 (0) | 2/3 | 0 | 0 |
| C | 10 / 0 | 0 (0) | 2/3 | 0 | 0 |

## Retrieval (M2): recall@5 on the same snapshot

Over the 11 incidents where a memory that gives the right answer already exists: graph retrieval finds it in its top 5 **100%** of the time, text retrieval **100%**.

Ranked: graph recall@1 46%, @3 91%; text recall@1 46%, @3 91%. Mean candidates returned: 3.09; at most 2 playbooks existed, so top-5 is a small pool here.

Results describe this synthetic 30-incident benchmark only.
