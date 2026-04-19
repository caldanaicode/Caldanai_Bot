"""Operator tooling — see ``README.md`` for usage.

These are standalone scripts, but making ``tools/`` a package
lets them import ``tools._common`` when invoked via
``python -m tools.<name>`` from the repo root — which is the
supported invocation style (it puts the repo root on
``sys.path`` so ``caldanai.environment`` also resolves).
"""
