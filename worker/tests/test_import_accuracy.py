"""A fixed set of distinct static-import resolution cases."""

import pytest

from worker.parsers.javascript_ts import parse_javascript
from worker.parsers.python_ast import parse_python
from worker.resolvers.imports import resolve_references


# language, source path, import statement, additional files, expected target, expected status
CASES = [
    ("py", "main.py", "import util", {"util.py"}, "util.py", "resolved"),
    ("py", "src/main.py", "import util", {"src/util.py"}, "src/util.py", "resolved"),
    ("py", "main.py", "import pkg.util", {"pkg/util.py"}, "pkg/util.py", "resolved"),
    ("py", "src/main.py", "import pkg.util", {"src/pkg/util.py"}, "src/pkg/util.py", "resolved"),
    ("py", "main.py", "import pkg", {"pkg/__init__.py"}, "pkg/__init__.py", "resolved"),
    ("py", "main.py", "from pkg.util import run", {"pkg/util.py"}, "pkg/util.py", "resolved"),
    ("py", "main.py", "from pkg import util", {"pkg/util.py"}, "pkg/util.py", "resolved"),
    ("py", "pkg/main.py", "from . import util", {"pkg/util.py"}, "pkg/util.py", "resolved"),
    ("py", "pkg/main.py", "from .util import run", {"pkg/util.py"}, "pkg/util.py", "resolved"),
    ("py", "pkg/sub/main.py", "from .. import util", {"pkg/util.py"}, "pkg/util.py", "resolved"),
    ("py", "pkg/sub/main.py", "from ..util import run", {"pkg/util.py"}, "pkg/util.py", "resolved"),
    ("py", "pkg/main.py", "from .util import *", {"pkg/util.py"}, "pkg/util.py", "resolved"),
    ("py", "main.py", "import util as alias", {"util.py"}, "util.py", "resolved"),
    ("py", "main.py", "from pkg import nested", {"pkg/nested/__init__.py"}, "pkg/nested/__init__.py", "resolved"),
    ("py", "main.py", "import os", set(), None, "external"),
    ("py", "main.py", "import missing", set(), None, "unresolved"),
    ("py", "main.py", "import util", {"util.py", "src/util.py"}, None, "unresolved"),
    ("py", "main.py", "import util", {"util.py", "util/__init__.py"}, None, "unresolved"),
    ("py", "main.py", "from .. import util", {"util.py"}, None, "unresolved"),
    ("py", "main.py", "from pkg import util", {"pkg.py", "pkg/util.py"}, "pkg.py", "resolved"),
    ("py", "main.py", "from pkg import util", {"pkg/__init__.py", "pkg/util.py"}, None, "unresolved"),
    ("py", "src/main.py", "from pkg import util", {"pkg/util.py", "src/pkg/util.py"}, None, "unresolved"),
    ("py", "main.py", "import pkg.util", {"pkg.py", "pkg/util.py"}, None, "unresolved"),
    ("py", "src/main.py", "import pkg.util", {"src/pkg.py", "src/pkg/util.py"}, None, "unresolved"),
    ("py", "main.py", "from pkg.util import run", {"pkg.py", "pkg/util.py"}, None, "unresolved"),
    ("py", "main.py", "import pkg.util", {"pkg.py", "pkg/__init__.py", "pkg/util.py"}, "pkg/util.py", "resolved"),
    ("js", "src/app.js", "import x from './util'", {"src/util.js"}, "src/util.js", "resolved"),
    ("js", "src/app.ts", "import x from './util'", {"src/util.ts"}, "src/util.ts", "resolved"),
    ("js", "src/app.tsx", "import x from './util'", {"src/util.tsx"}, "src/util.tsx", "resolved"),
    ("js", "src/app.jsx", "import x from './util'", {"src/util.jsx"}, "src/util.jsx", "resolved"),
    ("js", "src/app.js", "import './util.js'", {"src/util.js"}, "src/util.js", "resolved"),
    ("js", "src/app.js", "import './dir'", {"src/dir/index.js"}, "src/dir/index.js", "resolved"),
    ("js", "src/app.ts", "import './dir'", {"src/dir/index.ts"}, "src/dir/index.ts", "resolved"),
    ("js", "src/sub/app.ts", "import '../util'", {"src/util.ts"}, "src/util.ts", "resolved"),
    ("js", "app.js", "export {x} from './util'", {"util.js"}, "util.js", "resolved"),
    ("js", "app.js", "const x = require('./util')", {"util.js"}, "util.js", "resolved"),
    ("js", "app.js", "import 'react'", set(), None, "external"),
    ("js", "app.js", "import '@scope/package'", set(), None, "external"),
    ("js", "app.js", "import '@/util'", {"src/util.js"}, None, "unresolved"),
    ("js", "app.js", "import './missing'", set(), None, "unresolved"),
    ("js", "app.js", "import '../outside'", {"outside.js"}, None, "unresolved"),
    ("js", "app.js", "const x = import('./util')", {"util.js"}, None, "unresolved"),
    ("js", "app.js", "const x = require(name)", {"name.js"}, None, "unresolved"),
    ("js", "app.js", "import './util'", {"util.ts", "util.js"}, "util.ts", "resolved"),
    ("js", "app.js", "import './settings.json'", {"settings.json"}, "settings.json", "resolved"),
]


@pytest.mark.parametrize("language,source,statement,files,target,status", CASES)
def test_resolved_imports_match_fixture(language, source, statement, files, target, status):
    parser = parse_python if language == "py" else parse_javascript
    _, refs, warnings = parser(source, statement.encode())
    assert not warnings and len(refs) == 1
    resolve_references(refs, files | {source})
    assert (refs[0].target_path, refs[0].resolution_status) == (target, status)


def test_static_import_precision_and_recall():
    true_positive = false_positive = false_negative = 0
    static_cases = 0
    for language, source, statement, files, target, status in CASES:
        parser = parse_python if language == "py" else parse_javascript
        _, refs, warnings = parser(source, statement.encode())
        assert not warnings and len(refs) == 1
        ref = refs[0]
        if ref.mode == "dynamic":
            continue
        static_cases += 1
        resolve_references(refs, files | {source})
        expected = target if status == "resolved" else None
        actual = ref.target_path if ref.resolution_status == "resolved" else None
        if actual is not None:
            if actual == expected:
                true_positive += 1
            else:
                false_positive += 1
        if expected is not None and actual != expected:
            false_negative += 1

    assert static_cases >= 30
    precision = true_positive / (true_positive + false_positive)
    recall = true_positive / (true_positive + false_negative)
    print(f"\n정적 import: {static_cases}건, TP={true_positive}, FP={false_positive}, FN={false_negative}, "
          f"precision={precision:.2%}, recall={recall:.2%}")
    assert precision >= 0.95
