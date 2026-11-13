import stat
import time
import zipfile

import pytest

from worker.archive import ArchiveLimits, index_archive
from worker.github import AnalysisError, LimitExceeded


def archive(tmp_path, entries):
    path = tmp_path / "repository.zip"
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as output:
        for name, content in entries:
            output.writestr(name, content)
    return path


def test_index_keeps_all_paths_without_extracting_source(tmp_path):
    path = archive(tmp_path, [
        ("project-sha/", b""), ("project-sha/src/main.py", b"def run(): pass\n"),
        ("project-sha/src/data.bin", b"\x00\x01"), ("project-sha/readme.md", b"readme"),
        ("project-sha/한글/file.go", b"package main"),
    ])
    nodes, warnings = index_archive(path, "project", ArchiveLimits())
    by_path = {node.path: node for node in nodes}
    assert set(by_path) == {".", "src", "src/main.py", "src/data.bin", "readme.md", "한글", "한글/file.go"}
    assert by_path["src/main.py"].archive_entry == "project-sha/src/main.py"
    assert by_path["src/main.py"].parent_path == "src"
    assert by_path["src/data.bin"].archive_entry is None
    assert by_path["한글/file.go"].parse_status == "unsupported"
    assert warnings == []
    assert not (tmp_path / "src").exists()


@pytest.mark.parametrize("name", ["project/../escape.py", "project/dir/../../escape.py", "/project/absolute", "project/dir\\escape", "project/C:/escape"])
def test_rejects_unsafe_paths(tmp_path, name):
    if "\\" in name:
        path = archive(tmp_path, [(name.replace("\\", "_"), b"bad")])
        path.write_bytes(path.read_bytes().replace(name.replace("\\", "_").encode(), name.encode()))
    else:
        path = archive(tmp_path, [(name, b"bad")])
    with pytest.raises(AnalysisError, match="unsafe path"):
        index_archive(path, "project", ArchiveLimits())
    assert not (tmp_path / "escape.py").exists()


def test_skips_symlink_without_following_and_rejects_duplicate_paths(tmp_path):
    symlink = zipfile.ZipInfo("project/link")
    symlink.create_system = 3
    symlink.external_attr = (stat.S_IFLNK | 0o777) << 16
    path = archive(tmp_path, [(symlink, b"../../secret")])
    nodes, warnings = index_archive(path, "project", ArchiveLimits())
    link = next(node for node in nodes if node.path == "link")
    assert link.archive_entry is None and link.parse_status == "skipped"
    assert link.metadata["is_symlink"] is True
    assert warnings == ["Symbolic link was not followed: link"]

    with pytest.warns(UserWarning, match="Duplicate name"):
        path = archive(tmp_path, [("project/file.py", b"one"), ("project/file.py", b"two")])
    with pytest.raises(AnalysisError, match="duplicate"):
        index_archive(path, "project", ArchiveLimits())


def test_resource_limits_and_large_source_warning(tmp_path):
    path = archive(tmp_path, [("project/a.py", b"123456"), ("project/b.py", b"abc")])
    with pytest.raises(LimitExceeded, match="file count"):
        index_archive(path, "project", ArchiveLimits(max_files=1))
    with pytest.raises(LimitExceeded, match="MAX_EXTRACTED_BYTES"):
        index_archive(path, "project", ArchiveLimits(max_extracted_bytes=5))
    nodes, warnings = index_archive(path, "project", ArchiveLimits(max_source_file_bytes=5))
    assert next(node for node in nodes if node.path == "a.py").parse_status == "skipped"
    assert warnings == ["File exceeds analysis size limit: a.py"]


def test_rejects_invalid_archive(tmp_path):
    path = tmp_path / "invalid.zip"
    path.write_bytes(b"not a zip archive")
    with pytest.raises(AnalysisError) as error:
        index_archive(path, "project", ArchiveLimits())
    assert error.value.code == "INVALID_ARCHIVE"


def test_rejects_excessive_compression_ratio(tmp_path):
    path = archive(tmp_path, [("project/large.py", b"x" * 1_000_001)])
    with pytest.raises(LimitExceeded, match="compression ratio"):
        index_archive(path, "project", ArchiveLimits())


def test_expired_deadline_stops_indexing(tmp_path):
    path = archive(tmp_path, [("project/a.py", b"pass")])
    with pytest.raises(LimitExceeded, match="time limit"):
        index_archive(path, "project", ArchiveLimits(), deadline=time.monotonic() - 1)


def test_rejects_archive_with_multiple_roots(tmp_path):
    path = archive(tmp_path, [("first/a.py", b"a"), ("second/b.py", b"b")])
    with pytest.raises(AnalysisError, match="common root"):
        index_archive(path, "project", ArchiveLimits())


def test_index_does_not_load_source_file_contents(tmp_path, monkeypatch):
    path = archive(tmp_path, [(f"project/file{i}.py", b"x" * 100_000) for i in range(20)])

    def forbidden_read(*args, **kwargs):
        raise AssertionError("Indexing must not read file contents")

    monkeypatch.setattr(zipfile.ZipFile, "read", forbidden_read)
    nodes, warnings = index_archive(path, "project", ArchiveLimits())
    assert len(nodes) == 21 and not warnings
    assert all(not hasattr(node, "content") for node in nodes)


def test_environment_can_override_large_repository_limits(monkeypatch):
    monkeypatch.setenv("MAX_ARCHIVE_BYTES", "1048576")
    monkeypatch.setenv("MAX_FILES", "123")
    limits = ArchiveLimits.from_environment()
    assert limits.max_archive_bytes == 1048576 and limits.max_files == 123
    assert limits.max_extracted_bytes == 2 * 1024 * 1024 * 1024


def test_default_limit_allows_more_than_10000_files(tmp_path):
    path = tmp_path / "large.zip"
    with zipfile.ZipFile(path, "w") as output:
        for index in range(10_001):
            output.writestr(f"project/files/file{index}.txt", b"")
    nodes, warnings = index_archive(path, "project", ArchiveLimits())
    assert sum(node.kind == "file" for node in nodes) == 10_001
    assert not warnings
