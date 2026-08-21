# Agent Smith — Checklist binôme

> Répartition en **deux lots** :
> - **Lot A — Côté Agent** (LLM, extraction, boucle, prompts, CLIs, benchmark)
> - **Lot B — Côté Exécution** (Sandbox, client MCP, serveurs MCP, outils, Docker)
>
> Les deux lots sont séparés par un **contrat d'interface** défini au jour 1,
> ce qui permet de travailler en parallèle sans se bloquer.

---

# PARTIE 0 — À FAIRE ENSEMBLE (Sprint 0, ~1 journée)

Ne commencez pas à coder chacun de votre côté avant d'avoir fini cette partie.

## 0.1 La frontière entre vos deux lots

```
   ┌───────────────── LOT A ──────────────────┐   ┌────────── LOT B ──────────────┐
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

**A ne touche jamais** à ce qui est dans le lot B, et inversement.
La seule chose que A connaît de B : `Sandbox.execute()`, `Sandbox.get_manual()`, `Sandbox.close()`.

## 0.2 Les 5 malentendus à lever avant de coder (les deux doivent les avoir compris)

- [ ] **La sandbox contient le client MCP**, pas l'inverse : *« The sandbox wraps the MCP client, not the other way around. »*
- [ ] **`final_answer()` n'est PAS un outil MCP.** C'est une fonction injectée par la sandbox, toujours présente quel que soit le serveur MCP connecté.
- [ ] **Deux domaines de sécurité distincts.** La sandbox restreint le *code Python généré par le LLM*. Les outils MCP tournent **en dehors** de la sandbox → le timeout sandbox ne s'y applique pas, et `run_command` peut lancer des process.
- [ ] **Le manuel est généré dynamiquement** depuis `list_tools()` du serveur MCP connecté, jamais écrit en dur.
- [ ] **Le système sera testé avec un serveur MCP inconnu** → zéro nom d'outil hardcodé dans la sandbox ni dans l'agent.

## 0.3 Setup commun

- [ ] Repo git, branches `feat/agent` (A) et `feat/sandbox` (B)
- [ ] Python **3.10** exactement, `uv` comme gestionnaire de paquets
- [ ] `pyproject.toml` avec les entry points :
  - [ ] `sandbox = "agent_smith.sandbox.cli:main"` → `uv run sandbox`
  - [ ] `agent_mbpp` et `agent_swebench` importables → `uv run python -m agent_mbpp`
- [ ] `.env.example`, `.gitignore` (`.env`, `cache/`, `evaluations/`)
- [ ] `sandbox_template.json` à la racine
- [ ] `mcp_tools_mbpp.py` et `mcp_tools_swebench.py` à la racine (imposé par le sujet)

## 0.4 Modèles Pydantic — à écrire ensemble, personne ne les modifie seul ensuite

Fichier `schemas/` — c'est le contrat avec la moulinette.

- [ ] `SandboxConfig` (copier la définition exacte du sujet)
- [ ] `MBPPTaskInput`, `SWEBenchTaskInput`
- [ ] `StepMetrics` — tous les champs : `step`, `input_tokens`, `output_tokens`,
      `request_time_ms`, `timestamp`, `api_url`, `model_name`, `llm_output`,
      `sandbox_input`, `sandbox_output`, `retries`
- [ ] `SolutionOutput` — dont `system_prompt`, `steps`, `error`

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

- [ ] Décider ensemble **comment le serveur MCP MBPP reçoit la tâche** (il a besoin
      de `test_list` pour `run_tests`). Au choix :
      `python mcp_tools_mbpp.py --task-file ../cache/mbpp_task.json`
      ou variable d'env `MBPP_TASK_FILE`. **À figer maintenant**, A lance le process.
- [ ] Même décision pour SWE-bench : comment le serveur reçoit `docker_image`,
      `eval_script`, `TESTBED_PATH` (env vars ou args CLI).
- [ ] Décider qui construit l'objet `Sandbox` : A dans son CLI, à partir des args
      `--mcp-stdio` / `--mcp-server`.

## 0.6 Les deux mocks de démarrage

Pour ne pas s'attendre l'un l'autre :

- [ ] **B fournit à A un `FakeSandbox`** (10 lignes) dès le jour 1 : `execute()` fait
      un `exec()` naïf, `get_manual()` renvoie un texte en dur. A peut coder toute
      sa boucle dessus.
- [ ] **A fournit à B un `scripts/fake_agent.py`** : un script qui envoie 3 blocs de
      code en dur à la sandbox et affiche les `ExecutionResult`. B teste sans LLM.

## 0.7 Répartition des fichiers (évite les conflits git)

| Chemin | Propriétaire |
|---|---|
| `schemas/`, `contract.py` | **commun** (modif = accord des deux) |
| `llm/`, `agent/`, `agent_mbpp/`, `agent_swebench/` | **A** |
| `sandbox/`, `mcp/`, `mcp_tools_*.py`, `docker/` | **B** |
| `sandbox_template.json` | **B** |
| `BENCHMARK_REPORT.md` | **A** (ablation par B) |
| `README.md` | **commun** (chacun ses sections) |

---

# LOT A — CÔTÉ AGENT

## A.1 Couche LLM

- [ ] `class LLMResponse` : `text`, `input_tokens`, `output_tokens`, `latency_ms`, `retries`, `api_url`, `model_name`
- [ ] `class LLMProvider(ABC)` : `complete(messages, stop, max_tokens) -> LLMResponse`
- [ ] `class OpenAICompatibleProvider(LLMProvider)` (couvre OpenRouter, Groq, Together, Fireworks…)
- [ ] Abstraction suffisante pour changer de provider sans refactor (c'est ça qui est noté, pas le choix du provider)
- [ ] **Multi-tokens par provider — obligatoire**
  - [ ] `class TokenRotator` : `next_key()`, `mark_rate_limited(key, retry_after)`, `mark_exhausted(key)`
  - [ ] Plusieurs clés lues depuis l'env (`OPENROUTER_API_KEY`, `OPENROUTER_API_KEY_2`, ou liste séparée par virgules)
- [ ] Fallback de provider si indisponibilité
- [ ] Retry + backoff sur 429 / 5xx / timeout → comptés dans `retries` et `total_requests`
- [ ] **`stop_sequences`** (`<end_code>`, `</tool_call>`…) → empêche le modèle d'halluciner l'observation
- [ ] Usage tracking : tokens, retries, latence, nombre de requêtes
- [ ] Free tiers uniquement, **aucune clé en dur** (grade 0 sinon)

## A.2 Extraction de code

- [ ] `extract_code(llm_text: str) -> ExtractedCode | None`
- [ ] Format 1 — bloc Python (primaire) : ` ```python ... ``` ` + `<end_code>`
- [ ] Format 2 — XML Anthropic : `<invoke name="..."><parameter name="...">…</parameter></invoke>`
- [ ] Format 3 — JSON/Hermes : `<tool_call>{"name": "...", "arguments": {...}}</tool_call>`
- [ ] Format 4 — ReAct : `Action: tool_name` / `Action Input: {...}`
- [ ] `to_python_call(name, args) -> str` → `result = read_file(filepath="/testbed/file.py")`
- [ ] Tolérance : bloc non fermé, ` ``` ` sans langage, texte parasite
- [ ] Si interprétation « de secours » → le signaler pour que B/le LLM le sache
- [ ] `None` propre si rien d'exploitable → observation d'erreur explicite au LLM

