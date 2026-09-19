# TODO pour ce soir — lot mobenais

> Extrait de `TODO.md` (lot mobenais uniquement), ordonné par chemin critique.
> Rien du lot bclairot ici : un bug de son côté se signale dans `TODO.md`, il ne se corrige pas.

Chemin critique : **troncature → `agent_swebench` → runs de benchmark → rapport**.
Les trois derniers dépendent du premier, donc commencer par là même si c'est le plus petit morceau.

---

## 1. Troncature de l'historique (§mobenais.3) — à faire en premier

Sans ça, les tokens d'entrée croissent quadratiquement (chaque tour repaie tous les
précédents) et le budget MBPP de 6k saute vers l'itération 6 sur 10.
Aujourd'hui `message` ne fait que grossir dans `src/agent_loop.py:261-288`, rien n'est jamais retiré.

- [ ] Extraire un vrai `_build_messages()` (aujourd'hui l'historique est construit inline
      — c'est déjà le `[~]` de §mobenais.3) qui **reconstruit** la liste envoyée au lieu de
      passer `message` brut au provider
- [ ] Fenêtre glissante : prompt système + énoncé de la tâche **jamais tronqués**, puis les
      N derniers tours (commencer à N=3)
- [ ] Troncature des vieilles observations : couper à ~100 caractères avec un marqueur
      explicite `[... 1240 chars truncated]` pour que le modèle sache qu'il y avait du contenu
- [ ] Appeler la reconstruction **avant** `check_budget()` en tête d'itération : ça règle le
      reste ouvert de §mobenais.0 (« une requête unique peut franchir la limite à elle seule »)
      — aujourd'hui on ne peut que constater le dépassement, pas l'éviter
- [ ] Revérifier sur les 3 tâches de mise au point (`uno` / `dos` / `tres`) que les tokens
      d'entrée cumulés baissent bien, et de combien (chiffre à réutiliser dans le rapport)

> Décidé ce soir : **pas de compaction par un second LLM sur MBPP.** La fenêtre glissante
> donne la même économie pour 0 token et 0 latence, alors qu'un appel de résumé coûte le
> contexte complet en entrée (~25 % du budget). La compaction LLM est gardée pour SWE-bench.

## 2. Extraction de code (§mobenais.2)

Seul le format 1 marche, et partiellement.

- [ ] `<end_code>` n'est pas géré par `extract_code` alors que le prompt l'écrit et que
      `STOP_SEQUENCES` l'arme (`schemas/tools_agent.py:55`) — incohérence à corriger en premier
- [ ] Type `ExtractedCode` (aujourd'hui `str | None`) → sans lui, impossible de dire au LLM
      quel format a été reconnu
- [ ] Format 2 — XML Anthropic `<invoke name="..."><parameter name="...">…</parameter></invoke>`
- [ ] Format 3 — JSON/Hermes `<tool_call>{"name": ..., "arguments": {...}}</tool_call>`
- [ ] Format 4 — ReAct `Action:` / `Action Input:`
- [ ] `to_python_call(name, args) -> str`
- [ ] Tolérance bloc non fermé (renvoie `None` aujourd'hui)
- [ ] Signaler au LLM quand l'interprétation est « de secours »

## 3. Boucle agent — reste divers (§mobenais.3)

- [ ] Sur `max_iterations` atteint, `solution` reste `""` → renvoyer le dernier code candidat
- [ ] Le défaut d'`AgentLoopConf` est toujours un `Sandbox()` nu, donc `uv run -m src` tourne
      sans aucun outil (§mobenais.0 ; réglé pour `agent_mbpp` seulement)

## 4. `agent_swebench` (§mobenais.6) — le gros morceau, rien n'existe

- [ ] Créer le package `agent_swebench/` + l'ajouter à `packages` dans `pyproject.toml`
- [ ] CLI `uv run python -m agent_swebench --task-file ... --output ... --model-name ... --provider-url ...`
- [ ] Chargement `SWEBenchTaskInput`, lancement du serveur MCP SWE-bench avec **`TESTBED_PATH`
      dans l'environnement du sous-processus** (cf. le point ouvert de §0.5 : la variable ne
      traverse pas la frontière `--mcp-stdio` — à vérifier avec bclairot avant de coder)
- [ ] `SolutionOutput(benchmark="swebench", solution=<patch de get_patch()>)`
- [ ] Limites **30 iter / 300k in / 10k out / 900 s** en constantes de tête de module
- [ ] Prompt SWE-bench (§mobenais.4, n'existe pas) + sa méthodologie de debug pas-à-pas :
      lire → chercher → hypothèse → éditer → tester
- [ ] Mise au point sur `sympy__sympy-14711`, `sympy__sympy-13480`, `pydata__xarray-4629`
- [ ] Objectif **2/3**

### Compaction du contexte, côté SWE-bench uniquement

- [ ] D'abord la troncature **mécanique** (contenus de fichiers, tracebacks, sorties de tests) :
      80 % du gain pour 0 token et 0 latence
- [ ] Compaction par un second LLM seulement si ça ne suffit pas, et alors :
  - [ ] sur une **clé / un provider dédié**, jamais présent dans le pool de bascule de l'agent
        (sinon contention au pire moment) — les quotas free tier sont par clé sur fenêtre
        glissante, donc l'ordre de rotation ne « reset » rien, seule une clé séparée isole
  - [ ] un petit modèle rapide suffit : résumer ne demande aucun raisonnement
  - [ ] **compter l'appel dans `total_requests`** — la moulinette le définit comme
        « Total number of LLM API requests made (including retries) »
        (`moulinette/models_public.py:40`), et §C.3 range les métriques fausses en grade 0
  - [ ] le déclarer explicitement dans le README et le `BENCHMARK_REPORT`

## 5. Couche LLM (§mobenais.1) — marche, mais pas au niveau demandé

- [ ] `class TokenRotator` : `next_key()` / `mark_rate_limited(key, retry_after)` /
      `mark_exhausted(key)` — aujourd'hui la rotation est inline dans `AgentLoop.run()` et
      propagée par **mutation de `os.environ`**, c'est ça qu'il faut extraire
- [ ] Backoff temporisé + respect de `Retry-After` (aujourd'hui retry immédiat)
- [ ] Couvrir les timeouts réseau (`httpx.RequestError`), non gérés
- [ ] `LLMResult` : ajouter `retries`, `api_url`, `model_name` — la boucle les recompose à la main
- [ ] Généraliser les pools `gemini_pool` / `groq_pool`, encore nommés en dur
      (`src/agent_loop.py:161-162`)
- [ ] Créer `.env.example` (**absent**) : documenter `GEMINI_API_KEYS` / `GROQ_API_KEYS`
      (listes séparées par virgules) en plus des clés simples

## 6. Benchmark et rapport (§C.1) — pilote mobenais

Fichier `BENCHMARK_REPORT.md` **absent**.

- [ ] ≥ 5 modèles × ≥ 3 tâches SWE-bench identiques
- [ ] Setup : modèles, providers, tâches choisies **et pourquoi**
- [ ] Table par couple modèle × tâche : Pass/Fail · itérations · tokens in · tokens out · wall-clock
- [ ] Fiabilité provider : temps de réponse moyen, retries, disponibilité
- [ ] Métrique intermédiaire à ma charge : itérations entre « tests passent » et `final_answer`
      (idéal : 0)
- [ ] Ablation — **remplacer** « prompt vague vs explicite » par **« avec vs sans compaction »**,
      nettement plus intéressant et directement issu du travail du point 1
- [ ] Committer les `solution.json` correspondants

## 7. README (§C.2)

- [ ] Section « Benchmark Results and Analysis » : n'est qu'un `TODO: A remplir`
      (`README.md:296-298`) — dépend du point 6
- [x] Section « Agent Loop » écrite
- [ ] La relire une fois la troncature en place : la description de la boucle ne sera plus à jour

## 8. Divers exam / soutenance

- [ ] `exam_mbpp.sh` n'a **jamais** été lancé (3/3 sur des tâches maison ≠ 4/5 sur l'exam)
- [ ] Repasser la checklist grade 0 §C.3 : clés en dur, libs d'orchestration interdites,
      `system_prompt` / `llm_output` / `sandbox_input` / `sandbox_output` réellement remplis
- [ ] Cross-review §C.4 : savoir expliquer le lot bclairot sans notes, ≥ 1 commit chez lui

---

## Notes avant de partir

- Le sujet `en.subject.pdf` **n'est plus à la racine du repo** : le seul exemplaire retrouvé
  est dans la corbeille (`~/.local/share/Trash/files/en.subject.pdf`). À restaurer avant de
  reprendre, toutes les limites chiffrées viennent de là.
- À défaut, les limites sont vérifiables dans `moulinette/moulinette/models.py:96-106`
  (MBPP 10 / 6k / 1.5k / 120 s — SWE-bench 30 / 300k / 10k / 900 s).
- Point à remonter à bclairot : `TESTBED_PATH` ne traverse pas la frontière `--mcp-stdio`
  (déjà noté dans `TODO.md` §0.5 et §bclairot.7) — bloquant pour le point 4.
