from abc import abstractmethod
from typing import Optional

from PySide6.QtCore import QObject
from PySide6.QtWidgets import QSizePolicy, QMainWindow, QMenuBar, QStatusBar
from PySide6QtAds import CDockManager, CDockWidget

from ngta_ui.lib.ui.base import BaseDataObservatory


class DockManagerFactory:
    @staticmethod
    def createConfiguredDockManager(parent):
        DockManagerFactory.applyDefaultConfig()
        common_bg_color = "#2d2d2d"
        common_fg_color = "white"
        highlight_color = "purple"
        dock_manager = CDockManager(parent)
        dock_manager.setStyleSheet(f"""
            /* Common styles */
            QWidget {{ background-color: {common_bg_color}; color: {common_fg_color}; }} 

            /* Title Bar */
            ads--CDockAreaTitleBar {{ background-color: rgba(0, 0, 0, 80%); color: {common_fg_color}; }}
            ads--CDockAreaTitleBar QLabel,
            ads--CDockAreaTitleBar QPushButton,
            ads--CDockAreaTitleBar > #tabsMenuButton,
            ads--CDockAreaTitleBar > #detachGroupButton,
            ads--CDockAreaTitleBar > #dockAreaAutoHideButton,
            ads--CDockAreaTitleBar > #dockAreaCloseButton {{
                background-color: {highlight_color}; color: {common_fg_color};
            }}
            /* Highlight buttons when focused */
            ads--CDockAreaWidget[focused=true] ads--CDockAreaTitleBar > #tabsMenuButton,
            ads--CDockAreaWidget[focused=true] ads--CDockAreaTitleBar > #detachGroupButton,
            ads--CDockAreaWidget[focused=true] ads--CDockAreaTitleBar > #dockAreaAutoHideButton,
            ads--CDockAreaWidget[focused=true] ads--CDockAreaTitleBar > #dockAreaCloseButton {{
                background-color: palette(highlight); 
                color: {common_fg_color};
            }}

            /* Focused Tab */
            ads--CDockWidgetTab[focused=true] {{
                background: palette(highlight);
                border-color: palette(highlight);
            }}

            ads--CDockWidgetTabc> #tabCloseButton {{
                qproperty-icon: url(:/ads/images/close-button-focused.svg);
                background-color: rgba(255, 255, 255, 48);
            }}
            ads--CDockWidgetTab[focused=true] > #tabCloseButton:hover {{ background: {highlight_color}; }}
            ads--CDockWidgetTab[focused=true] > #tabCloseButton:pressed {{ background: rgba(255, 255, 255, 92); }}

            /* Focused Tab Label */
            ads--CDockWidgetTab[focused=true] QLabel {{
                color: palette(light);
                background-color: rgba(255, 255, 255, 92);
            }}
            ads--CDockWidgetTab[focused=true] QLabel:hover {{ background-color: {highlight_color}; }}

            /* Focused Dock Area */
            ads--CDockAreaWidget[focused=true] ads--CDockAreaTitleBar {{
                background: rgba(0, 0, 0, 80%);
                border-bottom: 10px solid palette(highlight);
                padding-bottom: 0px;
                padding-top: 5px;
                color: palette(light);
            }}
        """)
        return dock_manager

    @staticmethod
    def applyDefaultConfig():
        CDockManager.setAutoHideConfigFlag(CDockManager.AutoHideFeatureEnabled)
        CDockManager.setConfigFlag(CDockManager.FocusHighlighting, True)
        CDockManager.setAutoHideConfigFlag(CDockManager.DefaultAutoHideConfig)
        CDockManager.setAutoHideConfigFlag(CDockManager.AutoHideShowOnMouseOver, True)
        CDockManager.setAutoHideConfigFlag(CDockManager.DockAreaHasAutoHideButton)
        CDockManager.setAutoHideConfigFlag(CDockManager.AutoHideButtonTogglesArea)
        CDockManager.setAutoHideConfigFlag(CDockManager.AutoHideSideBarsIconOnly)
        CDockManager.setConfigFlag(CDockManager.EqualSplitOnInsertion)  # Setting the EqualSplitOnInsertion flag


# class BaseDockWidget(CDockWidget, QObject):
#     def __init__(self, title, dock_manager, enable_focus_events=False):
#         super(BaseDockWidget, self).__init__(title)
#         self.dock_manager = dock_manager
#         self.content_widget = CustomWidget()
#         self.setWidget(self.content_widget)
#         self.installEventFilter(self)
#         if enable_focus_events:
#             self.content_widget.setFocusPolicy(Qt.StrongFocus)
#
#     def eventFilter(self, obj, event):
#         if event.type() == QEvent.ContextMenu and obj is self:
#             dock_area = self.dock_manager.dockArea(self)
#             if dock_area:
#                 self.showContextMenu(dock_area, event.globalPos())
#             return True
#         return QObject.eventFilter(self, obj, event)
#
#     def showContextMenu(self, dock_area, position):
#         contextMenu = QMenu()
#         for dock_widget in dock_area.dockWidgets():
#             action = QAction(dock_widget.windowTitle(), self)
#             action.triggered.connect(lambda _, widget=dock_widget: widget.setAsCurrentTab())
#             contextMenu.addAction(action)
#         contextMenu.exec(position)

class CustomMainWindow(QMainWindow):
    def __init__(self, content_widget=None, menu_bar=None, status_bar=None, parent=None):
        super(CustomMainWindow, self).__init__(parent)

        # Set the central widget
        if content_widget:
            self.setCentralWidget(content_widget)

        # Set up the menu bar
        if menu_bar:
            self.setMenuBar(menu_bar)

        # Set up the status bar
        if status_bar:
            self.setStatusBar(status_bar)

    def setup_additional_logic(self):
        # Additional logic can go here.
        pass


class BaseDockWidget(CDockWidget, QObject):
    def __init__(self, title, dock_manager, enable_focus_events=False):
        super(BaseDockWidget, self).__init__(title)
        self.observer = BaseDataObservatory()
        self.dock_manager = dock_manager
        self.factory = self.get_factory()
        # Create the content widget, menu bar, and status bar using the factory
        self.content_widget = self.factory.create_content_widget()
        menu_bar = self.factory.create_menu_bar()
        status_bar = self.factory.create_status_bar()

        # Create and configure the custom QMainWindow
        self.main_window = CustomMainWindow(
            content_widget=self.content_widget,
            menu_bar=menu_bar,
            status_bar=status_bar
        )
        self.main_window.setup_additional_logic()

        # Set QMainWindow as the widget for the dock
        self.content_widget.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.main_window.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.setWidget(self.main_window)

    @staticmethod
    def get_factory():
        return BaseDockWidgetFactory()


class BaseDockWidgetFactory:
    @abstractmethod
    def create_content_widget(self):
        pass

    @abstractmethod
    def create_menu_bar(self) -> Optional[QMenuBar]:
        return None  # By default, do not create a menu bar

    @abstractmethod
    def create_status_bar(self) -> Optional[QStatusBar]:
        return None  # By default, do not create a status bar
