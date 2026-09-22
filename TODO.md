# Agent Smith — Checklist binôme

> Répartition en **deux lots** :
> - **Lot mobenais — Côté Agent** (LLM, extraction, boucle, prompts, CLIs, benchmark)
> - **Lot bclairot — Côté Exécution** (Sandbox, client MCP, serveurs MCP, outils, Docker)
>
> Les deux lots sont séparés par un **contrat d'interface** défini au jour 1,
> ce qui permet de travailler en parallèle sans se bloquer.

---

# PARTIE 0 — À FAIRE ENSEMBLE (Sprint 0, ~1 journée)

Ne commencez pas à coder chacun de votre côté avant d'avoir fini cette partie.

## 0.1 La frontière entre vos deux lots

```
   ┌───────────────── LOT mobenais ──────────────────┐   ┌────────── LOT bclairot ──────────────┐
   │                                          │   │                               │
   │  agent_mbpp / agent_swebench (CLI)       │   │   Sandbox                     │
   │             │                            │   │    ├─ sécurité (imports, FS,  │
   │  AgentLoop ─┼─ LLMProvider (multi-keys)  │   │    │   réseau, timeout, RAM)  │
   │             ├─ extract_code() 4 formats  │   │    ├─ final_answer()          │
   │             └─ system prompts            │   │    ├─ REPL `uv run sandbox`   │
   │                                          │   │    ├─ get_manual()            │
   │             ┌────── FRONTIÈRE ───────────┼───┤    └─ MCPClient (stdio+HTTP)  │
   │             │                            │   │                               │
   │   sandbox.execute(code) ─────────────────┼──►│   mcp_tools_mbpp.py           │
   │   sandbox.get_manual() ──────────────────┼──►│   mcp_tools_swebench.py       │
   │   ◄──────────────── ExecutionResult      │   │   DockerManager               │
   └──────────────────────────────────────────┘   └───────────────────────────────┘
```

**mobenais ne touche jamais** à ce qui est dans le lot bclairot, et inversement.
La seule chose que mobenais connaît de bclairot : `Sandbox.execute()`, `Sandbox.get_manual()`, `Sandbox.close()`.

## 0.2 Les 5 malentendus à lever avant de coder (les deux doivent les avoir compris)

- [ ] **La sandbox contient le client MCP**, pas l'inverse : *« The sandbox wraps the MCP client, not the other way around. »*
- [ ] **`final_answer()` n'est PAS un outil MCP.** C'est une fonction injectée par la sandbox, toujours présente quel que soit le serveur MCP connecté.
- [ ] **Deux domaines de sécurité distincts.** La sandbox restreint le *code Python généré par le LLM*. Les outils MCP tournent **en dehors** de la sandbox → le timeout sandbox ne s'y applique pas, et `run_command` peut lancer des process.
- [ ] **Le manuel est généré dynamiquement** depuis `list_tools()` du serveur MCP connecté, jamais écrit en dur.
- [ ] **Le système sera testé avec un serveur MCP inconnu** → zéro nom d'outil hardcodé dans la sandbox ni dans l'agent.

## 0.3 Setup commun

