from __future__ import annotations

import json
import unittest

from chat.preferences import Preference, extract, parse_rules, readback
from common.llm import LLMError, Reply
from eval import truth


class FakeModel:
    def __init__(self, content: str | None = None, error: bool = False) -> None:
        self.content, self.error = content, error

    def chat(self, messages, tools=None, json_mode=False):
        if self.error:
            raise LLMError("offline")
        return Reply(self.content or "")


class RuleParserTests(unittest.TestCase):
    def test_priyas_instruction(self):
        prefs = parse_rules(truth.load("s01").engineer_says)
        self.assertEqual(set(prefs), {
            Preference("preferred_channel", "ticket", "db_saturation"),
            Preference("wants_detail", "raw_logs", "db_saturation"),
        })

    def test_conditions_keep_instructions_apart(self):
        deploy = parse_rules("For bad deploys, page me right away.")
        self.assertEqual(deploy, [Preference("preferred_channel", "page", "bad_deploy")])
        db = parse_rules("For DB saturation, open a ticket.")[0]
        self.assertNotEqual(db.lineage("person:priya"), deploy[0].lineage("person:priya"))

    def test_negated_channel_is_not_chosen(self):
        self.assertEqual(parse_rules("Please don't ping me on Slack about the cache."), [])

    def test_unconditional_preference(self):
        self.assertEqual(parse_rules("Always open a ticket."),
                         [Preference("preferred_channel", "ticket", None)])

    def test_readback_is_plain_language(self):
        text = readback(parse_rules(truth.load("s01").engineer_says))
        self.assertIn("for DB saturation, notify you by ticket", text)
        self.assertTrue(text.endswith("Correct?"))


class ModelParserTests(unittest.TestCase):
    MESSAGE = "For DB saturation, open a ticket."

    def test_uses_a_valid_model_answer(self):
        content = json.dumps({"preferences": [
            {"predicate": "preferred_channel", "value": "ticket", "condition_family": "db_saturation"}]})
        self.assertEqual(extract(self.MESSAGE, FakeModel(content)),
                         [Preference("preferred_channel", "ticket", "db_saturation")])

    def test_falls_back_when_the_model_invents_vocabulary(self):
        content = json.dumps({"preferences": [
            {"predicate": "preferred_channel", "value": "carrier pigeon", "condition_family": None}]})
        self.assertEqual(extract(self.MESSAGE, FakeModel(content)), parse_rules(self.MESSAGE))

    def test_falls_back_when_the_model_is_down_or_rambles(self):
        for model in (FakeModel(error=True), FakeModel("Sure! Here you go")):
            with self.subTest(model=model):
                self.assertEqual(extract(self.MESSAGE, model), parse_rules(self.MESSAGE))


if __name__ == "__main__":
    unittest.main()
