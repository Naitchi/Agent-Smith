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
- [~] Même décision pour SWE-bench : comment le serveur reçoit `docker_image`,
      `eval_script`, `TESTBED_PATH` (env vars ou args CLI). `mcp_tools_swebench.py`
      reprend la même convention `--task-file` que MBPP pour `docker_image`/
      `eval_script` (via `SWEBenchTaskInput`) ; `TESTBED_PATH` n'est pas un champ
      du schéma et reste à câbler.
- [~] Décider qui construit l'objet `Sandbox` : mobenais dans son CLI, à partir des args
      `--mcp-stdio` / `--mcp-server`. CLI `sandbox` (bclairot) le construit et les args
      MCP sont maintenant branchés (`Sandbox(config=..., command_stdio=..., url=...)`) ;
      côté mobenais, `AgentLoopConf`/`src/__main__.py` construit encore un `Sandbox()`
      nu, sans jamais passer `--mcp-stdio`/`--mcp-server`.

## 0.6 Les deux mocks de démarrage

Pour ne pas s'attendre l'un l'autre :

- [~] **bclairot fournit à mobenais un `FakeSandbox`** (10 lignes) dès le jour 1 : `execute()` fait
      un `exec()` naïf, `get_manual()` renvoie un texte en dur. mobenais peut coder toute
      sa boucle dessus. *(jamais livré ; la vraie `Sandbox` a servi directement — d'où le
      bloquant mobenais.0)*
- [ ] **mobenais fournit à bclairot un `scripts/fake_agent.py`** : un script qui envoie 3 blocs de
      code en dur à la sandbox et affiche les `ExecutionResult`. bclairot teste sans LLM.
      *(n'existe pas ; `scripts/test_mcp.py` (bclairot) teste le client MCP, pas la sandbox)*

## 0.7 Répartition des fichiers (évite les conflits git)

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
- [ ] 🔴 **Reste bloquant : le MCP n'est jamais branché.** Ce même `stdio=None` positionnel
      écrase le défaut `server_path="./mcp_tools_mbpp.py"` → `Error building client: Either
      url or server_path must be provided`, `mcp_client` inutilisable. La sandbox tourne
      **sans aucun outil MCP** : pas de `run_tests`, donc aucune validation possible d'une
      solution MBPP. À trancher avec bclairot (cf. §0.5, qui est encore `[~]`).
- [x] ~~`AgentLoopConf` **ignore le `llm` qu'on lui passe** : `schemas/agent_class_monitoring.py:27`
      force `GeminiLLM("gemini-3.1-flash-lite")` alors que `model_name = random.choice(models_name)`
      → le `model_name` écrit dans `StepMetrics` n'est pas le modèle réellement interrogé
      (métriques de benchmark faussées, et provenance douteuse pour la correction).~~
      **Corrigé le 2026-09-10** : le `llm` passé est retenu tel quel, et `model_name` en est
      dérivé (`self.model_name = self.llm.model`) au lieu d'un tirage indépendant — une seule
      source de vérité, quel que soit le provider. `model: str` ajouté à `LLMProtocole`
      (`schemas/contract_model.py`, fichier commun → à signaler à bclairot).
- [ ] **Limites par défaut hors sujet** : `max_iterations=45`, `11_000_000` in, `15_000_000` out,
      `1_200_000` s — alors que le docstring de `default_conf()` annonce « les limites MBPP ».
      Cible MBPP : 10 / 6k / 1.5k / 120 s.
- [~] ~~`init_value()` **recharge les compteurs de tokens** depuis `backup_memory/backup.json` :
      un run précédent crashé gonfle les totaux du run suivant → dépassement de budget fantôme
      à la correction.~~ **Corrigé le 2026-09-14** pour les autres tâches : `init_value()` et
      `init_history()` fusionnés en `load_backup(task_id)`, qui ignore tout backup d'une autre
      tâche ou sans `task_id` (compteurs, modèle et historique). Une même tâche reprend
      historique, `steps`, compteurs et modèle précédent (`RELAIS_MODELE` injecté).
      **Reste** : si la moulinette relance la même tâche après un crash, le backup est repris
      et prime sur `--model-name` → désactiver la reprise sur le chemin moulinette.
- [ ] Le budget est vérifié **après** l'appel LLM → la limite de 6k tokens d'entrée peut être
      franchie avant d'être détectée (à traiter avec la troncature d'historique, §mobenais.3).
- [x] ~~`sandbox.get_manual()` existe côté bclairot mais **n'est appelé nulle part** côté agent
      (cf. §mobenais.4).~~ **Corrigé le 2026-09-10** : composé une fois avant la boucle dans
      `AgentLoop.run()`, compacté par `compact_manual()` (493 → 153 tokens), et c'est le prompt
      composé qui part dans `SolutionOutput.system_prompt`.
