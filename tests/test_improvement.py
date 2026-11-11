"""Tests offline cho cải tiến Bài 4: nhắc model đọc incident được dẫn link (H1/H6)."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from agent import run_agent
from status_tools import StatusTools
from test_lab import FakeProvider, tool_call, final

FIRST = '{"provider":"github","incident_id":"h02n9572mx9y"}'
LINKED = '{"provider":"github","incident_id":"xr3myzj7ms51"}'
URL_FIRST, URL_LINKED = 'https://stspg.io/7pwv28hvkmz8', 'https://stspg.io/pjgptg3cfc6n'


class ReferenceGateTests(unittest.TestCase):
    def test_unfollowed_reference_is_nudged_then_followed(self):
        fake = FakeProvider([tool_call('1', 'get_incident_details', FIRST), final('Xem ' + URL_FIRST),
                             tool_call('2', 'get_incident_details', LINKED),
                             final(f'Nguồn {URL_FIRST} và {URL_LINKED}')])
        result = run_agent('Điều tra', fake, StatusTools(), max_steps=6)
        self.assertEqual(result['status'], 'completed')
        events = [x for x in result['trace'] if x['event'] == 'validation_unfollowed_reference']
        self.assertEqual(events[0]['references'], {'xr3myzj7ms51': 'h02n9572mx9y'})
        self.assertEqual(len({x['step'] for x in result['trace'] if x['event'] == 'tool'}), 2)
        self.assertIn('xr3myzj7ms51', fake.histories[2][-1]['content'])

    def test_reference_nudged_only_once(self):
        fake = FakeProvider([tool_call('1', 'get_incident_details', FIRST), final('A ' + URL_FIRST),
                             final('B ' + URL_FIRST)])
        result = run_agent('Điều tra', fake, StatusTools(), max_steps=6)
        self.assertEqual(result['status'], 'completed')
        self.assertEqual(sum(x['event'] == 'validation_unfollowed_reference' for x in result['trace']), 1)

    def test_no_nudge_without_budget_for_tool_and_answer(self):
        fake = FakeProvider([tool_call('1', 'get_incident_details', FIRST), final('A ' + URL_FIRST)])
        result = run_agent('Điều tra', fake, StatusTools(), max_steps=3)
        self.assertEqual(result['status'], 'completed')
        self.assertFalse(any(x['event'] == 'validation_unfollowed_reference' for x in result['trace']))

    def test_canonical_incident_link_counts_as_source(self):
        fake = FakeProvider([tool_call('1', 'get_incident_details', LINKED),
                             final('https://www.githubstatus.com/incidents/xr3myzj7ms51')])
        self.assertEqual(run_agent('x', fake, StatusTools(), max_steps=2)['status'], 'completed')


if __name__ == '__main__':
    unittest.main()
