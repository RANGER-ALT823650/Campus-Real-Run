import contextlib
import io
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import generate_route
import route_config
import simulate_route


POINT_ARGS = ['--point0', '119.51', '32.20', '--point1', '119.51', '32.201',
              '--point2', '119.511', '32.201']


class ConfigTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.path = Path(self.temporary.name) / 'settings.json'
        self.base = ['--config', str(self.path), '--configure-only']

    def run_cli(self, arguments, **kwargs):
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            return simulate_route.main(self.base + arguments, **kwargs)

    def test_first_run_requires_coordinates_without_side_effects(self):
        with patch('simulate_route.subprocess.run') as playback:
            self.assertEqual(self.run_cli(['--non-interactive']), 2)
            self.assertFalse(self.path.exists())
            playback.assert_not_called()

    def test_defaults_are_three_thirty_and_saved_values_are_reused(self):
        self.assertEqual(self.run_cli(['--non-interactive'] + POINT_ARGS), 0)
        settings = route_config.load_config(self.path)
        self.assertAlmostEqual(settings['speed'], 1000 / 210)
        self.assertEqual(route_config.format_pace(settings['speed']), '3:30')
        self.assertEqual(self.run_cli(['--non-interactive', '--pace', '4:00', '--laps', '6',
                                      '--jitter', '0.7', '--jitter-variation', '0.2',
                                      '--speed-variation', '0.3', '--sample-rate', '2']), 0)
        changed = route_config.load_config(self.path)
        self.assertAlmostEqual(changed['speed'], 1000 / 240)
        self.assertEqual(changed['round_count'], 6)
        self.assertEqual(changed['fluctuation_range'], 0.7)
        self.assertEqual(changed['fluctuation_variation'], 0.2)
        self.assertEqual(changed['speed_variation'], 0.3)
        self.assertEqual(changed['sample_rate'], 2)
        self.assertEqual(self.run_cli(['--non-interactive']), 0)
        self.assertEqual(route_config.load_config(self.path), changed)
        self.assertIn('操场跑圈 6 圈', generate_route.generate_default_gpx(changed))

    def test_interactive_first_run_and_enter_to_reuse(self):
        answers = ['bad', '119.51 32.20', '119.51,32.201', '119.511 32.201',
                   '', '', '', '', '', '']
        with patch('builtins.input', side_effect=answers), patch('simulate_route.subprocess.run') as playback:
            self.assertEqual(self.run_cli([]), 0)
            playback.assert_not_called()
        settings = route_config.load_config(self.path)
        with patch('builtins.input', return_value=''):
            self.assertEqual(self.run_cli([]), 0)
        self.assertEqual(route_config.load_config(self.path), settings)

    def test_explicit_cli_values_take_priority_in_guide(self):
        with patch('builtins.input', side_effect=['', '', '', '']):
            self.assertEqual(self.run_cli(POINT_ARGS + ['--speed', '5', '--laps', '3']), 0)
        self.assertEqual(route_config.load_config(self.path)['speed'], 5)
        self.assertEqual(route_config.load_config(self.path)['round_count'], 3)

    def test_invalid_update_does_not_replace_saved_config(self):
        self.assertEqual(self.run_cli(['--non-interactive'] + POINT_ARGS), 0)
        before = self.path.read_bytes()
        for flags in (['--laps', '0'], ['--speed', 'nan'], ['--speed-variation', '9'],
                      ['--jitter', '0'], ['--sample-rate', '0'], ['--point0', '181', '32'],
                      ['--point2', '119.51', '32.202']):
            with self.subTest(flags=flags):
                self.assertEqual(self.run_cli(['--non-interactive'] + flags), 2)
                self.assertEqual(self.path.read_bytes(), before)

    def test_invalid_saved_file_is_not_overwritten(self):
        self.path.write_text('{broken', encoding='utf-8')
        self.assertEqual(self.run_cli(['--non-interactive'] + POINT_ARGS), 2)
        self.assertEqual(self.path.read_text(), '{broken')

    def test_zero_jitter_and_multiple_configs(self):
        self.assertEqual(self.run_cli(['--non-interactive', '--jitter', '0',
                                      '--jitter-variation', '0'] + POINT_ARGS), 0)
        self.assertEqual(route_config.load_config(self.path)['fluctuation_range'], 0)
        other = Path(self.temporary.name) / 'nested' / 'other.json'
        self.assertEqual(self.run_cli(['--config', str(other), '--non-interactive',
                                      '--laps', '2'] + POINT_ARGS), 0)
        self.assertEqual(route_config.load_config(other)['round_count'], 2)
        self.assertEqual(route_config.load_config(self.path)['round_count'], 10)
        self.assertFalse(list(other.parent.glob('*.tmp')))

    def test_cancellation_does_not_save_or_start_playback(self):
        # Remove --configure-only so the final guide choice is exercised.
        arguments = ['--config', str(self.path)] + POINT_ARGS
        for last_answer, result in [('q', 0), (KeyboardInterrupt(), 130)]:
            with patch('builtins.input', side_effect=[''] * 6 + [last_answer]), \
                    patch('simulate_route.subprocess.run') as playback, \
                    contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(simulate_route.main(arguments), result)
                self.assertFalse(self.path.exists())
                playback.assert_not_called()
        with patch('builtins.input', side_effect=[''] * 6 + ['s']), \
                patch('simulate_route.subprocess.run') as playback, \
                contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(simulate_route.main(arguments), 0)
            self.assertTrue(self.path.exists())
            playback.assert_not_called()

    def test_bad_pace_and_conflicting_speed_options(self):
        for pace in ('0:00', '3:60', '-1:30', '3:nan', 'nope'):
            with self.subTest(pace=pace), self.assertRaises(ValueError):
                route_config.pace_to_speed(pace)
        with self.assertRaises(SystemExit), contextlib.redirect_stderr(io.StringIO()):
            simulate_route.build_parser().parse_args(['--pace', '3:30', '--speed', '5'])


if __name__ == '__main__':
    unittest.main()
