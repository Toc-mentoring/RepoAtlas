"""Analyze a public GitHub URL and write metadata to JSON without using a DB."""

import argparse
import json
import os
import sys
import tempfile
from pathlib import Path

from worker.archive import ArchiveLimits
from worker.github import AnalysisError, parse_repository_url
from worker.runner import run_analysis


def _write_json(output: Path, result: dict) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    name = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=output.parent,
                                         prefix=f".{output.name}.", suffix=".tmp", delete=False) as stream:
            name = stream.name
            json.dump(result, stream, ensure_ascii=False, indent=2)
            stream.write("\n")
        os.replace(name, output)
    finally:
        if name is not None:
            Path(name).unlink(missing_ok=True)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Analyze a public GitHub repository without saving to a database")
    parser.add_argument("url", help="https://github.com/owner/repository")
    parser.add_argument("--sha", help="optional fixed 40-character commit SHA; defaults to the default branch")
    parser.add_argument("--output", type=Path, help="JSON output path (default: analysis-output/owner-repo-sha.json)")
    args = parser.parse_args(argv)
    try:
        repo = parse_repository_url(args.url)
        def show_progress(state, percent):
            print(f"{state}: {percent}%", file=sys.stderr, flush=True)

        result = run_analysis(repo.url, args.sha, ArchiveLimits.from_environment(), on_progress=show_progress)
        output = args.output or Path("analysis-output") / f"{repo.owner}-{repo.name}-{result['commit_sha'][:12]}.json"
        print("writing JSON...", file=sys.stderr, flush=True)
        _write_json(output, result)
    except (AnalysisError, OSError, ValueError) as exc:
        code = exc.code if isinstance(exc, AnalysisError) else "OUTPUT_ERROR"
        print(f"{code}: {exc}", file=sys.stderr)
        return 1
    print(f"{result['status']} {result['repository_url']} @ {result['commit_sha']}")
    print(f"files={result['stats']['file_count']} symbols={result['stats']['symbols']} "
          f"resolved_imports={result['stats']['resolved_imports']} warnings={len(result['warnings'])}")
    print(f"JSON: {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
