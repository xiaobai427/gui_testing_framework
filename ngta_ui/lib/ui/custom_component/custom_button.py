from PySide6.QtWidgets import QPushButton
import logging
import os
from abc import abstractmethod
from pathlib import Path

from PySide6.QtGui import QFont, QAction
from PySide6.QtWidgets import QLabel, QVBoxLayout, QWidget, QPushButton, QGroupBox, QHBoxLayout, \
    QCheckBox, QComboBox, QSpinBox, QMessageBox, QMenu, QDialog, QProgressBar, QSizePolicy, QGridLayout
from PySide6.QtCore import Qt, QSize, QObject, QEvent, QTimer, Signal, QThread, Slot

from PySide6QtAds import CDockManager, CDockWidget
from typing import Optional


class DraggableButton(QPushButton):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.setMouseTracking(True)
        self.drag_start_position = None
        self.drag_threshold = 5  # Minimum distance to consider a button move a drag
        self.dragging = False

        default_background_color = "rgba(0, 0, 0, 80%)"
        hover_background_color = "#5a5a5a"
        active_background_color = "#757575"
        font_color = "lightgray"
        padding_horizontal = "16px"
        padding_vertical = "12px"
        min_height = "30px"
        self.setStyleSheet(f"""
            DraggableButton {{
                background-color: {default_background_color};
                color: {font_color};
            }}
            DraggableButton:hover {{
                background-color: {hover_background_color};
            }}
            DraggableButton:pressed {{
                background-color: {active_background_color};
            }}
        """)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.drag_start_position = event.pos()
        super().mousePressEvent(event)  # Call the base class implementation

    def mouseMoveEvent(self, event):
        if event.buttons() == Qt.MouseButton.LeftButton and self.drag_start_position is not None:
            move_distance = (event.pos() - self.drag_start_position).manhattanLength()
            if move_distance > self.drag_threshold:
                self.dragging = True
                self.move(self.pos() + (event.pos() - self.drag_start_position))
        super().mouseMoveEvent(event)  # Call the base class implementation

    def mouseReleaseEvent(self, event):
        if self.dragging:
            self.dragging = False
        else:
            super().mouseReleaseEvent(event)  # Call the base class implementation only if the button is clicked
        self.drag_start_position = None


class ResizableButton(DraggableButton):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.resizing = False
        self.resize_margin = 2
        self.setMinimumSize(50, 30)
        self.resize_start_pos = None
        self.original_size = None
        self.original_pos = None

    def mousePressEvent(self, event):
        if self.cursor().shape() != Qt.CursorShape.ArrowCursor:
            self.resizing = True
            self.resize_start_pos = event.pos()
            self.original_size = self.size()
            self.original_pos = self.pos()
        else:
            super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if not self.resizing:
            self.update_cursor(event.pos())
            super().mouseMoveEvent(event)
        else:
            dx = event.pos().x() - self.resize_start_pos.x()
            dy = event.pos().y() - self.resize_start_pos.y()

            new_width = self.original_size.width() + dx
            new_height = self.original_size.height() + dy
            new_left = self.original_pos.x()
            new_top = self.original_pos.y()

            if self.cursor().shape() in (
                    Qt.CursorShape.SizeHorCursor, Qt.CursorShape.SizeFDiagCursor, Qt.CursorShape.SizeBDiagCursor):
                new_width = max(new_width, self.minimumWidth())

            if self.cursor().shape() in (
                    Qt.CursorShape.SizeVerCursor, Qt.CursorShape.SizeFDiagCursor, Qt.CursorShape.SizeBDiagCursor):
                new_height = max(new_height, self.minimumHeight())

            if self.cursor().shape() == Qt.CursorShape.SizeBDiagCursor or self.cursor().shape() == Qt.CursorShape.SizeHorCursor:
                if new_width != self.minimumWidth():
                    new_left = self.original_pos.x() + dx

            if self.cursor().shape() == Qt.CursorShape.SizeFDiagCursor or self.cursor().shape() == Qt.CursorShape.SizeVerCursor:
                if new_height != self.minimumHeight():
                    new_top = self.original_pos.y() + dy

            self.setGeometry(new_left, new_top, new_width, new_height)

    def mouseReleaseEvent(self, event):
        if self.resizing:
            self.resizing = False
        else:
            super().mouseReleaseEvent(event)

    def update_cursor(self, pos):
        near_right_border = self.width() - self.resize_margin <= pos.x() <= self.width()
        near_left_border = 0 <= pos.x() <= self.resize_margin
        near_bottom_border = self.height() - self.resize_margin <= pos.y() <= self.height()
        near_top_border = 0 <= pos.y() <= self.resize_margin

        if (near_right_border and near_bottom_border) or (near_left_border and near_top_border):
            self.setCursor(Qt.CursorShape.SizeFDiagCursor)
        elif (near_left_border and near_bottom_border) or (near_right_border and near_top_border):
            self.setCursor(Qt.CursorShape.SizeBDiagCursor)
        elif near_right_border or near_left_border:
            self.setCursor(Qt.CursorShape.SizeHorCursor)
        elif near_bottom_border or near_top_border:
            self.setCursor(Qt.CursorShape.SizeVerCursor)
        elif near_bottom_border and near_right_border:
            self.setCursor(Qt.CursorShape.SizeAllCursor)
        else:
            self.setCursor(Qt.CursorShape.ArrowCursor)
