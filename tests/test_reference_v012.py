"""Reference numbers derive from a current bound registry, not ignored digits."""
import copy
import json
import unittest

import test_claim_v011 as fixture
from copilot_delivery import Delivery
from copilot_runtime import usable
from copilot_section import section_projection


class ReferenceStructureTests(unittest.TestCase):
    def setUp(self):
        self.f = fixture.ClaimContentTests()
        self.f.setUp()
        self.addCleanup(self.f.doCleanups)
        self.rt, self.root = self.f.rt, self.f.root
        self.claim = self.f.claim("The computed length is 10 m.", "numerical")
        self.registry = {"schema_version":"1.0", "record_type":"reference_registry",
            "citation_style":{"marker_format":"[{number}]"},
            "references":[{"reference_id":"REF-A", "title":"Actual source title, 2026", "number":1, "bibliography_anchor":"refA"}],
            "citations":[{"citation_id":"CITE-A", "reference_id":"REF-A", "claim_id":"C", "number":1, "anchor":"citeA"}]}
        (self.root / "references.json").write_text(json.dumps(self.registry), encoding="utf-8")
        self.artifact = self.rt.register(self.f.rev(), "ArtifactRecord", "registry", {"path":"references.json", "artifact_type":"reference_registry"})["result"]["object_id"]
        self.structure = [{"kind":"reference", "number":1, "artifact_id":self.artifact}]
        self.text = "The computed length is 10 m. [[claim:" + self.claim + "]]\n\nSource [1] describes the inputs.\n\n[[reference:1]]"

    def section(self, text=None, structure=None):
        (self.root / "section.md").write_text(text or self.text, encoding="utf-8")
        return Delivery(self.root).section(self.f.rev(), "paper.refs", "section.md", [self.claim],
            structure=self.structure if structure is None else structure)["result"]["section_id"]

    def test_real_registry_identifier_projects_actual_title(self):
        oid = self.section()
        cp = self.rt.read()["copilot"]
        self.assertTrue(usable(self.root, cp, oid, verified=True))
        self.assertIn("[1] Actual source title, 2026", section_projection(cp, self.text, structure=self.structure, root=self.root))
        self.assertIn(self.artifact, cp["objects"][oid]["dependencies"])

    def test_false_result_next_to_citation_remains_rejected(self):
        with self.assertRaises(ValueError):
            self.section(self.text.replace("Source [1]", "Result 999 m [1]"))

    def test_undeclared_reference_is_rejected(self):
        with self.assertRaises(ValueError):
            self.section(self.text.replace("Source [1]", "Source [2]"))

    def test_self_reported_title_and_unknown_number_are_rejected(self):
        for bad in (dict(self.structure[0], title="Result 999"), dict(self.structure[0], number=999)):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                self.section(structure=[bad])

    def test_registry_file_drift_invalidates_the_current_section(self):
        oid = self.section()
        changed = copy.deepcopy(self.registry)
        changed["references"][0]["title"] = "A substituted title"
        (self.root / "references.json").write_text(json.dumps(changed), encoding="utf-8")
        self.assertFalse(usable(self.root, self.rt.read()["copilot"], oid, verified=True))
        with self.assertRaises(ValueError):
            self.section()


if __name__ == "__main__":
    unittest.main()
