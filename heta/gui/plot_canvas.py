# -*- coding: utf-8 -*-
"""
matplotlib 嵌入 PySide6 的包裝器
"""

from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg, NavigationToolbar2QT
from matplotlib.figure import Figure
from PySide6.QtWidgets import QVBoxLayout, QWidget


class PlotCanvas(FigureCanvasQTAgg):
    """可嵌入 PySide6 的 matplotlib 畫布"""

    def __init__(self, parent=None, width=8, height=6, dpi=100):
        self.fig = Figure(figsize=(width, height), dpi=dpi, facecolor='white')
        super().__init__(self.fig)
        self.setParent(parent)

    def update_figure(self, new_figure):
        """用新的 Figure 物件取代目前的圖表"""
        # 清除舊的 axes
        self.fig.clear()

        # 從新 Figure 複製所有 axes 的內容
        if new_figure is not None:
            for src_ax in new_figure.axes:
                # 建立對應的 subplot
                dest_ax = self.fig.add_subplot(111)
                # 直接用新 figure 取代
                break  # 只處理第一個 axes

            # 更好的方式：直接替換整個 figure
            self.fig = new_figure
            self.figure = new_figure
            new_figure.set_canvas(self)

        self.draw()


class PlotWidget(QWidget):
    """包含 PlotCanvas 和導覽工具列的完整繪圖元件"""

    def __init__(self, parent=None, width=8, height=6, dpi=100):
        super().__init__(parent)
        self.canvas = PlotCanvas(self, width, height, dpi)
        self.toolbar = NavigationToolbar2QT(self.canvas, self)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.toolbar)
        layout.addWidget(self.canvas)

    def update_figure(self, new_figure):
        """更新圖表並重新連結工具列"""
        if new_figure is not None:
            self.canvas.fig = new_figure
            self.canvas.figure = new_figure
            new_figure.set_canvas(self.canvas)
            self.canvas.draw()
            # 重建工具列
            layout = self.layout()
            layout.removeWidget(self.toolbar)
            self.toolbar.deleteLater()
            self.toolbar = NavigationToolbar2QT(self.canvas, self)
            layout.insertWidget(0, self.toolbar)
