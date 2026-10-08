import math
import random
from datetime import datetime, timedelta, timezone


def meters_per_degree(lat):
    """WGS-84 下 1 度经/纬度对应的米数（随纬度变化）。"""
    lat_rad = math.radians(lat)
    m_per_deg_lat = 111132.92 - 559.82 * math.cos(2 * lat_rad) + 1.175 * math.cos(4 * lat_rad)
    m_per_deg_lon = 111412.84 * math.cos(lat_rad) - 93.5 * math.cos(3 * lat_rad)
    return m_per_deg_lon, m_per_deg_lat


def generate_gpx(points, round_count, fluctuation_range, speed, sample_rate=1.0, start_time=None,
                 speed_variation=0.2, fluctuation_variation=0.1):
    """生成用于模拟跑步的 GPX 文件。

    三个坐标点的含义（每个点都是 (经度, 纬度)）：
        points[0] 起点：直道的一端（每圈的起点/终点）
        points[1] 直道的另一端
        points[2] 对面直道上的对应点（与 points[1] 隔着一段弯道相对）

    跑道形状 = 两条直道 + 两端各一个半圆弯道，所以
        单圈长度 = 2 * 直道长 + 2 * π * 弯道半径

    Args:
        points (list): 上述三个坐标点。
        round_count (int): 跑几圈。
        fluctuation_range (float): 每个坐标轴的 GPS 抖动幅度中心值（米），0 表示不抖动。
        speed (float): 目标速度中心值（米/秒），决定每个点之间的间距。
        sample_rate (float): 采样频率（点/秒），并写进 <time> 时间戳，
            让 pymobiledevice3 按真实速度回放（1 秒 1 个点最接近真实 GPS）。
        start_time (datetime): 轨迹起始时间，默认取当前时间（UTC）。
        speed_variation (float): 速度相对中心值的最大偏差（米/秒），0 表示匀速。
        fluctuation_variation (float): 抖动幅度相对中心值的最大偏差（米）。

    Returns:
        str: GPX 文本内容。
    """
    if not all(math.isfinite(value) for value in
               (speed, sample_rate, fluctuation_range, speed_variation, fluctuation_variation)):
        raise ValueError("速度、采样率和抖动参数必须是有限数值")
    if speed <= 0 or sample_rate <= 0 or round_count < 1 or int(round_count) != round_count:
        raise ValueError("速度和采样率必须大于 0，圈数必须为正整数")
    if not 0 <= speed_variation < speed or fluctuation_range < 0 or fluctuation_variation < 0:
        raise ValueError("随机偏差必须非负，速度偏差必须小于速度中心值")
    rng = random.Random()  # 每次生成独立随机序列，不固定 seed。
    (lon0, lat0), (lon1, lat1), (lon2, lat2) = [tuple(p) for p in points[:3]]
    m_per_deg_lon, m_per_deg_lat = meters_per_degree(lat0)

    def to_xy(lon, lat):
        """经纬度 -> 以起点为原点的平面米坐标（小范围近似）。"""
        return (lon - lon0) * m_per_deg_lon, (lat - lat0) * m_per_deg_lat

    def to_lonlat(x, y):
        """平面米坐标 -> 经纬度。"""
        return lon0 + x / m_per_deg_lon, lat0 + y / m_per_deg_lat

    def add_fluctuation(x, y, amplitude):
        """给平面坐标加上随机抖动（模拟 GPS 误差）。"""
        if fluctuation_range <= 0:
            return x, y
        return (x + rng.uniform(-amplitude, amplitude),
                y + rng.uniform(-amplitude, amplitude))

    def vary(value, center, spread):
        """均值回归随机过程：保留上一秒的变化，缓慢回到中心，并限制偏差。"""
        candidate = center + 0.92 * (value - center) + rng.gauss(0, spread * 0.15)
        return max(center - spread, min(center + spread, candidate))

    p0 = to_xy(lon0, lat0)
    p1 = to_xy(lon1, lat1)
    p2 = to_xy(lon2, lat2)

    straight = math.dist(p0, p1)                    # 直道长度
    radius = math.dist(p1, p2) / 2.0                # 弯道半径 = 对面点间距的一半
    if straight <= 0 or radius <= 0:
        raise ValueError("三个点无法构成跑道：直道长度和弯道半径都必须大于 0")

    # 单位向量：u 沿直道方向，w 指向对面直道
    ux, uy = (p1[0] - p0[0]) / straight, (p1[1] - p0[1]) / straight
    wx, wy = p2[0] - p1[0], p2[1] - p1[1]
    w_len = math.hypot(wx, wy)
    wx, wy = wx / w_len, wy / w_len

    curve_length = math.pi * radius
    lap_length = 2 * straight + 2 * curve_length

    def position(distance):
        """按累计路程取原跑道上的点，速度变化不改变跑道或总圈数。"""
        s = distance % lap_length
        if s < straight:
            return p0[0] + ux * s, p0[1] + uy * s
        s -= straight
        if s < curve_length:
            theta = math.pi - s / radius
            cx, cy = p1[0] + wx * radius, p1[1] + wy * radius
            return (cx + radius * math.cos(theta) * wx + radius * math.sin(theta) * ux,
                    cy + radius * math.cos(theta) * wy + radius * math.sin(theta) * uy)
        s -= curve_length
        if s < straight:
            return p1[0] + 2 * radius * wx - ux * s, p1[1] + 2 * radius * wy - uy * s
        s -= straight
        theta = math.pi - s / radius
        cx, cy = p0[0] + wx * radius, p0[1] + wy * radius
        return (cx - radius * math.cos(theta) * wx - radius * math.sin(theta) * ux,
                cy - radius * math.cos(theta) * wy - radius * math.sin(theta) * uy)

    if start_time is None:
        start_time = datetime.now(timezone.utc).replace(microsecond=0)
    elif start_time.tzinfo is None:
        start_time = start_time.replace(tzinfo=timezone.utc)

    step_seconds = 1.0 / sample_rate
    points_xml = []
    lon_min = lat_min = float("inf")
    lon_max = lat_max = float("-inf")
    distance = elapsed = 0.0
    total_distance = lap_length * round_count
    current_speed = rng.uniform(speed - speed_variation, speed + speed_variation)
    amplitude_spread = min(fluctuation_variation, fluctuation_range)
    amplitude = rng.uniform(fluctuation_range - amplitude_spread, fluctuation_range + amplitude_spread)
    while True:
        x, y = p0 if distance >= total_distance else position(distance)
        lon, lat = to_lonlat(*add_fluctuation(x, y, amplitude))
        lon_min, lon_max = min(lon_min, lon), max(lon_max, lon)
        lat_min, lat_max = min(lat_min, lat), max(lat_max, lat)
        when = start_time + timedelta(seconds=elapsed)
        timestamp = when.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
        points_xml.append(
            f'        <trkpt lat="{lat:.7f}" lon="{lon:.7f}">\n'
            f'          <time>{timestamp}</time>\n'
            f'        </trkpt>'
        )
        if distance >= total_distance:
            break
        current_speed = vary(current_speed, speed, speed_variation)
        amplitude = vary(amplitude, fluctuation_range, amplitude_spread)
        remaining = total_distance - distance
        # 最后一段可能不足一个采样周期；到达完整圈数后停止。
        elapsed += min(step_seconds, remaining / current_speed)
        distance = min(total_distance, distance + current_speed * step_seconds)

    return f'''<?xml version="1.0" encoding="UTF-8"?>
<gpx version="1.1" creator="Campus-Real-Run" xmlns="http://www.topografix.com/GPX/1/1">
  <metadata>
    <name>校园跑路线</name>
    <time>{start_time.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")}</time>
    <bounds minlat="{lat_min:.7f}" minlon="{lon_min:.7f}" maxlat="{lat_max:.7f}" maxlon="{lon_max:.7f}"/>
  </metadata>
  <trk>
    <name>操场跑圈 {round_count} 圈（单圈约 {lap_length:.0f} 米）</name>
    <trkseg>
{chr(10).join(points_xml)}
    </trkseg>
  </trk>
</gpx>
'''


def generate_default_gpx(settings=None):
    from route_config import DEFAULT_CONFIG_PATH, load_config, validate_config

    if settings is None:
        settings = load_config(DEFAULT_CONFIG_PATH)
    validate_config(settings)
    return generate_gpx(**settings)


if __name__ == '__main__':
    # 旧入口也使用同一套引导和配置；显式导出 GPX，不连接设备。
    from simulate_route import main

    raise SystemExit(main(export_only=True))
