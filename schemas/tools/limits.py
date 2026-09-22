from pathlib import Path

# Budgets et reglages de la boucle agent -- un seul endroit pour les regler.


PROJECT_ROOT = Path(__file__).resolve().parents[2]

MBPP_MAX_ITERATIONS = 10
MBPP_MAX_INPUT_TOKENS = 6_000
MBPP_MAX_OUTPUT_TOKENS = 1_500
MBPP_MAX_WALL_TIME_SECONDS = 120
MBPP_MCP_SERVER = PROJECT_ROOT / "mcp_tools_mbpp.py"
SW_BENCH_TOOLS = PROJECT_ROOT / "mcp_tools_swebench.py"

SWEBENCH_MAX_ITERATIONS = 30
SWEBENCH_MAX_INPUT_TOKENS = 300_000
SWEBENCH_MAX_OUTPUT_TOKENS = 10_000
SWEBENCH_MAX_WALL_TIME_SECONDS = 900
# Un bloc de code peut enchainer plusieurs outils, chacun borne a 30 s par
# `docker exec` cote serveur : les 30 s par defaut de la sandbox tueraient
# un bloc `run_tests()` + `get_patch()` avant son retour.
SWEBENCH_SANDBOX_TIMEOUT_SECONDS = 90
# Repertoire du depot dans les images SWE-bench officielles, si l'env ne le
# precise pas.
SWEBENCH_DEFAULT_TESTBED = "/testbed"


MAX_TOKENS_PAR_REQUETE = 2048

DEFAULT_TEMPERATURE = 0.0


MAX_CONSECUTIVE_ERRORS = 3
# Temps garde en reserve sous `max_wall_time_seconds` pour rendre la main et
# ecrire `solution.json` : depasse, c'est la moulinette qui tue le process et
# il n'y a AUCUNE sortie, contrairement a un depassement de tokens.
MARGE_SORTIE_SECONDS = 10
# Delai max d'une requete LLM, meme s'il reste plus de temps.
TIMEOUT_REQUETE_SECONDS = 60.0
# Reponse vide du modele (vu sur gemini-3.5-flash-lite) : relancee au lieu
# de bruler une iteration, dans cette limite.
MAX_REPONSES_VIDES = 2
# Mode NO_BASCULE (benchmark) : pauses fixes sur le meme modele avant
# d'abandonner, par iteration. 3 x 20 s couvrent une fenetre de quota/minute.
MAX_ATTENTES = 3
ATTENTE_SECONDS = 20.0
# Mode normal : tous les modeles sont tombes. Pause puis nouveau tour complet
# (les quotas par minute se rechargent) avant d'abandonner.
PAUSE_AVANT_ABANDON_SECONDS = 60.0
STATUS_BASCULE = {404, 408, 429, 500, 502, 503, 504}
# Budget de la seule section *limites* du manuel sandbox : les signatures
# d'outils MCP partent toujours en entier, hors de ce budget.
# 250 et pas 700 : le prompt systeme est repaye a CHAQUE requete, donc
# 700 couterait ~2150 tokens sur 10 iterations, un tiers du budget MBPP.
# Les 250 premiers caracteres portent les limites d'execution et le debut
# de la liste d'imports ; le reste est soit deja dans SYSTEM_PROMPT_MBPP
# (persistance, final_answer), soit decouvrable par l'observation d'erreur
# (builtins, attributs).
MAX_LIMITES_CHARS = 250

LAST_ITER_INTACTS = 10
MAX_OBS_CHARS = 100
CHARS_PAR_TOKEN = 4
MARGE_BUDGET = 0.9

BACKUP_DIR = PROJECT_ROOT / "backup_memory"
BACKUP_FILE = BACKUP_DIR / "backup.json"
