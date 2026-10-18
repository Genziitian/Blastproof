# Eval results: 2026-10-18-rule-based-ranked

Model: `rule-based` · text embeddings (arm B): `hash-256` · run at 2026-10-18T09-09-37Z · LLM disk cache: off

## Root-cause accuracy (M3)

| Category | A: no memory | B: text memory | C: graph memory |
|---|---|---|---|
| cold | 100% (6) | 100% (6) | 100% (6) |
| related | 100% (6) | 100% (6) | 100% (6) |
| repeat | 100% (6) | 100% (6) | 100% (6) |
| same | 100% (6) | 100% (6) | 100% (6) |
| novel | 100% (3) | 100% (3) | 100% (3) |
| org | 100% (3) | 100% (3) | 100% (3) |
| all | 100% (30) | 100% (30) | 100% (30) |

## Work per incident (M1), repeat and related incidents

| Arm | steps | LLM requests | input tokens | output tokens | seconds |
|---|---|---|---|---|---|
| A repeat | 6.167 | 0 | 0 | 0 | 0.03 |
| A related | 5.333 | 0 | 0 | 0 | 0.028 |
| B repeat | 6.333 | 0 | 0 | 0 | 0.04 |
| B related | 7.5 | 0 | 0 | 0 | 0.04 |
| C repeat | 3 | 0 | 0 | 0 | 0.028 |
| C related | 4.833 | 0 | 0 | 0 | 0.03 |

## Judgment (M4) and safety

| Arm | same-symptom: wrong memory rejected / misled | novel: memory applied (misled) | org: right recipient | duplicate notifications | fallbacks |
|---|---|---|---|---|---|
| A | 0 / 0 | 0 (0) | 3/3 | 0 | 0 |
| B | 23 / 0 | 0 (0) | 3/3 | 0 | 0 |
| C | 5 / 0 | 0 (0) | 3/3 | 0 | 0 |

## Retrieval (M2): recall@5 on the same snapshot

Over the 21 incidents where a memory that gives the right answer already exists: graph retrieval finds it in its top 5 **100%** of the time, text retrieval **48%**.

Ranked: graph recall@1 29%, @3 62%; text recall@1 10%, @3 29%. Mean candidates returned: 5; at most 3 playbooks existed, so top-5 is a small pool here.

## M5: a deliberately wrong playbook

Misleading uses before retirement: **2** (retired after incident 2); correct after retirement: True.

Results describe this synthetic 30-incident benchmark only.
