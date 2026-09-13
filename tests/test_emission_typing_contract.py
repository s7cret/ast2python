"""The static host contract must accept the emitter, not arbitrary objects."""

import subprocess
import sys


def test_emission_context_checks_real_host_and_rejects_wrong_host(tmp_path):
    contract = tmp_path / "emitter_contract.py"
    contract.write_text(
        "from ast2python.emission.context import EmissionContext\n"
        "from ast2python.emission.python import _DirectEmitter\n"
        "def accept(emitter: _DirectEmitter) -> EmissionContext:\n"
        "    return emitter\n",
        encoding="utf-8",
    )
    command = [sys.executable, "-m", "mypy", "--strict", "--no-incremental", str(contract)]
    accepted = subprocess.run(command, capture_output=True, text=True, timeout=60)
    assert accepted.returncode == 0, accepted.stdout + accepted.stderr
    contract.write_text(
        "from ast2python.emission.context import EmissionContext\n"
        "def reject(emitter: object) -> EmissionContext:\n"
        "    return emitter\n",
        encoding="utf-8",
    )
    rejected = subprocess.run(command, capture_output=True, text=True, timeout=60)
    assert rejected.returncode == 1, rejected.stdout + rejected.stderr
    assert "Incompatible return value type" in rejected.stdout
    assert "EmissionContext" in rejected.stdout
