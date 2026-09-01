import subprocess
import sys
from pathlib import Path

from ast2python.hardening.corpus import verify_normative_corpus
from ast2python.hardening.properties import run_property_gate

ROOT = Path(__file__).parents[2]
MANIFEST = ROOT / "tests" / "corpus" / "manifest.json"


def test_normative_corpus() -> None:
    report = verify_normative_corpus(MANIFEST)
    assert report["ok"], report
    assert report["case_count"] >= 20
    assert report["versions"] == [1, 2, 3, 4, 5, 6]


def test_property_gate() -> None:
    paths = [
        ROOT / row["consumer_bundle"]
        for row in __import__("json").loads(MANIFEST.read_text())["cases"]
    ]
    report = run_property_gate(paths)
    assert report["ok"], report


def test_normative_corpus_hashes_are_regenerated_by_deterministic_tool() -> None:
    completed = subprocess.run(
        [
            sys.executable,
            str(ROOT / "tools" / "regenerate_normative_corpus_hashes.py"),
            "--manifest",
            str(MANIFEST),
            "--check",
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr or completed.stdout
    assert "22 cases verified" in completed.stdout
