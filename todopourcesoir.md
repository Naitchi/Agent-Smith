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
      → `LAST_ITER_INTACTS = 3` (`schemas/tools/limits.py:45`) ; `vue_dans_budget()` retombe
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
      `src/agent_loop.py:30-42` importe des drapeaux de debug que
      `schemas/tools_agent.py:35-38` a commentés au dernier commit → `ImportError` sur
      `import src.agent_loop`. À décommenter avant toute mesure

> Décidé ce soir : **pas de compaction par un second LLM sur MBPP.** La fenêtre glissante
> donne la même économie pour 0 token et 0 latence, alors qu'un appel de résumé coûte le
> contexte complet en entrée (~25 % du budget). La compaction LLM est gardée pour SWE-bench.

## 2. Extraction de code (§mobenais.2) — les 4 formats du sujet

`extract_code()` réécrit (`schemas/tools/tools_agent.py`). Sujet p.10 : formats (a)-(d),
conversion en appel Python avant la sandbox, et signaler au LLM un bloc « malformed but
interpreted anyway (explain how) ».

- [x] `<end_code>` : retiré du texte avant extraction. **Faux problème** dans la version
      précédente de cette TODO : sur les 21 réponses enregistrées, le provider coupe
      **avant** `<end_code>`, la fence fermante est bien là
- [x] Type `ExtractedCode` (`schemas/extracted_code.py`) : `code`, `format`
      (`python` / `xml` / `hermes` / `react`), `note` pour le LLM
