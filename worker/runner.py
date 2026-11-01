"""Run an analysis in a child process with a hard wall-clock timeout."""

import json
import multiprocessing
import tempfile
import time
from dataclasses import asdict
from pathlib import Path

from worker.analyzer import analyze_repository
from worker.archive import ArchiveLimits
from worker.github import AnalysisError, GitHubClient, LimitExceeded, parse_repository_url, validate_sha


def _receive_progress(channel, timeout):
    try:
        return channel.recv() if channel.poll(timeout) else None
    except (EOFError, BrokenPipeError):
        return False


def _child_analysis(url: str, sha: str | None, limits_data: dict, result_path: str, channel):
    try:
        limits = ArchiveLimits(**limits_data)
        repo = parse_repository_url(url)
        if sha is None:
            github = GitHubClient()
            try:
                sha = github.resolve_default_commit(repo, deadline=time.monotonic() + limits.timeout_seconds)
            finally:
                github.close()
        else:
            sha = validate_sha(sha)
        result = analyze_repository(repo, sha, limits, workspace=Path(result_path).parent,
                                    progress=lambda state, progress: channel.send((state, progress)))
        payload = {"result": result}
    except AnalysisError as exc:
        payload = {"error": {"code": exc.code, "message": str(exc)}}
    except Exception:
        payload = {"error": {"code": "ANALYSIS_FAILED", "message": "Analysis process failed unexpectedly"}}
    try:
        Path(result_path).write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    finally:
        channel.close()


def run_analysis(url: str, sha: str | None, limits: ArchiveLimits, *, on_progress=None, on_tick=None) -> dict:
    parse_repository_url(url)
    if sha is not None:
        validate_sha(sha)
    context = multiprocessing.get_context("spawn")
    receiver, sender = context.Pipe(duplex=False)
    with tempfile.TemporaryDirectory(prefix="repoatlas-result-") as tmp:
        result_path = str(Path(tmp) / "result.json")
        process = context.Process(target=_child_analysis, args=(url, sha, asdict(limits), result_path, sender))
        started = time.monotonic()
        process.start()
        sender.close()
        try:
            channel_open = True
            while process.is_alive():
                if time.monotonic() - started >= limits.timeout_seconds:
                    raise LimitExceeded("Analysis time limit exceeded")
                event = _receive_progress(receiver, 0.25) if channel_open else None
                if event is False:
                    channel_open = False
                elif event is not None and on_progress:
                    on_progress(*event)
                if not channel_open:
                    time.sleep(0.05)
                if on_tick:
                    on_tick()
            process.join()
            while channel_open:
                event = _receive_progress(receiver, 0)
                if event is False or event is None:
                    break
                if on_progress:
                    on_progress(*event)
            if process.exitcode != 0 or not Path(result_path).is_file():
                raise AnalysisError("ANALYSIS_FAILED", "Analysis process exited without a result")
            payload = json.loads(Path(result_path).read_text(encoding="utf-8"))
            if "error" in payload:
                raise AnalysisError(payload["error"]["code"], payload["error"]["message"])
            return payload["result"]
        finally:
            if process.is_alive():
                process.terminate()
                process.join(5)
                if process.is_alive():
                    process.kill()
                    process.join()
            receiver.close()
