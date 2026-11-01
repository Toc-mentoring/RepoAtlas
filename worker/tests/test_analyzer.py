import json
import zipfile

from worker.analyzer import analyze_archive, analyze_repository
from worker.archive import ArchiveLimits
from worker.github import parse_repository_url


def test_snapshot_contains_facts_without_source_contents(tmp_path):
    path = tmp_path / "repo.zip"
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("repo-sha/src/main.py", "from . import helper\nsecret = 'dont-store-this'\ndef run(): pass\n")
        archive.writestr("repo-sha/src/helper.py", "class Helper: pass\n")
        archive.writestr("repo-sha/schema.sql", "CREATE TABLE users (id INT PRIMARY KEY);")
        archive.writestr("repo-sha/compose.yml", "services:\n  api:\n    environment:\n      TOKEN: dont-store-this\n")
    progress = []
    result = analyze_archive(path, parse_repository_url("https://github.com/example/repo"), "a" * 40,
                             ArchiveLimits(), progress=lambda *args: progress.append(args))
    assert result["status"] == "completed"
    assert result["stats"]["file_count"] == 4
    assert result["stats"]["resolved_imports"] == 1
    assert result["stats"]["tables"] == 1
    assert result["code_references"][0]["target_path"] == "src/helper.py"
    assert result["schema_tables"][0]["name"] == "users"
    assert progress == [("parsing", 30), ("resolving", 75)]
    assert "dont-store-this" not in json.dumps(result)
    assert "content" not in json.dumps(result)


def test_conflicting_schema_and_parse_errors_produce_partial_result(tmp_path):
    path = tmp_path / "repo.zip"
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("repo-sha/a.sql", "CREATE TABLE users (id INT);")
        archive.writestr("repo-sha/b.sql", "CREATE TABLE users (id TEXT);")
        archive.writestr("repo-sha/broken.py", "def broken(:\n")
    result = analyze_archive(path, parse_repository_url("https://github.com/example/repo"), "a" * 40, ArchiveLimits())
    assert result["status"] == "partial"
    assert result["schema_tables"] == []
    assert any("Conflicting table" in warning for warning in result["warnings"])
    assert next(n for n in result["source_nodes"] if n["path"] == "broken.py")["parse_status"] == "failed"


def test_archive_uses_parent_controlled_workspace(tmp_path, monkeypatch):
    class FakeGitHub:
        def download_archive(self, repo, sha, destination, **kwargs):
            assert destination.parent == tmp_path
            with zipfile.ZipFile(destination, "w") as archive:
                archive.writestr("repo-sha/main.py", "def run(): pass\n")

        def close(self):
            pass

    monkeypatch.setattr("worker.analyzer.GitHubClient", FakeGitHub)
    result = analyze_repository(parse_repository_url("https://github.com/example/repo"), "a" * 40,
                                ArchiveLimits(), workspace=tmp_path)
    assert result["status"] == "completed"
    assert (tmp_path / "snapshot.zip").is_file()
