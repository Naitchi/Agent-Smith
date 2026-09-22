# Benchmark Report

## 1. Setup

**Models (5, free tiers only, two providers).**

| model | provider | why it is in the benchmark |
|---|---|---|
| `qwen/qwen3.8-27b` | Groq | strongest open model on Groq, fast (~0.5 s / request) |
| `openai/gpt-oss-120b` | Groq | largest model available on a free tier, native tool-calling habits |
| `gemini-3.5-flash` | Google AI Studio | mid-size Gemini, 1M context |
| `gemini-3.5-flash-lite` | Google AI Studio | cheapest Gemini, highest free quota |
| `gemini-3.6-flash` | Google AI Studio | most recent Gemini available when the benchmark started |

Mistral (`codestral-2508`, `ministral-*`) was added to the fallback list later and is used in the
prompt ablation (section 5) and in the exam-style runs, but not in the 5 x 3 grid below.

**Tasks (3 SWE-bench Verified instances).**

| task | repository | why |
|---|---|---|
| `sympy__sympy-14711` | sympy | `sum()` of vectors fails on `0`; small single-file fix, fast test file |
| `sympy__sympy-13480` | sympy | `coth(log(tan(x)))` raises a `NameError`; one-line fix, **in the exam pool** |
| `pydata__xarray-4629` | xarray | `merge(combine_attrs="override")` shares the attrs dict; other code base, **in the exam pool** |

All three are "< 15 min fix" issues with test suites that run in seconds, so a failure measures
the agent (exploration, editing, discipline) rather than the 900 s budget.

**Protocol.** `scripts/run_benchmark.sh` runs every model x task pair with the subject's limits
(30 iterations, 300k / 10k tokens, 900 s under `timeout`), then validates the patch with the
moulinette's own `validate()` (`scripts/validate_swebench.py`, which only patches the file copy for
rootless Docker). `NO_FALLBACK=1` disables model switching, so each cell measures exactly one
model. A run that dies because the provider is unavailable (quota, overload) is marked
**INDISPO**, gets no verdict and is retried on the next launch.

- **v1**: first version (regex extraction, immediate abort on provider errors, backoff on 429).
- **v3**: current version (extraction without regex, three 20 s waits on the same model before
  giving up, handover note, last-call warning added afterwards).

## 2. Results

<!-- AUTO:v1:START -->
### Results (v1)

`final_answer`: no = the agent did not submit by itself; the CLI returned the container's patch (`get_patch()`), which is what was validated. INDISPO = provider unavailable (quota or overload).

| model | task | verdict | final_answer | iterations | tokens in | tokens out | time (s) |
|---|---|---|---|---|---|---|---|
| gemini-3.5-flash | pydata__xarray-4629 | INDISPO | no | 2 | 7378 | 123 | 85 |
| gemini-3.5-flash | sympy__sympy-13480 | INDISPO | no | 0 | 0 | 0 | 189 |
| gemini-3.5-flash | sympy__sympy-14711 | INDISPO | no | 3 | 4147 | 216 | 228 |
| gemini-3.5-flash-lite | pydata__xarray-4629 | INDISPO | no | 16 | 119774 | 395 | 44 |
| gemini-3.5-flash-lite | sympy__sympy-13480 | PASS | no | 30 | 186990 | 842 | 179 |
| gemini-3.5-flash-lite | sympy__sympy-14711 | PASS | no | 30 | 271160 | 2068 | 143 |
| gemini-3.6-flash | pydata__xarray-4629 | INDISPO | no | 0 | 0 | 0 | 20 |
| gemini-3.6-flash | sympy__sympy-13480 | INDISPO | no | 0 | 0 | 0 | 20 |
| gemini-3.6-flash | sympy__sympy-14711 | INDISPO | no | 12 | 104146 | 2191 | 125 |
| openai/gpt-oss-120b | pydata__xarray-4629 | FAIL | no | 0 | 0 | 0 | 1 |
| openai/gpt-oss-120b | sympy__sympy-13480 | PASS | yes | 13 | 28223 | 3005 | 167 |
| openai/gpt-oss-120b | sympy__sympy-14711 | FAIL | no | 0 | 0 | 0 | 2 |
| qwen/qwen3.8-27b | pydata__xarray-4629 | PASS | no | 5 | 18591 | 265 | 108 |
| qwen/qwen3.8-27b | sympy__sympy-13480 | PASS | yes | 4 | 9677 | 195 | 25 |
| qwen/qwen3.8-27b | sympy__sympy-14711 | PASS | no | 12 | 41251 | 899 | 301 |

