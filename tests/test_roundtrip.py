"""Round-trip fidelity harness (tasks 6.1-6.2).

Oracle: reverse(forward(sample)) must reproduce the sample's semantic
projection — origin ids, level, characteristics, subclass, per-slot picks,
core state scalars. Loss-admissible diffs must be enumerated explicitly;
anything else fails the suite (the drift tripwire).
"""

import json
import os
import subprocess
import sys
import tempfile
import unittest

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)

from converter.reverse.ds_hero_schema import load_spec, validate_document  # noqa: E402

CLI = os.path.join(REPO, "foundry_to_forgesteel.py")
FORWARD = os.path.join(REPO, "forgesteel_converter.py")
_WORK_DIR = None


def work_dir():
    """Created lazily so merely importing (discovery) touches no filesystem."""
    global _WORK_DIR
    if _WORK_DIR is None:
        os.makedirs("/tmp/opencode", exist_ok=True)
        _WORK_DIR = tempfile.mkdtemp(prefix="fsf-roundtrip-", dir="/tmp/opencode")
    return _WORK_DIR


def semantic_projection(doc):
    """The choices a player would see in ForgeSteel after import."""
    out = {}
    culture = doc["culture"]
    for key in ("environment", "organization", "upbringing", "language"):
        feature = culture.get(key) or {}
        out[f"culture.{key}"] = sorted(
            (feature.get("data") or {}).get("selected") or [])
    for feature in doc["career"]["features"]:
        ftype, data = feature.get("type"), feature.get("data") or {}
        if ftype in ("Skill Choice", "Language Choice"):
            out[f"career.{feature['id']}"] = sorted(data.get("selected") or [])
        elif ftype == "Perk":
            out[f"career.{feature['id']}"] = sorted(
                s["id"] for s in data.get("selected") or [])
    for entry in doc["class"]["featuresByLevel"]:
        for feature in entry.get("features", []):
            data = feature.get("data") or {}
            ftype = feature.get("type")
            fid = feature["id"]
            if ftype == "Skill Choice":
                out[f"class.{fid}"] = sorted(data.get("selected") or [])
            elif ftype in ("Choice", "Perk"):
                out[f"class.{fid}"] = sorted(
                    s["id"] if isinstance(s, dict) else s
                    for s in data.get("selected") or [])
            elif ftype == "Class Ability":
                out[f"class.{fid}"] = sorted(data.get("selectedIDs") or [])
            elif ftype == "Kit":
                out[f"class.{fid}"] = sorted(
                    s["id"] for k in [data] for s in k.get("selected") or [])
    out["subclass"] = sorted(s["id"] for s in doc["class"]["subclasses"]
                             if s.get("selected"))
    out["chars"] = sorted((c["characteristic"], c["value"])
                          for c in doc["class"]["characteristics"])
    out["level"] = doc["class"]["level"]
    for key in ("ancestry", "culture", "class", "career", "complication"):
        block = doc.get(key)
        out[key] = (block or {}).get("id")
    anc_sel = []
    for feature in doc["ancestry"]["features"]:
        # Traits surface either as a Choice selection or (for app-synthesized
        # options with no static-data Choice container) as a top-level
        # feature; both mean "the player has this trait".
        anc_sel.append(feature.get("id"))
        data = feature.get("data") or {}
        if data.get("selected"):
            anc_sel += [s["id"] if isinstance(s, dict) else s
                        for s in data["selected"]]
    out["ancestry_sel"] = sorted(i for i in anc_sel if i)
    state = doc["state"]
    out["state.core"] = (state["xp"], state["surges"], state["victories"],
                         state["renown"], state["wealth"])
    out["state.titles"] = sorted(t.get("id", "?") for t in state.get("titles", []))
    return out


