"""Databricks Metric View conversion substrate (BL-063 Phase 2).

Pure-function modules — stdlib + PyYAML ONLY (no requests/typer/keyring).
This constraint is load-bearing: PR 5 vendors these modules into Databricks
Genie notebooks via ``%run``, where the CLI's HTTP/auth deps don't exist.
"""
