"""每次生成一份临时 GPX，回放结束（或 Ctrl+C / 报错）后删除。"""

import argparse
import shutil
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET
from datetime import datetime
from pathlib import Path

from generate_route import generate_default_gpx
from route_config import (DEFAULT_CONFIG_PATH, format_pace, guide, load_config,
                          pace_to_speed, save_config, validate_config)


def build_parser():
    parser = argparse.ArgumentParser(description=__doc__)
    for index, label in enumerate(('起点', '同一直道另一端', '对面直道对应点')):
        parser.add_argument(f'--point{index}', nargs=2, type=float, metavar=('LON', 'LAT'), help=label + '，经度在前')
    speed = parser.add_mutually_exclusive_group()
    speed.add_argument('--pace', type=pace_to_speed, metavar='M:SS', help='配速，例如 3:30（每公里）')
    speed.add_argument('--speed', type=float, help='速度中心值（米/秒），与 --pace 二选一')
    parser.add_argument('--laps', type=int, dest='round_count', help='圈数')
    parser.add_argument('--jitter', type=float, dest='fluctuation_range', help='每轴位置抖动中心幅度（米）')
    parser.add_argument('--speed-variation', type=float, help='速度最大波动（米/秒）')
    parser.add_argument('--jitter-variation', type=float, dest='fluctuation_variation', help='抖动幅度最大波动（米）')
    parser.add_argument('--sample-rate', type=float, help='采样率（点/秒）')
    parser.add_argument('--config', type=Path, default=DEFAULT_CONFIG_PATH, help='默认值保存路径')
    parser.add_argument('--non-interactive', action='store_true', help='跳过引导，使用已保存设置和传入参数')
    action = parser.add_mutually_exclusive_group()
    action.add_argument('--dry-run', action='store_true', help='保存设置，生成并检查轨迹后删除；不连接手机')
    action.add_argument('--configure-only', action='store_true', help='仅保存设置，不生成 GPX、不连接手机')
    return parser


def resolve_settings(args):
    settings = load_config(args.config)
    supplied = set()
    points = settings['points'] or [None, None, None]
    for index in range(3):
        point = getattr(args, f'point{index}')
        if point is not None:
            points[index] = point
            supplied.add(f'point{index}')
    settings['points'] = points
    for key in ('speed', 'round_count', 'fluctuation_range', 'speed_variation',
                'fluctuation_variation', 'sample_rate'):
        value = getattr(args, key)
        if value is not None:
            settings[key] = value
            supplied.add(key)
    if args.pace is not None:
        settings['speed'] = args.pace
        supplied.add('speed')
    if args.non_interactive:
        validate_config(settings)
    else:
        guide(settings, supplied)
    return settings


def main(argv=None, *, export_only=False):
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        settings = resolve_settings(args)
        print(f"配速 {format_pace(settings['speed'])}/km（{settings['speed']:.3f} 米/秒），"
              f"{settings['round_count']} 圈，速度波动 ±{settings['speed_variation']:g} 米/秒。", flush=True)
        print(f"每轴抖动幅度 {settings['fluctuation_range']:g} ± {settings['fluctuation_variation']:g} 米，"
              f"采样率 {settings['sample_rate']:g} 点/秒。", flush=True)
        if not (args.non_interactive or args.dry_run or args.configure_only or export_only):
            while True:
                action = input('回车开始回放；s 仅保存设置；q 取消：').strip().lower()
                if action == 'q':
                    print('已取消，设置未保存。')
                    return 0
                if action in ('', 's'):
                    args.configure_only = action == 's'
                    break
                print('请输入回车、s 或 q。')
        save_config(args.config, settings)
        print(f'设置已保存，下次自动使用：{args.config}', flush=True)
        if args.configure_only:
            return 0
        gpx = generate_default_gpx(settings)
        if export_only and not args.dry_run:
            Path('data.gpx').write_text(gpx, encoding='utf-8')
            print('已导出 data.gpx，未连接手机。')
            return 0
        return replay(gpx, dry_run=args.dry_run)
    except KeyboardInterrupt:
        print('\n操作已停止。', flush=True)
        return 130
    except EOFError:
        print('未收到引导输入；自动运行请添加 --non-interactive 并提供首次坐标。', file=sys.stderr)
        return 2
    except (ValueError, OSError) as error:
        print(f'错误：{error}', file=sys.stderr)
        return 2


def replay(gpx, *, dry_run=False):
    with tempfile.TemporaryDirectory(prefix='campus-real-run-') as directory:
        gpx_file = Path(directory) / 'route.gpx'
        gpx_file.write_text(gpx, encoding='utf-8')
        root = ET.fromstring(gpx)
        ns = {'g': 'http://www.topografix.com/GPX/1/1'}
        points = root.findall('.//g:trkpt', ns)
        start = datetime.fromisoformat(points[0].find('g:time', ns).text.replace('Z', '+00:00'))
        end = datetime.fromisoformat(points[-1].find('g:time', ns).text.replace('Z', '+00:00'))
        print(root.find('g:trk/g:name', ns).text, flush=True)
        print(f'已生成 {len(points)} 个点，预计 {(end - start).total_seconds() / 60:.1f} 分钟。', flush=True)
        print(f'临时 GPX：{gpx_file}', flush=True)
        try:
            if dry_run:
                print('离线检查完成，未连接手机。', flush=True)
                return 0
            executable = shutil.which('pymobiledevice3')
            command = [executable] if executable else [sys.executable, '-m', 'pymobiledevice3']
            command += ['developer', 'dvt', 'simulate-location', 'play', str(gpx_file)]
            return subprocess.run(command).returncode
        except KeyboardInterrupt:
            print('\n回放已停止。', flush=True)
            return 130
        finally:
            gpx_file.unlink(missing_ok=True)
            print('临时 GPX 已删除。', flush=True)


if __name__ == '__main__':
    sys.exit(main())