## A.3 Boucle agent

- [ ] `class AgentLoop`
  - [ ] `__init__(llm, sandbox: SandboxProtocol, system_prompt, max_iterations)`
  - [ ] `run(task) -> SolutionOutput`
  - [ ] `_build_messages()` — historique Thought / Code / Observation
  - [ ] `_record_step(...) -> StepMetrics`
  - [ ] `_check_limits()` — itérations, tokens cumulés, temps mur
- [ ] `max_iterations` **paramétrable**
- [ ] Arrêt sur `result.final_answer is not None` OU limite atteinte
- [ ] Aucun crash possible → `SolutionOutput(success=False, error=...)` écrit quand même
- [ ] Troncature / résumé des vieilles observations pour tenir le budget

## A.4 System prompts (fortement noté)

- [ ] Doc des outils **injectée depuis `sandbox.get_manual()`** — jamais recopiée à la main
- [ ] Slots explicites : `Thought:` / `Code:` / `Observation:`
- [ ] **Au moins un exemple complet** de boucle de raisonnement (few-shot)
- [ ] Méthodologie de debug pas-à-pas : lire → chercher → hypothèse → éditer → tester
- [ ] Prompt MBPP et prompt SWE-bench séparés
- [ ] Comparaison empirique prompt vague vs prompt explicite (→ sert d'ablation §C.1)

> ⚠️ **MBPP : 6 000 tokens d'entrée cumulés sur toute la tâche.** L'historique
> grossit à chaque tour, donc un prompt système de 1 500 tokens rend la tâche
> mathématiquement impossible. **Mesure ton prompt en tokens dès le début.**

## A.5 CLI agent MBPP

- [ ] `uv run python -m agent_mbpp --task-file ... --output ... --model-name ... --provider-url ...`
- [ ] Clé API lue depuis l'environnement
- [ ] Chargement `MBPPTaskInput`, lancement du serveur MCP MBPP (selon §0.5)
- [ ] Écriture de `SolutionOutput` : `benchmark="mbpp"`, `solution` = code Python
- [ ] Limites : **10 itérations / 6k in / 1.5k out / 120 s**
- [ ] Objectif : **4/5**

## A.6 CLI agent SWE-bench

- [ ] `uv run python -m agent_swebench --task-file ... --output ... --model-name ... --provider-url ...`
- [ ] Chargement `SWEBenchTaskInput`, passage des infos au serveur MCP de B
- [ ] `SolutionOutput` : `benchmark="swebench"`, `solution` = patch renvoyé par `get_patch()`
- [ ] Limites : **30 itérations / 300k in / 10k out / 900 s**
- [ ] Objectif : **2/3**
- [ ] Tâches de mise au point : `sympy__sympy-14711`, `sympy__sympy-13480`, `pydata__xarray-4629`

---

# LOT B — CÔTÉ EXÉCUTION

## B.1 Sandbox — classe principale

- [ ] `class Sandbox`
  - [ ] `__init__(config: SandboxConfig, mcp_client: MCPClient | None = None)`
  - [ ] `execute(code: str) -> ExecutionResult`
  - [ ] `get_manual() -> str`
  - [ ] `close()`
- [ ] **Persistance des variables entre appels à `execute()`** (c'est l'intérêt du code-calling vs JSON tool calling)
- [ ] `final_answer(answer)` injecté dans le namespace
  - [ ] Implémentation typique : lève `_FinalAnswer(value)`, attrapée par `execute()`
  - [ ] Toujours présent, indépendamment du serveur MCP connecté
  - [ ] MBPP : `final_answer(code)` — SWE-bench : `final_answer(get_patch())`

## B.2 Sécurité — chaque point est testé par `exam_sandbox.sh` (tout-ou-rien)

- [ ] **Imports** : allowlist stricte
  - [ ] `guarded_import(name, globals, locals, fromlist, level)` remplaçant `__import__`
  - [ ] Gérer les patterns `"math.*"`
  - [ ] Bloquer les contournements : `importlib`, `__import__` direct
- [ ] **Filesystem** : allowlist de répertoires
  - [ ] `is_path_allowed(path, allowed) -> bool`
  - [ ] ⚠️ **`os.path.realpath` avant comparaison** → sinon `/testbed/../etc/passwd` passe
  - [ ] Wrapper sur `open()`, plus `os.open`, `pathlib.Path.open`, `shutil`
  - [ ] Plusieurs entrées (`/testbed` + `/tmp/agent`), évaluées **dans** la sandbox
- [ ] **Réseau** : neutraliser `socket.socket`, `socket.create_connection`
- [ ] **Timeout** : tuer au-delà de `max_execution_time_seconds` (code sandboxé uniquement)
- [ ] **Mémoire** : `resource.setrlimit(RLIMIT_AS, max_memory_mb * 1024 * 1024)`
- [ ] **Builtins restreints** : `build_safe_builtins(config) -> dict`
  - [ ] Retirer/écraser `eval`, `exec`, `compile`, `open`, `__import__`, `input`, `breakpoint`, `globals`, `help`
  - [ ] Bloquer l'évasion par attributs : `().__class__.__bases__[0].__subclasses__()`
- [ ] **Propagation** : `KeyboardInterrupt` et `SystemExit` jamais avalés
  ```python
  except (KeyboardInterrupt, SystemExit):
      raise
  except Exception as e:
      ...
  ```
- [ ] **Sécurité en stdlib pure** — `RestrictedPython` et équivalents interdits

## B.3 Choix d'isolation (à défendre en soutenance)

- [ ] Trancher : `exec()` in-process vs `subprocess` / `multiprocessing`
  - in-process : simple, mais timeout dur et RLIMIT difficiles à appliquer proprement
  - process séparé : vraie frontière, timeout par `kill`, mais il faut sérialiser l'état
- [ ] Documenter le trade-off dans le README

## B.4 Feedback explicite au LLM — 5 cas obligatoires

Le champ `error` de `ExecutionResult` doit couvrir :

- [ ] Aucun bloc de code valide trouvé *(cas remonté par A, format d'erreur à convenir)*
- [ ] Bloc mal formé mais interprété quand même → **expliquer comment**
- [ ] Timeout atteint → indiquer que la sortie est partielle
- [ ] Sortie d'outil tronquée → le dire explicitement
- [ ] Édition ayant introduit une erreur de syntaxe / lint

> *« The LLM should never be left guessing about what happened. »*

## B.5 CLI sandbox (REPL)

- [ ] `uv run sandbox` → REPL interactif
- [ ] `uv run sandbox sandbox_template.json`
- [ ] `uv run sandbox --mcp-stdio "python mcp_tools_mbpp.py" sandbox_template.json`
- [ ] `uv run sandbox --mcp-server <URL>`
- [ ] Comportement :
  - [ ] Boucle prompt → lecture → exécution dans le **même namespace**
  - [ ] Toutes les restrictions actives (imports, FS, timeout, RAM)
  - [ ] Affiche résultat ou erreur levée
  - [ ] Sortie propre sur `exit` **et** sur EOF (Ctrl+D)

## B.6 Génération du manuel

- [ ] `build_manual(tools: list[ToolSchema], config: SandboxConfig) -> str`
  - [ ] Nom, description, types de paramètres de chaque outil MCP
  - [ ] `final_answer` documenté à part (ce n'est pas un outil MCP)
  - [ ] Rappel des imports autorisés et des répertoires accessibles
- [ ] **Test** : connecter un autre serveur MCP → le manuel change tout seul

## B.7 Client MCP

- [ ] `class MCPClient`
  - [ ] `connect_stdio(command: str)` — lance le serveur en sous-process
  - [ ] `connect_http(url: str)` — transport streamable HTTP
  - [ ] `list_tools() -> list[ToolSchema]`
  - [ ] `list_resources()` / `list_prompts()` (le sujet demande de les exposer)
  - [ ] `call_tool(name, arguments) -> str`
  - [ ] `close()`
- [ ] `make_wrappers(client) -> dict[str, Callable]`
  - [ ] Une fonction Python par outil, avec `__name__` et `__doc__` corrects
  - [ ] Injectée dans le namespace sandbox
  - [ ] **Aucun nom d'outil hardcodé**

## B.8 `mcp_tools_mbpp.py`

- [ ] `run_tests(code: str) -> str` — exécute les tests de la tâche contre le code
- [ ] Réception de la tâche selon la convention figée en §0.5
- [ ] Outils additionnels libres (ex. `lint(code)`)

## B.9 `mcp_tools_swebench.py` — les 9 outils obligatoires

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

## B.10 Docker (SWE-bench)

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

Pilote : **A** (c'est lui qui a la couche multi-modèles). Ablation : **B**.

- [ ] **≥ 5 modèles** × **≥ 3 tâches SWE-bench** identiques
- [ ] Setup : modèles, providers, tâches choisies **et pourquoi**
- [ ] Table de résultats par couple modèle × tâche : Pass/Fail · itérations · tokens in · tokens out · wall-clock
- [ ] Fiabilité provider : temps de réponse moyen, retries, disponibilité — *(données de A)*
- [ ] **≥ 2 métriques intermédiaires** parmi :
  - [ ] Étape du premier accès au fichier qui figure dans le patch final *(métrique côté outils → B)*
  - [ ] Étape où les échecs de tests diminuent pour la première fois *(B)*
  - [ ] Itérations entre « tests passent » et `final_answer` — idéal : 0 *(A)*
- [ ] **Ablation** : un avant/après sur un changement, même modèle, mêmes tâches
  - suggestion A : prompt vague vs prompt explicite
  - suggestion B : avec vs sans `find_references`, ou troncature des sorties d'outils
- [ ] Conclusions appuyées sur les données : modèles retenus / écartés
- [ ] Les `solution.json` correspondants **committés dans le repo**

## C.2 README.md

- [ ] Première ligne en italique : `*This project has been created as part of the 42 curriculum by <login1>, <login2>.*`
- [ ] **Description** — commun
- [ ] **Instructions** (install, config, exécution) — commun
- [ ] **Resources** + description de l'usage de l'IA (quelles tâches, quelles parties) — commun
- [ ] Architecture système — commun
- [ ] Explication de la boucle agent — **A**
- [ ] Design de la sandbox (dont le choix d'isolation) — **B**
- [ ] Détails d'implémentation des outils — **B**
- [ ] Résultats de benchmark et analyse — **A**
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

- [ ] **A explique le lot B à voix haute**, sans notes : sécurité sandbox, choix
      d'isolation, comment les outils MCP deviennent des fonctions Python
- [ ] **B explique le lot A à voix haute** : boucle Thought→Code→Observation,
      les 4 formats d'extraction, rotation des clés, calcul du budget tokens
- [ ] Chacun a déjà fait **au moins un commit** dans le lot de l'autre
- [ ] Répétition : chacun fait une modif live dans le lot de l'autre, chronométrée
- [ ] `git checkout` propre après l'exercice
- [ ] Test de la commande complète :
      `./exam_TYPE.sh --student-path ./student --moulinette-path ./moulinette --env-file /path/to/.env`

---

# PARTIE D — PLANNING ET POINTS D'INTÉGRATION

| Jalon | A livre | B livre | Test d'intégration |
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
      et il ne dépend d'aucun LLM. B doit le faire passer avant tout le reste.
- [ ] **Intégration #1 le plus tôt possible.** Le sujet le dit : si l'agent ne résout
      pas la tâche la plus simple **sans limites**, ajouter les limites n'aidera pas.
- [ ] **Aucune modification unilatérale de `contract.py` ou `schemas/`.**
      Un changement là = un message à l'autre avant de commit.
- [ ] Merge sur `main` seulement après un test d'intégration qui passe.
