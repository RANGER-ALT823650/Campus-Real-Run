import contextlib
import io
import math
import random
import tempfile
import unittest
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import generate_route
import simulate_route


NS = {'g': 'http://www.topografix.com/GPX/1/1'}


def parse(gpx):
    points = ET.fromstring(gpx).findall('.//g:trkpt', NS)
    times = [datetime.fromisoformat(p.find('g:time', NS).text.replace('Z', '+00:00')) for p in points]
    return points, times


class RouteTests(unittest.TestCase):
    def setUp(self):
        self.lon, self.lat = 119.51, 32.20
        self.mx, self.my = generate_route.meters_per_degree(self.lat)
        self.points = [(self.lon, self.lat), (self.lon, self.lat + 100 / self.my),
                       (self.lon + 60 / self.mx, self.lat + 100 / self.my)]
        self.start = datetime(2026, 10, 8, tzinfo=timezone.utc)

    def test_full_distance_and_fractional_timestamps(self):
        points, times = parse(generate_route.generate_gpx(
            self.points, 2, 0, 3, sample_rate=2, start_time=self.start, speed_variation=0))
        self.assertAlmostEqual((times[-1] - times[0]).total_seconds(),
                               2 * (200 + 60 * math.pi) / 3, places=5)
        self.assertEqual(points[0].attrib, points[-1].attrib)
        self.assertTrue(all((b - a).total_seconds() == 0.5 for a, b in zip(times[:-2], times[1:-1])))
        self.assertGreater((times[-1] - times[-2]).total_seconds(), 0)
        self.assertLessEqual((times[-1] - times[-2]).total_seconds(), 0.5)

    def test_random_speed_stays_close_to_center(self):
        with patch('generate_route.random.Random', return_value=random.Random(17)):
            points, times = parse(generate_route.generate_gpx(self.points, 2, 0, 3, start_time=self.start))
        xy = [((float(p.attrib['lon']) - self.lon) * self.mx,
               (float(p.attrib['lat']) - self.lat) * self.my) for p in points]
        # Skip the partial final interval; GPX coordinates are rounded to ~1 cm.
        speeds = [math.dist(a, b) / (tb - ta).total_seconds()
                  for a, b, ta, tb in zip(xy[:-2], xy[1:-1], times[:-2], times[1:-1])]
        self.assertGreaterEqual(min(speeds), 2.78)
        self.assertLessEqual(max(speeds), 3.22)
        self.assertGreater(max(speeds) - min(speeds), 0.1)

    def test_jitter_amplitude_changes_within_bounds(self):
        amplitudes = []

        class RecordingRandom(random.Random):
            def uniform(self, a, b):
                if a < 0 < b:
                    amplitudes.append(b)
                return super().uniform(a, b)

        with patch('generate_route.random.Random', return_value=RecordingRandom(23)):
            generate_route.generate_gpx(self.points, 2, 0.5, 3, start_time=self.start)
        self.assertGreater(len(amplitudes), 100)
        self.assertGreaterEqual(min(amplitudes), 0.4)
        self.assertLessEqual(max(amplitudes), 0.6)
        self.assertGreater(max(amplitudes) - min(amplitudes), 0.02)

    def test_fresh_gpx_and_cleanup_on_success_error_interrupt(self):
        files, contents = [], []
        original = Path('data.gpx').read_bytes() if Path('data.gpx').exists() else None

        def replay(command):
            path = Path(command[-1])
            files.append(path)
            contents.append(path.read_text())
            self.assertEqual(command[:-1], ['/mock/pymobiledevice3', 'developer', 'dvt',
                                             'simulate-location', 'play'])
            self.assertGreater(len(parse(contents[-1])[0]), 100)
            if len(files) == 3:
                raise KeyboardInterrupt
            return SimpleNamespace(returncode=0 if len(files) == 1 else 7)

        with patch('simulate_route.shutil.which', return_value='/mock/pymobiledevice3'), \
                patch('simulate_route.subprocess.run', side_effect=replay), \
                contextlib.redirect_stdout(io.StringIO()):
            for code in (0, 7, 130):
                self.assertEqual(simulate_route.replay(generate_route.generate_gpx(
                    self.points, 2, 0.5, 3, start_time=self.start)), code)
                self.assertFalse(files[-1].exists())
                self.assertFalse(files[-1].parent.exists())
        self.assertEqual(len(set(files)), 3)
        self.assertEqual(len(set(contents)), 3)
        if original is not None:
            self.assertEqual(Path('data.gpx').read_bytes(), original)

    def test_dry_run_never_starts_playback(self):
        with tempfile.TemporaryDirectory() as directory, \
                patch('simulate_route.subprocess.run') as replay, \
                contextlib.redirect_stdout(io.StringIO()):
            arguments = ['--dry-run', '--non-interactive', '--config', str(Path(directory) / 'config.json')]
            for index, point in enumerate(self.points):
                arguments += [f'--point{index}', *map(str, point)]
            self.assertEqual(simulate_route.main(arguments), 0)
            replay.assert_not_called()


if __name__ == '__main__':
    unittest.main()