### Provider reliability (v1)

Average time = mean `request_time_ms` of the steps. Retries = sum of step `retries` (429, network, empty answers). Useful requests = steps / requests sent. Availability = runs not INDISPO / runs launched.

| model | average time / request (s) | retries | useful requests | availability |
|---|---|---|---|---|
| gemini-3.5-flash | 20.1 | 1 | 5/34 | 0/3 |
| gemini-3.5-flash-lite | 3.5 | 21 | 76/116 | 2/3 |
| gemini-3.6-flash | 6.7 | 15 | 12/87 | 0/3 |
| openai/gpt-oss-120b | 0.9 | 45 | 13/64 | 3/3 |
| qwen/qwen3.8-27b | 0.5 | 100 | 21/127 | 3/3 |

### Intermediary metrics (v1)

First contact = first step whose code names a file of the final patch; first edit = first `edit_file` on that file. Discipline = iterations between the first passing `run_tests()` and `final_answer` (ideal 0; "?" when the test summary was truncated).

| model | task | first contact | first edit | discipline |
|---|---|---|---|---|
| gemini-3.5-flash | pydata__xarray-4629 | - | - | - |
| gemini-3.5-flash | sympy__sympy-13480 | - | - | - |
| gemini-3.5-flash | sympy__sympy-14711 | - | - | - |
| gemini-3.5-flash-lite | pydata__xarray-4629 | 2 | 3 | - |
| gemini-3.5-flash-lite | sympy__sympy-13480 | 2 | 5 | - |
| gemini-3.5-flash-lite | sympy__sympy-14711 | 4 | 17 | - |
| gemini-3.6-flash | pydata__xarray-4629 | - | - | - |
| gemini-3.6-flash | sympy__sympy-13480 | - | - | - |
| gemini-3.6-flash | sympy__sympy-14711 | - | - | - |
| openai/gpt-oss-120b | pydata__xarray-4629 | - | - | - |
| openai/gpt-oss-120b | sympy__sympy-13480 | 1 | 4 | ? |
| openai/gpt-oss-120b | sympy__sympy-14711 | - | - | - |
| qwen/qwen3.8-27b | pydata__xarray-4629 | 1 | 4 | - |
| qwen/qwen3.8-27b | sympy__sympy-13480 | 1 | 2 | ? |
| qwen/qwen3.8-27b | sympy__sympy-14711 | 3 | 11 | - |
<!-- AUTO:v1:END -->

<!-- AUTO:v3:START -->
### Results (v3)

`final_answer`: no = the agent did not submit by itself; the CLI returned the container's patch (`get_patch()`), which is what was validated. INDISPO = provider unavailable (quota or overload).

| model | task | verdict | final_answer | iterations | tokens in | tokens out | time (s) |
|---|---|---|---|---|---|---|---|
| gemini-3.5-flash | pydata__xarray-4629 | INDISPO | no | 0 | 0 | 0 | 68 |
| gemini-3.5-flash | sympy__sympy-13480 | INDISPO | no | 0 | 0 | 0 | 66 |
| gemini-3.5-flash | sympy__sympy-14711 | INDISPO | no | 1 | 1167 | 52 | 77 |
| gemini-3.5-flash-lite | pydata__xarray-4629 | INDISPO | no | 2 | 3846 | 88 | 212 |
| gemini-3.5-flash-lite | sympy__sympy-13480 | PASS | no | 30 | 139100 | 517 | 498 |
| gemini-3.5-flash-lite | sympy__sympy-14711 | FAIL | no | 23 | 272014 | 4656 | 211 |
| gemini-3.6-flash | pydata__xarray-4629 | INDISPO | no | 0 | 0 | 0 | 67 |
| gemini-3.6-flash | sympy__sympy-13480 | INDISPO | no | 0 | 0 | 0 | 66 |
| gemini-3.6-flash | sympy__sympy-14711 | INDISPO | no | 0 | 0 | 0 | 126 |
| openai/gpt-oss-120b | pydata__xarray-4629 | INDISPO | no | 2 | 3172 | 124 | 65 |
| openai/gpt-oss-120b | sympy__sympy-13480 | FAIL | yes | 3 | 3771 | 1036 | 5 |
| openai/gpt-oss-120b | sympy__sympy-14711 | PASS | no | 28 | 127993 | 7151 | 888 |
| qwen/qwen3.8-27b | pydata__xarray-4629 | PASS | yes | 5 | 13873 | 249 | 67 |
| qwen/qwen3.8-27b | sympy__sympy-13480 | PASS | yes | 4 | 9677 | 195 | 38 |
| qwen/qwen3.8-27b | sympy__sympy-14711 | PASS | no | 23 | 91268 | 2398 | 749 |

