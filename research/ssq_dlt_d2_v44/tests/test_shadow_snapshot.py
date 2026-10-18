"""Independent two-draw oracle and re-pinned adversarial archival fixtures."""
import copy
import hashlib
import json
from pathlib import Path
import stat
import tempfile
import unittest
from unittest.mock import patch
import warnings
import zipfile

from research.ssq_dlt_d2_v44 import shadow_snapshot as module


def encoded(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":"), allow_nan=False).encode("utf-8")


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


class SyntheticSnapshot:
    """Construct evidence from an explicit independent oracle, not the parser."""
    counts = {"SSQ": 1, "DLT": 1}

    def __init__(self):
        self.urls = {
            "SSQ": "https://www.cwl.gov.cn/cwl_admin/front/cwlkj/search/kjxx/findDrawNotice?name=ssq&pageNo=1",
            "DLT": "https://webapi.sporttery.cn/gateway/lottery/getHistoryPageListV1.qry?gameNo=85&pageNo=1"}
        self.raw = {
            "SSQ": {"state": 0, "result": [{"code": "2026001", "date": "2026-01-01(四)",
                                            "red": "01,02,03,04,05,06", "blue": "07"}]},
            "DLT": {"success": True, "value": {"list": [{"lotteryDrawNum": "26001",
                    "lotteryDrawTime": "2026-01-01", "lotteryDrawResult": "01 02 03 04 05 06 07"}]}}}
        self.oracle = [dict(game="SSQ", issue="2026001", date="2026-01-01", front=[1,2,3,4,5,6], back=[7]),
                       dict(game="DLT", issue="26001", date="2026-01-01", front=[1,2,3,4,5], back=[6,7])]
        self.rows = []
        for projected in self.oracle:
            row = dict(copy.deepcopy(projected), draw_date_timezone="Asia/Shanghai",
                       historical_predraw_asof_proven=False, formal_training_eligible=False,
                       sources=[dict(capture_sha256=None, available_at=None, publisher_exact_at=None,
                                     availability_evidence=None, saved_raw_path="Z:/do-not-follow/original.bin")])
            row.update({field: None for field in module.NULL_TIMES})
            self.rows.append(row)
        self.mapping_rows = [dict(copy.deepcopy(row), row_id=row["game"]+":"+row["issue"],
                                  available_at=None, matches=[]) for row in self.oracle]
        self.positions = {"SSQ": 0, "DLT": 0}
        self.omit_mapping = False
        self.mapper = b'raise RuntimeError("ARCHIVE CODE MUST REMAIN INERT")\n'
        self.overrides = {}
        self.manifest_changes = {}

    def entries(self):
        files = {"code/mapper.py": self.mapper}
        raw_sources, original_sources = [], []
        for game in ("SSQ", "DLT"):
            raw = encoded(self.raw[game])
            raw_id = digest(raw)
            name = f"evidence/data01/sources/{raw_id}.bin"
            files[name] = raw
            source = dict(game=game, raw_id=raw_id, raw_sha256=raw_id, size=len(raw),
                          file_ref=dict(evidence_root="data01", relative_path=f"sources/{raw_id}.bin"),
                          requested_url=self.urls[game], final_url=self.urls[game], available_at=None,
                          record_array="result" if game == "SSQ" else "value.list", record_count=1)
            raw_sources.append(source)
            original_sources.append(dict(sha256=raw_id, bytes=len(raw), requested_url=self.urls[game],
                                         final_url=self.urls[game], available_at=None, publisher_exact_at=None, http_status=200))
            for row in self.rows:
                if row["issue"] == ("2026001" if game == "SSQ" else "26001"):
                    row["sources"][0]["capture_sha256"] = raw_id
            for mapped in self.mapping_rows:
                if mapped["issue"] == ("2026001" if game == "SSQ" else "26001"):
                    position = self.positions[game]
                    mapped["matches"] = [dict(raw_id=raw_id, record_position=position,
                        record_json_pointer=("/result/" if game == "SSQ" else "/value/list/")+str(position))]
        history = dict(schema="GLP_HISTORY_SNAPSHOT_v44_1", total_rows=2, available_at_null_rows=2,
                       formal_training_allowed=False, model_cutoff_at=None,
                       games={g: dict(row_count=1, rows=[r for r in self.rows if r["issue"] ==
                                                      ("2026001" if g == "SSQ" else "26001")]) for g in self.counts})
        source_manifest = dict(schema="GLP_OFFICIAL_SOURCE_MANIFEST_v44_1", original_HTTP_sources=original_sources)
        files["history_snapshot.json"] = encoded(history)
        files["source_manifest.json"] = encoded(source_manifest)
        files.update({k: v for k, v in self.overrides.items() if k != "row_mapping.json"})
        def binding(name):
            return dict(file=name, size=len(files[name]), sha256=digest(files[name]))
        mapping = dict(schema="SSQ_DLT_SAVED_BYTES_ROW_MAPPING_V1", mapper_version="1.0.0",
                       policy="CENTRAL_HTTP_JSON_ONLY_V1", counts=self.counts, total_rows=2,
                       raw_sources=raw_sources, rows=self.mapping_rows[:-1] if self.omit_mapping else self.mapping_rows,
                       history=binding("history_snapshot.json"), source_manifest=binding("source_manifest.json"),
                       canonical_draw_rows_sha256=digest(encoded(self.oracle)))
        files["row_mapping.json"] = self.overrides.get("row_mapping.json", encoded(mapping))
        bindings = {key: binding(name) for key, name in
                    (("history", "history_snapshot.json"), ("source_manifest", "source_manifest.json"),
                     ("row_mapping", "row_mapping.json"), ("mapper", "code/mapper.py"))}
        bindings["mapper"]["version"] = "1.0.0"
        manifest = dict(schema="V41_SOURCE_ASOF_MANIFEST_1", kind="DATA_SNAPSHOT_COMMITMENT_V1",
                        evidence_roots={"data01": "evidence/data01"}, row_counts=self.counts,
                        file_table=[binding(name) for name in sorted(files)], source_bindings=bindings,
                        edge="NO_EDGE", formal_A_samples=0, formal_training_eligibility="BLOCKED",
                        history_publication_time_proven=False)
        manifest.update(self.manifest_changes)
        manifest_bytes = encoded(manifest)
        entries = {"snapshot/"+name: raw for name, raw in files.items()}
        entries.update({"timestamp_proof/committed/"+name: raw for name, raw in files.items()})
        entries["snapshot/manifest.json"] = entries["timestamp_proof/committed/manifest.json"] = manifest_bytes
        return entries, digest(manifest_bytes)

    def write(self, folder, *, entry_mutator=None, duplicate=False, symlink=False):
        entries, manifest_pin = self.entries()
        if entry_mutator:
            entry_mutator(entries)
        table = [dict(file=name, size=len(raw), sha256=digest(raw)) for name, raw in sorted(entries.items())]
        entries["SHA_MANIFEST.json"] = encoded(dict(files=table))
        target = Path(folder)/"fixture.zip"
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", UserWarning)
            with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as archive:
                for name, raw in entries.items():
                    info = zipfile.ZipInfo("fixture/"+name)
                    if symlink and name == "snapshot/code/mapper.py":
                        info.create_system = 3
                        info.external_attr = (stat.S_IFLNK | 0o777) << 16
                    archive.writestr(info, raw)
                if duplicate:
                    archive.writestr("fixture/snapshot/manifest.json", entries["snapshot/manifest.json"])
        return target, digest(target.read_bytes()), manifest_pin

    def verify(self, folder, **options):
        path, archive_pin, manifest_pin = self.write(folder, **options)
        return module.verify_snapshot_archive(path, archive_pin, manifest_pin, expected_counts=self.counts)


