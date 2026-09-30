import importlib.util
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "scripts/check_engineering.py"
SPEC = importlib.util.spec_from_file_location("check_engineering", SCRIPT)
check = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(check)


def seed(root: Path, files: dict[str, str]) -> Path:
    for relative, text in files.items():
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
    return root


def no_pending(monkeypatch) -> None:
    monkeypatch.setattr(check, "PENDING", {name: frozenset() for name in check.PENDING})


def test_framework_imports_cover_every_import_form():
    source = "import fastapi\nfrom starlette.responses import Response\nimport fastapiish\nfrom .fastapi import x\n"
    assert check.framework_imports(source) == [1, 2]


def test_environment_reads_cover_attribute_call_and_import_forms():
    source = "import os\nos.environ['A']\nos.getenv('B')\nfrom os import environ\nos.path.join('a')\n"
    assert check.environment_reads(source) == [2, 3, 4]


def test_silent_catches_require_an_opening_comment():
    source = "try {} catch {\n  return 1;\n}\ntry {} catch {}\ntry {} catch {\n  // corrupt cache\n}\n"
    source += "try {} catch { /* keep status */ }\ntry {} catch (e) { throw e; }\np.catch(() => {});\n"
    assert check.silent_catches(source) == [1, 4]


def test_framework_import_outside_http_layer_fails(monkeypatch, tmp_path):
    no_pending(monkeypatch)
    root = seed(
        tmp_path,
        {
            f"{check.LAB}/main.py": "from fastapi import FastAPI\n",
            f"{check.LAB}/http/topics.py": "from fastapi import APIRouter\n",
            f"{check.LAB}/parsers.py": "import os\n\nfrom fastapi import HTTPException\n",
        },
    )
    assert check.structure_errors(root) == [f"{check.LAB}/parsers.py:3: framework-import is not allowed here"]


def test_environment_read_outside_config_module_fails(monkeypatch, tmp_path):
    no_pending(monkeypatch)
    root = seed(
        tmp_path,
        {
            check.CONFIG_MODULE: "import os\nROOT = os.environ.get('LEARNING_LAB_ROOT')\n",
            f"{check.LAB}/parsers.py": "import os\nROOT = os.environ.get('LEARNING_LAB_ROOT')\n",
        },
    )
    assert check.structure_errors(root) == [f"{check.LAB}/parsers.py:2: environment-read is not allowed here"]


def test_silent_catch_in_web_source_fails(monkeypatch, tmp_path):
    no_pending(monkeypatch)
    root = seed(tmp_path, {f"{check.WEB}/state/prefs.ts": "try {\n  load();\n} catch {\n  return {};\n}\n"})
    assert check.structure_errors(root) == [f"{check.WEB}/state/prefs.ts:3: silent-catch is not allowed here"]


def test_pending_exemption_allows_offender_and_fails_once_stale(monkeypatch, tmp_path):
    monkeypatch.setattr(
        check,
        "PENDING",
        {
            "framework-import": frozenset({f"{check.LAB}/parsers.py"}),
            "environment-read": frozenset({f"{check.LAB}/parsers.py"}),
            "silent-catch": frozenset(),
        },
    )
    root = seed(tmp_path, {f"{check.LAB}/parsers.py": "from fastapi import HTTPException\n"})
    assert check.structure_errors(root) == [
        f"{check.LAB}/parsers.py: stale environment-read exemption; remove it from PENDING"
    ]


def test_repository_structure_matches_pending_exemptions():
    assert check.structure_errors(SCRIPT.parents[1]) == []
