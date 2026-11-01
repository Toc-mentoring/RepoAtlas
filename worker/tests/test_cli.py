import json

from worker import cli


def test_cli_writes_json_without_database(monkeypatch, tmp_path, capsys):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    expected = {
        "repository_url": "https://github.com/example/repo", "commit_sha": "a" * 40,
        "status": "completed", "stats": {"file_count": 1, "symbols": 1, "resolved_imports": 0},
        "warnings": [], "source_nodes": [{"path": "main.py"}],
    }
    monkeypatch.setattr(cli, "run_analysis", lambda url, sha, limits: expected)
    output = tmp_path / "result.json"
    assert cli.main(["https://github.com/example/repo", "--output", str(output)]) == 0
    assert json.loads(output.read_text(encoding="utf-8")) == expected
    assert "JSON:" in capsys.readouterr().out


def test_cli_rejects_invalid_url_without_writing_file(tmp_path, capsys):
    output = tmp_path / "result.json"
    assert cli.main(["https://example.com/repo", "--output", str(output)]) == 1
    assert not output.exists()
    assert "INVALID_REPOSITORY_URL" in capsys.readouterr().err


def test_failed_output_does_not_replace_existing_result(tmp_path, monkeypatch):
    output = tmp_path / "result.json"
    output.write_text("previous result", encoding="utf-8")
    monkeypatch.setattr(cli, "run_analysis", lambda url, sha, limits: {"commit_sha": "a" * 40})

    def fail(*args, **kwargs):
        raise OSError("disk full")

    monkeypatch.setattr(cli.json, "dump", fail)
    assert cli.main(["https://github.com/example/repo", "--output", str(output)]) == 1
    assert output.read_text(encoding="utf-8") == "previous result"
    assert list(tmp_path.iterdir()) == [output]
