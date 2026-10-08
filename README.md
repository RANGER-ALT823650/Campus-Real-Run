# Campus-Real-Run

通过 Python 生成操场 GPX 轨迹，再用 [pymobiledevice3](https://github.com/doronz88/pymobiledevice3) 在 iPhone 上回放模拟定位。首次交互设置路线，后续自动记住参数；每次回放生成独立临时 GPX，结束、报错或 Ctrl+C 后删除。

## 设备与条件

- iPhone / iPad，建议 iOS 17.4+，开启「设置 → 隐私与安全性 → 开发者模式」。
- macOS、Linux 或 Windows 电脑，Python 3.11+，USB 数据线；设备需解锁并信任电脑。Windows 需要 Apple 设备驱动。
- 可访问 iOS 开发者定位服务。本项目安装 `pymobiledevice3 11.19.1`；新版本通常自动建立 tunnel，已有可用 tunnel 也可以继续使用。特殊系统版本和连接方式见[官方连接文档](https://doronz88.github.io/pymobiledevice3/guides/ios17-tunnels/)。
- 三个 **WGS-84** 坐标，均按「经度 纬度」输入：`point0` 是直道起点，`point1` 是同一直道另一端，`point2` 是对面直道对应点。高德 / 百度坐标需先转换到 WGS-84。

## 安装

```bash
git clone https://github.com/RANGER-ALT823650/Campus-Real-Run.git
cd Campus-Real-Run
python3 -m venv .venv
source .venv/bin/activate  # Windows：.venv\Scripts\activate
python -m pip install -r requirements.txt
```

连接检查：

```bash
pymobiledevice3 usbmux list
pymobiledevice3 amfi developer-mode-status
pymobiledevice3 developer dvt ls /
```

## 运行

```bash
python simulate_route.py
```

首次要求填写三个坐标；随后按提示设置配速、圈数、速度波动、位置抖动和采样率，回车保留显示值。设置完成后回车开始，输入 `s` 仅保存，输入 `q` 取消。

初始默认值：配速 **3:30/km**（约 **4.762 m/s**）、**10 圈**、速度波动 **±0.2 m/s**、每轴抖动中心幅度 **0.5 m**、抖动幅度波动 **±0.1 m**、采样率 **1 点/秒**。运行结束无需保留 GPX。

设置自动保存到脚本目录的 `.campus-run.json`，下次从中读取；该文件不上传 GitHub。三个点确定跑道形状和单圈距离，圈数确定总距离。换场地时重新指定三个点。

## 常用命令

```bash
# 只设置和保存参数，不连接手机（同样可交互填写首次坐标）
python simulate_route.py --configure-only

# 修改参数：显式传入的值优先，其余值仍由交互引导设置
python simulate_route.py --pace 3:30 --laps 8 --jitter 0.5 \
  --speed-variation 0.2 --jitter-variation 0.1 --sample-rate 1

# 跳过引导，直接使用上次保存的参数
python simulate_route.py --non-interactive

# 修改并保存速度（米/秒）；--speed 与 --pace 二选一
python simulate_route.py --non-interactive --speed 4.8 --laps 6

# 离线生成、检查、删除 GPX；也会保存参数，不连接手机
python simulate_route.py --dry-run

# 使用另一份配置，适合多个场地；新配置首次仍须填写坐标
python simulate_route.py --config ./other-route.json

# 关闭位置抖动
python simulate_route.py --non-interactive --jitter 0 --jitter-variation 0

# 查看全部参数与单位
python simulate_route.py --help
```

无交互的首次运行需同时提供 `--point0 经度 纬度 --point1 经度 纬度 --point2 经度 纬度`；可组合 `--configure-only` 或 `--dry-run`，先完成设置而不回放。

Ctrl+C 停止回放并删除临时 GPX。停止播放后，要恢复真实定位请运行：

```bash
pymobiledevice3 developer dvt simulate-location clear
```

仍需导出 `data.gpx` 时可以运行 `python generate_route.py`，它使用同一套引导和已保存参数，只导出、不回放。`main.py` 和 `campus_run_gui.py` 为原项目保留的旧入口，新流程使用 `simulate_route.py`。

## 简单原理

将三个经纬度点转换为局部米坐标，用两条直道和两段半圆弯道构建跑道，按累计路程采样。速度和抖动幅度使用有边界的均值回归随机过程，在中心值附近缓慢变化；生成的 GPX 携带时间戳，`pymobiledevice3 ... simulate-location play` 按时间间隔逐点设置设备位置。

默认配速是速度中心值；每次时长会略有变化。随机位置偏移会让相邻点计算的瞬时速度超出目标速度范围，含抖动的距离统计也会与几何路线长度略有不同。是否被某个 App 记录，取决于该 App 的定位与传感器实现。

## 测试与来源

```bash
python -m unittest discover -s tests -v
```

测试离线运行，不连接手机。基于 [TheUnknownThing/Campus-Real-Run](https://github.com/TheUnknownThing/Campus-Real-Run) 扩展，沿用 [GPL-3.0 许可证](LICENSE)。
