"""Sature un provider jusqu'au premier 429, pour valider la rotation de cles.

    uv run python scripts/force_rate_limit.py gemini
    uv run python scripts/force_rate_limit.py groq --key-index 2

Vise la limite par MINUTE (elle se reinitialise toute seule), pas celle par
jour : requetes minimales, max_tokens=1, arret des le premier 429.
"""
import argparse
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

import httpx
from dotenv import load_dotenv

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from schemas.tools_agent import GEMINI_API_URL, GROQ_API_URL  # noqa: E402

load_dotenv()

PROVIDERS = {
    "gemini": (GEMINI_API_URL, "GEMINI_API_KEYS", "GEMINI_API_KEY", "gemini-3.5-flash-lite"),
    "groq": (GROQ_API_URL, "GROQ_API_KEYS", "GROQ_API_KEY", "openai/gpt-oss-20b"),
}


def load_keys(plural: str, single: str) -> list[str]:
    raw = os.environ.get(plural, os.environ.get(single, ""))
    return [k.strip() for k in raw.split(",") if k.strip()]


def one_request(url: str, key: str, model: str, n: int) -> tuple[int, int, str]:
    """Renvoie (numero, status, info). Ne renvoie jamais la cle."""
    try:
        r = httpx.post(
            url,
            headers={"Authorization": f"Bearer {key}", "content-type": "application/json"},
            json={
                "model": model,
                "max_tokens": 1,
                "messages": [{"role": "user", "content": "hi"}],
            },
            timeout=30.0,
        )
        info = ""
        if r.status_code == 429:
            retry_after = r.headers.get("retry-after") or r.headers.get("x-ratelimit-reset-requests")
            info = f"Retry-After={retry_after!r} | {r.text[:200]}"
        return n, r.status_code, info
    except httpx.HTTPError as e:
        return n, -1, f"{type(e).__name__}: {e}"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("provider", choices=sorted(PROVIDERS))
    ap.add_argument("--burst", type=int, default=40, help="requetes envoyees (defaut 40)")
    ap.add_argument("--concurrency", type=int, default=10)
    ap.add_argument("--key-index", type=int, default=0, help="quelle cle du pool saturer")
    ap.add_argument("--model", default=None)
    args = ap.parse_args()

    url, plural, single, default_model = PROVIDERS[args.provider]
    model = args.model or default_model
    keys = load_keys(plural, single)
    if not keys:
        sys.exit(f"aucune cle dans {plural} ni {single}")
    if args.key_index >= len(keys):
        sys.exit(f"--key-index {args.key_index} hors du pool ({len(keys)} cle(s))")

    key = keys[args.key_index]
    print(f"provider={args.provider} model={model} "
          f"cle #{args.key_index + 1}/{len(keys)} (…{key[-4:]}) "
          f"burst={args.burst} concurrence={args.concurrency}")

    start = time.monotonic()
    codes: dict[int, int] = {}
    first_429 = None
    with ThreadPoolExecutor(max_workers=args.concurrency) as pool:
        futures = [pool.submit(one_request, url, key, model, n)
                   for n in range(1, args.burst + 1)]
        for fut in as_completed(futures):
            n, status, info = fut.result()
            codes[status] = codes.get(status, 0) + 1
            if status == 429 and first_429 is None:
                first_429 = (n, time.monotonic() - start, info)
                print(f"\n>>> 429 sur la requete #{n} apres {first_429[1]:.1f}s")
                print(f"    {info}\n")

    print(f"termine en {time.monotonic() - start:.1f}s")
    for status in sorted(codes):
        label = {200: "OK", 429: "rate limited", -1: "erreur reseau"}.get(status, "")
        print(f"  {status:>4} : {codes[status]:>3}  {label}")

    if first_429 is None:
        print("\naucun 429 : augmente --burst / --concurrency, ou la limite RPM "
              "de ce modele est plus haute que le burst envoye.")
    else:
        print("\nla rotation de cles peut maintenant etre testee sur cette cle.")


if __name__ == "__main__":
    main()
