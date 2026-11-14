"""Mocked authentic HTML table parsing and all-or-nothing ingestion gates."""
from datetime import date, timedelta
import json
from pathlib import Path
import tempfile
import unittest

from research.supercompute.v47_official_ingest import (
    ingest, append_verified, parse_publisher_table, SOURCES, PARSER_ID,
)


def history(game, count=10, start=None):
    if start is None:
        start = 2026000 if game == "ssq" else 26000
    result = []
    for i in range(count):
        front = ([1, 3, 7, 10, 20, 31] if game == "ssq"
                 else [2, 5, 11, 19, 30])
        back = [5] if game == "ssq" else [4, 12]
        result.append({"issue": str(start + i), "draw_date":
            (date(2026, 10, 1) + timedelta(days=i)).isoformat(),
            "front": front[:], "back": back[:]})
    return result


def html_table(game, rows):
    if game == "ssq":
        body = "".join(
            '<tr><td>{issue}</td><td>{draw_date}(四)</td>'
            '<td><span>{red}</span></td><td><i>{blue}</i></td><td>300</td><td><a href="#"><img src="detail.png"></a></td></tr>'.format(
                issue=x["issue"], draw_date=x["draw_date"],
                red="".join(f"<i>{n:02d}</i>" for n in x["front"]),
                blue=f'{x["back"][0]:02d}') for x in rows)
    else:
        body = "".join(
            '<tr><td>{draw_date}</td><td>{issue}</td><td>{numbers}</td>'
            '<td><a>详细</a></td></tr>'.format(
                issue=x["issue"], draw_date=x["draw_date"],
                numbers=" ".join(f"{n:02d}" for n in x["front"] + x["back"]))
            for x in rows)
    return ("<html><body><table><tbody>" + body +
            "</tbody></table></body></html>").encode()


def receipt(game, body):
    return {"source_url": SOURCES[game][0], "effective_url": SOURCES[game][0],
            "http_status": 200, "content_type": "text/html",
            "raw_sha256": __import__("hashlib").sha256(body).hexdigest(),
            "bytes": len(body), "parser_id": PARSER_ID,
            "fetched_utc": "2026-11-14T00:00:00Z"}


class LiveOfficialIngestionTests(unittest.TestCase):
    def test_parse_realistic_issuer_html(self):
        for game in ("ssq", "dlt"):
            records = history(game)
            self.assertEqual(parse_publisher_table(
                game, html_table(game, records)), records)
            with self.assertRaises(ValueError):
                parse_publisher_table(game, b"<html><body>404</body></html>")

    def test_refuse_conflict_and_skip(self):
        for game in ("ssq", "dlt"):
            base = history(game)
            extended = base + history(game, count=2, start=int(base[-1]["issue"]) + 1)
            extended[-2]["draw_date"] = "2026-10-11"
            extended[-1]["draw_date"] = "2026-10-12"
            out, audit = append_verified(base, extended[5:], game)
            self.assertEqual(out[-1]["issue"], str(int(base[-1]["issue"]) + 2))
            self.assertEqual(audit["overlap_count"], 5)
            self.assertEqual(audit["added_count"], 2)
            changed = [dict(r) for r in extended[5:]]
            changed[0]["front"] = [1, 2, 7, 10, 20, 31] if game == "ssq" \
                else [1, 5, 11, 19, 30]
            with self.assertRaises(ValueError):
                append_verified(base, changed, game)
            skipped = extended[5:-1]
            with self.assertRaises(ValueError):
                append_verified(base, skipped[:5] + [extended[-1]], game)

    def test_two_game_fetch_create_only_and_scored_provenance(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            base_paths = {}
            lookup = {}
            for game in ("ssq", "dlt"):
                base = history(game)
                path = root / (game + "-seed.json")
                path.write_text(json.dumps({"game": game.upper(), "draws": base}))
                base_paths[game] = path
                latest = history(game, count=2, start=int(base[-1]["issue"]) + 1)
                latest[0]["draw_date"], latest[1]["draw_date"] = "2026-10-11", "2026-10-12"
                html = html_table(game, base[5:] + latest)
                lookup[game] = (html, receipt(game, html))
            def fetch(game):
                return lookup[game]
            outdir = root / "run"
            out = ingest(base_paths, outdir, fetch=fetch)
            self.assertEqual(out["status"], "OVERLAP_VERIFIED")
            self.assertFalse(out["signed_official_data_verified"])
            self.assertEqual(out["games"]["ssq"]["new_target_issue"], "2026012")
            self.assertEqual(out["games"]["dlt"]["added_count"], 2)
            with self.assertRaises(FileExistsError):
                ingest(base_paths, outdir, fetch=fetch)

    def test_failure_creates_non_success_receipt_without_history_output(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            base_paths = {}
            for game in ("ssq", "dlt"):
                path = root / (game + "-seed.json")
                path.write_text(json.dumps({"game": game.upper(),
                    "draws": history(game)}))
                base_paths[game] = path
            def broken(game):
                raise TimeoutError("simulated publisher outage")
            with self.assertRaises(TimeoutError):
                ingest(base_paths, root / "fail", fetch=broken)
            data = json.loads((root / "fail/failure-receipt.json").read_text())
            self.assertFalse(data["official_source_verified"])
            self.assertEqual(data["failure_type"], "TimeoutError")
            self.assertFalse((root / "fail/ssq-verified-history.json").exists())


if __name__ == "__main__":
    unittest.main()
