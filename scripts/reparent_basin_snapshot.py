"""Reuse a validated, whole snapshot after an unrelated main advancement.

No checkout, real-index update, merge, rebase, reset or push is performed here.
Only a new Git object is created with the fetched target as its single parent.
The caller can adopt that object on its disposable runner and use normal push.
Exit 2 means recollect/rebuild is required; stdout contains only a commit SHA.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile

if __package__:
    from .test_rain_workflow_publication import (
        ARCHIVE, CSV, FEED, META, ROOT, STATUS, git_bytes, validate_publication,
    )
else:
    from test_rain_workflow_publication import (
        ARCHIVE, CSV, FEED, META, ROOT, STATUS, git_bytes, validate_publication,
    )


OUTPUTS = (CSV, META, FEED, STATUS)
# The snapshot can only move intact when its inputs are unchanged. A newer
# river-level/RNA input requires reconstruction, not publishing a dated copy
# as if it incorporated that reading. This guard favors integrity over uptime.
PROTECTED = OUTPUTS + (
    ".gitattributes", ".github/workflows/basin-station-forecast.yml",
    ".github/workflows/chuvas-horarias.yml",
    "scripts",
    "codigo_python/10_chuvas", "previne",
    "previsao_ao_vivo.json", "previsao_ao_vivo_mucum.json",
    "assets/data/estudo_bacia_taquari_antas/postos_g040.geojson",
    "assets/data/estudo_bacia_taquari_antas/pluviometria_g040.geojson",
    "assets/data/estudo_bacia_taquari_antas/ugs_g040.geojson",
)
ARCHIVE_NAME = re.compile(re.escape(ARCHIVE) + r"/\d{8}T\d{4}Z-([a-f0-9]{64})\.json\Z")


class RebuildRequired(ValueError):
    """The fast path cannot safely reuse this snapshot."""


def git(root: Path, *args: str, env=None, data: bytes | None = None,
        check: bool = True) -> subprocess.CompletedProcess:
    result = subprocess.run(
        ["git", "--no-optional-locks", *args], cwd=root, env=env,
        input=data, capture_output=True, timeout=60,
    )
    if check and result.returncode:
        raise RebuildRequired("Git recusou a preparação do snapshot: " +
                              result.stderr.decode(errors="replace").strip())
    return result


def commit_sha(root: Path, ref: str) -> str:
    return git(root, "rev-parse", "--verify", "--end-of-options", ref + "^{commit}").stdout.decode().strip()


def changed_paths(root: Path, before: str, after: str) -> list[str]:
    raw = git(root, "diff", "--name-only", "--no-renames", "-z", before, after, "--").stdout
    return [path.decode("utf-8") for path in raw.split(b"\0") if path]


def entry(root: Path, ref: str, path: str) -> tuple[str, str] | None:
    raw = git(root, "ls-tree", "-z", ref, "--", path).stdout.rstrip(b"\0")
    if not raw:
        return None
    header, actual_path = raw.split(b"\t", 1)
    mode, kind, digest = header.decode().split()
    if actual_path.decode() != path or mode != "100644" or kind != "blob":
        raise RebuildRequired("Artefato não regular: " + path)
    return mode, digest


def validate_snapshot(root: Path, ref: str, paths: list[str]) -> None:
    validate_publication(root, git_ref=ref, allow_legacy_unchanged=True)
    feed_bytes = git_bytes(root, ref, FEED)
    feed = json.loads(feed_bytes)
    status = json.loads(git_bytes(root, ref, STATUS))
    if (not isinstance(feed, dict) or not isinstance(status, dict)
            or not feed.get("generated_at_utc")
            or feed.get("generated_at_utc") != status.get("generated_at_utc")):
        raise RebuildRequired("Feed/status não identificam a mesma rodada.")
    archives = [path for path in paths if path.startswith(ARCHIVE + "/")]
    if FEED in paths and not archives:
        raise RebuildRequired("Feed alterado sem arquivo histórico da rodada.")
    for path in archives:
        match = ARCHIVE_NAME.fullmatch(path)
        body = git_bytes(root, ref, path)
        if not match or hashlib.sha256(body).hexdigest() != match[1]:
            raise RebuildRequired("Nome/hash histórico inválido: " + path)
        snapshot = json.loads(body)
        if (not isinstance(snapshot, dict)
                or snapshot.get("source_feed_sha256") != hashlib.sha256(feed_bytes).hexdigest()
                or snapshot.get("feed_generated_at_utc") != feed["generated_at_utc"]
                or snapshot.get("research_only") is not True
                or snapshot.get("official_alert") is not False):
            raise RebuildRequired("Histórico não corresponde ao feed: " + path)


def prepare_snapshot(root: Path, *, candidate: str = "HEAD",
                     target: str = "origin/main") -> str:
    candidate = commit_sha(root, candidate)
    target = commit_sha(root, target)
    parents = git(root, "show", "-s", "--format=%P", candidate).stdout.decode().split()
    if len(parents) != 1:
        raise RebuildRequired("O candidato deve ser um único commit de publicação.")
    base = parents[0]
    paths = changed_paths(root, base, candidate)
    if not paths or any(path not in OUTPUTS and not ARCHIVE_NAME.fullmatch(path) for path in paths):
        raise RebuildRequired("O commit contém alterações fora do snapshot permitido.")
    for path in paths:
        if entry(root, candidate, path) is None:
            raise RebuildRequired("Exclusão de artefato não permitida: " + path)
        if path.startswith(ARCHIVE + "/") and entry(root, base, path) is not None:
            raise RebuildRequired("Não substituir arquivo histórico existente: " + path)
    validate_snapshot(root, candidate, paths)
    if git(root, "merge-base", "--is-ancestor", candidate, target, check=False).returncode == 0:
        return target  # Already accepted; never republish an older snapshot.
    if target == base:
        raise RebuildRequired("A base remota não avançou; não repetir o mesmo push.")
    comparison = git(root, "diff", "--quiet", base, target, "--", *PROTECTED, check=False)
    if comparison.returncode != 0:
        raise RebuildRequired("Upstream alterou dados, produtor ou catálogo; reconstrução obrigatória.")
    # A shallow runner may not have ancestry past base. Equality of protected
    # blobs is not enough to establish an authorized forward publication.
    if git(root, "merge-base", "--is-ancestor", base, target, check=False).returncode != 0:
        raise RebuildRequired("A main recebida não descende da base da coleta.")
    for path in paths:
        if path.startswith(ARCHIVE + "/"):
            remote_entry = entry(root, target, path)
            if remote_entry is not None and remote_entry != entry(root, candidate, path):
                raise RebuildRequired("Colisão com histórico upstream: " + path)
    # GIT_INDEX_FILE isolates every tree operation from the user's real index.
    with tempfile.TemporaryDirectory(prefix="previne-snapshot-index-") as folder:
        env = {**os.environ, "GIT_INDEX_FILE": str(Path(folder) / "index")}
        git(root, "read-tree", target, env=env)
        for path in paths:
            mode, digest = entry(root, candidate, path)
            git(root, "update-index", "--add", "--cacheinfo", mode, digest, path, env=env)
        tree = git(root, "write-tree", env=env).stdout.decode().strip()
        message = git(root, "show", "-s", "--format=%B", candidate).stdout
        prepared = git(root, "-c", "commit.gpgsign=false", "commit-tree", tree, "-p", target,
                       env=env, data=message).stdout.decode().strip()
    # Audit exact blob identity, not a textual merge or a successful Git exit.
    if set(changed_paths(root, target, prepared)) - set(paths):
        raise RebuildRequired("O commit preparado alterou arquivos alheios.")
    for path in paths:
        if entry(root, prepared, path) != entry(root, candidate, path):
            raise RebuildRequired("Bytes do snapshot divergiram: " + path)
    validate_snapshot(root, prepared, paths)
    return prepared


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--candidate", default="HEAD")
    parser.add_argument("--target", default="origin/main")
    args = parser.parse_args()
    try:
        prepared = prepare_snapshot(ROOT, candidate=args.candidate, target=args.target)
    except (OSError, ValueError, UnicodeError, subprocess.SubprocessError) as exc:
        print("SNAPSHOT_REBUILD_REQUIRED:", exc, file=sys.stderr)
        return 2
    print(prepared)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
