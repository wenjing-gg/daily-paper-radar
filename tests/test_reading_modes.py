"""无个人研究想法时，关键词订阅与通用简报仍应正常工作。"""
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from analysis_prompt import build_analysis_prompt, reading_context
from run_daily import validate


class ReadingModeTests(unittest.TestCase):
    def profile(self, **changes):
        return {'sources': {'huggingface': {'enabled': True}}, 'llm_enrich': {'backend': 'none'}, **changes}

    def test_keywords_only_are_passed_to_model_without_research_idea(self):
        profile = self.profile(keywords=['retrieval', 'reasoning'])
        self.assertEqual(validate(profile), 'none')
        real_dumps = json.dumps
        with patch('analysis_prompt.json.dumps', wraps=real_dumps) as encode:
            build_analysis_prompt(profile, [], {})
        context = encode.call_args_list[0].args[0]
        self.assertEqual(context['筛选模式'], 'keywords')
        self.assertEqual(context['主题关键词（可独立使用）'], profile['keywords'])
        self.assertEqual(context['关注方向（可选）'], '')

    def test_direction_only_does_not_require_keywords(self):
        profile = self.profile(focus_description='检索增强生成', keywords=[])
        self.assertEqual(validate(profile), 'none')
        self.assertEqual(reading_context(profile)['mode'], 'direction')

    def test_no_preferences_generates_general_digest_mode(self):
        profile = self.profile(focus_description='', paper_preferences='', keywords=[])
        self.assertEqual(validate(profile), 'none')
        self.assertEqual(reading_context(profile)['mode'], 'general')

    def test_optional_reading_preferences_work_independently(self):
        profile = self.profile(paper_preferences='优先看评测方法')
        self.assertEqual(reading_context(profile)['mode'], 'preferences')


if __name__ == '__main__':
    unittest.main()
