# WonderLantern Z6 QEMU

Z6 C3.80 实验性模拟器源码包，包含原厂菜单/拍摄 UI、合成 RAW→功能性 ISP→LCD、原生网格、主/副拨轮输入。

**固件由使用者自行提供。** 包内没有尼康固件、解密程序、转储、密钥、标定、提取的字体图标或原厂 UI 截图。它运行在电脑上，不是可刷相机的固件。

## 开始使用

Linux 或 WSL，Python3.12以上。Windows用户自行选择WSL发行版，公开包没有本机发行版名称限制。

```sh
sudo apt-get update
sudo apt-get install build-essential ninja-build pkg-config python3-venv libglib2.0-dev libpixman-1-dev zlib1g-dev libfdt-dev
python3 -m venv .venv
. .venv/bin/activate
python -m pip install -r requirements.txt
python tools/build.py --jobs 4
python tools/make_cmos.py
python tools/interactive.py --firmware /path/to/your/z6-c380-main.bin --profile shooting --photo-liveview --port 8787
```

浏览器打开 http://127.0.0.1:8787/ 。默认M档，主拨轮按钮或键盘 `[`、`]` 每次调一格快门；副拨轮为 `{`、`}`，区域也接受鼠标滚轮。必须提供已提取的Z6 C3.80 MAIN，长度33502842，SHA256见[固件说明](docs/firmware.md)，完整升级包不能直接输入。

本地基线已验证原厂LCD从1/8000变为1/6400、1/5000，反向可恢复。当前无镜头模拟选择S仍显示A，调快门先用M；其根因未完全闭合。菜单退出恢复连续取景请用“拍摄启动”，这会重建guest；同一服务保留模式/网格，快门档位不保留。副轮已接原厂输入，未验证无镜头时光圈变化。

这不是精确EXPEED或完整CMOS模型，不能代替真机曝光、保存、AF、编码或声音验收。[验证记录](docs/testing.md)、[架构](docs/architecture.md)、[构建说明](docs/build.md)、[操作](docs/usage.md)。

## 致谢

感谢 [WonderLantern Z7 QEMU](https://github.com/WonderLantern/z7-qemu) 的作者 [R3tr0ooo](https://github.com/R3tr0ooo) 及贡献者公开实验性尼康模拟器、图形处理流程和研究工具，为本项目的 Z6 移植提供了起点。我们保留共用代码的来源署名和许可证说明，并独立开发、核验 Z6 的机型配置与接口。

源码采用GPL-2.0-or-later，[完整许可证](COPYING)、[简要说明](NOTICE.md)、[贡献说明](CONTRIBUTING.md)。
