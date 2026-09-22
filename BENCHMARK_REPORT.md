# Benchmark Report

## 1. Setup

## 2. Results

<!-- AUTO:v1:START -->
### Resultats (v1)

`final_answer` : non = l'agent n'a pas soumis lui-meme ; la CLI a rendu le patch du conteneur (`get_patch()`), c'est lui qui a ete valide.

| modele | tache | verdict | final_answer | iterations | tokens in | tokens out | temps (s) |
|---|---|---|---|---|---|---|---|
| gemini-3.5-flash | pydata__xarray-4629 | INDISPO | non | 2 | 7378 | 123 | 85 |
| gemini-3.5-flash | sympy__sympy-13480 | INDISPO | non | 0 | 0 | 0 | 189 |
| gemini-3.5-flash | sympy__sympy-14711 | INDISPO | non | 3 | 4147 | 216 | 228 |
| gemini-3.5-flash-lite | pydata__xarray-4629 | INDISPO | non | 16 | 119774 | 395 | 44 |
| gemini-3.5-flash-lite | sympy__sympy-13480 | PASS | non | 30 | 186990 | 842 | 179 |
| gemini-3.5-flash-lite | sympy__sympy-14711 | PASS | non | 30 | 271160 | 2068 | 143 |
| gemini-3.6-flash | pydata__xarray-4629 | INDISPO | non | 0 | 0 | 0 | 20 |
| gemini-3.6-flash | sympy__sympy-13480 | INDISPO | non | 0 | 0 | 0 | 20 |
| gemini-3.6-flash | sympy__sympy-14711 | INDISPO | non | 12 | 104146 | 2191 | 125 |
| openai/gpt-oss-120b | pydata__xarray-4629 | FAIL | non | 0 | 0 | 0 | 1 |
| openai/gpt-oss-120b | sympy__sympy-13480 | PASS | oui | 13 | 28223 | 3005 | 167 |
| openai/gpt-oss-120b | sympy__sympy-14711 | FAIL | non | 0 | 0 | 0 | 2 |
| qwen/qwen3.8-27b | pydata__xarray-4629 | PASS | non | 5 | 18591 | 265 | 108 |
| qwen/qwen3.8-27b | sympy__sympy-13480 | PASS | oui | 4 | 9677 | 195 | 25 |
| qwen/qwen3.8-27b | sympy__sympy-14711 | PASS | non | 12 | 41251 | 899 | 301 |

### Fiabilite des providers (v1)

Temps moyen = moyenne des `request_time_ms` des steps. Retries = somme des `retries` (429, reseau, reponses vides). Requetes utiles = steps / requetes envoyees. Disponibilite = cases non INDISPO / cases lancees.

| modele | temps moyen / requete (s) | retries | requetes utiles | disponibilite |
|---|---|---|---|---|
| gemini-3.5-flash | 20.1 | 1 | 5/34 | 0/3 |
| gemini-3.5-flash-lite | 3.5 | 21 | 76/116 | 2/3 |
| gemini-3.6-flash | 6.7 | 15 | 12/87 | 0/3 |
| openai/gpt-oss-120b | 0.9 | 45 | 13/64 | 3/3 |
| qwen/qwen3.8-27b | 0.5 | 100 | 21/127 | 3/3 |

### Metriques intermediaires (v1)

1er contact = 1er step dont le code nomme un fichier du patch final ; 1re edition = 1er `edit_file` sur ce fichier. Discipline = iterations entre le 1er `run_tests()` qui passe et `final_answer` (ideal 0 ; « ? » si le resume des tests a ete tronque).

| modele | tache | 1er contact | 1re edition | discipline |
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

<!-- AUTO:main:START -->
_Aucun run dans BENCHMARK/main/._
<!-- AUTO:main:END -->

<!-- AUTO:no_regex:START -->
### Resultats (no_regex)

`final_answer` : non = l'agent n'a pas soumis lui-meme ; la CLI a rendu le patch du conteneur (`get_patch()`), c'est lui qui a ete valide.

