# Development and release gates

Local core gates:

```bash
python -m compileall -q ast2python tests
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest -q
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest -q -p pytest_cov \
  --cov=ast2python --cov-branch
python -m ast2python.distribution manifest --root .
python -m ast2python.release --root .
```

Release infrastructure must additionally run Ruff, Black, MyPy and Python 3.11–3.13,
build clean wheel/sdist artifacts twice, verify RECORD/safe paths, install only exact
wheels, run exact Pine2AST and PineLib acceptance and generate SBOM/provenance evidence.
