from __future__ import annotations

import json
import unittest

from chat.preferences import Preference, extract, parse_rules, readback
from chat.war_room import affirms
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

    def test_a_negated_detail_is_never_saved_as_what_it_negates(self):
        self.assertEqual(
            parse_rules("For DB saturation, please do not paste raw logs, just a summary."),
            [Preference("wants_detail", "summary", "db_saturation")])
        self.assertEqual(
            parse_rules("Open a ticket and paste the raw slow-query lines, not a summary."),
            [Preference("preferred_channel", "ticket", None),
             Preference("wants_detail", "raw_logs", None)])

    def test_raw_lines_win_when_asked_for_with_a_summary(self):
        self.assertEqual(parse_rules("Page me with raw logs and a summary."),
                         [Preference("preferred_channel", "page", None),
                          Preference("wants_detail", "raw_logs", None)])

    def test_curly_apostrophes_still_negate(self):
        self.assertEqual(parse_rules("For DB saturation, don\u2019t open a ticket, page me."),
                         [Preference("preferred_channel", "page", "db_saturation")])

    def test_only_a_plain_yes_approves_a_read_back(self):
        for reply in ("Yes, that's right.", "yes", "Correct.", "Yep"):
            with self.subTest(reply=reply):
                self.assertTrue(affirms(reply))
        for reply in ("No, that's wrong.", "Correct me if I am wrong, but no", "Yes? No.",
                      "Right, but don\u2019t use Slack", "", None):
            with self.subTest(reply=reply):
                self.assertFalse(affirms(reply))

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
