"""Offline Git proofs for intact snapshot publication; no HTTP or live data."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re
import shutil
import sys
import unittest

from scripts import test_rain_workflow_publication as pub
from scripts.archive_basin_station_forecast import archive_snapshot
from scripts import reparent_basin_snapshot as retry


@unittest.skipUnless(shutil.which("git") and pub.bash_path(), "Git and Bash required")
class SnapshotRetryTests(unittest.TestCase):
    def setUp(self):
        self.lab = pub.PublicationGitTests()
        self.lab.setUp()
        self.addCleanup(self.lab.doCleanups)

    def payload(self, *, commit=True):
        lab = self.lab
        lab.write_pair(lab.worker, 1, 0)
        feed = {"generated_at_utc": "2026-10-07T20:05:00Z", "stations": [],
                "missing": None, "rain_zero": 0, "source_time": "2026-10-07T19:45:00Z"}
        for path in (pub.FEED, pub.STATUS):
            lab.write(lab.worker, path, json.dumps(feed) + "\n")
        archive = archive_snapshot(lab.worker / pub.FEED, lab.worker / pub.ARCHIVE)
        if commit:
            lab.commit(lab.worker, "validated snapshot")
        return archive.relative_to(lab.worker).as_posix()

    def advance(self, changes=None):
        lab = self.lab
        lab.write(lab.seed, "app.txt", "remote user work\n")
        lab.write(lab.seed, "assets/data/ai_lab/shadow_live_latest.json", '{"generated_at_utc":"2026-10-07T20:06Z"}\n')
        for path, value in (changes or {}).items():
            lab.write(lab.seed, path, value)
        lab.commit(lab.seed, "independent update")
        lab.git(lab.seed, "push", "origin", "main")
        lab.git(lab.worker, "fetch", "origin", "main")
        return lab.git(lab.worker, "rev-parse", "origin/main").stdout.decode().strip()

    def tree_bytes(self, ref, path):
        return pub.git_bytes(self.lab.worker, ref, path)

    def test_unrelated_advance_preserves_exact_blobs_real_index_worktree_and_history(self):
        lab = self.lab
        archive = self.payload()
        candidate = lab.git(lab.worker, "rev-parse", "HEAD").stdout.decode().strip()
        upstream = self.advance({pub.ARCHIVE + "/other-existing.json": "upstream archive\n"})
        lab.write(lab.worker, "local-untracked.txt", "preserve me\n")
        lab.write(lab.worker, pub.STATUS, "local unstaged work\n")
        before_status = lab.git(lab.worker, "status", "--porcelain=v1", "-z").stdout
        before_index = lab.git(lab.worker, "ls-files", "--stage", "-z").stdout
        prepared = retry.prepare_snapshot(lab.worker)
        self.assertEqual(lab.git(lab.worker, "show", "-s", "--format=%P", prepared).stdout.decode().strip(), upstream)
        self.assertEqual(lab.git(lab.worker, "rev-parse", "HEAD").stdout.decode().strip(), candidate)
        self.assertEqual(lab.git(lab.worker, "status", "--porcelain=v1", "-z").stdout, before_status)
        self.assertEqual(lab.git(lab.worker, "ls-files", "--stage", "-z").stdout, before_index)
        self.assertEqual((lab.worker / pub.STATUS).read_bytes(), b"local unstaged work\n")
        for path in (*retry.OUTPUTS, archive):
            self.assertEqual(self.tree_bytes(prepared, path), self.tree_bytes(candidate, path))
        for path in ("app.txt", "assets/data/ai_lab/shadow_live_latest.json", pub.ARCHIVE + "/other-existing.json"):
            self.assertEqual(self.tree_bytes(prepared, path), self.tree_bytes(upstream, path))
        self.assertEqual(lab.git(lab.worker, "merge-base", "--is-ancestor", upstream, prepared).returncode, 0)
        pub.validate_publication(lab.worker, git_ref=prepared)
        # A normal fast-forward push, not force, accepts the prepared object.
        lab.git(lab.worker, "push", "origin", prepared + ":main")
        self.assertEqual(pub.git_bytes(lab.remote, "main", pub.FEED), self.tree_bytes(candidate, pub.FEED))

    def test_repeated_advances_reuse_same_snapshot_and_already_published_does_not_regress(self):
        lab = self.lab
        archive = self.payload()
        original = self.tree_bytes("HEAD", pub.FEED)
        self.advance()
        prepared = retry.prepare_snapshot(lab.worker)
        self.advance({"other-job.txt": "another writer\n"})
        prepared = retry.prepare_snapshot(lab.worker, candidate=prepared)
        self.assertEqual(self.tree_bytes(prepared, pub.FEED), original)
        self.assertEqual(hashlib.sha256(self.tree_bytes(prepared, archive)).hexdigest(), Path(archive).stem.split("-")[1])
        lab.git(lab.worker, "push", "origin", prepared + ":main")
        lab.git(lab.worker, "fetch", "origin", "main")
        self.assertEqual(retry.prepare_snapshot(lab.worker, candidate=prepared), prepared)

    def test_related_upstream_outputs_code_and_catalog_require_rebuild(self):
        self.payload()
        for path in (*retry.OUTPUTS, "scripts/build_basin_station_forecast.py",
                     "previne/robo/source.py", "codigo_python/10_chuvas/source.py",
                     "previsao_ao_vivo.json", "previsao_ao_vivo_mucum.json",
                     "assets/data/estudo_bacia_taquari_antas/postos_g040.geojson",
                     "assets/data/estudo_bacia_taquari_antas/ugs_g040.geojson"):
            with self.subTest(path=path):
                self.advance({path: "upstream data or producer changed\n"})
                with self.assertRaises(retry.RebuildRequired):
                    retry.prepare_snapshot(self.lab.worker)

    def test_invalid_pair_status_archive_and_extra_paths_fail_closed(self):
        lab = self.lab
        archive = self.payload()
        original_candidate = lab.git(lab.worker, "rev-parse", "HEAD").stdout.decode().strip()
        self.advance()
        # Each malformed change is tested as a single publication commit.
        bad = {pub.CSV: b"bad CSV\n", pub.META: b"{}\n", pub.STATUS: b"{}\n",
               archive: b"bad historical bytes\n", "unexpected.txt": b"not a snapshot\n"}
        for path, body in bad.items():
            with self.subTest(path=path):
                lab.write(lab.worker, path, body)
                lab.commit(lab.worker, "malformed snapshot")
                with self.assertRaises((retry.RebuildRequired, ValueError)):
                    retry.prepare_snapshot(lab.worker)
                # Temporary lab only: return to the known complete candidate.
                lab.git(lab.worker, "reset", "--hard", original_candidate)

    def test_upstream_archive_collision_never_overwrites(self):
        archive = self.payload()
        self.advance({archive: "different upstream historical bytes\n"})
        with self.assertRaises(retry.RebuildRequired):
            retry.prepare_snapshot(self.lab.worker)

    def test_no_remote_advancement_is_not_a_fast_retry(self):
        self.payload()
        with self.assertRaises(retry.RebuildRequired):
            retry.prepare_snapshot(self.lab.worker)

    def test_deleted_outputs_and_merge_candidates_are_refused(self):
        lab = self.lab
        self.payload()
        original = lab.git(lab.worker, "rev-parse", "HEAD").stdout.decode().strip()
        target = self.advance()
        lab.git(lab.worker, "rm", pub.STATUS)
        lab.commit(lab.worker, "deleted output")
        with self.assertRaises(retry.RebuildRequired):
            retry.prepare_snapshot(lab.worker)
        tree = lab.git(lab.worker, "rev-parse", original + "^{tree}").stdout.decode().strip()
        merged = lab.run_command(["git", "commit-tree", tree, "-p", original, "-p", target, "-m", "merge fixture"], lab.worker).stdout.decode().strip()
        with self.assertRaises(retry.RebuildRequired):
            retry.prepare_snapshot(lab.worker, candidate=merged)

    def test_unrelated_root_with_identical_protected_blobs_is_refused(self):
        lab = self.lab
        base_tree = lab.git(lab.worker, "rev-parse", "HEAD^{tree}").stdout.decode().strip()
        self.payload()
        foreign = lab.run_command(["git", "commit-tree", base_tree, "-m", "unrelated root"], lab.worker).stdout.decode().strip()
        with self.assertRaises(retry.RebuildRequired):
            retry.prepare_snapshot(lab.worker, target=foreign)

    def test_csv_crlf_bytes_provenance_and_missing_zero_timestamps_are_unchanged(self):
        lab = self.lab
        self.payload(commit=False)
        raw = (lab.worker / pub.CSV).read_bytes().replace(b"\n", b"\r\n")
        lab.write(lab.worker, pub.CSV, raw)
        lab.write(lab.worker, pub.META, json.dumps({"schema_version": 1, "cells": {}, "csv_sha256": hashlib.sha256(raw).hexdigest()}))
        lab.commit(lab.worker, "exact CRLF snapshot")
        self.advance()
        prepared = retry.prepare_snapshot(lab.worker)
        self.assertEqual(self.tree_bytes(prepared, pub.CSV), raw)
        self.assertEqual(pub.validate_publication(lab.worker, git_ref=prepared), hashlib.sha256(raw).hexdigest())
        feed = json.loads(self.tree_bytes(prepared, pub.FEED))
        self.assertIsNone(feed["missing"])
        self.assertEqual(feed["rain_zero"], 0)
        self.assertEqual(feed["generated_at_utc"], "2026-10-07T20:05:00Z")
        self.assertEqual(feed["source_time"], "2026-10-07T19:45:00Z")

    def test_real_workflow_fast_path_does_not_collect_or_rebuild(self):
        lab = self.lab
        archive = self.payload(commit=False)
        expected = {path: (lab.worker / path).read_bytes() for path in (*retry.OUTPUTS, archive)}
        self.advance()
        shim = r'''
sleep() { printf 'LAB_SLEEP %s\n' "$1"; }
python() {
  if [[ "$*" == *"baixar_chuvas_horarias.py"* || "$*" == *"build_basin_station_forecast.py"* ]]; then
    echo UNEXPECTED_REBUILD; return 98
  fi
  command "$LAB_PYTHON" "$@"
}
'''
        result = lab.run_command([pub.bash_path(), "--noprofile", "--norc", "-e", "-o", "pipefail", "-c",
                                  shim + pub.publication_shell("basin-station-forecast")], lab.worker,
                                 check=False, env={**lab.env, "LAB_PYTHON": Path(sys.executable).as_posix()})
        output = (result.stdout + result.stderr).decode(errors="replace")
        self.assertEqual(result.returncode, 0, output)
        self.assertNotIn("UNEXPECTED_REBUILD", output)
        self.assertIn("Snapshot intacto", output)
        for path, value in expected.items():
            self.assertEqual(pub.git_bytes(lab.remote, "main", path), value)
        self.assertEqual(pub.git_bytes(lab.remote, "main", "app.txt"), b"remote user work\n")


class WorkflowRetryContractTests(unittest.TestCase):
    def test_runtime_tests_and_single_pages_group(self):
        yml = (pub.ROOT / ".github/workflows/basin-station-forecast.yml").read_text(encoding="utf-8")
        for path in ("scripts/reparent_basin_snapshot.py", "scripts/test_reparent_basin_snapshot.py"):
            self.assertIn("      - '" + path + "'", yml)
        self.assertIn("scripts.test_reparent_basin_snapshot", yml)
        shell = pub.publication_shell("basin-station-forecast")
        self.assertLess(shell.index("scripts/reparent_basin_snapshot.py"), shell.index("git reset --keep origin/main"))
        self.assertNotRegex(shell, r"--force|git rebase|git pull")
        pages = (pub.ROOT / ".github/workflows/deploy-pages.yml").read_text(encoding="utf-8")
        exact_group = r"^  group: github-pages-site\s*$"
        self.assertIsNotNone(re.search(exact_group, pages, re.MULTILINE))
        self.assertIsNone(re.search(exact_group, pages.replace("group: github-pages-site", "group: github-pages-site-${{ github.event_name }}"), re.MULTILINE))
        self.assertIn("cancel-in-progress: false", pages)
        self.assertIn("ref: main", pages)


if __name__ == "__main__":
    unittest.main()