- [x] ~~`SYSTEM_PROMPT` est rédigé en français alors qu'il exige des réponses en anglais.~~
      **Corrigé le 2026-09-09** : prompt entièrement en anglais (73 tokens). Le fond reste
      à écrire (cf. §mobenais.4).
- [ ] `uv run -m src` part sur un prompt de test (`DEFAULT_TASK`) de type injection —
      à remplacer par une vraie tâche MBPP avant toute démo.

## mobenais.1 Couche LLM

- [~] `class LLMResponse` : `text`, `input_tokens`, `output_tokens`, `latency_ms`, `retries`, `api_url`, `model_name`
      *(`schemas/llm_result.py::LLMResult` a text + tokens + `latency_ms` ; manquent `retries`,
      `api_url`, `model_name` — la boucle les recompose à la main)*
- [ ] `class LLMProvider(ABC)` : `complete(messages, stop, max_tokens) -> LLMResponse`
      *(seulement un `Protocol` `LLMProtocole.__call__(system, messages)`, pas d'ABC ni de
      paramètres `stop` / `max_tokens`)*
- [~] `class OpenAICompatibleProvider(LLMProvider)` (couvre OpenRouter, Groq, Together, Fireworks…)
      *(`GeminiLLM` et `GroqLLM` dans `schemas/llmclass.py` : deux classes quasi identiques,
      URL et `max_tokens=2048` en dur, à fusionner en une classe paramétrée par URL)*
- [ ] Abstraction suffisante pour changer de provider sans refactor (c'est ça qui est noté, pas le choix du provider)
      *(non : `AgentLoop.run()` connaît Gemini et Groq nommément — pools, URLs et classes en dur)*
- [~] **Multi-tokens par provider — obligatoire**
      *(rotation réelle sur 429, mais écrite inline dans `AgentLoop.run()` et propagée par
      mutation de `os.environ` — à extraire)*
  - [ ] `class TokenRotator` : `next_key()`, `mark_rate_limited(key, retry_after)`, `mark_exhausted(key)`
  - [x] Plusieurs clés lues depuis l'env (`GEMINI_API_KEYS` / `GROQ_API_KEYS`, liste séparée par virgules,
        repli sur la clé simple) — *à documenter dans `.env.example`, qui ne liste que `GROQ_API_KEY`
        et `GEMINI_API_KEY`*
- [x] Fallback de provider si indisponibilité *(bascule modèle Gemini → Groq quand toutes les clés
      sont rate-limitées, puis `AgentLoopError` si le pool est vide)*
- [~] Retry + backoff sur 429 / 5xx / timeout → comptés dans `retries` et `total_requests`
      *(429 uniquement, retry immédiat sans backoff ni `Retry-After` ; 5xx et timeouts remontent
      en erreur. Le comptage `retries` / `total_requests`, lui, est bon)*
- [ ] **`stop_sequences`** (`<end_code>`, `</tool_call>`…) → empêche le modèle d'halluciner l'observation
- [x] Usage tracking : tokens, retries, latence, nombre de requêtes
- [x] Free tiers uniquement, **aucune clé en dur** (grade 0 sinon)

## mobenais.2 Extraction de code

- [~] `extract_code(llm_text: str) -> ExtractedCode | None`
      *(`schemas/tools_agent.py::extract_code` renvoie `str | None` ; pas de type `ExtractedCode`,
      donc aucun moyen de dire au LLM quel format a été reconnu)*
