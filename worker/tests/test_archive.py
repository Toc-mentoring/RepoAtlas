import stat
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
    assert by_path["src/main.py"].content == b"def run(): pass\n"
    assert by_path["src/main.py"].parent_path == "src"
    assert by_path["src/data.bin"].content is None
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


def test_rejects_symlink_and_duplicate_paths(tmp_path):
    symlink = zipfile.ZipInfo("project/link")
    symlink.create_system = 3
    symlink.external_attr = (stat.S_IFLNK | 0o777) << 16
    path = archive(tmp_path, [(symlink, b"../../secret")])
    with pytest.raises(AnalysisError, match="symbolic link"):
        index_archive(path, "project", ArchiveLimits())

    with pytest.warns(UserWarning, match="Duplicate name"):
        path = archive(tmp_path, [("project/file.py", b"one"), ("project/file.py", b"two")])
    with pytest.raises(AnalysisError, match="duplicate"):
        index_archive(path, "project", ArchiveLimits())


def test_resource_limits_and_large_source_warning(tmp_path):
    path = archive(tmp_path, [("project/a.py", b"123456"), ("project/b.py", b"abc")])
    with pytest.raises(LimitExceeded, match="file count"):
        index_archive(path, "project", ArchiveLimits(max_files=1))
    nodes, warnings = index_archive(path, "project", ArchiveLimits(max_source_file_bytes=5))
    assert next(node for node in nodes if node.path == "a.py").parse_status == "skipped"
    assert warnings == ["File exceeds analysis size limit: a.py"]


def test_rejects_archive_with_multiple_roots(tmp_path):
    path = archive(tmp_path, [("first/a.py", b"a"), ("second/b.py", b"b")])
    with pytest.raises(AnalysisError, match="common root"):
        index_archive(path, "project", ArchiveLimits())