- [x] Repo git, branches `feat/agent` (mobenais) et `feat/sandbox` (bclairot)
- [x] Python **3.10** exactement, `uv` comme gestionnaire de paquets
- [x] `pyproject.toml` avec les entry points :
  - [x] `sandbox = "agent_smith.sandbox.cli:main"` → `uv run sandbox`
  - [ ] `agent_mbpp` et `agent_swebench` importables → `uv run python -m agent_mbpp`
        *(`src/agent_MBPP.py` existe mais est vide (0 octet) et non commité ; aucun entry point
        dans `pyproject.toml`, qui n'expose que `sandbox`)*
- [x] `.env.example`, `.gitignore` (`.env`, `cache/`, `evaluations/`)
- [x] `sandbox_template.json` à la racine
- [x] `mcp_tools_mbpp.py` et `mcp_tools_swebench.py` à la racine (imposé par le sujet)

## 0.4 Modèles Pydantic — à écrire ensemble, personne ne les modifie seul ensuite

Fichier `schemas/` — c'est le contrat avec la moulinette.

- [x] `SandboxConfig` (copier la définition exacte du sujet)
- [x] `MBPPTaskInput`, `SWEBenchTaskInput`
- [x] `StepMetrics` — tous les champs : `step`, `input_tokens`, `output_tokens`,
      `request_time_ms`, `timestamp`, `api_url`, `model_name`, `llm_output`,
      `sandbox_input`, `sandbox_output`, `retries`
- [x] `SolutionOutput` — dont `system_prompt`, `steps`, `error`

## 0.5 Contrat d'interface — à écrire ensemble, jour 1

C'est le fichier le plus important du projet pour un binôme.

```python
# agent_smith/contract.py
from typing import Protocol
from pydantic import BaseModel

class ExecutionResult(BaseModel):
    stdout: str = ""
    stderr: str = ""
    error: str | None = None          # message d'erreur formaté POUR le LLM
    final_answer: str | None = None   # non-None => la boucle agent s'arrête
    timed_out: bool = False
    truncated: bool = False
    duration_ms: float = 0.0

class SandboxProtocol(Protocol):
    def execute(self, code: str) -> ExecutionResult: ...
    def get_manual(self) -> str: ...
    def close(self) -> None: ...
```

- [x] Décider ensemble **comment le serveur MCP MBPP reçoit la tâche** (il a besoin
      de `test_list` pour `run_tests`). Retenu :
      `python mcp_tools_mbpp.py --task-file ../cache/mbpp_task.json`. mobenais lance le process.
- [x] Même décision pour SWE-bench : comment le serveur reçoit `docker_image`,
      `eval_script`, `TESTBED_PATH` (env vars ou args CLI). `mcp_tools_swebench.py`
      reprend la même convention `--task-file` que MBPP pour `docker_image`/
      `eval_script` (via `SWEBenchTaskInput`) ; `TESTBED_PATH` est lu depuis
      `os.environ["TESTBED_PATH"]` dans `DockerManager.__init__`, exactement le
      nom de variable imposé par le sujet (p.19). **Mais** : ce n'est vérifié que
      quand le serveur est lancé en process direct — voir le nouveau point ouvert
      dans bclairot.7 (la variable ne traverse pas la frontière `--mcp-stdio`).
- [~] Décider qui construit l'objet `Sandbox` : mobenais dans son CLI, à partir des args
      `--mcp-stdio` / `--mcp-server`. CLI `sandbox` (bclairot) le construit et les args
      MCP sont maintenant branchés (`Sandbox(config=..., command_stdio=..., url=...)`) ;
      côté mobenais, `AgentLoopConf`/`src/__main__.py` construit encore un `Sandbox()`
      nu, sans jamais passer `--mcp-stdio`/`--mcp-server`.

## 0.6 Répartition des fichiers (évite les conflits git)

| Chemin | Propriétaire |
|---|---|
| `schemas/`, `contract.py` | **commun** (modif = accord des deux) |
| `llm/`, `agent/`, `agent_mbpp/`, `agent_swebench/` | **mobenais** |
| `sandbox/`, `mcp/`, `mcp_tools_*.py`, `docker/` | **bclairot** |
| `sandbox_template.json` | **bclairot** |
| `BENCHMARK_REPORT.md` | **mobenais** (ablation par bclairot) |
| `README.md` | **commun** (chacun ses sections) |

---

# LOT mobenais — CÔTÉ AGENT

## mobenais.0 Bloquants et bugs relevés — audit du 2026-09-08

- [x] ~~🔴 BLOQUANT — la chaîne agent ne démarre plus (`TypeError` sur `MCPClient`).~~
      **Levé le 2026-09-09** : `src/sandbox.py:41` passe `stdio` en positionnel sur
      `server_path`, donc pas de `TypeError`. `Sandbox()` se construit et
      `execute("print(1+1)")` renvoie `stdout='2\n'`.
- [~] ~~🔴 **Reste bloquant : le MCP n'est jamais branché.**~~ **Levé le 2026-09-16 sur le
      chemin moulinette** : `server_path` a disparu de la signature (bclairot, PR #14), et
      `agent_mbpp/__main__.py` construit maintenant
      `Sandbox(command_stdio=mcp_stdio_command(args.task_file))` puis le passe à
      `AgentLoopConf` — `run_tests`/`check_syntax` apparaissent dans `get_manual()`.
      **Reste** : le défaut d'`AgentLoopConf` est toujours un `Sandbox()` nu, donc
      `uv run -m src` tourne encore sans aucun outil ; et `agent_swebench` reste à câbler
      (avec `TESTBED_PATH` dans l'environnement du sous-processus serveur, cf. §bclairot.10).
- [x] ~~`AgentLoopConf` **ignore le `llm` qu'on lui passe** : `schemas/agent_class_monitoring.py:27`
      force `GeminiLLM("gemini-3.1-flash-lite")` alors que `model_name = random.choice(models_name)`
      → le `model_name` écrit dans `StepMetrics` n'est pas le modèle réellement interrogé
      (métriques de benchmark faussées, et provenance douteuse pour la correction).~~
      **Corrigé le 2026-09-10** : le `llm` passé est retenu tel quel, et `model_name` en est
      dérivé (`self.model_name = self.llm.model`) au lieu d'un tirage indépendant — une seule
      source de vérité, quel que soit le provider. `model: str` ajouté à `LLMProtocole`
      (`schemas/contract_model.py`, fichier commun → à signaler à bclairot).
- [x] ~~**Limites par défaut hors sujet**~~ **Corrigé le 2026-09-16** : les défauts
      d'`AgentLoopConf` sont désormais 10 / 6k / 1.5k / 120 s. Les tâches de mise au point de
      `src/__main__.py`, qui débordent ce cadre par construction, passent leurs limites
      explicitement — c'est le cas « sujet » qui doit être atteint sans rien configurer.
- [~] ~~`init_value()` **recharge les compteurs de tokens** depuis `backup_memory/backup.json` :
      un run précédent crashé gonfle les totaux du run suivant → dépassement de budget fantôme
      à la correction.~~ **Corrigé le 2026-09-14** pour les autres tâches : `init_value()` et
      `init_history()` fusionnés en `load_backup(task_id)`, qui ignore tout backup d'une autre
      tâche ou sans `task_id` (compteurs, modèle et historique). Une même tâche reprend
      historique, `steps`, compteurs et modèle précédent (`RELAIS_MODELE` injecté).
      **Corrigé le 2026-09-16** : `AgentLoop.run()` prend un `resume: bool = True`, et
      `agent_mbpp` passe `resume=False` — le backup ne peut plus primer sur `--model-name`.
- [~] ~~Le budget est vérifié **après** l'appel LLM~~ **Corrigé le 2026-09-16** :
      `check_budget()` est aussi appelé en tête d'itération, avant d'émettre la requête.
      **Reste** : une requête unique peut toujours franchir la limite à elle seule — c'est la
      troncature d'historique (§mobenais.3) qui réglera ce cas.
- [x] ~~`sandbox.get_manual()` existe côté bclairot mais **n'est appelé nulle part** côté agent
      (cf. §mobenais.4).~~ **Corrigé le 2026-09-10** : composé une fois avant la boucle dans
      `AgentLoop.run()`, compacté par `compact_manual()` (493 → 153 tokens), et c'est le prompt
      composé qui part dans `SolutionOutput.system_prompt`.
- [x] ~~`SYSTEM_PROMPT` est rédigé en français alors qu'il exige des réponses en anglais.~~
      **Corrigé le 2026-09-09** : prompt entièrement en anglais (73 tokens). Le fond reste
      à écrire (cf. §mobenais.4).
- [x] ~~`uv run -m src` part sur un prompt de test (`DEFAULT_TASK`) de type injection —
      à remplacer par une vraie tâche MBPP avant toute démo.~~ **Corrigé** : l'injection
      (« oublie les instructions PRECEDENTE… », `d99ec6e`) a laissé place aux trois tâches
      de mise au point `collatz`/`lcs`/`puzzle`, choisies pour forcer la boucle à découper
      son travail sur plusieurs `execute()`.

## mobenais.1 Couche LLM

> Mis à jour le 2026-09-22. Noms de code en anglais depuis la refonte du même jour
> (`handle_unavailable`, `NO_FALLBACK`, `CHARS_PER_TOKEN`…).

- [x] `LLMResult` : `text`, `input_tokens`, `output_tokens`, `latency_ms`, `model_name`, `api_url`
      *(les `retries` sont comptés par étape dans `StepMetrics`)*
- [x] `class LLMProvider(ABC)` + `OpenAICompatibleProvider` (`llm/provider.py`)
- [x] Abstraction : ajouter un fournisseur = un `ProviderSpec` dans `llm/registry.py`
      *(Mistral ajouté ainsi le 2026-09-22, sans toucher à la boucle)*
- [x] 3 fournisseurs gratuits vérifiés par appel réel : Groq (3 modèles), Gemini (9), Mistral (4)
- [x] **Multi-tokens par provider** : `TokenRotator` (`llm/rotator.py`, `reset_key` / `next_key`),
      clés dans `*_API_KEYS` ou `*_API_KEY` séparées par des virgules
- [x] Bascule dans l'ordre de `AUTHORIZED_LLM` (Groq → Gemini → Mistral) ; clé et URL suivent
      le modèle via `make_llm` ; relais de contexte par `create_newcontext`
- [x] Retry / pannes : 429 → clé suivante ; 404/408/413/429/5xx/réseau → modèle suivant ;
      413 → d'abord historique raccourci ; tous tombés → pause 60 s puis nouveau tour ;
      mode `NO_FALLBACK=1` (benchmark) → 3 pauses de 20 s sur le même modèle
- [x] `stop_sequences` : `<end_code>` et `</tool_call>`
- [x] Usage tracking : tokens, retries, latence, nombre de requêtes
- [x] Free tiers uniquement, **aucune clé en dur**

## mobenais.2 Extraction de code

- [x] `extract_code(text) -> ExtractedCode | None` (`schemas/tools/tools_agent.py`, sans regex)
- [x] Format 1 — bloc Python + `<end_code>`, aussi ```` ```tool_code ```` (Gemini)
- [x] Format 2 — XML Anthropic `<invoke>` / `<parameter>`
- [x] Format 3 — JSON/Hermes `<tool_call>` (et ```` ```json ```` d'appel)
- [x] Format 4 — ReAct `Action:` / `Action Input:`
- [x] `to_python_call(name, args)`
- [x] Tolérance : bloc non fermé, fence sans langage, ```` ``` ```` dans une chaîne, `Code:` sans fence
- [x] Interprétation « de secours » signalée au LLM (`note` préfixée à l'observation)
- [x] Vérifié : 0 différence avec l'ancienne version sur 293 réponses réelles

## mobenais.3 Boucle agent

- [x] `AgentLoop` (`src/agent_loop.py`) : `run`, `ask_model`, `handle_unavailable`, `fit_view`…
- [x] `max_iterations` paramétrable, arrêt sur `final_answer` ou limite, jamais de crash
- [x] Troncature des vieilles observations (`truncate_history`, fenêtre adaptée au budget)
- [x] Solution de repli si limite atteinte : dernier code (MBPP), `get_patch()` du conteneur (SWE-bench)
- [x] Avertissement au modèle quand il reste ≤ 2 itérations ou ≥ 80 % des tokens d'entrée
      (dans le message envoyé seulement, jamais dans `sandbox_output`)

## mobenais.4 System prompts (fortement noté)

- [x] Doc des outils injectée depuis `sandbox.get_manual()` (`compact_manual`)
- [x] Slots `Thought:` / `Code:` / `Observation:` + exemple complet
- [x] Méthodologie pas-à-pas, versions MBPP et SWE-bench
- [x] Prompts MBPP et SWE-bench séparés (`schemas/tools/prompts.py`)
- [x] Ablation prompt vague vs explicite : 5 tâches MBPP × 2 modèles
      (`BENCHMARK/ablation_prompt/`) — codestral 1/5 → 5/5, qwen 5/5 → 5/5 en moins d'itérations

## mobenais.5 CLI agent MBPP

- [x] `uv run python -m agent_mbpp --task-file ... --output ... --model-name ... --provider-url ...`
      + options `--mcp-server <url>` (HTTP) / `--mcp-stdio "<cmd>"`
- [x] Fonctions communes aux deux CLI dans `agent/__init__.py`
- [x] Limites **10 / 6k / 1.5k / 120 s** (`MBPP_LIMITS`, `schemas/tools/limits.py`)
- [x] Objectif **4/5** : **5/5** le 2026-09-22 sur 5 tâches tirées au hasard, lancées comme
      l'examen (`run-agent 120` puis `validate`)

## mobenais.6 CLI agent SWE-bench

- [x] `uv run python -m agent_swebench ...` (mêmes options, dont `--mcp-server`)
- [x] Chargement `SWEBenchTaskInput`, serveur MCP de bclairot lancé avec `TESTBED_PATH`
- [x] `solution` = patch `get_patch()`, avec repli sur le diff du conteneur
- [x] Limites **30 / 300k / 10k / 900 s** (`SWEBENCH_LIMITS`)
- [ ] Objectif **2/3** : examen du 2026-09-22 en cours (pool d'examen, graine 7)
- [x] Tâches de mise au point validées : sympy-14711, sympy-13480, xarray-4629, django-15741

## mobenais.7 Reste à faire / à signaler

- [ ] Relancer les 6 cases Gemini INDISPO de `BENCHMARK/v3` quand le quota quotidien revient
      (`RUN_LABEL=v3 scripts/run_benchmark.sh`)
- [ ] Clés Gemini / Groq sur des projets distincts : aujourd'hui les 5 clés partagent le même
      quota (`...PerDayPerProject...`), la rotation n'apporte pas de capacité
- [ ] **À signaler à bclairot** : le conteneur SWE-bench n'a aucune restriction réseau
      (`src/docker_manager.py`), un `run_command("curl ...")` pourrait sortir. Aucune trace
      dans les 334 étapes enregistrées, mais à fermer (`network_disabled=True`) si les outils
      n'en ont pas besoin
- [ ] **À signaler à bclairot** : `SyncMCPClient.start()` n'attend la session MCP que 10 s
      (`src/mcp_sync_client.py:102`). Sur `scikit-learn-13439`, juste après le pull de l'image,
      le conteneur a démarré trop lentement : « could not launch the session », agent arrêté en
      code 1. À rallonger (30 s ?) ou à rendre configurable

---

# LOT bclairot — CÔTÉ EXÉCUTION

## bclairot.1 Sandbox — classe principale

- [x] `class Sandbox`
  - [~] `__init__(config: SandboxConfig, mcp_client: MCPClient | None = None)` (pas de param `mcp_client`)
  - [x] `execute(code: str) -> ExecutionResult`
  - [x] `get_manual() -> str`
  - [x] `close()`
- [x] **Persistance des variables entre appels à `execute()`** (c'est l'intérêt du code-calling vs JSON tool calling)
- [x] `final_answer(answer)` injecté dans le namespace
  - [x] Implémentation typique : lève `_FinalAnswer(value)`, attrapée par `execute()`
  - [x] Toujours présent, indépendamment du serveur MCP connecté
  - [x] MBPP : `final_answer(code)` — SWE-bench : `final_answer(get_patch())`
        (documenté explicitement dans les prompts `mbpp_methodology`/
        `swebench_methodology` de chaque serveur MCP — pas la sandbox elle-même,
        mais c'est bien de là que l'agent doit l'apprendre)

## bclairot.2 Sécurité — chaque point est testé par `exam_sandbox.sh` (tout-ou-rien)

- [x] **Imports** : allowlist stricte
  - [x] `guarded_import(name, globals, locals, fromlist, level)` remplaçant `__import__` (`_restricted_import`)
  - [x] Gérer les patterns `"math.*"`
  - [x] Bloquer les contournements : `importlib`, `__import__` direct
- [~] **Filesystem** : allowlist de répertoires
  - [x] `is_path_allowed(path, allowed) -> bool` (inline dans `_restricted_open`)
  - [x] ⚠️ **`os.path.realpath` avant comparaison** → sinon `/testbed/../etc/passwd` passe
  - [ ] Wrapper sur `open()`, plus `os.open`, `pathlib.Path.open`, `shutil` (seul `open` est wrappé)
  - [x] Plusieurs entrées (`/testbed` + `/tmp/agent`), évaluées **dans** la sandbox
- [~] **Réseau** : neutraliser `socket.socket`, `socket.create_connection` (`socket.socket` seulement)
- [x] **Timeout** : tuer au-delà de `max_execution_time_seconds` (code sandboxé uniquement)
- [x] **Mémoire** : `resource.setrlimit(RLIMIT_AS, max_memory_mb * 1024 * 1024)`
- [x] **Builtins restreints** : `build_safe_builtins(config) -> dict` (allowlist dans `_make_initial_namespace`)
  - [x] Retirer/écraser `eval`, `exec`, `compile`, `open`, `__import__`, `input`, `breakpoint`, `globals`, `help`
  - [x] Bloquer l'évasion par attributs : `().__class__.__bases__[0].__subclasses__()`
- [x] **Propagation** : `KeyboardInterrupt` et `SystemExit` jamais avalés
  ```python
  except (KeyboardInterrupt, SystemExit):
      raise
  except Exception as e:
      ...
  ```
- [x] **Sécurité en stdlib pure** — `RestrictedPython` et équivalents interdits

## bclairot.3 Choix d'isolation (à défendre en soutenance)

- [x] Trancher : `exec()` in-process vs `subprocess` / `multiprocessing` → **`multiprocessing.Process` + `dill` pour l'état**
  - in-process : simple, mais timeout dur et RLIMIT difficiles à appliquer proprement
  - process séparé : vraie frontière, timeout par `kill`, mais il faut sérialiser l'état
- [x] Documenter le trade-off dans le README (section "Sandbox Design")

## bclairot.4 Feedback explicite au LLM — 5 cas obligatoires

Le champ `error` de `ExecutionResult` doit couvrir :

- [x] Aucun bloc de code valide trouvé (fait côté mobenais, `src/agent_loop.py:179-181` :
      `if code is None: sandbox_output = "No valid code block was found in the
      model's response."` — pas dans `ExecutionResult.error` à proprement parler
      puisque `sandbox.execute()` n'est jamais appelé dans ce cas, mais l'agent
      reçoit bien un message explicite)
- [ ] Bloc mal formé mais interprété quand même → **expliquer comment** (toujours
      pas fait — `extract_code` ne signale jamais qu'il a pris un bloc sans tag
      de langage reconnu ; fix esquissé mais pas appliqué, vu que c'est le fichier
      de mobenais)
- [x] Timeout atteint → indiquer que la sortie est partielle (`result.timed_out=True` +
      `error="Error: Execution timed out."`, stdout/stderr partiels tout de même capturés)
- [x] Sortie d'outil tronquée → le dire explicitement (`ExecutionResult.truncated` bool,
      posé par `_get_stdout_stderr`)
- [ ] Édition ayant introduit une erreur de syntaxe / lint — `edit_file` **existe
      maintenant** (bclairot.9 fini) mais ne valide toujours aucune syntaxe après
      remplacement, donc ce cas reste ouvert pour de vrai cette fois (plus bloqué
      par "pas encore écrit")

> *« The LLM should never be left guessing about what happened. »*

## bclairot.5 CLI sandbox (REPL)

- [x] `uv run sandbox` → REPL interactif
- [x] `uv run sandbox sandbox_template.json`
- [x] `uv run sandbox --mcp-stdio "python mcp_tools_mbpp.py" sandbox_template.json` (branché : `cli.py` passe `command_stdio`/`url` à `Sandbox(...)`)
- [x] `uv run sandbox --mcp-server <URL>` (idem, branché)
- [x] Comportement :
  - [x] Boucle prompt → lecture → exécution dans le **même namespace**
  - [x] Toutes les restrictions actives (imports, FS, timeout, RAM)
  - [x] Affiche résultat ou erreur levée
  - [x] Sortie propre sur `exit` **et** sur EOF (Ctrl+D)

## bclairot.6 Génération du manuel

- [x] `build_manual(tools: list[ToolSchema], config: SandboxConfig) -> str` — `get_manual()`
      (`mcp_bridge.py`) est maintenant dynamique : itère `self._tools` (récupérés du
      serveur MCP connecté) et appelle `_format_tool()` par outil, plus `self.config`
      pour les limites/imports/répertoires. Reste une méthode sur `Sandbox`, pas une
      fonction pure `(tools, config) -> str`.
  - [x] Nom, description, types de paramètres de chaque outil MCP (`_format_tool`
        lit `tool.input_schema["properties"]`/`required` + `tool.description`)
  - [~] `final_answer` documenté à part (ce n'est pas un outil MCP) (mentionné dans le texte figé)
  - [x] Rappel des imports autorisés et des répertoires accessibles
- [ ] **Test** : connecter un autre serveur MCP → le manuel change tout seul
      (partiellement vérifié : `get_manual()` reflète bien dynamiquement les
      tools de `mcp_tools_mbpp.py` en vrai ; le test équivalent avec
      `mcp_tools_swebench.py` échoue à cause du nouveau bug `TESTBED_PATH` ci-dessous,
      pas à cause de `get_manual()` lui-même)

## bclairot.7 Client MCP

- [~] `class MCPClient` (`src/mcp_client.py`) — présente, mais sous une forme différente
      de la checklist : un seul point d'entrée `__init__(url=None, command_stdio=None)`
      + `connect()`/`build_client()` plutôt que deux méthodes séparées
  - [~] `connect_stdio(command: str)` — unifié dans `__init__`/`connect()`, pas de méthode dédiée
  - [~] `connect_http(url: str)` — idem
  - [x] `list_tools() -> list[ToolSchema]` → `get_tools_list() -> list[Tool]`
  - [x] `list_resources()` / `list_prompts()` → `get_resources_list()` / `get_prompt_list()`
  - [x] `call_tool(name, arguments) -> str` → `use_tool(name, params) -> CallToolResult`
        (objet structuré, pas une `str` brute — extrait en `str` côté `mcp_bridge.py`)
  - [x] `close()` → `disconnect()`
- [~] `make_wrappers(client) -> dict[str, Callable]` — pas de fonction autonome de ce nom ;
      l'équivalent est réparti entre `Sandbox._make_tool_proxy` (un outil) et
      `SandboxMCPBridgeMixin.proxy_*`/`make_mcp_proxy` (resources/prompts), tous deux
      appelés depuis `_worker` pour peupler `namespace`
  - [x] Une fonction Python par outil, avec `__name__` et `__doc__` corrects — **fait** :
        `_make_tool_proxy` reçoit maintenant un `tool_docs` en plus de
        `tool_param_names`, et assigne `proxy.__name__ = name` /
        `proxy.__doc__ = tool_docs.get(name, "")` avant de retourner la closure.
        Vérifié en vrai (sandbox connectée à `mcp_tools_mbpp.py`, `run_tests.__name__`
        et `.__doc__` corrects dans le process enfant).
  - [x] Injectée dans le namespace sandbox (`namespace[name] = self._make_tool_proxy(...)`)
  - [x] **Aucun nom d'outil hardcodé** (tout vient de `tool_names`/`self._tools` obtenus dynamiquement)
  - [ ] **Nouveau bug trouvé (2026-09-16)** : `TESTBED_PATH` (et toute variable
        d'env côté parent) ne traverse pas la frontière stdio. `mcp.stdio_client`
        n'hérite que d'une allowlist fixe (`HOME, LOGNAME, PATH, SHELL, TERM, USER`
        sous POSIX — `mcp/client/stdio.py:get_default_environment`), et
        `MCPClient.build_client()` ne passe aucun `env=` à `StdioServerParameters`
        pour compenser. Donc lancer `mcp_tools_swebench.py` via
        `--mcp-stdio`/`Sandbox(command_stdio=...)` plante avec
        `RuntimeError: no environment variable TESTBED_PATH set`, même si la
        variable est bien définie côté process parent. Fix : passer
        `env=os.environ.copy()` (ou au moins fusionner ce qu'il faut) à
        `StdioServerParameters` dans `build_client()`.

## bclairot.8 `mcp_tools_mbpp.py`

- [x] `run_tests(code: str) -> str` — exécute les tests de la tâche contre le code
- [x] Réception de la tâche selon la convention figée en §0.5
- [x] Outils additionnels libres (ex. `lint(code)`)

## bclairot.9 `mcp_tools_swebench.py` — les 9 outils obligatoires ✅ fini, testé sur un vrai Docker

Testés **indépendamment de l'agent** : ils doivent marcher seuls.

**Filesystem**
- [x] `read_file(filepath, start_line, end_line)` → format `cat -n` : `<line_number>: <line_content>`
- [x] `edit_file(filepath, old_str, new_str)` — remplacement exact
  - [x] Erreur explicite si `old_str` absent **ou** présent plusieurs fois
- [x] `list_files(directory, pattern)`

**Recherche** — format imposé : `/absolute/path.py:<line_number> <line_content>`
- [x] `search_code(pattern, file_pattern)`
- [x] `search_function_or_class_definition_in_code(name)`
- [x] `find_references(name, filepath, line)`

**Exécution**
- [x] `run_tests()` — lance l'`eval_script`
- [x] `get_patch()` — **exactement** `git -c core.fileMode=false diff`
- [x] `run_command(command, workdir)` → stdout, stderr **et** exit code

- [x] Troncature des sorties volumineuses + message indiquant la troncature
      (`MCPServerSWEBench._truncate`/`_format_result`)

Testé en vrai de bout en bout (pas juste lu) : `edit_file` → `run_tests` (passe) →
`get_patch` (diff propre) sur le testbed local. Voir la mémoire de session pour le
détail des bugs trouvés en cours de route (grep `-e`, mauvais index de tuple,
`workdir` relatif rejeté par Docker, `.git/` pollué dans `find_references`...).

## bclairot.10 Docker (SWE-bench) ✅ fini

- [x] `class DockerManager`
  - [x] `pull(image)` / `start(image, testbed_path)` → `pull_image()`/`run_container()`
  - [x] `exec(command, workdir) -> (stdout, stderr, exit_code)` (ordre réel :
        `(exit_code, stdout, stderr)`, mais les 3 infos sont bien là)
  - [x] `cleanup()` — **obligatoire**, y compris sur exception et Ctrl+C : câblé sur
        `SIGTERM`/`SIGINT` dans `mcp_tools_swebench.py` (`MCPServerSWEBench.close()`)
- [x] Choisir et documenter : sandbox **dans** le conteneur, ou sur l'hôte avec les outils MCP qui font le pont
      (Option B retenue et documentée dans le README, section "Tool Implementation Details")
- [x] Contraintes de sécurité sandbox appliquées **dans les deux cas** — cohérent par
      construction : la même `Sandbox` (avec toutes ses restrictions) tourne qu'elle
      soit connectée à `mcp_tools_mbpp.py` ou `mcp_tools_swebench.py`
- [x] Montage éventuel de `${TESTBED_PATH}` — pas un montage Docker, mais résolu
      quand même : lu depuis la variable d'env `TESTBED_PATH` (imposée par le sujet)
      plutôt que déduit de l'image
- [ ] Dépendances additionnelles possibles dans le conteneur (`ruff`, `jedi`, `tree`)
      — pas fait, optionnel selon le sujet

---

# PARTIE C — À FAIRE ENSEMBLE (fin de projet)

## C.1 BENCHMARK_REPORT.md

Pilote : **mobenais** (c'est lui qui a la couche multi-modèles). Ablation : **bclairot**.

- [ ] **≥ 5 modèles** × **≥ 3 tâches SWE-bench** identiques
- [ ] Setup : modèles, providers, tâches choisies **et pourquoi**
- [ ] Table de résultats par couple modèle × tâche : Pass/Fail · itérations · tokens in · tokens out · wall-clock
- [ ] Fiabilité provider : temps de réponse moyen, retries, disponibilité — *(données de mobenais)*
- [ ] **≥ 2 métriques intermédiaires** parmi :
  - [ ] Étape du premier accès au fichier qui figure dans le patch final *(métrique côté outils → bclairot)*
  - [ ] Étape où les échecs de tests diminuent pour la première fois *(bclairot)*
  - [ ] Itérations entre « tests passent » et `final_answer` — idéal : 0 *(mobenais)*
- [ ] **Ablation** : un avant/après sur un changement, même modèle, mêmes tâches
  - suggestion mobenais : prompt vague vs prompt explicite
  - suggestion bclairot : avec vs sans `find_references`, ou troncature des sorties d'outils
- [ ] Conclusions appuyées sur les données : modèles retenus / écartés
- [ ] Les `solution.json` correspondants **committés dans le repo**

## C.2 README.md

- [ ] Première ligne en italique : `*This project has been created as part of the 42 curriculum by <login1>, <login2>.*`
- [ ] **Description** — commun
- [ ] **Instructions** (install, config, exécution) — commun
- [ ] **Resources** + description de l'usage de l'IA (quelles tâches, quelles parties) — commun
- [ ] Architecture système — commun
- [ ] Explication de la boucle agent — **mobenais**
- [ ] Design de la sandbox (dont le choix d'isolation) — **bclairot**
- [ ] Détails d'implémentation des outils — **bclairot**
- [ ] Résultats de benchmark et analyse — **mobenais**
- [ ] **Rédigé en anglais**

## C.3 Sécurité IA & interdits (grade 0)

- [ ] Pas de récupération de solution depuis PR, issues, sources externes
- [ ] Pas de patch mémorisé sans exploration réelle
- [ ] Pas de contournement de la sandbox
- [ ] `system_prompt`, `llm_output`, `sandbox_input`, `sandbox_output` **réellement remplis**
- [ ] Aucune clé API dans le code source
- [ ] Pas de bibliothèque d'orchestration agentique (`smolagents`, `langgraph`, `crewai`, `autogen`, `llama-index`)
- [ ] Ne pas committer : images Docker, poids de modèles, sorties générées

## C.4 Cross-review — indispensable en soutenance

En soutenance, on demande **2 à 3 modifications live de 2-5 min**, et la question
peut tomber sur le lot de l'autre. Si l'un des deux ne sait pas où modifier,
c'est éliminatoire.

- [ ] **mobenais explique le lot bclairot à voix haute**, sans notes : sécurité sandbox, choix
      d'isolation, comment les outils MCP deviennent des fonctions Python
- [ ] **bclairot explique le lot mobenais à voix haute** : boucle Thought→Code→Observation,
      les 4 formats d'extraction, rotation des clés, calcul du budget tokens
- [ ] Chacun a déjà fait **au moins un commit** dans le lot de l'autre
- [ ] Répétition : chacun fait une modif live dans le lot de l'autre, chronométrée
- [ ] `git checkout` propre après l'exercice
- [ ] Test de la commande complète :
      `./exam_TYPE.sh --student-path ./student --moulinette-path ./moulinette --env-file /path/to/.env`

---

# PARTIE D — PLANNING ET POINTS D'INTÉGRATION

| Jalon | mobenais livre | bclairot livre | Test d'intégration |
|---|---|---|---|
| **J1** | `fake_agent.py` | `FakeSandbox` | Les schémas Pydantic + `contract.py` sont figés |
| **J2** | LLM + extraction basique (blocs ```python) | Sandbox nue + les 6 restrictions | `uv run sandbox` marche ; `exam_sandbox.sh` passe |
| **J3** | Boucle agent sur `FakeSandbox` | Client MCP + `mcp_tools_mbpp.py` (`run_tests`) | **Intégration #1** : vraie sandbox + vrai MCP + vraie boucle sur 1 tâche MBPP, **limites désactivées** |
| **J4** | Prompt MBPP optimisé, limites réactivées | Manuel dynamique + REPL finalisé | `exam_mbpp.sh` → 4/5 |
| **J5-6** | CLI `agent_swebench`, prompt SWE | Les 9 outils SWE + `DockerManager` | **Intégration #2** : `sympy__sympy-14711` de bout en bout |
| **J7** | Multi-providers, multi-tokens, 4 formats d'extraction | Robustesse outils, troncature, cleanup Docker | `exam_swebench.sh` → 2/3 |
| **J8-9** | Runs de benchmark (~15) + rapport | Ablation + métriques intermédiaires | `BENCHMARK_REPORT.md` complet |
| **J10** | README + cross-review | README + cross-review | Répétition soutenance |

## Règles d'or du binôme sur ce projet

- [ ] **`exam_sandbox.sh` est prioritaire absolu.** C'est le seul exam en tout-ou-rien
      et il ne dépend d'aucun LLM. bclairot doit le faire passer avant tout le reste.
- [ ] **Intégration #1 le plus tôt possible.** Le sujet le dit : si l'agent ne résout
      pas la tâche la plus simple **sans limites**, ajouter les limites n'aidera pas.
- [ ] **Aucune modification unilatérale de `contract.py` ou `schemas/`.**
      Un changement là = un message à l'autre avant de commit.
- [ ] Merge sur `main` seulement après un test d'intégration qui passe.