| modele | tache | verdict | final_answer | iterations | tokens in | tokens out | temps (s) |
|---|---|---|---|---|---|---|---|
| gemini-3.5-flash | pydata__xarray-4629 | INDISPO | non | 0 | 0 | 0 | 2 |
| gemini-3.5-flash | sympy__sympy-13480 | INDISPO | non | 4 | 5943 | 325 | 126 |
| gemini-3.5-flash | sympy__sympy-14711 | INDISPO | non | 7 | 28596 | 516 | 274 |
| gemini-3.5-flash-lite | pydata__xarray-4629 | INDISPO | non | 7 | 44296 | 284 | 208 |
| gemini-3.5-flash-lite | sympy__sympy-13480 | PASS | non | 30 | 139100 | 517 | 498 |
| gemini-3.5-flash-lite | sympy__sympy-14711 | FAIL | non | 23 | 272014 | 4656 | 211 |
| gemini-3.6-flash | pydata__xarray-4629 | INDISPO | non | 1 | 1889 | 266 | 15 |
| gemini-3.6-flash | sympy__sympy-13480 | INDISPO | non | 0 | 0 | 0 | 60 |
| gemini-3.6-flash | sympy__sympy-14711 | INDISPO | non | 6 | 26283 | 618 | 55 |
| openai/gpt-oss-120b | pydata__xarray-4629 | INDISPO | non | 4 | 6830 | 279 | 3 |
| openai/gpt-oss-120b | sympy__sympy-13480 | FAIL | oui | 3 | 3771 | 1036 | 5 |
| openai/gpt-oss-120b | sympy__sympy-14711 | PASS | non | 28 | 127993 | 7151 | 888 |
| qwen/qwen3.8-27b | pydata__xarray-4629 | INDISPO | non | 3 | 5767 | 195 | 3 |
| qwen/qwen3.8-27b | sympy__sympy-13480 | INDISPO | non | 3 | 4070 | 167 | 13 |
| qwen/qwen3.8-27b | sympy__sympy-14711 | PASS | non | 23 | 91268 | 2398 | 749 |

### Fiabilite des providers (no_regex)

Temps moyen = moyenne des `request_time_ms` des steps. Retries = somme des `retries` (429, reseau, reponses vides). Requetes utiles = steps / requetes envoyees. Disponibilite = cases non INDISPO / cases lancees.

| modele | temps moyen / requete (s) | retries | requetes utiles | disponibilite |
|---|---|---|---|---|
| gemini-3.5-flash | 11.7 | 0 | 11/41 | 0/3 |
| gemini-3.5-flash-lite | 11.1 | 4 | 60/65 | 2/3 |
| gemini-3.6-flash | 3.5 | 1 | 7/25 | 0/3 |
| openai/gpt-oss-120b | 1.1 | 210 | 35/255 | 2/3 |
| qwen/qwen3.8-27b | 0.6 | 160 | 29/208 | 1/3 |

### Metriques intermediaires (no_regex)

1er contact = 1er step dont le code nomme un fichier du patch final ; 1re edition = 1er `edit_file` sur ce fichier. Discipline = iterations entre le 1er `run_tests()` qui passe et `final_answer` (ideal 0 ; « ? » si le resume des tests a ete tronque).

| modele | tache | 1er contact | 1re edition | discipline |
|---|---|---|---|---|
| gemini-3.5-flash | pydata__xarray-4629 | - | - | - |
| gemini-3.5-flash | sympy__sympy-13480 | 1 | 3 | - |
| gemini-3.5-flash | sympy__sympy-14711 | - | - | - |
| gemini-3.5-flash-lite | pydata__xarray-4629 | 2 | 3 | - |
| gemini-3.5-flash-lite | sympy__sympy-13480 | 2 | 3 | - |
| gemini-3.5-flash-lite | sympy__sympy-14711 | - | - | - |
| gemini-3.6-flash | pydata__xarray-4629 | - | - | - |
| gemini-3.6-flash | sympy__sympy-13480 | - | - | - |
| gemini-3.6-flash | sympy__sympy-14711 | - | - | - |
| openai/gpt-oss-120b | pydata__xarray-4629 | - | - | - |
| openai/gpt-oss-120b | sympy__sympy-13480 | - | - | ? |
| openai/gpt-oss-120b | sympy__sympy-14711 | 7 | 8 | - |
| qwen/qwen3.8-27b | pydata__xarray-4629 | 2 | 3 | - |
| qwen/qwen3.8-27b | sympy__sympy-13480 | 1 | 2 | - |
| qwen/qwen3.8-27b | sympy__sympy-14711 | 3 | 20 | - |
<!-- AUTO:no_regex:END -->

## 3. Provider reliability

Voir le tableau « fiabilite » de la section 2.

## 4. Intermediary metrics

Voir le tableau « metriques intermediaires » de la section 2.

## 5. Ablation

## 6. Conclusions
