"""PyInstaller 打包用的入口脚本，就是简单调一下 GUI 的 main()。

单独放一个文件而不是直接指向 src/temu_delisting_gui/main.py，是因为
PyInstaller 的 Analysis 入口脚本本身不能用包内的相对 import。
"""
from temu_delisting_gui.main import main

if __name__ == "__main__":
    main()
