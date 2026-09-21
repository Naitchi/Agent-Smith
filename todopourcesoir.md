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

- [x] Extraire un vrai `_build_messages()` (aujourd'hui l'historique est construit inline
      — c'est déjà le `[~]` de §mobenais.3) qui **reconstruit** la liste envoyée au lieu de
      passer `message` brut au provider
      → `tronc_message()` (`src/agent_loop.py:100`) + `AgentLoop.vue_dans_budget()`
      (`src/agent_loop.py:394`) : c'est `vue` qui part au provider, `message` garde
      l'historique complet pour le backup et la reprise
- [x] Fenêtre glissante : prompt système + énoncé de la tâche **jamais tronqués**, puis les
      N derniers tours (commencer à N=3)
      → `LAST_ITER_INTACTS = 3` (`schemas/tools_agent.py:26`) ; `vue_dans_budget()` retombe
      à 2 puis 1 tour intact si la requête ne rentre pas. Nuance : les vieux tours sont
      **tronqués, pas retirés** — la fenêtre allège, elle ne supprime rien
- [x] Troncature des vieilles observations : couper à ~100 caractères avec un marqueur
      explicite `[... 1240 chars truncated]` pour que le modèle sache qu'il y avait du contenu
      → `MAX_OBS_CHARS = 100`, marqueur posé dans `tronc_message()` (`src/agent_loop.py:118`)
- [x] Appeler la reconstruction **avant** `check_budget()` en tête d'itération : ça règle le
      reste ouvert de §mobenais.0 (« une requête unique peut franchir la limite à elle seule »)
      — aujourd'hui on ne peut que constater le dépassement, pas l'éviter
      → `src/agent_loop.py:214-215` ; `vue_dans_budget()` estime la requête
      (`CHARS_PAR_TOKEN`, `MARGE_BUDGET = 0.9`) et lève `MaxInputTokensError` **avant**
      l'envoi quand même un seul tour ne rentre pas
- [ ] Revérifier sur les 3 tâches de mise au point (`uno` / `dos` / `tres`) que les tokens
      d'entrée cumulés baissent bien, et de combien (chiffre à réutiliser dans le rapport)
      → pas lancé, aucun chiffre avant/après nulle part. **Et pas lançable en l'état :**
      `src/agent_loop.py:30-42` importe `DEBUG_BASCULE` / `FORCE_429_MODELS`, que
      `schemas/tools_agent.py:35-38` a commentés au dernier commit → `ImportError` sur
      `import src.agent_loop`. À décommenter avant toute mesure

> Décidé ce soir : **pas de compaction par un second LLM sur MBPP.** La fenêtre glissante
> donne la même économie pour 0 token et 0 latence, alors qu'un appel de résumé coûte le
> contexte complet en entrée (~25 % du budget). La compaction LLM est gardée pour SWE-bench.

## 2. Extraction de code (§mobenais.2)

Seul le format 1 marche, et partiellement.

- [ ] `<end_code>` n'est pas géré par `extract_code` alors que le prompt l'écrit et que
      `STOP_SEQUENCES` l'arme (`schemas/tools_agent.py:80`) — incohérence à corriger en premier
      → toujours ouvert. Pire que noté : la stop sequence coupe la réponse **sur** le
      ``` fermant, donc `text.split("```")` ne rend que 2 parties et
      `extract_code` (`schemas/tools_agent.py:138`) renvoie `None` sur une réponse correcte
- [ ] Type `ExtractedCode` (aujourd'hui `str | None`) → sans lui, impossible de dire au LLM
      quel format a été reconnu
- [ ] Format 2 — XML Anthropic `<invoke name="..."><parameter name="...">…</parameter></invoke>`
- [ ] Format 3 — JSON/Hermes `<tool_call>{"name": ..., "arguments": {...}}</tool_call>`
- [ ] Format 4 — ReAct `Action:` / `Action Input:`
- [ ] `to_python_call(name, args) -> str`
- [ ] Tolérance bloc non fermé (renvoie `None` aujourd'hui)
- [ ] Signaler au LLM quand l'interprétation est « de secours »

## 3. Boucle agent — reste divers (§mobenais.3)

- [x] Sur `max_iterations` atteint, `solution` reste `""` → renvoyer le dernier code candidat
      → repli sur le dernier `sandbox_input` non vide dans `agent_mbpp/__main__.py:135-139`.
      Fait **côté CLI seulement** : `AgentLoop.run()` rend toujours `solution=""`, donc
      `agent_swebench` (§4) devra le refaire ou le remonter dans la boucle
- [ ] Le défaut d'`AgentLoopConf` est toujours un `Sandbox()` nu, donc `uv run -m src` tourne
      sans aucun outil (§mobenais.0 ; réglé pour `agent_mbpp` seulement)
- [ ] **`compact_manual()` supprime la liste des outils MCP — `agent_mbpp` n'utilise donc
      jamais `run_tests` / `check_syntax`.** Vérifié sur les deux runs enregistrés
      (`solution.json` tâche 92, `cache/mbpp_solution.json` tâche 304) : le `system_prompt`
      sauvegardé ne contient ni `run_tests`, ni `check_syntax`, ni `MCP` — et aucun
      `sandbox_input` ne les appelle. Le modèle réécrit ses `assert` à la main.
      Cause : `compact_manual()` (`src/agent_loop.py:90`) coupe à `MAX_MANUAL_CHARS = 700`
      en retirant la **plus longue** « phrase » (`split(". ")`). Or la section outils de
      `get_manual()` est un bloc à newlines sans `". "` : elle forme une pseudo-phrase de
      ~460 caractères, donc **la toute première supprimée**. Le manuel réel tombe de
      ~1265 à 611 caractères et perd, dans l'ordre : les outils MCP, `list_resources` /
      `get_resource`, puis `Authorized builtins`.
      C'est la même règle qu'au §1 mais jamais appliquée ici : *ce qui ne doit jamais être
      tronqué* doit être mis hors de portée du compacteur, pas confié à une heuristique —
      qui plus est une heuristique « retire le plus long », donc le plus informatif.
  - [x] Garder la section outils intacte et ne compacter que les limites. `get_manual()`
        rend une seule chaîne plate (`src/sandbox/mcp_bridge.py:428`) : soit on la découpe
        sur `"Available MCP tools"` côté boucle (à moi, un peu fragile), soit `get_manual()`
        sépare les deux — **API de bclairot, donc à lui signaler, pas à corriger**
        → fait côté boucle, sans toucher son fichier. Coupe **structurelle** :
        `manual.partition("\n")`, car `base` ne contient aucun `\n` (vérifié) — pas de
        recherche du texte `"Available MCP tools"`. Si `base` gagne un jour un `\n`, on
        garde trop de verbatim, on ne perd pas les outils.
        Les limites sont coupées **net** avec le marqueur de `_truncate`, sans découpage en
        « phrases » : `split(". ")` rend des fragments sur ce texte, c'est l'erreur d'origine.
        `MAX_MANUAL_CHARS = 700` → `MAX_LIMITES_CHARS = 250`, et le sens change : budget de
        la **seule** section limites, outils hors budget.
        Vérifié en conditions réelles (vrai serveur MCP, sans appel LLM) : `run_tests`,
        `check_syntax`, `get_resource` et `Authorized imports` arrivent tous au modèle.
  - [ ] Nommer `run_tests` explicitement dans `SYSTEM_PROMPT_MBPP` : il dit aujourd'hui
        « run the given tests in the same block », ce qui pousse activement vers les
        `assert` maison même quand le manuel passe — **pas encore fait**, le manuel est
        réparé mais le prompt tire toujours dans l'autre sens
  - [ ] Le serveur MCP `mbpp_methodology` de bclairot (`mcp_tools_mbpp.py:104`) documente
        déjà le workflow en 6 étapes autour de `run_tests` — jamais récupéré, faute de
        savoir que `get_prompt()` existe. Vérifier avec lui si c'est lui qu'il faut charger
        plutôt que de dupliquer la méthodologie dans notre prompt
  - [ ] Conséquence §6 : tant que ça tient, un run MBPP lance le serveur MCP en sous-processus
        pour rien, et toute mesure « avec vs sans outils » mesurerait deux fois la même chose
- [ ] **`max_wall_time_seconds` doit définir un timeout, pas seulement un constat.**
      Aujourd'hui il n'est lu que par `check_budget()` (`src/agent_loop.py:428-433`), donc
      *après* que la requête soit revenue. Le seul timeout réel est le `60.0` en dur de
      `OpenAICompatibleProvider.__init__` (`llm/provider.py:88`), que `make_llm()` ne
      surcharge même pas : il ne sait rien du budget de la tâche.
      C'est le pendant exact du point §1.4 pour le temps — la boucle plafonne déjà la
      sortie (`plafond_sortie()`) et l'entrée (`vue_dans_budget()`) sur le budget restant,
      il manque le troisième :
  - [ ] `delai_restant(start)` → `max_wall_time_seconds - (monotonic() - start)`, passé en
        `timeout` de la requête (le provider relit `self.timeout` à chaque `complete()`,
        comme il relit la clé : même point d'accroche)
  - [ ] Vérifier le délai restant **dans la boucle de bascule** aussi : `while True`
        (`src/agent_loop.py:217-279`) réessaie sans jamais regarder l'heure. Sur MBPP
        (120 s) une cascade de 429 peut enchaîner 9 modèles × N clés × 60 s sans qu'aucun
        `check_budget()` ne s'intercale — `MAX_CONSECUTIVE_ERRORS = 3` borne la boucle
        externe, pas celle-là
  - [ ] Garder une marge pour écrire `solution.json` : dépasser le wall-time n'est pas un
        échec propre comme le dépassement de tokens (qui rend un `SolutionOutput` avec
        `error`), c'est la moulinette qui tue le process — donc **aucune sortie du tout**

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

- [~] D'abord la troncature **mécanique** (contenus de fichiers, tracebacks, sorties de tests) :
      80 % du gain pour 0 token et 0 latence
      → **le mécanisme existe déjà, côté bclairot** : `_truncate()`
      (`mcp_tools_swebench.py:58`) coupe à `max_std_length` et pose un marqueur, et
      `_format_result()` le branche sur 8 outils sur 9 — `read_file`, `run_tests`,
      `search_code`, `find_references`, `get_patch`, `run_command`... donc contenus de
      fichiers, tracebacks et sorties de tests sont couverts. C'est la même forme que le
      `compact_manual` que je comptais écrire : rien à inventer, l'archi est déjà bonne.
      Reste **deux réglages**, pas un mécanisme :
  - [ ] `max_std_length = 10000` par défaut, soit ~2500 tokens par observation : si chaque
        appel sature, 30 itérations font 75k des 300k. Le plafond existe, il est juste
        large — c'est le chiffre à régler, et il se règle depuis `SWEBenchTools(...)`
        côté `agent_swebench`, sans toucher son fichier
  - [ ] Ça se **compose** avec le §1 : le serveur plafonne chaque observation à
        `max_std_length`, la fenêtre glissante rabote ensuite les vieilles à
        `MAX_OBS_CHARS`. Deux étages, deux rôles — garder cette séparation pour SWE-bench
        plutôt que de réécrire quoi que ce soit dans la boucle
  - [ ] **Du coup, la compaction LLM est encore moins probable qu'estimé** : les deux
        étages mécaniques sont déjà là et gratuits. Ne l'ouvrir qu'avec un chiffre qui
        montre que ça ne suffit pas
- [ ] Deux points à signaler à bclairot sur `mcp_tools_swebench.py` (son fichier) :
  - [ ] `edit_file` est le seul outil qui ne passe pas par `_format_result`, et c'est
        aussi le seul dont le retour **réémet des chaînes fournies par le modèle** :
        `f"Successfully replaced '{old_str}' with '{new_str}'"`. Un remplacement de 3000
        caractères renvoie ~6000 caractères non tronqués. Même chose pour l'erreur
        « found N times ». C'est le seul trou de la couche mécanique
  - [ ] Marqueurs incohérents entre les deux côtés, et pas au même sens : `_truncate` écrit
        `... (truncated, N chars total)` où N est la taille **totale**, `tronc_message`
        écrit `[... N chars truncated]` où N est la taille **coupée**. Même mot, deux
        grandeurs — à aligner avant que le modèle voie les deux dans un même contexte
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
      (`src/agent_loop.py:191-192`)
- [~] Créer `.env.example` (**absent**) : documenter `GEMINI_API_KEYS` / `GROQ_API_KEYS`
      (listes séparées par virgules) en plus des clés simples
      → fichier créé (`GROQ_API_KEY` / `GEMINI_API_KEY` / `TESTBED_PATH`), mais les deux
      variantes **au pluriel** manquent — or c'est la seule doc de la rotation de clés,
      que `src/agent_loop.py:201-210` lit via `provider.keys_env`

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

- ~~Le sujet `en.subject.pdf` **n'est plus à la racine du repo** : le seul exemplaire retrouvé
  est dans la corbeille (`~/.local/share/Trash/files/en.subject.pdf`).~~ **Plus dans la
  corbeille non plus**, mais récupérable depuis git : il a été committé en `53b06f0` puis
  supprimé en `92d15f7` — `git show 53b06f0:en.subject.pdf > en.subject.pdf` (2.3 Mo).
  Attention, il est dans `.gitignore` : s'il revient, il ne repartira pas dans un commit.
- À défaut, les limites sont vérifiables dans `moulinette/moulinette/models.py:96-106`
  (MBPP 10 / 6k / 1.5k / 120 s — SWE-bench 30 / 300k / 10k / 900 s).
- Point à remonter à bclairot : `TESTBED_PATH` ne traverse pas la frontière `--mcp-stdio`
  (déjà noté dans `TODO.md` §0.5 et §bclairot.7) — bloquant pour le point 4.

---

## Point d'étape (relecture du 2026-09-21)

Fait cette nuit : **le point 1 (troncature) à 4 items sur 5** — c'est le seul bloc entamé,
mais c'était bien celui dont dépendait tout le reste. Le point 3 avance d'un item, le
`.env.example` est à moitié fait.

Rien sur les points 2, 4, 6, 8 : `agent_swebench/` n'existe pas, `BENCHMARK_REPORT.md`
non plus, `extract_code` est inchangé.

Ajouté au §3 après relecture : `max_wall_time_seconds` ne sert nulle part de timeout, il
n'est que constaté a posteriori. Des trois limites du sujet, c'est la seule qui, dépassée,
ne produit pas de `solution.json` — donc la plus coûteuse à laisser non bornée.

Ajouté au §3 aussi, et c'est le plus gros : **`agent_mbpp` n'utilise pas les outils de
bclairot.** Pas un choix, un effet de bord — `compact_manual()` supprime la section outils
du manuel avant qu'elle n'atteigne le modèle. Le 3/3 revendiqué sur les tâches maison a
donc été obtenu *sans* `run_tests`, ce qui change ce que ce chiffre vaut.

~~**Bloquant immédiat :** `import src.agent_loop` lève un `ImportError`~~ — réglé,
`DEBUG_BASCULE` et `FORCE_429_MODELS` sont décommentés, `import src.agent_loop` passe.

### Coût du manuel réparé — chiffres mesurés, pas estimés

Le `system_prompt` est **repayé à chaque requête**, c'est le terme dominant sur MBPP.
Mesuré sur le run enregistré (`solution.json`, tâche 226) : `system_prompt` de 1607
caractères, 1er appel à 500 tokens, 3 itérations pour 1826 tokens cumulés — soit ~110
tokens de croissance par tour contre ~500 repayés à chaque fois.

| budget limites | prompt | vs avant | ~tokens sur 10 iter | imports | outils |
|---|---|---|---|---|---|
| 700 (1er choix) | 2297 | +690 | **+2150** | oui | oui |
| **250 (retenu)** | 1847 | +240 | **+748** | oui | oui |
| avant le fix | 1607 | — | — | **non** | **non** |

D'où 250 et pas 700 : à 700 le manuel mangeait un tiers du budget. À 250 on paie ~750
tokens sur la tâche entière pour rendre `run_tests` atteignable — et on récupère au passage
`Authorized imports`, que l'ancienne heuristique supprimait aussi.

Ce qui saute à 250 : `Authorized builtins`, les attributs, les chemins. Assumé — la
persistance et `final_answer` sont déjà nommés dans `SYSTEM_PROMPT_MBPP`, le reste se
découvre à la première observation d'erreur.

À confirmer sur un vrai run : le pari est que `run_tests` fait converger en moins
d'itérations, et qu'une itération économisée (~500-800 tokens) rembourse largement les 750.
