# MiniCode Smoke Eval Cases

`benchmarks/smoke_eval.py` generates temporary workspaces for each run instead
of storing mutable case fixtures in the repository.

The five task classes are:

- `code_understanding`: read and explain one function without file changes.
- `code_location`: find the file that defines a function without edits.
- `single_file_edit`: make a focused edit to one Python file and pass checks.
- `bug_fix`: fix business code while preserving tests.
- `intent_constraint`: respect read-only and no-shell constraints.
