"""Normalization rule tables (the "plausible replacements")."""

from __future__ import annotations

# Exact, word-boundary-aware string replacements. ``find`` is looked for as a
# whole word (so ``node_memory_MemTotal`` does not match
# ``node_memory_MemTotal_bytes``) and replaced with ``replace`` everywhere in
# the dashboard JSON (expressions, legend formats, ...). Add new tuples as you
# find more "odd things".
REPLACEMENTS: list[tuple[str, str]] = [
    ("node_memory_MemTotal", "node_memory_MemTotal_bytes"),
    ("node_memory_MemFree", "node_memory_MemFree_bytes"),
    ("node_memory_MemAvailable", "node_memory_MemAvailable_bytes"),
    ("node_memory_Active", "node_memory_Active_bytes"),
    ("node_memory_Buffers", "node_memory_Buffers_bytes"),
    ("node_memory_Inactive", "node_memory_Inactive_bytes"),
    ("node_memory_KernelStack", "node_memory_KernelStack_bytes"),
    ("node_disk_bytes_read", "node_disk_read_bytes_total"),
    ("node_disk_bytes_written", "node_disk_written_bytes_total"),
]

# Datasource reference aliases: ``(find, type)``. Any datasource reference
# (``name`` in v2 format, ``uid`` in classic format, or a bare string) equal to
# ``find`` is rewritten to the real UID of the datasource of ``type`` on the
# instance (resolved at runtime from ``data/state/datasources.json``).
DATASOURCE_ALIASES: list[tuple[str, str]] = [
    ("${DS_PROMETHEUS}", "prometheus"),
    ("$DS_PROMETHEUS", "prometheus"),
    ("${ds_prometheus}", "prometheus"),
    ("$ds_prometheus", "prometheus"),
    ("$DataSource", "prometheus"),
    ("$datasource", "prometheus"),
    ("PBFA97CFB590B2093", "prometheus"),
    ("P8E80F9AEF21F6940", "loki"),
    ("${DS_LOKI}", "loki"),
]
