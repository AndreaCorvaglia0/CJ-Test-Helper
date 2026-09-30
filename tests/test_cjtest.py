import datetime as dt
import os
import tempfile
import unittest
from pathlib import Path

from cjtest import criteria, engine, generator, outputs, package_loader, profile, static_checks
from tests import fixtures

PILOT = os.environ.get("CJTEST_PILOT")  # path to a real Package Manager export, optional


def load_mini():
    tmp = tempfile.TemporaryDirectory()
    pkg = package_loader.load(fixtures.write(Path(tmp.name) / "mini.json"))
    tmp.cleanup()
    prof = profile.infer(pkg)
    prof["settings"]["engagement_mailbox"] = "tester@example.com"
    return pkg, prof


class CriteriaTest(unittest.TestCase):
    def test_nested_and_null_semantics(self):
        xml = fixtures.criteria(fixtures.cond("s", "A", "Is", "true"),
                                '<ConditionSet Operator="OR">' + fixtures.cond("s", "B", "Is", "false")
                                + fixtures.cond("s", "B", "IsNull") + "</ConditionSet>")
        node = criteria.parse(xml, lambda k: ("DE", k.split(".")[-1]))
        ev = lambda a, b: criteria.evaluate(node, {("DE", "A"): a, ("DE", "B"): b}.get)
        self.assertTrue(ev("true", None))
        self.assertTrue(ev("True", "false"))
        self.assertFalse(ev("true", "true"))
        self.assertFalse(ev(None, None))  # null never equals a value

    def test_case_insensitive_equal(self):
        node = criteria.parse(fixtures.criteria(fixtures.cond("s", "C", "Equal", "EMAIL")), lambda k: ("DE", "C"))
        self.assertTrue(criteria.evaluate(node, lambda v: "Email", case_insensitive=True))
        self.assertFalse(criteria.evaluate(node, lambda v: "Email", case_insensitive=False))


class LoaderAndProfileTest(unittest.TestCase):
    def setUp(self):
        self.pkg, self.prof = load_mini()

    def test_placeholders_resolved(self):
        j = self.pkg.journey
        self.assertEqual(j.root, "D0")
        self.assertEqual(self.pkg.entry_de, "Entry")
        crit = j.activities["D2"].outcomes[0].criteria
        self.assertEqual(criteria.variables(crit), {("Master", "Consent"), ("Master", "Dunning")})

    def test_profile_inference(self):
        p = self.prof
        self.assertEqual(p["injection_des"], ["Master", "Target", "Config"])  # commented join ignored
        self.assertEqual(p["de_levels"]["Config"], "scenario")
        self.assertEqual(p["field_links"]["Target.SalesforceId"], "contact_key")
        self.assertEqual(p["field_links"]["Target.Description"], "scenario_key")
        self.assertEqual(p["fixed_values"], {"Config.ACTIVE": "True"})
        self.assertEqual(p["date_rules"]["Config.START_DATE"], "yesterday")
        self.assertEqual(p["date_rules"]["Config.WAIT1"], "yesterday")


class EngineTest(unittest.TestCase):
    def setUp(self):
        self.pkg, self.prof = load_mini()
        self.result = engine.Engine(self.pkg, self.prof).derive()

    def test_full_coverage(self):
        self.assertEqual(self.result.uncovered, [])

    def test_random_split_only_in_statistical_scenario(self):
        kinds = [s.kind for s in self.result.scenarios]
        self.assertEqual(kinds.count("statistical"), 1)
        for s in self.result.scenarios:
            if s.kind == "path":
                self.assertEqual(s.assignment[("Config", "CG")], "false")

    def test_engagement_yes_only_after_referenced_email(self):
        for s in self.result.scenarios:
            for c in s.cases:
                if c.engagement.get("G1"):
                    self.assertIn(("E1", "e1-o"), c.steps)

    def test_remainder_when_no_match(self):
        e = engine.Engine(self.pkg, self.prof)
        leaves = e.walk({("Config", "CG"): "false", ("Config", "CHANNEL"): "SMS",
                         ("Master", "Consent"): None, ("Master", "Dunning"): None})
        self.assertEqual([s[0] for s in leaves[0].steps], ["D0", "D1", "U1"])


class GeneratorTest(unittest.TestCase):
    def setUp(self):
        self.pkg, self.prof = load_mini()
        self.result = engine.Engine(self.pkg, self.prof).derive()
        self.ds = generator.Generator(self.pkg, self.prof, self.result, "RUN1", dt.date(2026, 1, 15)).build()

    def test_no_validation_errors(self):
        self.assertEqual(self.ds.errors, [])

    def test_keys_consistent_across_des(self):
        master = {r["ContactId"] for r in self.ds.contact_rows["Master"]}
        target = self.ds.contact_rows["Target"]
        self.assertEqual(master, {r["SalesforceId"] for r in target})
        campaigns = {r["CampaignName"] for rows in self.ds.scenario_rows["Config"].values() for r in rows}
        self.assertEqual({r["Description"] for r in target}, campaigns)

    def test_emails(self):
        for rec in self.ds.case_records.values():
            engaged = any(rec.case.engagement.values())
            for key, mail in zip(rec.contact_keys, rec.emails):
                if engaged:
                    self.assertEqual(mail, f"tester+{key.lower()}@example.com")
                else:
                    self.assertTrue(mail.endswith("@example.invalid"))

    def test_engagement_wait_in_future(self):
        for sid, rows in self.ds.scenario_rows["Config"].items():
            wait = rows[0]["WAIT1"]
            if sid in self.ds.engagement_deadlines:
                self.assertGreater(wait, "2026-01-15 23:59")
            else:
                self.assertEqual(wait, "2026-01-14")

    def test_outputs_written(self):
        with tempfile.TemporaryDirectory() as tmp:
            files = outputs.write_run(Path(tmp), self.pkg, self.prof, self.result, self.ds, static_checks.run(self.pkg))
            for k in ("testbook", "matrix", "report", "manifest"):
                self.assertTrue(files[k].exists())


@unittest.skipUnless(PILOT, "set CJTEST_PILOT to a real package export")
class PilotTest(unittest.TestCase):
    def test_pilot_generates_without_errors(self):
        pkg = package_loader.load(PILOT)
        prof = profile.infer(pkg)
        prof["settings"]["engagement_mailbox"] = "tester@example.com"
        result = engine.Engine(pkg, prof).derive()
        ds = generator.Generator(pkg, prof, result, "PILOT").build()
        self.assertEqual(ds.errors, [])
        self.assertGreater(len(result.covered), 0)


if __name__ == "__main__":
    unittest.main()