- [~] Format 1 — bloc Python (primaire) : ` ```python ... ``` ` + `<end_code>`
      *(fences ```` ``` ````/```py``` OK, dernier bloc retenu ; `<end_code>` non géré)*
- [ ] Format 2 — XML Anthropic : `<invoke name="..."><parameter name="...">…</parameter></invoke>`
- [ ] Format 3 — JSON/Hermes : `<tool_call>{"name": "...", "arguments": {...}}</tool_call>`
- [ ] Format 4 — ReAct : `Action: tool_name` / `Action Input: {...}`
- [ ] `to_python_call(name, args) -> str` → `result = read_file(filepath="/testbed/file.py")`
- [ ] Tolérance : bloc non fermé, ` ``` ` sans langage, texte parasite
      *(bloc non fermé → `None` ; « ``` sans langage » OK)*
- [ ] Si interprétation « de secours » → le signaler pour que bclairot/le LLM le sache
- [x] `None` propre si rien d'exploitable → observation d'erreur explicite au LLM

## mobenais.3 Boucle agent

- [x] `class AgentLoop`
  - [x] `__init__(llm, sandbox: SandboxProtocol, system_prompt, max_iterations)` (via `AgentLoopConf`)
  - [x] `run(task) -> SolutionOutput`
  - [~] `_build_messages()` — historique Thought / Code / Observation (fait inline, pas de méthode dédiée)
  - [x] `_record_step(...) -> StepMetrics` (construit inline dans la boucle)
  - [x] `_check_limits()` — itérations, tokens cumulés, temps mur (`budget_exceeded`)
- [x] `max_iterations` **paramétrable**
- [x] Arrêt sur `result.final_answer is not None` OU limite atteinte
- [x] Aucun crash possible → `SolutionOutput(success=False, error=...)` écrit quand même
- [ ] Troncature / résumé des vieilles observations pour tenir le budget
      *(prioritaire : c'est ce qui rend les 6k tokens d'entrée MBPP tenables)*
- [ ] Sur `max_iterations` atteint, `solution` reste `""` — renvoyer le dernier code candidat

## mobenais.4 System prompts (fortement noté)

> État au 2026-09-10 : `SYSTEM_PROMPT_MBPP` écrit dans `schemas/tools_agent.py`
> (280 tokens ; 434 une fois `get_manual()` compacté concaténé). Validé sur 3 tâches
> MBPP, résolues en 2-3 itérations pour ~1300-2000 tokens d'entrée sur les 6000.
> Restent : le prompt SWE-bench, et l'ablation vague vs explicite.

- [x] Doc des outils **injectée depuis `sandbox.get_manual()`** — jamais recopiée à la main
      *(`AgentLoop.run()` la concatène au prompt ; `compact_manual()` coupe les phrases les plus
      longues d'abord, sans rien hardcoder sur le contenu → reste valide avec un serveur MCP inconnu)*
- [x] Slots explicites : `Thought:` / `Code:` / `Observation:` *(cadrés par `SYSTEM_PROMPT_MBPP`, avec `<end_code>`)*
- [x] **Au moins un exemple complet** de boucle de raisonnement (few-shot) *(2 tours, dans `SYSTEM_PROMPT_MBPP`)*
- [~] Méthodologie de debug pas-à-pas : lire → chercher → hypothèse → éditer → tester
      *(version MBPP faite : « imprime la valeur obtenue à côté de l'attendue, ne corrige que ce
      que l'écart montre, ne réécris pas la fonction ». La version SWE-bench reste à écrire)*
- [~] Prompt MBPP et prompt SWE-bench séparés
      *(`SYSTEM_PROMPT_MBPP` écrit — 280 tokens, 434 avec le manuel compacté. Le prompt
      SWE-bench n'existe pas)*
- [ ] Comparaison empirique prompt vague vs prompt explicite (→ sert d'ablation §C.1)

> ⚠️ **MBPP : 6 000 tokens d'entrée cumulés sur toute la tâche.** L'historique
> grossit à chaque tour, donc un prompt système de 1 500 tokens rend la tâche
> mathématiquement impossible. **Mesure ton prompt en tokens dès le début.**

## mobenais.5 CLI agent MBPP

> État au 2026-09-10 : package `agent_mbpp/` créé à la racine (`python -m agent_mbpp`),
> ajouté à `packages` dans `pyproject.toml`. Validé de bout en bout sur 3 tâches MBPP :
> résolues en 2-3 itérations, 1300-2000 tokens d'entrée sur 6000, tests rejoués OK.
> `src/agent_MBPP.py` (0 octet) est à supprimer.

- [x] `uv run python -m agent_mbpp --task-file ... --output ... --model-name ... --provider-url ...`
- [x] Clé API lue depuis l'environnement *(refus explicite si aucune clé, jamais en argument)*
- [~] Chargement `MBPPTaskInput`, lancement du serveur MCP MBPP (selon §0.5)
      *(chargement + validation Pydantic faits ; `start_mcp_server()` écrit bien
      `cache/mbpp_task.json` mais ne lance pas le process — bloqué par le MCP non branché
      côté sandbox, cf. §mobenais.0)*
- [x] Écriture de `SolutionOutput` : `benchmark="mbpp"`, `solution` = code Python
      *(le prompt exige `final_answer(<source>)` ; filet dans `main()` qui reprend le dernier
      `sandbox_input` si la boucle s'arrête sans `final_answer`)*
- [x] Limites : **10 itérations / 6k in / 1.5k out / 120 s** *(constantes en tête de
      `agent_mbpp/__main__.py` ; les défauts d'`AgentLoopConf` restent hors sujet, cf. §mobenais.0)*
- [ ] Objectif : **4/5** *(3/3 sur des tâches de test maison ; jamais passé sur `exam_mbpp.sh`)*

## mobenais.6 CLI agent SWE-bench

> ⚠️ **Rien n'est commencé** (aucun fichier).

- [ ] `uv run python -m agent_swebench --task-file ... --output ... --model-name ... --provider-url ...`
- [ ] Chargement `SWEBenchTaskInput`, passage des infos au serveur MCP de bclairot
- [ ] `SolutionOutput` : `benchmark="swebench"`, `solution` = patch renvoyé par `get_patch()`
- [ ] Limites : **30 itérations / 300k in / 10k out / 900 s**
- [ ] Objectif : **2/3**
- [ ] Tâches de mise au point : `sympy__sympy-14711`, `sympy__sympy-13480`, `pydata__xarray-4629`

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
  - [ ] MBPP : `final_answer(code)` — SWE-bench : `final_answer(get_patch())`

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
- [ ] Documenter le trade-off dans le README

## bclairot.4 Feedback explicite au LLM — 5 cas obligatoires

Le champ `error` de `ExecutionResult` doit couvrir :

- [ ] Aucun bloc de code valide trouvé *(cas remonté par mobenais, format d'erreur à convenir — `extract_code` renvoie `None` mais rien ne construit encore l'observation d'erreur associée)*
- [ ] Bloc mal formé mais interprété quand même → **expliquer comment**
- [x] Timeout atteint → indiquer que la sortie est partielle (`result.timed_out=True` +
      `error="Error: Execution timed out."`, stdout/stderr partiels tout de même capturés)
- [x] Sortie d'outil tronquée → le dire explicitement (`ExecutionResult.truncated` bool,
      posé par `_get_stdout_stderr`)
- [ ] Édition ayant introduit une erreur de syntaxe / lint *(dépend de `edit_file`, pas encore écrit — bclairot.9)*

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
  - [ ] Une fonction Python par outil, avec `__name__` et `__doc__` corrects — **pas fait** :
        `_make_tool_proxy` renvoie une closure nommée `proxy` sans `__name__`/`__doc__`
        réassignés vers ceux de l'outil MCP réel
  - [x] Injectée dans le namespace sandbox (`namespace[name] = self._make_tool_proxy(...)`)
  - [x] **Aucun nom d'outil hardcodé** (tout vient de `tool_names`/`self._tools` obtenus dynamiquement)

## bclairot.8 `mcp_tools_mbpp.py`

- [x] `run_tests(code: str) -> str` — exécute les tests de la tâche contre le code
- [x] Réception de la tâche selon la convention figée en §0.5
- [x] Outils additionnels libres (ex. `lint(code)`)

## bclairot.9 `mcp_tools_swebench.py` — les 9 outils obligatoires

Testés **indépendamment de l'agent** : ils doivent marcher seuls.

**Filesystem**
- [ ] `read_file(filepath, start_line, end_line)` → format `cat -n` : `<line_number>: <line_content>`
- [ ] `edit_file(filepath, old_str, new_str)` — remplacement exact
  - [ ] Erreur explicite si `old_str` absent **ou** présent plusieurs fois
- [ ] `list_files(directory, pattern)`

**Recherche** — format imposé : `/absolute/path.py:<line_number> <line_content>`
- [ ] `search_code(pattern, file_pattern)`
- [ ] `search_function_or_class_definition_in_code(name)`
- [ ] `find_references(name, filepath, line)`

**Exécution**
- [ ] `run_tests()` — lance l'`eval_script`
- [ ] `get_patch()` — **exactement** `git -c core.fileMode=false diff`
- [ ] `run_command(command, workdir)` → stdout, stderr **et** exit code

- [ ] Troncature des sorties volumineuses + message indiquant la troncature

## bclairot.10 Docker (SWE-bench)

- [ ] `class DockerManager`
  - [ ] `pull(image)` / `start(image, testbed_path)`
  - [ ] `exec(command, workdir) -> (stdout, stderr, exit_code)`
  - [ ] `cleanup()` — **obligatoire**, y compris sur exception et Ctrl+C (`try/finally` + handler signal)
- [ ] Choisir et documenter : sandbox **dans** le conteneur, ou sur l'hôte avec les outils MCP qui font le pont
- [ ] Contraintes de sécurité sandbox appliquées **dans les deux cas**
- [ ] Montage éventuel de `${TESTBED_PATH}`
- [ ] Dépendances additionnelles possibles dans le conteneur (`ruff`, `jedi`, `tree`)

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
