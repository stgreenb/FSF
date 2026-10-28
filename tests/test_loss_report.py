"""Tests for the structured loss report (task 5.1)."""

import json
import os
import unittest

from converter.reverse.loss_report import ACTIONS, REASONS, LossReport


class TestLossReport(unittest.TestCase):
    def test_schema_completeness(self):
        report = LossReport()
        report.input_path = "/in.json"
        report.output_path = "/out.ds-hero"
        report.sources = {"packs": "1.1.0", "fs_data": "abc123"}
        report.count("ability", converted=12)
        report.loss("Deadweight", "treasure", "deadweight",
                    reason="payload-unavailable", action="dropped")
        report.warning("state-reset", "stamina damage discarded")
        payload = report.to_dict()
        for key in ("input", "output", "sources", "counts", "losses", "warnings"):
            self.assertIn(key, payload)
        entry = payload["losses"][0]
        for key in ("item", "type", "dsid", "reason", "action"):
            self.assertIn(key, entry)
        self.assertEqual(payload["counts"]["treasure"],
                         {"converted": 0, "dropped": 1})

    def test_closed_vocabularies_enforced(self):
        report = LossReport()
        with self.assertRaises(ValueError):
            report.loss("x", "feature", None, reason="made-up", action="dropped")
        with self.assertRaises(ValueError):
            report.loss("x", "feature", None, reason="unmappable", action="vaporized")
        with self.assertRaises(ValueError):
            report.warning("not-a-code")
        self.assertEqual(REASONS, frozenset({
            "unmappable", "payload-unavailable", "unsupported-construct",
            "version-mismatch", "defaulted"}))
        self.assertEqual(ACTIONS, frozenset({
            "dropped", "recovered-by-name", "defaulted"}))

    def test_warnings_independent_of_losses(self):
        report = LossReport()
        report.warning("payload-divergence", "elementalist-2-1 differs")
        self.assertFalse(report.has_losses)
        self.assertTrue(report.has_warnings)

    def test_write_sidecar(self):
        report = LossReport()
        report.loss("Custom", "feature", None, reason="unmappable",
                    action="dropped", detail="homebrew")
        path = "/tmp/opencode/fsf-report.json"
        os.makedirs("/tmp/opencode", exist_ok=True)
        report.write(path)
        with open(path) as fh:
            data = json.load(fh)
        self.assertEqual(len(data["losses"]), 1)
        self.assertEqual(data["losses"][0]["reason"], "unmappable")

    def test_summary_line(self):
        report = LossReport()
        report.count("ability", converted=10)
        report.loss("A", "ability", None, reason="unmappable", action="dropped")
        line = report.summary_line("Pyre", 2)
        self.assertIn("Pyre", line)
        self.assertIn("level 2", line)
        self.assertIn("unmappable x1", line)

    def test_top_reasons_capped(self):
        report = LossReport()
        for reason in REASONS:
            report.loss("x", "feature", None, reason=reason, action="dropped")
        self.assertEqual(len(report.top_reasons(2)), 2)


if __name__ == "__main__":
    unittest.main()
