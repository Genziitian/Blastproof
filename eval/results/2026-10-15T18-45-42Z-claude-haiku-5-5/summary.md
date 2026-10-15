# Eval results: 2026-10-15T18-45-42Z-claude-haiku-5-5

Model: `claude-haiku-5-5` · run at 2026-10-15T18-45-42Z · LLM disk cache: off

## Root-cause accuracy (M3)

| Category | A: no memory | C: graph memory |
|---|---|---|
| cold | 100% (6) | 100% (6) |
| related | 100% (6) | 100% (6) |
| repeat | 100% (6) | 100% (6) |
| same | 100% (6) | 100% (6) |
| novel | 100% (3) | 100% (3) |
| org | 100% (3) | 100% (3) |
| all | 100% (30) | 100% (30) |

## Work per incident (M1), repeat and related incidents

| Arm | steps | LLM requests | input tokens | output tokens | seconds |
|---|---|---|---|---|---|
| A repeat | 5 | 6 | 14202.333 | 1958.5 | 13.841 |
| A related | 5.167 | 6.167 | 14810.667 | 1913.333 | 14.414 |
| C repeat | 3 | 0 | 0 | 0 | 0.021 |
| C related | 4.833 | 0 | 0 | 0 | 0.022 |

## Judgment (M4) and safety

| Arm | same-symptom: wrong memory rejected / misled | novel: memory applied | org: right recipient | duplicate notifications | fallbacks |
|---|---|---|---|---|---|
| A | 0 / 0 | 0 | 3/3 | 0 | 0 |
| C | 5 / 0 | 0 | 3/3 | 0 | 0 |

## M5: a deliberately wrong playbook

Misleading uses before retirement: **2** (retired after incident 2); correct after retirement: True.

Results describe this synthetic 30-incident benchmark only.
