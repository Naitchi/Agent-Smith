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

## mobenais.1 Couche LLM

- [ ] `class LLMResponse` : `text`, `input_tokens`, `output_tokens`, `latency_ms`, `retries`, `api_url`, `model_name`
- [ ] `class LLMProvider(ABC)` : `complete(messages, stop, max_tokens) -> LLMResponse`
- [ ] `class OpenAICompatibleProvider(LLMProvider)` (couvre OpenRouter, Groq, Together, Fireworks…)
- [ ] Abstraction suffisante pour changer de provider sans refactor (c'est ça qui est noté, pas le choix du provider)
- [x] **Multi-tokens par provider — obligatoire**
  - [ ] `class TokenRotator` : `next_key()`, `mark_rate_limited(key, retry_after)`, `mark_exhausted(key)`
        (pas une classe dédiée, mais la rotation est faite inline dans `AgentLoop.run`)
  - [x] Plusieurs clés lues depuis l'env (`GEMINI_API_KEYS`/`GROQ_API_KEYS`, liste
        séparée par virgules — `src/agent_loop.py:101-109`)
- [x] Fallback de provider si indisponibilité (bascule Gemini → Groq quand le pool
      Gemini est épuisé, `src/agent_loop.py:148-157`)
- [ ] Retry + backoff sur 429 / 5xx / timeout → comptés dans `retries` et `total_requests`
- [ ] **`stop_sequences`** (`<end_code>`, `</tool_call>`…) → empêche le modèle d'halluciner l'observation
- [ ] Usage tracking : tokens, retries, latence, nombre de requêtes
- [x] Free tiers uniquement, **aucune clé en dur** (grade 0 sinon)

## mobenais.2 Extraction de code

- [ ] `extract_code(llm_text: str) -> ExtractedCode | None`
- [ ] Format 1 — bloc Python (primaire) : ` ```python ... ``` ` + `<end_code>`
- [ ] Format 2 — XML Anthropic : `<invoke name="..."><parameter name="...">…</parameter></invoke>`
- [ ] Format 3 — JSON/Hermes : `<tool_call>{"name": "...", "arguments": {...}}</tool_call>`
- [ ] Format 4 — ReAct : `Action: tool_name` / `Action Input: {...}`
- [ ] `to_python_call(name, args) -> str` → `result = read_file(filepath="/testbed/file.py")`
- [ ] Tolérance : bloc non fermé, ` ``` ` sans langage, texte parasite
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

## mobenais.4 System prompts (fortement noté)

- [ ] Doc des outils **injectée depuis `sandbox.get_manual()`** — jamais recopiée à la main
- [ ] Slots explicites : `Thought:` / `Code:` / `Observation:`
- [ ] **Au moins un exemple complet** de boucle de raisonnement (few-shot)
- [ ] Méthodologie de debug pas-à-pas : lire → chercher → hypothèse → éditer → tester
- [ ] Prompt MBPP et prompt SWE-bench séparés
- [ ] Comparaison empirique prompt vague vs prompt explicite (→ sert d'ablation §C.1)

> ⚠️ **MBPP : 6 000 tokens d'entrée cumulés sur toute la tâche.** L'historique
> grossit à chaque tour, donc un prompt système de 1 500 tokens rend la tâche
> mathématiquement impossible. **Mesure ton prompt en tokens dès le début.**

## mobenais.5 CLI agent MBPP

- [ ] `uv run python -m agent_mbpp --task-file ... --output ... --model-name ... --provider-url ...`
- [ ] Clé API lue depuis l'environnement
- [ ] Chargement `MBPPTaskInput`, lancement du serveur MCP MBPP (selon §0.5)
- [ ] Écriture de `SolutionOutput` : `benchmark="mbpp"`, `solution` = code Python
- [ ] Limites : **10 itérations / 6k in / 1.5k out / 120 s**
- [ ] Objectif : **4/5**

## mobenais.6 CLI agent SWE-bench

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
