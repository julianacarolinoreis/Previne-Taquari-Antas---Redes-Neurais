"""Publication gate and offline regressions for the two observed-rain writers.

Runtime (stdlib only): python -B scripts/test_rain_workflow_publication.py
    --validate-pair [--git-ref HEAD] [--allow-legacy-unchanged]
Tests: python -B -m unittest scripts.test_rain_workflow_publication -v
All mutable Git fixtures use temporary file:// remotes; no HTTP or credentials.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
CSV = "assets/data/chuvas_horarias.csv"
META = CSV + ".provenance.json"
FEED = "assets/data/basin_station_forecast_latest.json"
STATUS = "assets/data/basin_station_status_latest.json"
ARCHIVE = "assets/data/basin_station_forecast_archive"
GATE = "scripts/test_rain_workflow_publication.py"


def git_bytes(root: Path, ref: str, path: str, *, optional: bool = False) -> bytes | None:
    result = subprocess.run(
        ["git", "--no-optional-locks", "show", f"{ref}:{path}"],
        cwd=root, capture_output=True, timeout=30,
    )
    if result.returncode:
        if optional:
            return None
        raise ValueError(f"Arquivo ausente em {ref}: {path}")
    return result.stdout


def validate_pair_bytes(csv_bytes: bytes, metadata_bytes: bytes) -> str:
    try:
        metadata = json.loads(metadata_bytes)
    except (ValueError, UnicodeError) as exc:
        raise ValueError("Proveniencia JSON invalida") from exc
    if (
        not isinstance(metadata, dict)
        or type(metadata.get("schema_version")) is not int
        or metadata.get("schema_version") != 1
        or not isinstance(metadata.get("cells"), dict)
        or any(not isinstance(cells, dict) for cells in metadata["cells"].values())
    ):
        raise ValueError("Schema de proveniencia invalido")
    digest = hashlib.sha256(csv_bytes).hexdigest()
    if metadata.get("csv_sha256") != digest:
        raise ValueError("SHA CSV/proveniencia incompatível; publicacao bloqueada")
    return digest


def validate_publication(root: Path, *, git_ref: str | None = None,
                         allow_legacy_unchanged: bool = False) -> str:
    if git_ref:
        csv_bytes = git_bytes(root, git_ref, CSV)
        metadata_bytes = git_bytes(root, git_ref, META, optional=True)
        previous = git_ref + "^"
    else:
        csv_bytes = (root / CSV).read_bytes()
        metadata_path = root / META
        metadata_bytes = metadata_path.read_bytes() if metadata_path.exists() else None
        previous = "HEAD"
    if metadata_bytes is not None:
        return validate_pair_bytes(csv_bytes, metadata_bytes)
    # Legacy may accompany a feed-only commit, but cannot introduce or change
    # CSV bytes, remove existing metadata, or acquire a confirmation by default.
    if (
        allow_legacy_unchanged
        and git_bytes(root, previous, CSV, optional=True) == csv_bytes
        and git_bytes(root, previous, META, optional=True) is None
    ):
        return "LEGACY_UNCONFIRMED_UNCHANGED"
    raise ValueError("Sidecar ausente para CSV novo/alterado; publicacao bloqueada")


def publication_shell(writer: str) -> str:
    path = ROOT / ".github/workflows" / (writer + ".yml")
    name = "Publica chuva observada e o feed da bacia" if writer == "basin-station-forecast" else "Baixar chuvas horarias e publicar"
    text = path.read_text(encoding="utf-8")
    step = text.split("      - name: " + name + "\n", 1)[1].split("\n      - name:", 1)[0]
    body = step.split("        run: |\n", 1)[1]
    return "\n".join(line[10:] if line.startswith("          ") else line for line in body.splitlines()) + "\n"


def validate_rain_git_attributes(root: Path, *, cached: bool = False,
                                 env: dict[str, str] | None = None) -> None:
    """Require effective byte-preserving attributes, not a one-line file.

    Git resolves precedence, patterns, nested rules and info/attributes. Check
    both worktree and index at the workflow gate so unrelated model rules are
    allowed but an override/clean filter/encoding cannot silently change CSV.
    """
    command = ["git", "--no-optional-locks", "check-attr", "-z"]
    if cached:
        command.append("--cached")
    command.extend(["text", "filter", "working-tree-encoding", "--", CSV])
    result = subprocess.run(command, cwd=root, env=env, capture_output=True, timeout=30)
    if result.returncode:
        raise ValueError("Não foi possível verificar atributos Git da chuva")
    fields = result.stdout.split(b"\0")
    if len(fields) != 10 or fields[-1] != b"":
        raise ValueError("Resposta inválida ao verificar atributos Git da chuva")
    resolved = {}
    for offset in range(0, 9, 3):
        path, attribute, value = fields[offset:offset + 3]
        if path != CSV.encode() or attribute in resolved:
            raise ValueError("Resposta incompatível de atributos Git da chuva")
        resolved[attribute] = value
    if (resolved.get(b"text") != b"unset"
            or any(resolved.get(attribute) not in (b"unspecified", b"unset")
                   for attribute in (b"filter", b"working-tree-encoding"))):
        raise ValueError("Atributos Git podem alterar os bytes da chuva; publicação bloqueada")


class PairValidationTests(unittest.TestCase):
    def test_valid_exact_bytes(self):
        payload = b"a,b\r\n1,0\r\n"
        metadata = json.dumps({"schema_version": 1, "csv_sha256": hashlib.sha256(payload).hexdigest(), "cells": {}}).encode()
        self.assertEqual(validate_pair_bytes(payload, metadata), hashlib.sha256(payload).hexdigest())
        with self.assertRaises(ValueError):
            validate_pair_bytes(payload.replace(b"\r\n", b"\n"), metadata)

    def test_invalid_schema_and_hash_fail_closed(self):
        for metadata in (None, [], {"schema_version": True}, {"schema_version": 2},
                         {"schema_version": 1, "cells": [], "csv_sha256": "x"},
                         {"schema_version": 1, "cells": {"a": []}, "csv_sha256": "x"},
                         {"schema_version": 1, "cells": {}, "csv_sha256": "0" * 64}):
            with self.subTest(metadata=metadata), self.assertRaises(ValueError):
                validate_pair_bytes(b"CSV", json.dumps(metadata).encode())
        with self.assertRaises(ValueError):
            validate_pair_bytes(b"CSV", b"{broken")


class WorkflowContractTests(unittest.TestCase):
    def test_runtime_and_workflow_tests_are_in_trigger_and_sparse_contracts(self):
        for writer in ("chuvas-horarias", "basin-station-forecast"):
            text = (ROOT / ".github/workflows" / (writer + ".yml")).read_text(encoding="utf-8")
            self.assertIn("      - '" + GATE + "'", text)
            self.assertIn("      - '.gitattributes'", text)
            self.assertIn("scripts.test_rain_workflow_publication", text)
        text = (ROOT / ".github/workflows/basin-station-forecast.yml").read_text(encoding="utf-8")
        sparse = text.split("          sparse-checkout: |\n", 1)[1].split("\n      - name:", 1)[0]
        self.assertIn("/.gitattributes", sparse)
        self.assertIn("/.github/workflows/basin-station-forecast.yml", sparse)
        self.assertIn("/.github/workflows/chuvas-horarias.yml", sparse)
        self.assertNotIn("/index.html", sparse)
        for cached in (False, True):
            validate_rain_git_attributes(ROOT, cached=cached)

    def test_both_writers_gate_worktree_and_commit_and_never_rebase(self):
        for writer in ("chuvas-horarias", "basin-station-forecast"):
            with self.subTest(writer=writer):
                shell = publication_shell(writer)
                self.assertNotRegex(shell, r"git (?:pull|rebase)|--autostash|--force")
                self.assertIn("git reset --keep origin/main", shell)
                self.assertIn("timeout 120s python -B codigo_python/10_chuvas/baixar_chuvas_horarias.py", shell)
                self.assertIn("git add --sparse " + META, shell)
                gate = "python -B " + GATE + " --validate-pair"
                self.assertLess(shell.index(gate), shell.index("git add --sparse"))
                self.assertLess(shell.index(gate + " --git-ref HEAD"), shell.index("git push origin HEAD:main"))
                self.assertIn("1 2 3 4 5", shell)

    def test_basin_rebuilds_feed_archive_and_tests_before_restaging(self):
        shell = publication_shell("basin-station-forecast")
        reset = shell.index("git reset --keep origin/main")
        build = shell.index("python -B scripts/build_basin_station_forecast.py", reset)
        archive = shell.index("python -B scripts/archive_basin_station_forecast.py", build)
        tests = shell.index("scripts.test_basin_station_forecast_archive", archive)
        gate = shell.index(" --validate-pair --allow-legacy-unchanged", tests)
        stage = shell.index("git add --sparse", gate)
        self.assertLess(reset, build)
        self.assertLess(build, archive)
        self.assertLess(archive, tests)
        self.assertLess(tests, gate)
        self.assertLess(gate, stage)
        self.assertIn("scripts.test_rain_workflow_publication", shell[tests:gate])
        self.assertEqual(shell.count(STATUS), 2)


def bash_path() -> str | None:
    windows = Path(r"C:\Program Files (x86)\Git\bin\bash.exe")
    return str(windows) if windows.exists() else shutil.which("bash")


@unittest.skipUnless(shutil.which("git") and bash_path(), "Git and Bash required for offline integration")
class PublicationGitTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="previne-publication-")
        self.addCleanup(self.temporary.cleanup)
        self.folder = Path(self.temporary.name)
        self.remote = self.folder / "remote.git"
        self.seed = self.folder / "seed"
        self.worker = self.folder / "worker"
        self.seed.mkdir()
        # No credential helpers, prompts, system hooks, signing, or global
        # config in the lab. All origin URLs are checked to be local file://.
        self.env = {**os.environ, "GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_GLOBAL": os.devnull,
                    "GIT_TERMINAL_PROMPT": "0", "GIT_EDITOR": "true", "GIT_SEQUENCE_EDITOR": "true"}
        self.git(self.folder, "init", "--bare", "--initial-branch=main", self.remote)
        self.git(self.seed, "init", "--initial-branch=main")
        self.configure(self.seed)
        self.write_pair(self.seed, 0, 0)
        self.write_feed(self.seed, "00")
        self.write(self.seed, "app.txt", "base\n")
        self.write(self.seed, ".gitattributes", (ROOT / ".gitattributes").read_bytes())
        for relative in (GATE, "scripts/archive_basin_station_forecast.py", "scripts/reparent_basin_snapshot.py"):
            self.write(self.seed, relative, (ROOT / relative).read_bytes())
        self.commit(self.seed, "base")
        self.git(self.seed, "remote", "add", "origin", self.remote.as_uri())
        self.git(self.seed, "push", "origin", "main")
        self.git(self.remote, "config", "uploadpack.allowFilter", "true")
        self.git(self.folder, "clone", "--depth=1", "--filter=blob:none", "--no-checkout", "--branch=main", self.remote.as_uri(), self.worker)
        self.git(self.worker, "sparse-checkout", "init", "--no-cone")
        self.git(self.worker, "sparse-checkout", "set", "--no-cone", "/.gitattributes", "/scripts/", "/" + CSV, "/" + META, "/" + FEED, "/" + STATUS)
        self.git(self.worker, "checkout", "main")
        self.configure(self.worker)
        self.assertEqual(self.git(self.worker, "rev-parse", "--is-shallow-repository").stdout.strip(), b"true")
        self.assertFalse((self.worker / ARCHIVE).exists())
        self.assertTrue(self.git(self.worker, "remote", "get-url", "origin").stdout.decode().strip().startswith("file://"))
        self.assertEqual(self.git(self.worker, "config", "remote.origin.partialclonefilter").stdout.strip(), b"blob:none")

    def run_command(self, args, cwd, *, check=True, env=None):
        result = subprocess.run(list(map(str, args)), cwd=cwd, env=env or self.env,
                                capture_output=True, timeout=60)
        if check and result.returncode:
            self.fail(f"{args!r}: {result.returncode}\n{result.stdout.decode(errors='replace')}\n{result.stderr.decode(errors='replace')}")
        return result

    def git(self, cwd, *args, check=True):
        return self.run_command(["git", "--no-optional-locks", *args], cwd, check=check)

    def configure(self, root):
        for key, value in (("user.name", "fixture"), ("user.email", "fixture@example.invalid"), ("commit.gpgsign", "false"), ("core.autocrlf", "false")):
            self.git(root, "config", key, value)

    def write(self, root, path, body):
        target = root / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(body if isinstance(body, bytes) else body.encode())

    def write_pair(self, root, a, b):
        # Separate rows beyond Git's context window: changes in A and B must
        # automerge without textual conflict in the unsafe-path regressions.
        middle = "".join(f"unchanged-{index},0\n" for index in range(10))
        payload = f"station,rain\nA,{a}\n{middle}B,{b}\n".encode()
        self.write(root, CSV, payload)
        self.write(root, META, json.dumps({"schema_version": 1, "csv_sha256": hashlib.sha256(payload).hexdigest(), "cells": {}}, indent=2) + "\n")

    def write_feed(self, root, minute):
        feed = {"generated_at_utc": f"2026-10-02T10:{minute}:00Z", "stations": []}
        self.write(root, FEED, json.dumps(feed) + "\n")
        self.write(root, STATUS, json.dumps(feed) + "\n")
        self.write(root, ARCHIVE + f"/20261002T10{minute}Z.json", json.dumps({"feed_generated_at_utc": feed["generated_at_utc"]}) + "\n")

    def commit(self, root, message):
        self.git(root, "add", "--sparse", ".")
        self.git(root, "commit", "-m", message)

    def remote_update(self, *, pair=True):
        if pair:
            self.write_pair(self.seed, 2, 7)
        self.write_feed(self.seed, "06")
        self.write(self.seed, "app.txt", "remote\n")
        self.commit(self.seed, "other writer")
        self.git(self.seed, "push", "origin", "main")

    def execute_publisher(self, writer, *, scenario="normal"):
        self.write_pair(self.worker, 1, 0)
        if writer == "basin-station-forecast":
            self.write_feed(self.worker, "05")
        if scenario in ("unrelated_concurrent", "same_feed_concurrent", "collect_failure_conflict", "collect_timeout_conflict", "rebuild_failure", "fallback_test_failure"):
            self.remote_update(pair=scenario != "unrelated_concurrent")
        helper = self.folder / "fixture.py"
        helper.write_text('''import hashlib, json, os, pathlib, sys
p = pathlib.Path("assets/data/chuvas_horarias.csv")
if sys.argv[1] == "collect":
    lines = p.read_text().splitlines()
    lines[1] = "A," + str(int(lines[1].split(",")[1]) + 1)
    p.write_bytes(("\\n".join(lines) + "\\n").encode())
    pathlib.Path(str(p) + ".provenance.json").write_text(json.dumps({"schema_version": 1, "csv_sha256": hashlib.sha256(p.read_bytes()).hexdigest(), "cells": {}}))
else:
    feed = {"generated_at_utc": "2026-10-02T10:10:00Z", "stations": [], "csv_sha256": hashlib.sha256(p.read_bytes()).hexdigest()}
    for name in ("basin_station_forecast_latest.json", "basin_station_status_latest.json"):
        (p.parent / name).write_text(json.dumps(feed))
''', encoding="utf-8")
        shim = r'''
sleep() { printf 'LAB_SLEEP %s\n' "$1"; }
timeout() {
  shift
  if [[ "$LAB_SCENARIO" == "collect_timeout_conflict" ]]; then return 124; fi
  "$@"
}
python() {
  printf 'LAB_PYTHON %s\n' "$*"
  if [[ "$*" == *"baixar_chuvas_horarias.py"* ]]; then
    if [[ "$LAB_SCENARIO" == "collect_failure_conflict" ]]; then return 1; fi
    command "$LAB_PYTHON" -B "$LAB_FIXTURE" collect
  elif [[ "$*" == *"build_basin_station_forecast.py"* ]]; then
    if [[ "$LAB_SCENARIO" == "rebuild_failure" ]]; then return 1; fi
    command "$LAB_PYTHON" -B "$LAB_FIXTURE" build
  elif [[ "$*" == *"-m unittest"* ]]; then
    if [[ "$LAB_SCENARIO" == "fallback_test_failure" ]]; then return 1; fi
    return 0
  else
    command "$LAB_PYTHON" "$@"
  fi
}
git() {
  if [[ "$1" == "push" && ( "$LAB_SCENARIO" == "persistent_push_rejection" || "$LAB_SCENARIO" == "fetch_failure" ) ]]; then printf 'LAB_PUSH_REJECTED\n'; return 1; fi
  if [[ "$1" == "fetch" && "$LAB_SCENARIO" == "fetch_failure" ]]; then return 1; fi
  command git "$@"
}
'''
        env = {**self.env, "LAB_SCENARIO": scenario, "LAB_PYTHON": Path(sys.executable).as_posix(),
               "LAB_FIXTURE": helper.as_posix(), "INI": "", "FIM": ""}
        result = self.run_command([bash_path(), "--noprofile", "--norc", "-e", "-o", "pipefail", "-c", shim + publication_shell(writer)], self.worker, check=False, env=env)
        output = (result.stdout + result.stderr).decode(errors="replace")
        csv_bytes = git_bytes(self.remote, "main", CSV)
        meta_bytes = git_bytes(self.remote, "main", META)
        validate_pair_bytes(csv_bytes, meta_bytes)
        self.assertEqual(git_bytes(self.remote, "main", ARCHIVE + "/20261002T1000Z.json"), git_bytes(self.seed, "HEAD", ARCHIVE + "/20261002T1000Z.json"))
        return result, output, csv_bytes

    def test_nine_basin_scenarios(self):
        scenarios = ("normal", "unrelated_concurrent", "same_feed_concurrent", "collect_failure_conflict", "collect_timeout_conflict", "persistent_push_rejection", "fetch_failure", "rebuild_failure", "fallback_test_failure")
        # Each scenario gets a fresh depth-1 partial sparse clone and bare origin.
        for scenario in scenarios:
            with self.subTest(scenario=scenario):
                fixture = PublicationGitTests()
                fixture.setUp()
                try:
                    result, output, csv_bytes = fixture.execute_publisher("basin-station-forecast", scenario=scenario)
                    success = scenario in scenarios[:5]
                    self.assertEqual(result.returncode == 0, success, output)
                    if success and scenario != "normal":
                        self.assertEqual(git_bytes(fixture.remote, "main", "app.txt"), b"remote\n")
                        self.assertIsNotNone(git_bytes(fixture.remote, "main", ARCHIVE + "/20261002T1006Z.json"))
                        archived_paths = fixture.git(fixture.remote, "ls-tree", "-r", "--name-only", "main", ARCHIVE).stdout.decode().splitlines()
                        rebuilt_paths = [name for name in archived_paths if re.fullmatch(re.escape(ARCHIVE) + r"/20261002T1010Z-[a-f0-9]{64}\.json", name)]
                        self.assertEqual(len(rebuilt_paths), 1)
                        snapshot = json.loads(git_bytes(fixture.remote, "main", rebuilt_paths[0]))
                        self.assertEqual(snapshot["feed_generated_at_utc"], "2026-10-02T10:10:00Z")
                        feed = json.loads(git_bytes(fixture.remote, "main", FEED))
                        self.assertEqual(feed["csv_sha256"], hashlib.sha256(csv_bytes).hexdigest())
                        self.assertEqual(git_bytes(fixture.remote, "main", FEED), git_bytes(fixture.remote, "main", STATUS))
                        self.assertIn("scripts.test_basin_station_forecast_archive", output)
                        self.assertIn("scripts.test_rain_workflow_publication", output)
                    if scenario == "persistent_push_rejection":
                        self.assertEqual(output.count("LAB_PUSH_REJECTED"), 5)
                        self.assertEqual(re.findall(r"LAB_SLEEP (\d+)", output), ["2", "4", "6", "8"])
                    print("OFFLINE_SCENARIO", scenario, "PASS", flush=True)
                finally:
                    fixture.doCleanups()

    def test_chuvas_cross_writer_race_recollects_and_keeps_remote_observations(self):
        result, output, csv_bytes = self.execute_publisher("chuvas-horarias", scenario="same_feed_concurrent")
        self.assertEqual(result.returncode, 0, output)
        self.assertIn(b"B,7\n", csv_bytes)
        self.assertIn(b"A,3\n", csv_bytes)
        self.assertEqual(output.count("LAB_PYTHON -B codigo_python/10_chuvas/baixar_chuvas_horarias.py"), 2)
        self.assertEqual(git_bytes(self.remote, "main", "app.txt"), b"remote\n")

    def test_same_csv_metadata_only_reconfirmation_is_published(self):
        original = (self.worker / CSV).read_bytes()
        metadata = json.loads((self.worker / META).read_text())
        metadata["cells"] = {"rain": {"202610021000": "2026-10-02T14:00:00Z"}}
        self.write(self.worker, META, json.dumps(metadata))
        shell = publication_shell("chuvas-horarias")
        shim = 'timeout() { return 124; }; sleep() { :; };\n'
        result = self.run_command([bash_path(), "--noprofile", "--norc", "-e", "-o", "pipefail", "-c", shim + shell], self.worker, check=False, env={**self.env, "INI": "", "FIM": ""})
        self.assertEqual(result.returncode, 0, (result.stdout + result.stderr).decode(errors="replace"))
        self.assertEqual(git_bytes(self.remote, "main", CSV), original)
        self.assertEqual(json.loads(git_bytes(self.remote, "main", META))["cells"], metadata["cells"])

    def test_bad_pair_never_reaches_remote(self):
        self.write(self.worker, CSV, "corrupted\n")
        for writer in ("basin-station-forecast", "chuvas-horarias"):
            with self.subTest(writer=writer):
                before = self.git(self.remote, "rev-parse", "main").stdout
                shim = 'timeout() { return 124; }; sleep() { :; };\n'
                result = self.run_command([bash_path(), "--noprofile", "--norc", "-e", "-o", "pipefail", "-c", shim + publication_shell(writer)], self.worker, check=False, env={**self.env, "INI": "", "FIM": ""})
                self.assertNotEqual(result.returncode, 0)
                self.assertEqual(self.git(self.remote, "rev-parse", "main").stdout, before)

    def test_autocrlf_true_preserves_exact_collector_bytes_with_csv_minus_text(self):
        self.git(self.worker, "config", "core.autocrlf", "true")
        self.git(self.worker, "rm", ".gitattributes")
        csv_bytes = (self.worker / CSV).read_bytes().replace(b"\n", b"\r\n")
        metadata = {"schema_version": 1, "csv_sha256": hashlib.sha256(csv_bytes).hexdigest(), "cells": {}}
        self.write(self.worker, CSV, csv_bytes)
        self.write(self.worker, META, json.dumps(metadata))
        self.commit(self.worker, "negative control: autocrlf without attributes")
        self.assertNotEqual(git_bytes(self.worker, "HEAD", CSV), csv_bytes)
        with self.assertRaises(ValueError):
            validate_publication(self.worker, git_ref="HEAD")
        # Add the exact future rule; do not normalize the existing source CSV.
        self.write(self.worker, ".gitattributes", (ROOT / ".gitattributes").read_bytes())
        self.write(self.worker, CSV, csv_bytes)
        self.write(self.worker, META, json.dumps(metadata))
        self.commit(self.worker, "positive control: CSV -text")
        self.assertEqual(git_bytes(self.worker, "HEAD", CSV), csv_bytes)
        self.assertEqual(validate_publication(self.worker, git_ref="HEAD"), metadata["csv_sha256"])
        (self.worker / CSV).unlink()
        self.git(self.worker, "restore", "--worktree", "--", CSV)
        self.assertEqual((self.worker / CSV).read_bytes(), csv_bytes)
        self.assertEqual(validate_publication(self.worker), metadata["csv_sha256"])

    def test_effective_attributes_accept_unrelated_training_rules(self):
        self.write(self.worker, ".gitattributes", CSV + " -text\n"
                   "assets/data/stz_user_models/training_n5*.csv -text\n"
                   "assets/models/stz_user_shadow/** binary\n"
                   "assets/data/stz_shadow_archive/**/*.gz binary\n")
        self.git(self.worker, "add", ".gitattributes")
        for cached in (False, True):
            validate_rain_git_attributes(self.worker, cached=cached, env=self.env)

    def test_effective_attributes_reject_missing_and_later_overrides(self):
        for rules in ("other.csv -text\n", CSV + " -text\n*.csv text\n",
                      CSV + " -text\nassets/data/*.csv text=auto\n",
                      CSV + " -text\n" + CSV + " !text\n"):
            with self.subTest(rules=rules):
                self.write(self.worker, ".gitattributes", rules)
                self.git(self.worker, "add", ".gitattributes")
                for cached in (False, True):
                    with self.assertRaises(ValueError):
                        validate_rain_git_attributes(self.worker, cached=cached, env=self.env)

    def test_effective_attributes_reject_nested_and_info_overrides(self):
        for relative in ("assets/data/.gitattributes", ".git/info/attributes"):
            with self.subTest(relative=relative):
                self.write(self.worker, relative, "chuvas_horarias.csv text\n" if relative.startswith("assets/") else CSV + " text\n")
                if relative.startswith("assets/"):
                    self.git(self.worker, "add", "--sparse", relative)
                for cached in (False, True):
                    with self.assertRaises(ValueError):
                        validate_rain_git_attributes(self.worker, cached=cached, env=self.env)
                self.write(self.worker, relative, "# cleared fixture override\n")
                if relative.startswith("assets/"):
                    self.git(self.worker, "add", "--sparse", relative)

    def test_effective_attributes_reject_filters_encoding_and_staged_divergence(self):
        for transform in ("filter=example", "working-tree-encoding=UTF-16"):
            with self.subTest(transform=transform):
                self.write(self.worker, ".gitattributes", CSV + " -text " + transform + "\n")
                self.git(self.worker, "add", ".gitattributes")
                for cached in (False, True):
                    with self.assertRaises(ValueError):
                        validate_rain_git_attributes(self.worker, cached=cached, env=self.env)
        # A valid worktree cannot conceal an unsafe already-staged rule.
        self.write(self.worker, ".gitattributes", CSV + " text\n")
        self.git(self.worker, "add", ".gitattributes")
        self.write(self.worker, ".gitattributes", CSV + " -text\n")
        validate_rain_git_attributes(self.worker, env=self.env)
        with self.assertRaises(ValueError):
            validate_rain_git_attributes(self.worker, cached=True, env=self.env)

    def test_legacy_unchanged_only_and_committed_pair_gate(self):
        self.git(self.worker, "rm", META)
        with self.assertRaises(ValueError):
            validate_publication(self.worker, allow_legacy_unchanged=True)
        self.commit(self.worker, "legacy fixture")
        self.assertEqual(validate_publication(self.worker, allow_legacy_unchanged=True), "LEGACY_UNCONFIRMED_UNCHANGED")
        self.write(self.worker, "feed-only.txt", "new feed\n")
        self.commit(self.worker, "feed-only on legacy")
        self.assertEqual(validate_publication(self.worker, git_ref="HEAD", allow_legacy_unchanged=True), "LEGACY_UNCONFIRMED_UNCHANGED")
        self.write(self.worker, CSV, "changed\n")
        with self.assertRaises(ValueError):
            validate_publication(self.worker, allow_legacy_unchanged=True)
        self.write_pair(self.worker, 1, 0)
        self.commit(self.worker, "valid pair")
        self.write(self.worker, CSV, "dirty\n")
        self.assertEqual(validate_publication(self.worker, git_ref="HEAD"), hashlib.sha256(git_bytes(self.worker, "HEAD", CSV)).hexdigest())
        with self.assertRaises(ValueError):
            validate_publication(self.worker)

    def test_clean_csv_automerge_of_paired_commit_still_can_break_hash(self):
        self.write_pair(self.worker, 1, 0)
        self.commit(self.worker, "local pair")
        # Older in-flight writer updates CSV only, on a different row.
        self.write(self.seed, CSV, (self.seed / CSV).read_bytes().replace(b"B,0\n", b"B,7\n"))
        self.commit(self.seed, "legacy CSV-only writer")
        self.git(self.seed, "push", "origin", "main")
        self.git(self.worker, "fetch", "origin", "main")
        result = self.git(self.worker, "rebase", "origin/main", check=False)
        self.assertEqual(result.returncode, 0, result.stderr.decode(errors="replace"))
        merged = git_bytes(self.worker, "HEAD", CSV)
        self.assertIn(b"A,1\n", merged)
        self.assertIn(b"B,7\n", merged)
        with self.assertRaises(ValueError):
            validate_publication(self.worker, git_ref="HEAD")

    def test_autostash_conflict_can_return_success_with_bad_committed_pair(self):
        self.write_pair(self.worker, 1, 0)
        self.git(self.worker, "add", CSV)
        self.git(self.worker, "commit", "-m", "old CSV-only publisher")
        self.write_pair(self.seed, 0, 7)
        self.commit(self.seed, "other paired writer")
        self.git(self.seed, "push", "origin", "main")
        result = self.git(self.worker, "pull", "--rebase", "--autostash", "origin", "main", check=False)
        self.assertEqual(result.returncode, 0, (result.stdout + result.stderr).decode(errors="replace"))
        with self.assertRaises(ValueError):
            validate_publication(self.worker, git_ref="HEAD")
        self.assertTrue(self.git(self.worker, "diff", "--name-only", "--diff-filter=U").stdout)
        # Proves push does not inspect the unmerged/dirty working tree.
        self.git(self.worker, "push", "origin", "HEAD:main")
        with self.assertRaises(ValueError):
            validate_pair_bytes(git_bytes(self.remote, "main", CSV), git_bytes(self.remote, "main", META))


def main() -> int:
    if "--validate-pair" not in sys.argv:
        unittest.main()
        return 0
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--validate-pair", action="store_true", required=True)
    parser.add_argument("--git-ref")
    parser.add_argument("--allow-legacy-unchanged", action="store_true")
    args = parser.parse_args()
    try:
        result = validate_publication(ROOT, git_ref=args.git_ref, allow_legacy_unchanged=args.allow_legacy_unchanged)
    except (OSError, ValueError, subprocess.SubprocessError) as exc:
        print("PUBLICATION_GATE_FAILED:", exc, file=sys.stderr)
        return 1
    print("PUBLICATION_GATE_OK:", result)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