class TestShadowSnapshot(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.fixture = SyntheticSnapshot()

    def reject(self, **options):
        with self.assertRaises(module.SnapshotRejected):
            self.fixture.verify(self.temp.name, **options)

    def test_independent_oracle_and_inert_code(self):
        result = self.fixture.verify(self.temp.name)
        self.assertEqual(result["counts"], {"SSQ": 1, "DLT": 1})
        self.assertEqual([{k: r[k] for k in module.PROJECTION} for r in result["rows"]], self.fixture.oracle)
        self.assertEqual(len(result["files"]), 6)
        self.assertTrue(all(r["available_at"] is None for r in result["rows"]))
        self.assertEqual(result["files"]["code/mapper.py"], self.fixture.mapper)

    def test_wrong_archive_pin(self):
        path, _, manifest_pin = self.fixture.write(self.temp.name)
        with self.assertRaisesRegex(module.SnapshotRejected, "ARCHIVE_SHA256_MISMATCH"):
            module.verify_snapshot_archive(path, "0"*64, manifest_pin, expected_counts=self.fixture.counts)

    def test_wrong_manifest_pin(self):
        path, archive_pin, _ = self.fixture.write(self.temp.name)
        with self.assertRaisesRegex(module.SnapshotRejected, "MANIFEST_SHA256_MISMATCH"):
            module.verify_snapshot_archive(path, archive_pin, "0"*64, expected_counts=self.fixture.counts)

    def test_repin_raw_number_conflict(self):
        self.fixture.raw["SSQ"]["result"][0]["red"] = "01,02,03,04,05,08"
        self.reject()

    def test_repin_history_number_conflict(self):
        self.fixture.rows[0]["front"] = [1,2,3,4,5,8]
        self.reject()

    def test_repin_draw_date_conflict(self):
        self.fixture.rows[0]["date"] = "2026-01-02"
        self.reject()

    def test_repin_issue_year_conflict(self):
        self.fixture.rows[0]["date"] = "2025-01-01"
        self.reject()

    def test_repin_nonexistent_json_pointer(self):
        self.fixture.positions["DLT"] = 1
        self.reject()

    def test_repin_missing_mapping(self):
        self.fixture.omit_mapping = True
        self.reject()

    def test_repin_cross_game_identity(self):
        self.fixture.rows[0]["game"] = "DLT"
        self.reject()

    def test_repin_temporal_backfill(self):
        for field in module.NULL_TIMES:
            with self.subTest(field=field):
                self.fixture = SyntheticSnapshot()
                self.fixture.rows[0][field] = "2026-01-01T00:00:00Z"
                self.reject()

    def test_repin_source_temporal_backfill(self):
        for field in ("available_at", "publisher_exact_at", "availability_evidence"):
            with self.subTest(field=field):
                self.fixture = SyntheticSnapshot()
                self.fixture.rows[0]["sources"][0][field] = "invented"
                self.reject()

    def test_repin_formal_promotion(self):
        for changes in ({"formal_A_samples": 1}, {"edge": "EDGE"},
                        {"formal_training_eligibility": "PASS"}, {"history_publication_time_proven": True}):
            with self.subTest(changes=changes):
                self.fixture = SyntheticSnapshot()
                self.fixture.manifest_changes.update(changes)
                self.reject()

    def test_duplicate_json_key_repin(self):
        self.fixture.overrides["history_snapshot.json"] = b'{"games":{},"games":{}}'
        self.reject()

    def test_nonfinite_json_repin(self):
        self.fixture.overrides["history_snapshot.json"] = b'{"games":NaN}'
        self.reject()

    def test_unsafe_windows_paths(self):
        for name in ("../outside", "C:/outside", "snapshot/raw:stream", "snapshot/CON.txt",
                     "snapshot/trailing. ", "snapshot\\raw", "snapshot/../raw"):
            with self.subTest(name=name):
                self.reject(entry_mutator=lambda entries: entries.update({name: b"unsafe"}))
        self.assertFalse((Path(self.temp.name)/"outside").exists())

    def test_casefold_duplicate_paths(self):
        self.reject(entry_mutator=lambda entries: entries.update({"SNAPSHOT/manifest.json": b"duplicate"}))

    def test_exact_duplicate_paths(self):
        self.reject(duplicate=True)

    def test_symlink_refused(self):
        self.reject(symlink=True)

    def test_archive_resource_bounds(self):
        for field in ("MAX_ARCHIVE_BYTES", "MAX_MEMBER_BYTES", "MAX_TOTAL_BYTES", "MAX_MEMBERS"):
            with self.subTest(bound=field), patch.object(module, field, 1):
                self.reject()

    def test_committed_copy_tamper_even_with_outer_repin(self):
        self.reject(entry_mutator=lambda entries: entries.update({"timestamp_proof/committed/code/mapper.py": b"changed"}))

    def test_bound_file_tamper_even_with_outer_repin(self):
        self.reject(entry_mutator=lambda entries: entries.update({"snapshot/code/mapper.py": b"changed"}))

    def test_unapproved_source_host(self):
        self.fixture.urls["SSQ"] = self.fixture.urls["SSQ"].replace("www.cwl.gov.cn", "www.cwl.gov.cn.attacker.invalid")
        self.reject()

    def test_source_game_identity(self):
        self.fixture.urls["DLT"] = self.fixture.urls["DLT"].replace("gameNo=85", "gameNo=86")
        self.reject()

    def test_invalid_archive_cli_does_not_create_database(self):
        path, _, manifest_pin = self.fixture.write(self.temp.name)
        db, receipt = Path(self.temp.name)/"unused.sqlite3", Path(self.temp.name)/"receipt.json"
        with self.assertRaises(module.SnapshotRejected):
            module.main(["--archive", str(path), "--archive-sha256", "0"*64,
                         "--manifest-sha256", manifest_pin, "--db", str(db), "--output", str(receipt)])
        self.assertFalse(db.exists())
        self.assertFalse(receipt.exists())

    def test_no_implicit_default_counts(self):
        path, archive_pin, manifest_pin = self.fixture.write(self.temp.name)
        with self.assertRaisesRegex(module.SnapshotRejected, "MANIFEST_ROW_COUNTS"):
            module.verify_snapshot_archive(path, archive_pin, manifest_pin)


if __name__ == "__main__":
    unittest.main()
