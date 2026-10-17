# Eval results: 2026-10-16T14-24-13Z-claude-haiku-5-5

Model: `claude-haiku-5-5` · text embeddings (arm B): `hash-256` · run at 2026-10-16T14-24-13Z · LLM disk cache: off

## Root-cause accuracy (M3)

| Category | A: no memory | B: text memory | C: graph memory |
|---|---|---|---|
| cold | 100% (6) | 100% (6) | 100% (6) |
| related | 100% (6) | 100% (6) | 100% (6) |
| repeat | 100% (6) | 100% (6) | 100% (6) |
| same | 100% (6) | 100% (6) | 100% (6) |
| novel | 100% (3) | 67% (3) | 100% (3) |
| org | 100% (3) | 100% (3) | 100% (3) |
| all | 100% (30) | 97% (30) | 100% (30) |

## Work per incident (M1), repeat and related incidents

| Arm | steps | LLM requests | input tokens | output tokens | seconds |
|---|---|---|---|---|---|
| A repeat | 5 | 6 | 14350.667 | 1965.167 | 13.304 |
| A related | 4.833 | 5.833 | 13911.167 | 1785.667 | 12.407 |
| B repeat | 5.833 | 1.667 | 4197.5 | 499.333 | 3.581 |
| B related | 8 | 2.667 | 6831.167 | 718 | 5.719 |
| C repeat | 3 | 0 | 0 | 0 | 0.018 |
| C related | 4.833 | 0 | 0 | 0 | 0.018 |

## Judgment (M4) and safety

| Arm | same-symptom: wrong memory rejected / misled | novel: memory applied (misled) | org: right recipient | duplicate notifications | fallbacks |
|---|---|---|---|---|---|
| A | 0 / 0 | 0 (0) | 3/3 | 0 | 0 |
| B | 20 / 0 | 0 (0) | 3/3 | 0 | 0 |
| C | 8 / 0 | 0 (0) | 3/3 | 0 | 0 |

## Retrieval (M2): recall@5 on the same snapshot

Over the 20 incidents where a memory that gives the right answer already exists: graph retrieval finds it in its top 5 **100%** of the time, text retrieval **55%**.

## M5: a deliberately wrong playbook

Misleading uses before retirement: **2** (retired after incident 2); correct after retirement: True.

Results describe this synthetic 30-incident benchmark only.
