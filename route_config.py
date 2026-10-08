"""路线参数、首次设置引导和本地默认值保存。"""

import json
import math
import os
import tempfile
from pathlib import Path


DEFAULT_CONFIG_PATH = Path(__file__).resolve().parent / '.campus-run.json'
DEFAULTS = {
    'points': None,
    'speed': 1000 / 210,  # 每公里 3 分 30 秒。
    'round_count': 10,
    'fluctuation_range': 0.5,
    'speed_variation': 0.2,
    'fluctuation_variation': 0.1,
    'sample_rate': 1.0,
}


def pace_to_speed(text):
    try:
        minutes, seconds = text.strip().split(':')
        minutes, seconds = int(minutes), float(seconds)
        if minutes < 0 or not math.isfinite(seconds) or not 0 <= seconds < 60:
            raise ValueError
        duration = minutes * 60 + seconds
        if duration <= 0:
            raise ValueError
        return 1000 / duration
    except (ValueError, AttributeError):
        raise ValueError('配速格式应为 分:秒，例如 3:30，且必须大于 0') from None


def format_pace(speed):
    seconds = round(1000 / speed)
    return f'{seconds // 60}:{seconds % 60:02d}'


def load_config(path):
    settings = DEFAULTS.copy()
    if not path.exists():
        return settings
    try:
        saved = json.loads(path.read_text(encoding='utf-8'))
    except (OSError, ValueError) as error:
        raise ValueError(f'无法读取设置文件 {path}：{error}') from error
    if not isinstance(saved, dict) or set(saved) - set(DEFAULTS):
        raise ValueError(f'设置文件格式不正确：{path}')
    settings.update(saved)
    validate_config(settings)
    return settings


def parse_point(text):
    try:
        parts = text.replace('，', ' ').replace(',', ' ').split()
        if len(parts) != 2:
            raise ValueError
        point = [float(part) for part in parts]
        validate_point(point)
        return point
    except (ValueError, AttributeError):
        raise ValueError('请输入 WGS-84 经度 纬度，例如 119.5107 32.2021（经度在前）') from None


def validate_point(point):
    if not isinstance(point, (list, tuple)) or len(point) != 2:
        raise ValueError('每个点必须包含经度和纬度')
    if any(isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value)
           for value in point):
        raise ValueError('经纬度必须是有限数值')
    lon, lat = point
    if not -180 <= lon <= 180 or not -90 < lat < 90:
        raise ValueError('经度须在 -180–180 之间，纬度须在 -90–90 之间（不含极点）')


def validate_config(settings):
    for key in DEFAULTS:
        if key == 'points':
            continue
        value = settings[key]
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
            raise ValueError(f'{key} 必须是有限数值')
    if not isinstance(settings['round_count'], int) or settings['round_count'] < 1:
        raise ValueError('圈数必须为正整数')
    if settings['speed'] <= 0 or settings['sample_rate'] <= 0:
        raise ValueError('速度和采样率必须大于 0')
    if not 0 <= settings['speed_variation'] < settings['speed']:
        raise ValueError('速度波动须非负且小于速度中心值')
    if not 0 <= settings['fluctuation_variation'] <= settings['fluctuation_range']:
        raise ValueError('抖动波动须非负且不大于抖动幅度；关闭抖动请同时设为 0')
    points = settings['points']
    if not isinstance(points, (list, tuple)) or len(points) != 3:
        raise ValueError('首次运行必须设置三个经纬度点（--point0、--point1、--point2，或使用交互引导）')
    for point in points:
        validate_point(point)
    (x0, y0), (x1, y1), (x2, y2) = points
    if math.dist(points[0], points[1]) == 0 or math.dist(points[1], points[2]) == 0:
        raise ValueError('直道两端和对面直道对应点不能重合')
    if abs((x1 - x0) * (y2 - y1) - (y1 - y0) * (x2 - x1)) < 1e-14:
        raise ValueError('三个点不能共线：第三点必须在对面的直道上')


def save_config(path, settings):
    """验证后原子保存，避免中断时留下半份设置。"""
    validate_config(settings)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', dir=path.parent,
                                         prefix=f'.{path.name}.', suffix='.tmp', delete=False) as file:
            temporary = Path(file.name)
            json.dump(settings, file, indent=2, ensure_ascii=False, allow_nan=False)
            file.write('\n')
        os.replace(temporary, path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def prompt_value(label, current, convert, valid=lambda value: True, display=str):
    while True:
        hint = f' [{display(current)}]' if current is not None else ' [必填]'
        text = input(f'{label}{hint}：').strip()
        if not text and current is not None:
            return current
        try:
            value = convert(text)
            if not valid(value):
                raise ValueError('数值超出范围')
            return value
        except ValueError as error:
            print(f'输入无效：{error}，请重试。')


def guide(settings, supplied):
    print('路线设置：回车保留默认值。坐标使用 WGS-84，经度在前。')
    points = settings['points'] or [None, None, None]
    labels = ['起点（直道一端）', '同一直道另一端', '对面直道对应点（跨过弯道）']
    for index, label in enumerate(labels):
        if f'point{index}' not in supplied:
            points[index] = prompt_value(label, points[index], parse_point,
                                         display=lambda p: f'{p[0]} {p[1]}')
    settings['points'] = points
    if 'speed' not in supplied:
        settings['speed'] = prompt_value('配速（分:秒 / 公里）', settings['speed'], pace_to_speed,
                                          display=format_pace)
    fields = [('round_count', '圈数', int, lambda v: v >= 1),
              ('speed_variation', '速度最大波动（米/秒）', float,
               lambda v: math.isfinite(v) and 0 <= v < settings['speed']),
              ('fluctuation_range', '每轴位置抖动中心幅度（米）', float,
               lambda v: math.isfinite(v) and v >= 0),
              ('fluctuation_variation', '抖动幅度最大波动（米）', float,
               lambda v: math.isfinite(v) and 0 <= v <= settings['fluctuation_range']),
              ('sample_rate', '采样率（点/秒）', float, lambda v: math.isfinite(v) and v > 0)]
    for key, label, convert, valid in fields:
        if key not in supplied:
            # 中心值调小后，旧的波动值也必须落在新的范围内。
            if not valid(settings[key]):
                print(f'{label}的旧值与新中心值不兼容，默认调整为 0；可重新输入。')
                settings[key] = 0.0
            settings[key] = prompt_value(label, settings[key], convert, valid)
    validate_config(settings)
    return settings