### Provider reliability (v3)

Average time = mean `request_time_ms` of the steps. Retries = sum of step `retries` (429, network, empty answers). Useful requests = steps / requests sent. Availability = runs not INDISPO / runs launched.

| model | average time / request (s) | retries | useful requests | availability |
|---|---|---|---|---|
| gemini-3.5-flash | 11.0 | 2 | 1/61 | 0/3 |
| gemini-3.5-flash-lite | 11.4 | 4 | 55/63 | 2/3 |
| gemini-3.6-flash | - | 0 | 0/57 | 0/3 |
| openai/gpt-oss-120b | 1.2 | 210 | 33/268 | 2/3 |
| qwen/qwen3.8-27b | 0.6 | 175 | 32/216 | 3/3 |

### Intermediary metrics (v3)

First contact = first step whose code names a file of the final patch; first edit = first `edit_file` on that file. Discipline = iterations between the first passing `run_tests()` and `final_answer` (ideal 0; "?" when the test summary was truncated).

| model | task | first contact | first edit | discipline |
|---|---|---|---|---|
| gemini-3.5-flash | pydata__xarray-4629 | - | - | - |
| gemini-3.5-flash | sympy__sympy-13480 | - | - | - |
| gemini-3.5-flash | sympy__sympy-14711 | - | - | - |
| gemini-3.5-flash-lite | pydata__xarray-4629 | - | - | - |
| gemini-3.5-flash-lite | sympy__sympy-13480 | 2 | 3 | - |
| gemini-3.5-flash-lite | sympy__sympy-14711 | - | - | - |
| gemini-3.6-flash | pydata__xarray-4629 | - | - | - |
| gemini-3.6-flash | sympy__sympy-13480 | - | - | - |
| gemini-3.6-flash | sympy__sympy-14711 | - | - | - |
| openai/gpt-oss-120b | pydata__xarray-4629 | - | - | - |
| openai/gpt-oss-120b | sympy__sympy-13480 | - | - | ? |
| openai/gpt-oss-120b | sympy__sympy-14711 | 7 | 8 | - |
| qwen/qwen3.8-27b | pydata__xarray-4629 | 2 | 3 | 0 |
| qwen/qwen3.8-27b | sympy__sympy-13480 | 1 | 2 | ? |
| qwen/qwen3.8-27b | sympy__sympy-14711 | 3 | 20 | - |
<!-- AUTO:v3:END -->

## 3. Provider reliability

- **Groq is fast but rate-limited per minute.** Requests take 0.5 to 1.2 s, but in v3 only
  32 / 216 (qwen) and 33 / 268 (gpt-oss-120b) requests produced a step: the rest were 429
  answers absorbed by key rotation and waits. Its 413 errors (tokens-per-minute limit of 7000
  on qwen) are now handled by shrinking the history, then switching model.
- **Gemini is slower and limited per day.** Requests take 3.5 to 20 s. `gemini-3.5-flash` and
  `gemini-3.6-flash` were unavailable in 6 of 6 v3 runs: the error is
  `GenerateRequestsPerDayPerProjectPerModel-FreeTier` on all five keys, because the keys belong to
  the same Google project and therefore share one daily quota. Waiting cannot fix a daily quota.
