#!/usr/bin/env python3
# -*- coding: utf-8 -*-
from __future__ import annotations

import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PROMPT = ROOT / "prompts" / "patentability_overlap_assessment.md"


class PromptContractTests(unittest.TestCase):
    def test_overlap_assessment_prompt_contract(self) -> None:
        text = PROMPT.read_text(encoding="utf-8")

        self.assertIn("patentability_overlap_report_{YYYYMMDDHHmmss}.md", text)
        self.assertIn("не является официальным заключением", text)
        for status in ("полное перекрытие", "частичное перекрытие", "перекрытие не выявлено"):
            self.assertIn(status, text)
        for behavior in (
            "останови подготовку описания, формулы, реферата и фигур",
            "продолжай workflow",
            "продолжай стандартный workflow",
        ):
            self.assertIn(behavior, text)

    def test_overlap_assessment_is_in_workflow_docs(self) -> None:
        for relative_path in ("SKILL.md", "docs/PRD.md", "docs/skill-structure.md"):
            text = (ROOT / relative_path).read_text(encoding="utf-8")
            self.assertIn("patentability_overlap_assessment.md", text)

    def test_no_patent_grant_guarantee_phrases(self) -> None:
        checked_paths = [
            ROOT / "SKILL.md",
            ROOT / "prompts" / "patentability_overlap_assessment.md",
            ROOT / "prompts" / "disclosure_builder.md",
            ROOT / "prompts" / "disclosure_preview.md",
            ROOT / "README.md",
            ROOT / "docs" / "PRD.md",
        ]
        forbidden_patterns = [
            r"патент\s+точно\s+выдадут",
            r"гаранти(?:я|руется|рованн\w*)\s+патентоспособност",
            r"гаранти(?:я|руется|рованн\w*)\s+выдач",
        ]

        for path in checked_paths:
            text = path.read_text(encoding="utf-8").casefold()
            for pattern in forbidden_patterns:
                self.assertIsNone(re.search(pattern, text), f"{path}: {pattern}")


if __name__ == "__main__":
    unittest.main()
