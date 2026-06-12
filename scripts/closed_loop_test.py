"""Closed-loop test for the company-name -> 法人 feature.

Loads a company-name CSV/XLSX, resolves each company name to a CNPJ via the
cnpj.biz search + matcher, fetches the responsible party through the existing
analysis pipeline, and compares the discovered 法人 against the file's own
ground-truth responsible column.

Usage:
    .venv\\Scripts\\python.exe scripts/closed_loop_test.py [path] [--limit N] [--concurrency N]

Requires Blurpath proxy credentials in .env so the headless browser can clear
Cloudflare on cnpj.biz.
"""
from __future__ import annotations

import argparse
import re
import sys
import unicodedata
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from cnpj_tool.importer import parse_upload_details  # noqa: E402
from cnpj_tool.server import build_analyzer  # noqa: E402

DEFAULT_CSV = r"C:\Users\Administrator\Downloads\巴西最新到130.csv"


def _tokens(value: str) -> set[str]:
    decomposed = unicodedata.normalize("NFKD", str(value or ""))
    ascii_text = "".join(ch for ch in decomposed if not unicodedata.combining(ch)).casefold()
    return {token for token in re.sub(r"[^a-z0-9]+", " ", ascii_text).split() if len(token) > 1}


def _names_match(hint: str, found_names: list[str]) -> bool:
    hint_tokens = _tokens(hint)
    if not hint_tokens:
        return False
    for name in found_names:
        found_tokens = _tokens(name)
        if not found_tokens:
            continue
        overlap = hint_tokens & found_tokens
        if not overlap:
            continue
        if len(overlap) >= max(1, len(hint_tokens) - 1) or len(overlap) / len(hint_tokens) >= 0.6:
            return True
        # one name is a shortened form of the other (e.g. "Guilherme Blanke" vs
        # "Guilherme de Abreu Blanke"): the smaller token-set is fully contained.
        smaller = found_tokens if len(found_tokens) <= len(hint_tokens) else hint_tokens
        if len(overlap) >= 2 and overlap == smaller:
            return True
    return False


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("path", nargs="?", default=DEFAULT_CSV)
    parser.add_argument("--limit", type=int, default=10, help="rows to test (0 = all)")
    parser.add_argument("--concurrency", type=int, default=0, help="override SYSTEM_CONCURRENCY")
    args = parser.parse_args()

    source = Path(args.path)
    if not source.exists():
        print(f"File not found: {source}")
        return 2

    details = parse_upload_details(source.name, source.read_bytes())
    if details.mode != "name" or not details.name_queries:
        print(f"File parsed as mode={details.mode} with {len(details.name_queries)} name rows; expected name mode.")
        return 2

    queries = details.name_queries if args.limit <= 0 else details.name_queries[: args.limit]
    print(f"Loaded {len(details.name_queries)} company-name rows; testing {len(queries)}.\n")

    analyzer = build_analyzer()
    if args.concurrency:
        analyzer.max_concurrency = max(1, args.concurrency)
    if analyzer.search_companies is None:
        print("search_companies is not wired (browser client unavailable).")
        return 2

    progress = {"n": 0}

    def on_result(result) -> None:
        meta = result.name_meta or {}
        names = list(result.responsible.names) if result.responsible else []
        hit = _names_match(meta.get("responsible_hint", ""), names)
        progress["n"] += 1
        verdict = "MATCH" if hit else result.status
        print(
            f"[{progress['n']:>3}] {meta.get('query_name', '')[:38]:38} -> "
            f"{(meta.get('matched_cnpj') or '-'):14} | found: {('; '.join(names) or '-')[:40]:40} "
            f"| expected: {(meta.get('responsible_hint') or '-')[:30]:30} | {verdict}"
        )

    try:
        results = analyzer.analyze_many_by_name(queries, on_result=on_result)
    finally:
        analyzer.close()

    # Materialize the same output CSV the desktop app would produce.
    from cnpj_tool.checkpoints import CheckpointStore
    from cnpj_tool.config import output_dir_path
    from cnpj_tool.source_files import output_filename_for

    output_dir = output_dir_path()
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / output_filename_for(source.name, "name")
    output_path.write_bytes(CheckpointStore(output_dir).build_name_summary_csv(results=results))

    total = len(results)
    resolved = sum(1 for result in results if (result.name_meta or {}).get("matched_cnpj"))
    matched = sum(
        1
        for result in results
        if _names_match(
            (result.name_meta or {}).get("responsible_hint", ""),
            (result.responsible.names if result.responsible else []) or [],
        )
    )
    pct = (matched / total * 100) if total else 0.0
    print("\n==== Closed-loop summary ====")
    print(f"Rows tested        : {total}")
    print(f"Resolved to a CNPJ : {resolved}/{total}")
    print(f"法人 matched ground : {matched}/{total}  ({pct:.0f}%)")
    print(f"Output written     : {output_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