# Forward-converter gaps surfaced by the harness (each independently
# verified as a limitation of the forward direction, not the reverse).
# The forward converter writes ONE flat advancement-flag entry per origin
# item (last skill def wins) and omits some def flags entirely — unlike the
# live Foundry module, which records precise per-def selections (proven on
# the swami-native live export, which reverse-maps with zero skill drift).
FORWARD_GAPS = {
    "Pyre.ds-hero": {
        "career.mages-apprentice-feature-1",  # 'Skill (Magic)' flag omitted
        "class.elementalist-1-1",             # single-skill class def omitted
    },
    "Pyre (2).ds-hero": {
        "career.mages-apprentice-feature-1",
        "class.elementalist-1-1",
    },
    "Swami.ds-hero": {
        "culture.upbringing",                     # 'Martial' flag omitted
        "career.career-soldier-feature-2",        # flat-flag overwrite
        "class.tactician-1-1",                    # single-skill class def omitted
    },
    "Keth.ds-hero": {
        "culture.upbringing",                     # 'Creative' flag omitted
        "career.career-warden-feature-1",         # flat-flag overwrite
        "career.career-warden-feature-2",         # flat-flag overwrite
        "career.career-warden-feature-3",         # 'Skill (Intrigue)' flag omitted
        "class.fury-1-1",                         # class def flag omitted
        # Neither forward nor native exports can recover perk->slot pairing:
        # the module models a Perk choice as an 'itemGrant' advancement that
        # never records the granted item, and perk items carry no back-link
        # to their granting definition. Two Exploration-list perks across
        # two Exploration perk slots are an unrecoverable tie and may swap.
        "career.career-warden-feature-6",
        "class.fury-2-1",
    },
}


def run_roundtrip(sample_path):
    """forward -> reverse; returns (rt_doc, forward_json, report)."""
    base = os.path.splitext(os.path.basename(sample_path))[0]
    fwd_path = os.path.join(work_dir(), f"{base}.fwd.json")
    rt_path = os.path.join(work_dir(), f"{base}.rt.ds-hero")
    fwd = subprocess.run(
        [sys.executable, FORWARD, sample_path, fwd_path],
        capture_output=True, text=True, cwd=REPO)
    assert fwd.returncode == 0, f"forward failed: {fwd.stderr[-400:]}"
    rev = subprocess.run(
        [sys.executable, CLI, fwd_path, rt_path],
        capture_output=True, text=True, cwd=REPO)
    assert rev.returncode == 0, f"reverse failed: {rev.stderr[-400:]}"
    with open(rt_path, encoding="utf-8") as fh:
        rt_doc = json.load(fh)
    with open(rt_path + ".report.json", encoding="utf-8") as fh:
        report = json.load(fh)
    with open(fwd_path, encoding="utf-8") as fh:
        fwd_doc = json.load(fh)
    return rt_doc, fwd_doc, report


class TestRoundTrip(unittest.TestCase):
    def check_sample(self, name, extra_admissible=frozenset()):
        sample = os.path.join(REPO, name)
        with open(sample, encoding="utf-8") as fh:
            original = json.load(fh)
        rt_doc, _fwd, report = run_roundtrip(sample)
        # structural gate must have passed inside the CLI; recheck
        self.assertEqual(validate_document(rt_doc, load_spec()), [])
        a = semantic_projection(original)
        b = semantic_projection(rt_doc)
        admissible = set(FORWARD_GAPS.get(name, set())) | set(extra_admissible)
        diffs = {k: (a[k], b.get(k)) for k in a if a[k] != b.get(k)}
        unexpected = {k: v for k, v in diffs.items() if k not in admissible}
        self.assertEqual(
            unexpected, {},
            f"{name}: unexpected round-trip drift: "
            f"{json.dumps(unexpected, indent=1, default=str)}\n"
            f"(admissible known-forward-gaps: {sorted(admissible)})")
        stale = admissible - set(diffs)
        if stale:
            self.fail(f"{name}: keys declared admissible but now matching "
                      f"({sorted(stale)}) — forward gap fixed? update harness")

    def test_pyre(self):
        self.check_sample("Pyre.ds-hero")

    def test_pyre2(self):
        self.check_sample("Pyre (2).ds-hero")

    def test_swami(self):
        self.check_sample("Swami.ds-hero")

    def test_keth(self):
        self.check_sample("Keth.ds-hero")

    def test_drift_guard(self):
        """A perturbed reverse mapping must fail the suite loudly."""
        sample = os.path.join(REPO, "Pyre.ds-hero")
        rt_doc, _fwd, _report = run_roundtrip(sample)
        rt_doc["class"]["level"] += 1  # perturb one projection value
        a = semantic_projection(json.load(open(sample, encoding="utf-8")))
        b = semantic_projection(rt_doc)
        self.assertNotEqual(a["level"], b["level"])
        self.assertIn("level", {k for k in a if a[k] != b.get(k)})


if __name__ == "__main__":
    unittest.main()
