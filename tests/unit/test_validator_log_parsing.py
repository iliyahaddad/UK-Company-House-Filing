import unittest

from app.validation.validator import ArelleValidator


class LogParsingTests(unittest.TestCase):
    def test_empty_log_is_error_not_silent_pass(self):
        errors, warnings, info = ArelleValidator._classify_text([])
        self.assertEqual((errors, warnings, info), ([], [], []))

    def test_disclosure_system_not_recognized_is_an_error(self):
        lines = ['[arelle:disclosureSystemName] Disclosure System "hmrc" not recognized (a plug-in may be needed). - ']
        errors, warnings, info = ArelleValidator._classify_text(lines)
        self.assertEqual(len(errors), 1)
        self.assertEqual(warnings, [])

    def test_plain_error_line_classified(self):
        errors, warnings, info = ArelleValidator._classify_text(["[ERROR] JFCVC.3312 fact missing"])
        self.assertEqual(len(errors), 1)

    def test_warning_line_classified(self):
        errors, warnings, info = ArelleValidator._classify_text(["[WARNING] ix11.8.1.2 header should be hidden"])
        self.assertEqual(warnings, ["[WARNING] ix11.8.1.2 header should be hidden"])
        self.assertEqual(errors, [])

    def test_xml_log_empty_string_yields_nothing(self):
        errors, warnings, info = ArelleValidator._parse_xml_logs("")
        self.assertEqual((errors, warnings, info), ([], [], []))

    def test_xml_log_with_error_entry(self):
        xml = ('<?xml version="1.0"?><log>'
               '<entry level="ERROR" messageCode="xbrl:test"><message>Bad thing</message></entry>'
               '</log>')
        errors, warnings, info = ArelleValidator._parse_xml_logs(xml)
        self.assertTrue(any("Bad thing" in e for e in errors))


class ValidatorFailsClosedTests(unittest.TestCase):
    def test_result_with_no_log_is_invalid(self):
        validator = ArelleValidator()
        result = validator._result(
            valid=False, errors=["Arelle produced no log, so the result cannot be trusted."],
            warnings=[], info=[], raw_log="", version="x", selected_ds="hmrc",
            connectivity="offline", packages=[],
        )
        self.assertFalse(result["valid"])
        self.assertGreater(len(result["errors"]), 0)


if __name__ == "__main__":
    unittest.main()