- [x] Format 1 — fences détectées **en début de ligne** (plus de `split("```")`) :
      ```` ``` ```` / `~~~`, 3+ caractères, langue `python`/`py`/`python3`/`ipython`/vide,
      et **`tool_code`** (format d'appel sur lequel Gemini est entraîné). Dernier bloc
      Python retenu, un ```` ```bash ```` ignoré. Une ligne ```` ``` ```` **dans une chaîne**
      du code ne coupe plus le bloc : si le bloc ne se parse pas, on essaie la fence suivante
- [x] Format 2 — XML Anthropic `<invoke name><parameter name>` (plusieurs appels, dernier
      `</invoke>` coupé toléré ; valeurs JSON pour nombres/booléens/listes, chaînes brutes)
- [x] Format 3 — Hermes `<tool_call>{...}</tool_call>` (`arguments` ou `parameters`, en
      objet ou en chaîne JSON façon OpenAI, préfixe `functions.` retiré, balise fermante
      manquante tolérée) + ```` ```json {"name", "arguments"} ````
- [x] Format 4 — ReAct `Action:` / `Action Input:` (JSON, sinon chaîne en argument positionnel)
- [x] `to_python_call(name, args)` → `result = read_file(filepath='...')` + `print(result)`
      (le modèle ne voit que ce qui est imprimé). Nom ou argument non identifiant → rejeté
- [x] Tolérance : bloc non fermé (exécuté, avec note), `Code:` sans fence (seulement si
      ça se parse, avec note), texte seul → `None`
- [x] Signalement : toute conversion ou interprétation de secours préfixe l'observation
      par `[extraction: ...]` (`src/agent_loop.py`) ; `None` → message qui rappelle le format
- [x] `STOP_SEQUENCES = [END_CODE, "</tool_call>"]` (exemple du sujet V.6)
- [x] Vérifié : 21 cas couvrant chaque format + les **21 réponses réelles** enregistrées
      (MBPP + SWE-bench) redonnent exactement le même `sandbox_input`, sans note
- [ ] Pas encore vu un vrai modèle répondre en XML / Hermes / ReAct : à observer pendant
      les runs multi-modèles du §6 (compter les `format` != `python` par modèle)
- [x] Le `400 Bad Request` de `gpt-oss-20b` (§4) pourrait venir du paramètre `stop` —
      à vérifier, et encore plus maintenant qu'il a 2 valeurs
      → non (cf. §4)

## 3. Boucle agent — reste divers (§mobenais.3)

- [x] Sur `max_iterations` atteint, `solution` reste `""` → renvoyer le dernier code candidat
      → repli sur le dernier `sandbox_input` non vide dans `agent_mbpp/__main__.py:135-139`.
      Fait **côté CLI seulement** : `AgentLoop.run()` rend toujours `solution=""`, donc
      `agent_swebench` (§4) devra le refaire ou le remonter dans la boucle
      → refait dans `agent_swebench` (voir §4) : repli sur `get_patch()` relu dans le
      conteneur. Toujours pas remonté dans la boucle — deux replis, un par CLI
- [x] **Check-up du lot (soir du 2026-09-21)** — vérifié avec un faux LLM + une fausse
      sandbox (sans réseau) : succès, 429 → rotation → bascule, erreur partielle, 400,
      rien d'exploitable → `max_iterations`, sortie vide. Les 6 cas se comportent comme
      prévu ; codes de sortie des 2 CLI vérifiés (`--help` 0, erreur 1).
  - [x] **Sortie partielle perdue** : sur erreur ou timeout, seule `error:` partait au
        LLM, le `stdout` / `stderr` imprimé avant était jeté, et timeout / troncature
        n'étaient jamais dits (exigé par le sujet). → `observation()`
        (`src/agent_loop.py`) rend tout, avec `[timeout: … partial]` et
        `[output truncated: …]` ; « nothing bro » → `(no output: use print() to see values)`
  - [x] `status` possiblement non défini dans l'`except httpx.HTTPStatusError` externe
        → relu depuis l'exception
  - [x] Vérif des clés : `API_KEY_VARS` contenait `TESTBED_PATH` dans un `any(...)`
        (un `.env` sans clé passait), `agent_mbpp` / `src/__main__` ignoraient les
        `*_API_KEYS`. → une seule `has_api_key()` (`llm/registry.py`), même lecture
        que la boucle, pour les 3 points d'entrée
  - [x] `agent_mbpp` sortait en code 0 sur erreur → code 1, comme `agent_swebench`
  - [x] Nettoyage sans changement de comportement : branche `501` morte retirée
        (pas dans `STATUS_BASCULE`), doublons pools / 1re clé → `_retirer_des_pools()`
        et `premiere_cle()`, `OutputParameter` en dataclass appelée par noms de champs,
        `__output__` → `_output`, `backup_json` sans `rmtree`, imports un par ligne,
        `except (Exception, TimeoutError, Exception)` → `except Exception`, préfixe
        `Observation:` aligné sur le prompt, types sur `AgentLoopConf`, docstring de
        `vue_dans_budget` à jour
  - [ ] Laissés volontairement : `except Exception` de haut niveau (filets anti-crash),
        nom `schemas/Error.py` (renommer = toucher la structure), import aliasé des CLI
        en un bloc (plus lisible que le découpage ruff)
  - [ ] À trancher : `LLM_COMPACT = []` (`schemas/tools/tools_agent.py`) n'est utilisé
        nulle part depuis l'abandon de la compaction LLM ; un `400` consomme une
        itération sans créer de `StepMetrics` (comportement antérieur)
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
  - [x] Nommer `run_tests` explicitement dans `SYSTEM_PROMPT_MBPP` : il dit aujourd'hui
        « run the given tests in the same block », ce qui pousse activement vers les
        `assert` maison même quand le manuel passe
        → réécrit autour de `run_tests(code=src)`. Le flux a été validé dans la vraie
        sandbox avant d'écrire l'exemple (échec → `{"success":false,"output":"Test 1/3
        failed: AssertionError: ..."}`, `src` persiste entre les steps, `final_answer(src)`
        rend la source testée).
        Point de conception : **une seule variable `src`**, passée à `run_tests` puis à
        `final_answer`. Ça supprime une classe d'erreur entière — soumettre une source
        différente de celle qu'on a testée.
  - [ ] Le serveur MCP `mbpp_methodology` de bclairot (`mcp_tools_mbpp.py:104`) documente
        déjà le workflow en 6 étapes autour de `run_tests` — jamais récupéré, faute de
        savoir que `get_prompt()` existe. Vérifier avec lui si c'est lui qu'il faut charger
        plutôt que de dupliquer la méthodologie dans notre prompt
  - [ ] Conséquence §6 : tant que ça tient, un run MBPP lance le serveur MCP en sous-processus
        pour rien, et toute mesure « avec vs sans outils » mesurerait deux fois la même chose
- [x] **`max_wall_time_seconds` doit définir un timeout, pas seulement un constat.**
      Aujourd'hui il n'est lu que par `check_budget()` (`src/agent_loop.py:428-433`), donc
      *après* que la requête soit revenue. Le seul timeout réel est le `60.0` en dur de
      `OpenAICompatibleProvider.__init__` (`llm/provider.py:88`), que `make_llm()` ne
      surcharge même pas : il ne sait rien du budget de la tâche.
      C'est le pendant exact du point §1.4 pour le temps — la boucle plafonne déjà la
      sortie (`plafond_sortie()`) et l'entrée (`vue_dans_budget()`) sur le budget restant,
      il manque le troisième :
  - [x] `delai_restant(start)` → `max_wall_time_seconds - (monotonic() - start)`, passé en
        `timeout` de la requête (le provider relit `self.timeout` à chaque `complete()`,
        comme il relit la clé : même point d'accroche)
        → fait : `delai_restant()` = min(`start + max_wall_time`, `deadline` du process) − marge. Le timeout de chaque requête suit l'échéance. `deadline` vient des CLI (`PROCESS_START + MAX_WALL_TIME`) : la moulinette chronomètre depuis le lancement, pull d'image compris
  - [x] Vérifier le délai restant **dans la boucle de bascule** aussi : `while True`
        (`src/agent_loop.py:217-279`) réessaie sans jamais regarder l'heure. Sur MBPP
        (120 s) une cascade de 429 peut enchaîner 9 modèles × N clés × 60 s sans qu'aucun
        `check_budget()` ne s'intercale — `MAX_CONSECUTIVE_ERRORS = 3` borne la boucle
        externe, pas celle-là
        → fait : `check_budget()` à chaque tentative de la boucle de requêtes (rotation, attente, bascule)
  - [x] Garder une marge pour écrire `solution.json` : dépasser le wall-time n'est pas un
        échec propre comme le dépassement de tokens (qui rend un `SolutionOutput` avec
        `error`), c'est la moulinette qui tue le process — donc **aucune sortie du tout**
        → fait : `MARGE_SORTIE_SECONDS = 10` ; les deux CLI écrivent `solution.json` **avant** de fermer la sandbox (l'arrêt du conteneur prend ~10 s)

## 4. `agent_swebench` (§mobenais.6) — CLI écrite, 3 tâches résolues sur 3

> Les packages sont dans `Agent/` (`Agent/agent_mbpp/`, `Agent/agent_swebench/`).
> `pyproject.toml` les déclare en `"Agent/agent_mbpp"` / `"Agent/agent_swebench"` : hatchling
> les installe comme modules racine, donc `uv run python -m agent_swebench` marche depuis la
> racine, comme le lance la moulinette (`moulinette/quickstart.sh:78`). Cassé entre le
> déplacement et ce fix (« No module named agent_swebench » vu via `quickstart.sh`).

- [x] Créer le package `agent_swebench/` + l'ajouter à `packages` dans `pyproject.toml`
      → l'ancien `sw-bench_agent/` renommé (`git mv`) : le tiret le rendait inimportable par
      `python -m`. Depuis déplacé dans `Agent/` (cf. encadré ci-dessus).
      Corrigé au passage : `SW_BENCH_TOOLS` (`schemas/tools/limits.py:13`, alors dans `tools_agent.py`) pointait vers
      `mcp_tools_sw_bench.py`, qui n'existe pas → `mcp_tools_swebench.py`
- [x] CLI `uv run python -m agent_swebench --task-file ... --output ... --model-name ... --provider-url ...`
      → `Agent/agent_swebench/__main__.py`, calqué sur `agent_mbpp`. Sort en **code 1** sur
      erreur (l'ancien `except` rendait 0 : la moulinette croyait l'agent fini sans
      `solution.json`). `agent_mbpp` corrigé pareil au check-up du soir (code 1 sur erreur).
      Cible `make run_sw-bench` corrigée (`agent_sw-bench` → `agent_swebench`, variable
      `SWE_TASK ?= cache/swebench_task.json` au lieu du `TASK` MBPP)
- [x] Chargement `SWEBenchTaskInput`, lancement du serveur MCP SWE-bench avec **`TESTBED_PATH`
      dans l'environnement du sous-processus**
      → **cause** : `src/mcp_client.py:85` crée `StdioServerParameters(command, args)` sans
      `env`, et le SDK MCP ne passe alors qu'une liste blanche (`HOME`, `PATH`…).
      **Contourné** dans `mcp_stdio_command()` : préfixe `env TESTBED_PATH=<valeur>`
      (défaut `/testbed`). Vérifié en réel : 9 outils chargés, `pwd` → `/testbed`.
      Le vrai fix (`env=` dans `MCPClient`) reste à proposer à bclairot
- [x] `SolutionOutput(benchmark="swebench", solution=<patch de get_patch()>)`
      → si le modèle ne rend pas un diff valide (`is_patch()` : commence par `diff --git`,
      sans marqueur stderr / exit code / troncature), repli sur `get_patch()` relu dans le
      conteneur **avant** `sandbox.close()` — les `edit_file` déjà faits ne sont pas perdus
- [x] Limites **30 iter / 300k in / 10k out / 900 s** → `schemas/tools/limits.py:15-18`,
      importées en tête de module. En plus : timeout sandbox à 90 s par bloc (les 30 s par
      défaut tueraient un bloc `run_tests()` + `get_patch()`)
- [x] Prompt SWE-bench + méthodologie pas-à-pas lire → chercher → hypothèse → éditer → tester
      → `SYSTEM_PROMPT_SWEBENCH` (`schemas/tools/prompts.py:67`). Pas repris le
      `swebench_methodology` de bclairot : jamais chargé côté agent, même question qu'en §3
- [x] **Premier run réel : 0 outil, 23 itérations pour rien.** `SyncMCPClient.start()`
      n'attend que **10 s** (`src/mcp_sync_client.py:102`) et le serveur démarre son
      conteneur avant de répondre : le pull de l'image (4,2 Go) a fait expirer la session,
      `Sandbox` a avalé l'erreur et l'agent a tourné sans outils (69k tokens brûlés).
      Mesuré image présente : démarrage serveur ~2,3 s. Corrigé côté CLI :
  - [x] `ensure_image()` tire l'image **avant** d'ouvrir la session (0,02 s si déjà là)
  - [x] arrêt immédiat en erreur si `sandbox.tool_names` est vide
- [ ] Trois points à signaler à bclairot (ses fichiers) :
  - [ ] timeout de session à 10 s trop court pour SWE-bench (`src/mcp_sync_client.py:102`)
  - [ ] **conteneurs jamais supprimés** : `cleanup()` fait stop puis remove, mais le serveur
        est tué pendant le `stop` (jusqu'à 10 s) → conteneur `Exited (137)` laissé à chaque run
  - [ ] `DockerManager` démarre le conteneur **avant** de lire `TESTBED_PATH` : si la
        variable manque, il lève et le conteneur reste orphelin
- [x] `400 Bad Request` sur `openai/gpt-oss-20b` (vu 2 fois) : pas un quota, un paramètre
      de requête refusé par ce modèle — à identifier
      → **ni `stop`, ni un message assistant vide** : testés à la main (3 + 2 requêtes, toutes 200). Cause inconnue ; la boucle garde maintenant le **corps** de l'erreur HTTP dans le log et `last_error`, le prochain 400 dira pourquoi
- [x] **Premier run résolu de bout en bout : `django__django-9296`** (via `quickstart.sh`)
      → patch `Paginator.__iter__` dans `django/core/paginator.py`, `RESOLVED_FULL`.
      22 itér / 30 · 104k / 300k in · 914 / 10k out · 236 / 900 s · 22 requêtes.
      Soit ~4,7k tokens d'entrée par itération **avec** outils : 1/3 du budget → la
      compaction LLM reste inutile
- [x] **Deuxième run résolu : `django__django-11066`** (via `quickstart.sh`, validé par
      `scripts/validate_swebench.py`) → `content_type.save(using=db, update_fields=...)`,
      le fix suggéré par l'issue. `RESOLVED_FULL`, 4 tests OK dont
      `test_existing_content_type_rename_other_database`.
      7 itér · 19k in · 329 out · 83 s · 9 requêtes (2 bascules sur 503 Gemini)

      | tâche | itér | tokens in | temps | résultat |
      |---|---|---|---|---|
      | django__django-9296 | 22 | 104k | 236 s | RESOLVED_FULL |
      | django__django-11066 | 7 | 19k | 83 s | RESOLVED_FULL |
      | sympy__sympy-14711 | 25 | 169k | 150 s | RESOLVED_FULL |
- [x] **Troisième run résolu : `sympy__sympy-14711`** (1ʳᵉ des 3 tâches de mise au point)
      → `if other == 0: return self` dans `Vector.__add__`. `RESOLVED_FULL`, 4 tests OK.
      25 itér / 30 · 169k / 300k in · 3,8k out · 150 s · 26 requêtes, sur
      `gemini-3.5-flash-lite` après un 503. Déroulé (lu dans `steps`) :
      exploration 1-12 (dont `_check_vector` lu/cherché 3 fois), 1ʳᵉ édition en 14 dans
      `_check_vector` → **récursion infinie** (`==` → `__eq__` → `_check_vector`) vue par
      `run_tests()` en 15, fix dans `__add__` en 19, retrait de la 1ʳᵉ édition en 22,
      tests OK en 23, `print(get_patch())` en 24, `final_answer` en 25.
      Ce qu'il en ressort :
  - [ ] **Budget plus serré que sur django** : 56 % des tokens d'entrée, 25/30 itér. La
        requête passe de 1k à 18k tokens. Pas de compaction LLM pour autant, mais
        surveiller ce chiffre sur `sympy-13480` / `xarray-4629`
  - [x] **1 itération entre « tests OK » et `final_answer`** (métrique §6, idéal 0) :
        dire dans `SYSTEM_PROMPT_SWEBENCH` d'appeler directement `final_answer(get_patch())`
        dès que `run_tests()` passe, sans afficher le patch avant
        → fait : `SYSTEM_PROMPT_SWEBENCH` dit « your NEXT block is only final_answer(get_patch()) … Do not print the patch first »
  - [x] **2 itérations perdues sur des réponses vides** (`llm_output: ''`, étapes 2 et 13,
        `gemini-3.5-flash-lite`) : l'extraction n'y peut rien. Relancer la requête sur une
        réponse vide au lieu de brûler une itération (compter la relance dans `retries`)
        → fait : réponse vide relancée (`MAX_REPONSES_VIDES = 2`), ses tokens comptés dans le step, la relance dans `retries`
- [x] **La validation de la moulinette échoue sur ce poste quel que soit le patch** :
      `500 … failed to Lchown "/tmp/patch.diff" for UID 103940 … invalid argument`.
      Ce n'est **pas** la fermeture de notre conteneur (la moulinette en crée un neuf,
      `interact.py:411-418`). Cause : Docker **rootless** (`docker info` → `rootless`),
      plage subuid de 65536 (`/etc/subuid`), et `copy_to_container` de swebench tarre le
      fichier avec l'UID hôte 103940 → le patch n'entre jamais dans le conteneur.
      **Aucun `sudo` en jeu** (rien dans le repo) : c'est l'absence de root qui bloque.
      Deux démons sur ce poste : `dockerd` système en root (inaccessible, pas dans le
      groupe `docker`) et **mon** `dockerd` rootless, visé par
      `DOCKER_HOST=unix:///run/user/103940/docker.sock`. Un Docker root ferait le `lchown`
      sans broncher : la moulinette marche telle quelle sur une machine rootful.
      L'agent, lui, n'est pas touché (il n'utilise que `exec`, pas de copie par archive).
      → `scripts/validate_swebench.py` : appelle la **vraie** `validate()` de la moulinette
      (même notation FAIL_TO_PASS / PASS_TO_PASS, mêmes limites), en remplaçant seulement
      `copy_to_container` en mémoire par une version root:root. Sans toucher la moulinette :
      `uv run --project moulinette python scripts/validate_swebench.py <task> <solution>`
  - [ ] **À vérifier avant l'exam** : si la machine d'évaluation a le même Docker rootless,
        la validation SWE-bench y échoue pour tout le monde — à signaler
  - [ ] Nettoyage : la validation ratée laisse son conteneur **en marche** (l'exception
        part avant le `try/finally` de la moulinette), et chaque run agent laisse un
        `Exited (137)` (bug `cleanup()` ci-dessus). 7 conteneurs en trop après 2 runs
        (images de ~4 Go sur `/goinfre`) → tous supprimés le 2026-09-21 à la main.
        À refaire après chaque série de runs du §6 tant que bclairot n'a pas corrigé :
        `docker ps -a | grep sweb` puis `docker rm -f <id>`
- [~] Mise au point sur `sympy__sympy-14711`, `sympy__sympy-13480`, `pydata__xarray-4629`
      → **sympy-14711 résolu** (ci-dessus). Restent sympy-13480 et xarray-4629
- [~] Objectif **2/3** → 3/3 sur les tâches tentées avec outils (django-9296,
      django-11066, sympy-14711) ; à confirmer sur les 2 tâches de mise au point restantes

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
        large — c'est le chiffre à régler.
        **Correction :** il ne se règle **pas** depuis `agent_swebench` — le serveur est
        lancé en sous-processus et son `__main__` n'expose aucun `--max-std-length`
        (`mcp_tools_swebench.py:415-450`). Il faut ce flag côté bclairot. À ne demander
        que si la mesure montre que 10000 pèse
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
      → **Décidé : on ne le fait pas tant qu'on tient dans les budgets.** Rediscuté ce soir
      (LLM résumeur sur un provider dédié) : le seul run montre ~3k tokens / itération
      (69k / 23, sans outils), loin des 300k, et l'échec venait des **quotas**, qu'un appel
      de plus aggraverait. Se rouvre seulement si un vrai run avec outils sort du budget.
      Conditions gardées ci-dessous pour ce cas-là, plus : ne résumer chaque observation
      **qu'une fois**, quand elle sort de la fenêtre, et repli sur la troncature mécanique
      si le résumeur échoue
  - [ ] sur une **clé / un provider dédié**, jamais présent dans le pool de bascule de l'agent
        (sinon contention au pire moment) — les quotas free tier sont par clé sur fenêtre
        glissante, donc l'ordre de rotation ne « reset » rien, seule une clé séparée isole
  - [ ] un petit modèle rapide suffit : résumer ne demande aucun raisonnement
  - [ ] **compter l'appel dans `total_requests`** — la moulinette le définit comme
        « Total number of LLM API requests made (including retries) »
        (`moulinette/models_public.py:40`), et §C.3 range les métriques fausses en grade 0
  - [ ] le déclarer explicitement dans le README et le `BENCHMARK_REPORT`

## 5. Couche LLM (§mobenais.1) — marche, mais pas au niveau demandé

- [x] `class TokenRotator` : `next_key()` / `mark_rate_limited(key, retry_after)` /
      `mark_exhausted(key)` — aujourd'hui la rotation est inline dans `AgentLoop.run()` et
      propagée par **mutation de `os.environ`**, c'est ça qu'il faut extraire
      → `llm/rotator.py` : `premiere_cle()` / `cle_suivante()` / `position()`, une position **par fournisseur** (avant : un seul `key_index` partagé). La clé active reste posée dans `os.environ` que le provider relit : c'est le seul point de contact, la boucle ne touche plus l'env
- [x] Backoff temporisé + respect de `Retry-After` (aujourd'hui retry immédiat)
      → en mode `NO_BASCULE` seulement : attente `Retry-After` (sinon 2, 4, 8 s), plafonnée à `ATTENTE_MAX_SECONDS` et au temps restant, `MAX_ATTENTES` fois. En mode normal on bascule tout de suite (plus rapide à l'exam)
- [x] Couvrir les timeouts réseau (`httpx.RequestError`), non gérés
      → `httpx.RequestError` (timeout, coupure) traité comme un 5xx : bascule, ou attente en `NO_BASCULE` ; l'échéance est revérifiée avant
- [x] `LLMResult` : ajouter `retries`, `api_url`, `model_name` — la boucle les recompose à la main
      → `model_name` et `api_url` remplis par le provider, repris dans `StepMetrics` ; `retries` reste compté par la boucle (c'est elle qui relance)
- [x] Généraliser les pools `gemini_pool` / `groq_pool`, encore nommés en dur
      (`src/agent_loop.py:191-192`)
      → un pool par fournisseur construit depuis `PROVIDERS` (`self._pools`), plus rien en dur
- [x] Créer `.env.example` : documenter `GEMINI_API_KEYS` / `GROQ_API_KEYS`
      (listes séparées par virgules) en plus des clés simples
      → restauré (il avait été supprimé du working tree) et complété avec les deux variantes
      au pluriel + un commentaire sur la rotation, relu contre `src/agent_loop.py:225-232`
      (lecture via `provider.keys_env`, clé suivante avant bascule de modèle)

## 6. Benchmark et rapport (§C.1) — pilote mobenais

`BENCHMARK_REPORT.md` (racine, nom imposé par le sujet V.7) : tableaux **générés** par
`scripts/benchmark_report.py` entre des marqueurs `<!-- AUTO:<label>:... -->`, le texte
autour s'écrit à la main et n'est jamais écrasé. Données : `BENCHMARK/<label>/<modèle>/<tâche>/`
(`solution.json`, logs, `verdict.txt`). Une case `INDISPO` (quota) est retentée au
prochain `make bench`. Le `BENCHMARK/BENCHMARK.MD` vide créé à la main n'est pas utilisé.

- [x] ≥ 5 modèles × ≥ 3 tâches SWE-bench identiques
      → outillé et **lancé** le 2026-09-21 (`make bench` = `scripts/run_benchmark.sh`) : 5 modèles × 3 tâches, `NO_BASCULE=1`, résultats dans `BENCHMARK/main/`, tableaux générés dans `BENCHMARK_REPORT.md`
- [ ] Setup : modèles, providers, tâches choisies **et pourquoi**
- [~] Table par couple modèle × tâche : Pass/Fail · itérations · tokens in · tokens out · wall-clock
      → générée ; se remplit au fil des runs
- [~] Fiabilité provider : temps de réponse moyen, retries, disponibilité
      → générée (formules écrites sous le tableau) ; se remplit au fil des runs
- [~] Métriques intermédiaires (le sujet en veut ≥ 2) → générées : **1er contact / 1re
      édition** du fichier patché (exploration) et **discipline** (itérations entre le 1er
      `run_tests()` OK et `final_answer`). Vérifié sur le run sympy-14711 : 3 / 14 / 1,
      identique à l'analyse à la main. La détection « tests OK » est une heuristique
      (sympy / unittest / pytest) : « ? » si le résumé a été tronqué
- [ ] Ablation — « avec vs sans compaction » **ne tient plus** (compaction LLM abandonnée).
      Candidats : fenêtre glissante (`LAST_ITER_INTACTS`) ou la consigne « final_answer
      direct » du prompt SWE, même modèle / mêmes tâches, via
      `RUN_LABEL=ablation_x make bench`
- [ ] Committer les `solution.json` correspondants

## 7. README (§C.2)

- [ ] Section « Benchmark Results and Analysis » : n'est qu'un `TODO: A remplir`
      (`README.md:296-298`) — dépend du point 6
- [x] Section « Agent Loop » écrite
- [ ] La relire une fois la troncature en place : la description de la boucle ne sera plus à jour

## 8. Divers exam / soutenance

- [ ] `exam_mbpp.sh` n'a **jamais** été lancé (3/3 sur des tâches maison ≠ 4/5 sur l'exam)
- [ ] Repasser la checklist grade 0 §C.3 (`sandbox_output` désormais complet : sortie
      partielle, timeout et troncature, cf. check-up §3) : clés en dur, libs d'orchestration interdites,
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
  (déjà noté dans `TODO.md` §0.5 et §bclairot.7) — cause et contournement notés au §4 ;
  plus bloquant grâce au préfixe `env`, mais le vrai fix reste chez lui.

---

## Point d'étape (relecture du 2026-09-21)

Fait cette nuit : **le point 1 (troncature) à 4 items sur 5** — c'est le seul bloc entamé,
mais c'était bien celui dont dépendait tout le reste. Le point 3 avance d'un item, le
`.env.example` est à moitié fait.

Rien sur les points 2, 4, 6, 8 : `agent_swebench/` n'existe pas, `BENCHMARK_REPORT.md`
non plus, `extract_code` est inchangé.

**Mise à jour (après-midi) :** préalables du §4 levés — package `agent_swebench/`
importable et déclaré dans `pyproject.toml`, chemin `SW_BENCH_TOOLS` corrigé,
`.env.example` complet, cause du `TESTBED_PATH` identifiée (`src/mcp_client.py:85`).
Prochaine étape : écrire la CLI et faire un premier bout-en-bout sur `sympy__sympy-14711`.

Ajouté au §3 après relecture : `max_wall_time_seconds` ne sert nulle part de timeout, il
n'est que constaté a posteriori. Des trois limites du sujet, c'est la seule qui, dépassée,
ne produit pas de `solution.json` — donc la plus coûteuse à laisser non bornée.

Ajouté au §3 aussi, et c'est le plus gros : **`agent_mbpp` n'utilise pas les outils de
bclairot.** Pas un choix, un effet de bord — `compact_manual()` supprime la section outils
du manuel avant qu'elle n'atteigne le modèle. Le 3/3 revendiqué sur les tâches maison a
donc été obtenu *sans* `run_tests`, ce qui change ce que ce chiffre vaut.

~~**Bloquant immédiat :** `import src.agent_loop` lève un `ImportError`~~ — réglé,
les drapeaux de debug sont décommentés, `import src.agent_loop` passe.

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

### Coût total après le prompt réécrit

Le prompt est passé de 1160 à 1344 caractères, donc le `system_prompt` complet
(prompt + manuel) va de **1607 à 2071 caractères, ~500 → ~645 tokens par requête**, soit
**~+1445 tokens sur 10 itérations = 24 % du budget**. C'est le même ordre de grandeur que
ce que j'avais refusé en descendant le manuel de 700 à 250 — à assumer explicitement.

Le pari qui le justifie, en deux temps :
- chaque bloc de code se réduit à `src = "..."` + `print(run_tests(code=src))`, au lieu de
  la fonction **plus** les `assert` maison **plus** les `print`. Les tokens de *sortie* et
  ceux des observations baissent donc à chaque tour — le run enregistré montrait ~110
  tokens de croissance par tour, c'est ce chiffre qui doit descendre ;
- et une itération économisée vaut 500-800 tokens.

**Rien de tout ça n'est encore mesuré.** C'est exactement la mesure du §1.5 : la lancer sur
`uno`/`dos`/`tres` puis sur de vraies tâches MBPP, et comparer croissance par tour et
nombre d'itérations avant/après. Si le pari est faux, le levier de repli est
`MAX_LIMITES_CHARS` (250 → 0 : le prompt nomme déjà `run_tests`, le manuel ne sert plus
qu'à `check_syntax` et aux imports autorisés).

---

## Point d'étape (soir du 2026-09-21)

**Point 4 : la CLI `agent_swebench` est écrite** (prompt, limites, `TESTBED_PATH`, repli sur
le patch du conteneur, code de sortie). Vérifié de bout en bout **sans LLM** : sandbox →
serveur MCP → conteneur, 9 outils, `/testbed`. **Jamais vérifié avec un LLM** : le seul
run a d'abord tourné sans outils (timeout de session pendant le pull), puis tout est
tombé en 429/503.

Réorganisation au passage :
- les constantes de `tools_agent.py` éclatées en `schemas/tools/limits.py` (budgets,
  réglages de boucle), `schemas/tools/prompts.py` (prompts, `END_CODE`) et
  `schemas/tools/tools_agent.py` (logique, modèles autorisés, flags de debug) ;
- idée écartée : générer ces constantes au `make install` — la moulinette ne lance jamais
  `make`, et un fichier généré est une 2e source de vérité.

~~**Bloquant pour l'exam :** `python -m agent_mbpp` / `agent_swebench` ne se lancent plus
depuis la racine depuis le déplacement dans `Agent/`~~ — réglé dans `pyproject.toml`
(encadré du §4), vérifié via `quickstart.sh`.

**Aussi dans le `Makefile` :** `make install` fait `mv .env.example .env` — il **écrase le
vrai `.env`** et supprime `.env.example` (c'est ce qui l'avait fait disparaître) ;
`make fclean` réécrit `.env.example` sans les variantes `*_API_KEYS`. `cp -n` réglerait
le premier.

**À vérifier :** la TODO dit `LAST_ITER_INTACTS = 3`, le code a `10`. À 10, sur MBPP
(10 itérations), la fenêtre glissante ne tronque plus rien.

Prochaine étape : quand les quotas reviennent, `make run_sw-bench` sur `sympy__sympy-14711`
et relever tokens / itération — c'est ce chiffre qui clôt (ou rouvre) la question de la
compaction.

**Mise à jour (19h30) : 1ʳᵉ tâche SWE-bench résolue**, `django__django-9296`, `RESOLVED_FULL`
et métriques valides (22 itér, 104k in, 236 s). ~4,7k tokens / itération avec outils :
**la question de la compaction est close** tant que ça tient. La validation de la
moulinette ne marche pas sur ce poste (Docker rootless, détail au §4) →
`scripts/validate_swebench.py` pour valider localement, à utiliser pour tous les runs du §6.

**Mise à jour (20h30) : 2ᵉ tâche résolue**, `django__django-11066` (7 itér, 19k in, 83 s,
`RESOLVED_FULL`). 2/2 sur les tâches tentées avec outils. `quickstart.sh` affiche toujours
`FAILED` à cause de Docker rootless : la note réelle se lit avec
`scripts/validate_swebench.py`. Conteneurs orphelins nettoyés (7).

**Mise à jour (20h45) : 3ᵉ tâche résolue**, `sympy__sympy-14711` (25 itér, 169k in, 150 s,
`RESOLVED_FULL`). **3/3** sur les tâches tentées avec outils. Ce run est le plus coûteux :
56 % du budget d'entrée et 25/30 itérations, dont 2 perdues sur des réponses vides de
Gemini et 1 à afficher le patch avant `final_answer`. Deux gains faciles notés au §4 (prompt
+ relance sur réponse vide), à faire avant sympy-13480 / xarray-4629.
Rootless : confirmé qu'aucun `sudo` n'intervient — c'est **mon** démon Docker, sans root,
qui ne peut pas mapper l'UID 103940 ; le démon root du poste m'est inaccessible.

**Mise à jour (21h) : check-up du lot.** Un vrai trou corrigé — sur erreur ou timeout, le
LLM ne voyait que `error:` et perdait tout ce qu'il avait imprimé avant, sans jamais savoir
qu'il y avait eu timeout ou troncature (exigé par le sujet) → `observation()`. Aussi :
`agent_mbpp` sort en code 1 sur erreur, vérif des clés unifiée (`has_api_key()`, le
`TESTBED_PATH` dans `API_KEY_VARS` laissait passer un `.env` sans clé), `status` non défini
possible, et nettoyage sans changement de comportement (détail au §3). Vérifié par 6
scénarios faux LLM / fausse sandbox ; **pas encore relancé sur un vrai modèle**.

---

## Point d'étape (nuit du 2026-09-21) — « corrige tout ma partie »

Tout ce qui restait ouvert dans le lot et faisable **sans quota** est fait, vérifié par un
banc faux LLM / fausse sandbox (9 scénarios boucle + 25 réponses réelles de l'extracteur,
somme des tokens des steps = total vérifiée partout) :

- **Wall-time = vraie limite** : échéance = min(`max_wall_time`, lancement du process +
  limite) − 10 s de marge ; timeout de chaque requête calé dessus ; vérifiée à chaque
  tentative ; `solution.json` écrit **avant** la fermeture de la sandbox. La seule limite
  qui, dépassée, ne laissait aucune sortie.
- **Couche LLM** : `TokenRotator` (`llm/rotator.py`), pools génériques depuis `PROVIDERS`,
  erreurs réseau gérées, `LLMResult` porte `model_name` / `api_url`, attente
  `Retry-After` en mode `NO_BASCULE`.
- **Réponses vides** relancées (tokens comptés), **prompt SWE** : `final_answer` direct.
- **400 gpt-oss-20b** : ni `stop` ni message vide ; le corps de l'erreur est maintenant logué.
- **Makefile** : `make install` fait `cp -n` (n'écrase plus le `.env` et ses clés) ;
  `make bench`.
- **Benchmark lancé** en arrière-plan (`make bench`, 5 modèles × 3 tâches, `NO_BASCULE`).

Reste à la main : sections Setup / Ablation / Conclusions de `BENCHMARK_REPORT.md`
**depuis les chiffres réels**, l'ablation (2ᵉ série de runs), le README, `exam_mbpp.sh`,
et le commit (le tien).

**Mise à jour : 1er passage du benchmark (`BENCHMARK/v1`)**, 15 cases, `NO_BASCULE`.
Résultats bruts : qwen3.8-27b 3/3 PASS, gemini-3.5-flash-lite 2 PASS + 1 INDISPO,
gpt-oss-120b 1 PASS + 2 FAIL, gemini-3.5-flash et gemini-3.6-flash **0/3 disponibles** (429 /
503 / réseau : quota Gemini du jour épuisé). Le log du corps HTTP ajouté plus tôt a
**résolu le 400** et révélé deux vrais défauts, corrigés :
- **gpt-oss = outils natifs** : il répond par un appel JSON (`container.exec`,
  `repo_browser.search_code`), Groq le rejette en 400 `tool_use_failed` (on envoie
  `tool_choice: none`) mais renvoie la génération dans `failed_generation`. →
  `llm/provider.py::_generation_refusee` la rend en `<tool_call>` : l'extracteur la
  convertit en appel Python, la sandbox dit au modèle si l'outil n'existe pas (tokens
  estimés chars/4, faute d'`usage` dans une erreur). Les 2 FAIL de v1 = 0 itération.
- **qwen = 413 ITPM** (« Limit 7000, Requested 8451 ») compté comme erreur → run arrêté
  après 3. → `reduire_requete()` lit la limite, `vue_dans_budget()` rabote la fenêtre
  sous 90 % et la requête repart.
- Plusieurs PASS de v1 viennent du **repli `get_patch()`** (pas de `final_answer`) :
  colonne `final_answer` ajoutée au tableau pour les distinguer.

→ **v1 (avant) vs v2 (après ces deux correctifs), mêmes modèles / mêmes tâches = l'ablation
du §6**, avec des données réelles. `v2` lancé (`RUN_LABEL=v2 make bench`).
Les cases Gemini `INDISPO` se retentent en relançant la commande quand le quota revient.