- **`gemini-3.5-flash-lite`** is the most available Gemini model (2 / 3 runs completed in v1 and v3).
- **Mistral** answered every call during the checks and completed 17 of 30 steps of an exam-style
  run on `django__django-15741` after all Groq and Gemini models had failed (validated PASS).

Key rotation works (keys are cycled on 429 and reset on every model switch), but it only adds
capacity when keys come from different projects or accounts.

## 4. Intermediary metrics

- **First contact** with a file of the final patch is early for qwen (step 1 to 3): the prompt's
  "search, then read" method works. gpt-oss-120b needed 7 steps on `sympy-14711`.
- **First edit** varies much more (step 2 to 20): on `sympy-14711` both qwen and gpt-oss-120b
  spent many steps reading and testing before editing.
- **Discipline** (iterations between the first passing `run_tests()` and `final_answer`) is only
  measurable where the agent submitted by itself. qwen scored the ideal **0** on `xarray-4629`.
  Most other runs never called `final_answer` and hit the iteration or token limit even though the
  patch was already correct; this is why a last-call warning was added (the model is told when
  2 iterations or 20 % of the input budget remain).

## 5. Ablation

**Change tested: vague system prompt vs explicit system prompt.** Same 5 MBPP tasks (drawn at random
from the moulinette), same models, only the system prompt changes. Runs are in
`BENCHMARK/ablation_prompt/`, validated with `moulinette_eval validate mbpp`, `NO_FALLBACK=1`.

- *vague* = `SYSTEM_PROMPT`: "write Python in a ```py block, print values, call final_answer".
- *explicit* = `SYSTEM_PROMPT_MBPP`: one Thought + one code block, keep the source in a variable,
  run `run_tests(code=src)`, submit only after seeing `"success": true`, fix only what the failing
  assertion shows, plus a full two-turn example.

| model | prompt | tasks passed | submitted `final_answer` | avg iterations | avg tokens in | avg tokens out |
|---|---|---|---|---|---|---|
| qwen3.8-27b | vague | 5/5 | 5/5 | 2.8 | 1441 | 253 |
| qwen3.8-27b | explicit | 5/5 | 5/5 | 2.2 | 1708 | 180 |
| codestral-2508 | vague | 1/5 | 4/5 | 3.8 | 2509 | 630 |
| codestral-2508 | explicit | **5/5** | 5/5 | 2.4 | 1848 | 142 |

- For **codestral** the explicit prompt is decisive: with the vague prompt it submitted 4 answers
  but only 1 was correct, because it called `final_answer` without running the tests. The rule
  "submit only after seeing success" turns 1/5 into 5/5.
- For **qwen** both prompts solve everything; the explicit one needs fewer iterations (2.2 vs 2.8)
  and fewer output tokens, for ~270 more input tokens per task (the longer prompt is re-sent at
  every request), well within the 6000-token MBPP budget.

v1 vs v3 is not a clean ablation (several changes at once), but it shows the effect of waiting on
the same model instead of aborting on the first 429 / 503: qwen stayed at 3/3 and submitted one
more task by itself (`xarray-4629`, discipline 0).

## 6. Conclusions

- **Kept as first choice: `qwen/qwen3.8-27b`** - 6 / 6 PASS over v1 and v3, fast, early first
  contact. It is first in `AUTHORIZED_LLM`, the fallback order.
- **Kept as second choice: `openai/gpt-oss-120b`** - solves tasks (PASS on `sympy-14711`), but
  often answers with native tool calls that Groq rejects; `rejected_generation` recovers them as
  `<tool_call>` blocks. Heavily rate-limited (210 retries in v3).
- **Kept as fallback: `gemini-3.5-flash-lite`** - most available Gemini model, 3 PASS / 1 FAIL
  over the runs it completed, but slow and prone to filling the input budget.
- **Not usable in practice today: `gemini-3.5-flash`, `gemini-3.6-flash`** - no completed run in
  v3 because the shared daily quota is always exhausted. They stay in the fallback list, after
  Groq, in case the quota is available.
- **Mistral `codestral-2508`** is a strong last resort: 5/5 on MBPP with the explicit prompt and
  it rescued an exam-style SWE-bench run.
- **Main lever left:** API keys from separate projects/accounts (to multiply quotas), since most
  failed cells are INDISPO, not FAIL.
