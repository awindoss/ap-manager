# ==============================================================================
# views/main_window.py
# Main application window: hosts the QTreeView that displays the library.
#
# Phase 3 adds node creation/editing, the visual delegate and a context menu.
# The window never writes to the database directly: every mutation goes through
# AppController -> LibraryService (plan.md §27).
# ==============================================================================
import sqlite3
from typing import List, Optional, Sequence

from PySide6.QtCore import QModelIndex, QPoint, Qt
from PySide6.QtGui import QAction, QCloseEvent, QKeySequence
from PySide6.QtWidgets import (
    QAbstractItemView,
    QDialog,
    QLabel,
    QMainWindow,
    QMenu,
    QMessageBox,
    QTreeView,
)

from controllers.app_controller import AppController
from services.pdf_launcher import LaunchReport, PdfLaunchError
from utils.constants import (
    APP_NAME,
    APP_VERSION,
    DEFAULT_WINDOW_HEIGHT,
    DEFAULT_WINDOW_WIDTH,
)
from utils.logger import log_error, log_info
from views.delegates.tree_delegate import TreeDelegate
from views.dialogs.add_node_dialog import AddNodeDialog
from views.dialogs.missing_files_dialog import MissingFilesDialog
from views.dialogs.node_properties_dialog import NodePropertiesDialog
from views.dialogs.pdf_management_dialog import PdfManagementDialog
from views.dialogs.pdf_selector_dialog import PdfSelectorDialog
from views.dialogs.settings_dialog import SettingsDialog
from views.tree_model import DisplayPath, TreeItem, TreeModel


class MainWindow(QMainWindow):
    """
    The single window of the application.

    The window owns the `TreeModel`; the `AppController` owns the business
    layer, so the view never touches SQL directly.
    """

    def __init__(
        self,
        controller: Optional[AppController] = None,
        parent: Optional[QMainWindow] = None,
    ) -> None:
        super().__init__(parent)
        self.controller: AppController = controller or AppController()
        self.model = TreeModel(self.controller.library, self)
        self.tree_delegate = TreeDelegate(self)

        self._selection_actions: List[QAction] = []

        self._build_ui()
        self._build_menus()
        self.refresh()

    # --------------------------------------------------------------------------
    # Construction
    # --------------------------------------------------------------------------
    def _build_ui(self) -> None:
        self.setWindowTitle(f"{APP_NAME} v{APP_VERSION}")
        # Window geometry is persisted from Phase 7 on (config.json -> ui.*).
        self.resize(DEFAULT_WINDOW_WIDTH, DEFAULT_WINDOW_HEIGHT)

        self.tree_view = QTreeView(self)
        self.tree_view.setModel(self.model)
        self.tree_view.setItemDelegate(self.tree_delegate)
        self.tree_view.setHeaderHidden(True)
        self.tree_view.setUniformRowHeights(True)
        self.tree_view.setAlternatingRowColors(True)
        self.tree_view.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.tree_view.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        # Double-click is handled explicitly below: an expandable node toggles,
        # a childless node with PDFs opens them (one directly, several through
        # the selector).
        self.tree_view.setExpandsOnDoubleClick(False)
        self.tree_view.doubleClicked.connect(self._on_double_clicked)
        self.tree_view.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.tree_view.customContextMenuRequested.connect(self._show_context_menu)

        selection_model = self.tree_view.selectionModel()
        if selection_model is not None:
            selection_model.currentChanged.connect(self._on_current_changed)

        self.setCentralWidget(self.tree_view)

        self._status_label = QLabel("", self)
        self.statusBar().addPermanentWidget(self._status_label)

    def _build_menus(self) -> None:
        file_menu = self.menuBar().addMenu("文件(&F)")

        new_root_action = QAction("新建根节点(&N)…", self)
        new_root_action.setShortcut(QKeySequence("Ctrl+N"))
        new_root_action.setStatusTip("在顶层创建新的图书馆节点")
        new_root_action.triggered.connect(self._create_root_node)
        file_menu.addAction(new_root_action)

        self._new_child_action = QAction("新建子节点(&C)…", self)
        self._new_child_action.setShortcut(QKeySequence("Ctrl+Shift+N"))
        self._new_child_action.setStatusTip("在当前选中的节点下创建子节点")
        self._new_child_action.triggered.connect(self._create_child_from_selection)
        file_menu.addAction(self._new_child_action)

        file_menu.addSeparator()

        quit_action = QAction("退出(&Q)", self)
        quit_action.setShortcut(QKeySequence.StandardKey.Quit)
        quit_action.triggered.connect(self.close)
        file_menu.addAction(quit_action)

        edit_menu = self.menuBar().addMenu("编辑(&E)")

        self._edit_action = QAction("编辑属性(&P)…", self)
        self._edit_action.setShortcut(QKeySequence("F2"))
        self._edit_action.setStatusTip("编辑选中节点的名称、图标与文字样式")
        self._edit_action.triggered.connect(self._edit_selected)
        edit_menu.addAction(self._edit_action)

        self._style_action = QAction("设置样式(&S)…", self)
        self._style_action.setStatusTip("打开节点属性对话框并定位到样式设置")
        self._style_action.triggered.connect(self._style_selected)
        edit_menu.addAction(self._style_action)

        edit_menu.addSeparator()

        self._manage_pdf_action = QAction("管理 PDF(&D)…", self)
        self._manage_pdf_action.setShortcut(QKeySequence("Ctrl+Shift+P"))
        self._manage_pdf_action.setStatusTip("添加、移除、重新定位或打开该节点的 PDF")
        self._manage_pdf_action.triggered.connect(self._manage_pdfs_for_selection)
        edit_menu.addAction(self._manage_pdf_action)

        self._open_pdf_action = QAction("打开 PDF(&O)", self)
        self._open_pdf_action.setShortcut(QKeySequence("Ctrl+O"))
        self._open_pdf_action.setStatusTip("打开选中节点的 PDF（多个时弹出选择框）")
        self._open_pdf_action.triggered.connect(self._open_pdf_for_selection)
        edit_menu.addAction(self._open_pdf_action)

        self._open_all_pdf_action = QAction("打开全部 PDF(&A)", self)
        self._open_all_pdf_action.setStatusTip("逐个打开选中节点的全部 PDF")
        self._open_all_pdf_action.triggered.connect(self._open_all_pdfs_for_selection)
        edit_menu.addAction(self._open_all_pdf_action)

        self._selection_actions = [
            self._new_child_action,
            self._edit_action,
            self._style_action,
            self._manage_pdf_action,
        ]

        view_menu = self.menuBar().addMenu("查看(&V)")

        refresh_action = QAction("刷新(&R)", self)
        refresh_action.setShortcut(QKeySequence("F5"))
        refresh_action.triggered.connect(self.refresh)
        view_menu.addAction(refresh_action)

        view_menu.addSeparator()

        expand_action = QAction("展开全部(&E)", self)
        expand_action.triggered.connect(self.tree_view.expandAll)
        view_menu.addAction(expand_action)

        collapse_action = QAction("折叠全部(&C)", self)
        collapse_action.triggered.connect(self.tree_view.collapseAll)
        view_menu.addAction(collapse_action)

        tools_menu = self.menuBar().addMenu("工具(&T)")

        self._inspect_action = QAction("文件检查(&C)…", self)
        self._inspect_action.setStatusTip("检查整个书库中的缺失 PDF")
        self._inspect_action.triggered.connect(self._inspect_pdfs)
        tools_menu.addAction(self._inspect_action)

        self._relink_missing_action = QAction("重新定位缺失 PDF(&L)…", self)
        self._relink_missing_action.setStatusTip("列出所有找不到的 PDF 并逐个重新定位")
        self._relink_missing_action.triggered.connect(self._relink_missing_pdfs)
        tools_menu.addAction(self._relink_missing_action)

        settings_menu = self.menuBar().addMenu("设置(&S)")

        self._pdf_reader_action = QAction("PDF 阅读器(&R)…", self)
        self._pdf_reader_action.setStatusTip("指定打开 PDF 的外部阅读器，或使用系统默认")
        self._pdf_reader_action.triggered.connect(self._open_settings)
        settings_menu.addAction(self._pdf_reader_action)

        self._update_action_states()

    # --------------------------------------------------------------------------
    # Model synchronisation
    # --------------------------------------------------------------------------
    def refresh(self) -> None:
        """
        Rebuild the whole tree from the database.

        A full rebuild is still the consistency mechanism (Phase 2), but the
        expanded display paths and the selected instance are captured first and
        restored afterwards, so editing one node no longer collapses the tree
        (Phase 3 P0-1 in _mds/phase3_feasibility.md).
        """
        expanded_paths = self._collect_expanded_paths()
        selected_paths = self._collect_selected_paths()

        self.model.refresh()
        self._restore_view_state(expanded_paths, selected_paths)

        self._update_status()
        self._update_action_states()
        log_info(
            f"Library view refreshed: {self.model.root_count} root(s), "
            f"{self.model.displayed_item_count} display item(s), "
            f"{len(expanded_paths)} expanded path(s) restored."
        )

    def _collect_expanded_paths(self) -> List[DisplayPath]:
        """Every expanded display instance, identified by its node-id path."""
        paths: List[DisplayPath] = []

        def visit(index: QModelIndex) -> None:
            item = self.model.item_from_index(index)
            if item is None:
                return
            if self.tree_view.isExpanded(index):
                paths.append(item.display_path)
            for row in range(self.model.rowCount(index)):
                visit(self.model.index(row, 0, index))

        for row in range(self.model.rowCount(QModelIndex())):
            visit(self.model.index(row, 0, QModelIndex()))
        return paths

    def _collect_selected_paths(self) -> List[DisplayPath]:
        """Selected display instances (column 0), identified by node-id path."""
        selection_model = self.tree_view.selectionModel()
        if selection_model is None:
            return []

        paths: List[DisplayPath] = []
        for index in selection_model.selectedIndexes():
            if index.column() != 0:
                continue
            item = self.model.item_from_index(index)
            if item is not None:
                paths.append(item.display_path)
        return paths

    def _restore_view_state(
        self,
        expanded_paths: Sequence[DisplayPath],
        selected_paths: Sequence[DisplayPath],
    ) -> None:
        for path in sorted(set(expanded_paths), key=len):
            index = self.model.find_index_by_display_path(path)
            if index.isValid() and not self.tree_view.isExpanded(index):
                self.tree_view.expand(index)

        if not selected_paths:
            return
        # A collapsed branch must stay collapsed: both setCurrentIndex() and
        # scrollTo() can make Qt reveal (expand) the selected item's ancestors.
        # A selection that is no longer visible is therefore not restored.
        if not self._is_path_visible(selected_paths[0]):
            return

        index = self.model.find_index_by_display_path(selected_paths[0])
        if index.isValid():
            self.tree_view.setCurrentIndex(index)
            self.tree_view.scrollTo(index)

    def _is_path_visible(self, path: DisplayPath) -> bool:
        """True when all ancestors of ``path`` are currently expanded."""
        for depth in range(1, len(path)):
            ancestor = self.model.find_index_by_display_path(path[:depth])
            if not ancestor.isValid() or not self.tree_view.isExpanded(ancestor):
                return False
        return True

    def _update_status(self) -> None:
        parts = [
            f"节点 {self.model.displayed_node_count}",
            f"显示实例 {self.model.displayed_item_count}",
            f"根节点 {self.model.root_count}",
        ]
        if self.model.unreachable_node_ids:
            parts.append(f"不可达 {len(self.model.unreachable_node_ids)}")
        if self.model.cycle_warnings:
            parts.append(f"循环告警 {len(self.model.cycle_warnings)}")
        if self.model.missing_pdf_node_ids:
            parts.append(f"缺失 PDF {len(self.model.missing_pdf_node_ids)}")
        if self.model.is_truncated:
            parts.append("结果已截断")
        self._status_label.setText(" | ".join(parts))

    # --------------------------------------------------------------------------
    # Selection / reveal helpers
    # --------------------------------------------------------------------------
    def _selected_node_id(self) -> Optional[int]:
        index = self.tree_view.currentIndex()
        if not index.isValid():
            return None
        return self.model.node_id_from_index(index)

    def _on_current_changed(self, _current: QModelIndex, _previous: QModelIndex) -> None:
        self._update_action_states()

    def _update_action_states(self) -> None:
        item = self.model.item_from_index(self.tree_view.currentIndex())
        has_selection = item is not None
        for action in self._selection_actions:
            action.setEnabled(has_selection)

        pdf_count = (
            len(item.node.pdf_paths)
            if item is not None and item.node is not None
            else 0
        )
        self._open_pdf_action.setEnabled(has_selection and pdf_count > 0)
        self._open_all_pdf_action.setEnabled(has_selection and pdf_count > 1)

    def _reveal_node(self, node_id: int) -> None:
        """Expand to and select the first display instance of ``node_id``."""
        instances = self.model.find_items_by_node_id(node_id)
        if not instances:
            return

        path = instances[0].display_path
        for depth in range(1, len(path) + 1):
            ancestor = self.model.find_index_by_display_path(path[:depth])
            if ancestor.isValid():
                self.tree_view.expand(ancestor)

        index = self.model.find_index_by_display_path(path)
        if index.isValid():
            self.tree_view.setCurrentIndex(index)
            self.tree_view.scrollTo(
                index, QAbstractItemView.ScrollHint.PositionAtCenter
            )
            self.tree_view.setFocus()

    # --------------------------------------------------------------------------
    # Node creation / editing
    # --------------------------------------------------------------------------
    def _create_root_node(self) -> None:
        self._open_add_node_dialog(None)

    def _create_child_from_selection(self) -> None:
        parent_id = self._selected_node_id()
        if parent_id is None:
            self.statusBar().showMessage("请先选择一个父节点。", 3000)
            return
        self._create_child_node(parent_id)

    def _create_child_node(self, parent_id: int) -> None:
        self._open_add_node_dialog(parent_id)

    def _open_add_node_dialog(self, parent_id: Optional[int]) -> None:
        parent_node = self.controller.get_node(parent_id) if parent_id is not None else None
        if parent_id is not None and parent_node is None:
            QMessageBox.warning(self, "无法新建节点", "父节点不存在，请刷新后重试。")
            self.refresh()
            return

        dialog = AddNodeDialog(parent_node.name if parent_node is not None else "", self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return

        values = dialog.node_values()
        try:
            new_id = self.controller.create_node(
                values["name"],
                parent_id=parent_id,
                icon=values["icon"],
                style_bold=values["style_bold"],
                style_color=values["style_color"],
            )
        except (ValueError, sqlite3.Error) as error:
            log_error(f"Could not create node: {error}")
            QMessageBox.critical(self, "无法创建节点", str(error))
            return

        if new_id is None:
            return

        self.refresh()
        self._reveal_node(new_id)
        self.statusBar().showMessage(f"已创建节点「{values['name']}」。", 4000)

    def _edit_selected(self) -> None:
        node_id = self._selected_node_id()
        if node_id is None:
            self.statusBar().showMessage("请先选择一个节点。", 3000)
            return
        self._edit_node(node_id)

    def _style_selected(self) -> None:
        node_id = self._selected_node_id()
        if node_id is None:
            self.statusBar().showMessage("请先选择一个节点。", 3000)
            return
        self._edit_node(node_id, focus_style=True)

    def _edit_node(self, node_id: int, focus_style: bool = False) -> None:
        node = self.controller.get_node(node_id)
        if node is None:
            QMessageBox.warning(self, "无法编辑节点", "节点不存在，请刷新后重试。")
            self.refresh()
            return

        dialog = NodePropertiesDialog(node, self)
        if focus_style:
            dialog.focus_style()
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return

        changes = dialog.changes()
        if not changes:
            return

        try:
            self.controller.update_node(node_id, **changes)
        except (ValueError, sqlite3.Error) as error:
            log_error(f"Could not update node {node_id}: {error}")
            QMessageBox.critical(self, "无法保存节点", str(error))
            return

        # In-place update: no model reset, so expansion and selection survive.
        if not self.model.notify_node_changed(node_id):
            self.refresh()

        self._update_status()
        updated = self.controller.get_node(node_id)
        if updated is not None:
            self.statusBar().showMessage(f"已更新节点「{updated.name}」。", 4000)

    # --------------------------------------------------------------------------
    # PDF management (Phase 4)
    # --------------------------------------------------------------------------
    def _manage_pdfs_for_selection(self) -> None:
        node_id = self._selected_node_id()
        if node_id is None:
            self.statusBar().showMessage("请先选择一个节点。", 3000)
            return
        self._manage_pdfs(node_id)

    def _open_pdf_for_selection(self) -> None:
        node_id = self._selected_node_id()
        if node_id is None:
            self.statusBar().showMessage("请先选择一个节点。", 3000)
            return
        self._open_pdf_for_node(node_id)

    def _open_all_pdfs_for_selection(self) -> None:
        node_id = self._selected_node_id()
        if node_id is None:
            self.statusBar().showMessage("请先选择一个节点。", 3000)
            return
        self._open_all_pdfs(node_id)

    def _manage_pdfs(self, node_id: int, select_path: Optional[str] = None) -> None:
        """Open the PDF manager for ``node_id`` and refresh the tree afterwards."""
        try:
            dialog = PdfManagementDialog(
                self.controller,
                node_id,
                self,
                select_path=select_path,
            )
        except ValueError as error:
            log_error(f"Could not open the PDF manager for node {node_id}: {error}")
            QMessageBox.warning(self, "无法管理 PDF", str(error))
            self.refresh()
            return

        dialog.exec()
        self._after_node_change(node_id)

    def _after_node_change(self, node_id: int) -> None:
        """Repaint one node in place; fall back to a full refresh if needed."""
        if not self.model.notify_node_changed(node_id):
            self.refresh()
            return
        self._update_status()
        self._update_action_states()

    def _open_pdf_for_node(self, node_id: int) -> None:
        """
        Open a node's PDF.

        One file opens directly; several files go through the selector dialog
        (plan.md §19.1). If every file is missing, offer re-location instead of
        silently doing nothing.
        """
        node = self.controller.get_node(node_id)
        if node is None:
            QMessageBox.warning(self, "无法打开 PDF", "节点不存在，请刷新后重试。")
            self.refresh()
            return

        pdf_files = self.controller.describe_pdfs(node_id)
        if not pdf_files:
            self.statusBar().showMessage(f"「{node.name}」没有关联 PDF。", 4000)
            return

        if not any(pdf_file.exists for pdf_file in pdf_files):
            self._offer_relink(node_id, pdf_files)
            return

        if len(pdf_files) == 1:
            self._launch_pdf(pdf_files[0].stored_path)
            return

        dialog = PdfSelectorDialog(node.name, pdf_files, self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        selected = dialog.selected_pdf()
        if selected is not None:
            self._launch_pdf(selected.stored_path)

    def _launch_pdf(self, stored_path: str) -> None:
        try:
            self.controller.open_pdf(stored_path)
        except PdfLaunchError as error:
            log_error(f"Could not open PDF {stored_path!r}: {error}")
            QMessageBox.critical(self, "无法打开 PDF", str(error))
            return
        self.statusBar().showMessage(f"已打开 PDF：{stored_path}", 4000)

    def _open_all_pdfs(self, node_id: int) -> None:
        try:
            report = self.controller.open_node_pdfs(node_id)
        except ValueError as error:
            QMessageBox.warning(self, "无法打开 PDF", str(error))
            return
        self._report_launch(report)

    def _report_launch(self, report: LaunchReport) -> None:
        if report.failures:
            details = "\n".join(
                f"• {path}\n  {message}" for path, message in report.failures[:5]
            )
            if len(report.failures) > 5:
                details += "\n…"
            prefix = (
                f"已打开 {report.opened_count} 个 PDF，"
                if report.opened_count
                else ""
            )
            QMessageBox.warning(
                self,
                "部分 PDF 未能打开",
                f"{prefix}{report.failure_count} 个 PDF 无法打开：\n\n{details}",
            )
        if report.opened:
            self.statusBar().showMessage(
                f"已打开 {report.opened_count} 个 PDF。", 4000
            )
        elif not report.failures:
            self.statusBar().showMessage("没有可打开的 PDF。", 4000)

    def _offer_relink(self, node_id: int, pdf_files: Sequence) -> None:
        preview = "\n".join(
            f"• {pdf_file.stored_path}" for pdf_file in list(pdf_files)[:5]
        )
        if len(pdf_files) > 5:
            preview += "\n…"
        answer = QMessageBox.question(
            self,
            "PDF 文件缺失",
            f"以下 PDF 文件无法找到：\n\n{preview}\n\n"
            "是否打开 PDF 管理以重新定位？",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.Yes,
        )
        if answer == QMessageBox.StandardButton.Yes:
            first = next(iter(pdf_files), None)
            self._manage_pdfs(
                node_id,
                select_path=first.stored_path if first is not None else None,
            )

    # --------------------------------------------------------------------------
    # File checks / settings
    # --------------------------------------------------------------------------
    def _inspect_pdfs(self) -> None:
        inspection = self.controller.inspect_pdfs()
        summary = (
            f"共检查 {inspection.total_pdfs} 个 PDF "
            f"（分布在 {inspection.nodes_with_pdfs} 个节点中），"
            f"缺失 {len(inspection.missing)} 个。"
        )

        if inspection.missing:
            answer = QMessageBox.question(
                self,
                "文件检查",
                f"{summary}\n\n是否查看并重新定位缺失的文件？",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.Yes,
            )
            if answer == QMessageBox.StandardButton.Yes:
                self._relink_missing_pdfs()
            return

        QMessageBox.information(
            self,
            "文件检查",
            f"{summary}\n\n全部 PDF 文件均可访问。",
        )

    def _relink_missing_pdfs(self) -> None:
        dialog = MissingFilesDialog(
            self.controller,
            self,
            reveal_callback=self._reveal_and_manage,
        )
        dialog.exec()
        if dialog.changed:
            self.refresh()
        else:
            self._update_status()

    def _reveal_and_manage(self, node_id: int, stored_path: Optional[str] = None) -> None:
        self._reveal_node(node_id)
        self._manage_pdfs(node_id, select_path=stored_path)

    def _open_settings(self) -> None:
        dialog = SettingsDialog(self.controller.get_pdf_reader_path(), self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return

        try:
            reader_path = self.controller.set_pdf_reader_path(dialog.reader_path())
        except (ValueError, OSError) as error:
            log_error(f"Could not save the PDF reader setting: {error}")
            QMessageBox.critical(self, "无法保存设置", str(error))
            return

        label = reader_path or "系统默认阅读器"
        self.statusBar().showMessage(f"PDF 阅读器：{label}", 5000)

    # --------------------------------------------------------------------------
    # Context menu
    # --------------------------------------------------------------------------
    def _show_context_menu(self, position: QPoint) -> None:
        index = self.tree_view.indexAt(position)
        if index.isValid():
            # Standard desktop behaviour: right-clicking a row selects it, so the
            # menu actions and the highlighted row refer to the same node.
            self.tree_view.setCurrentIndex(index)
        menu = self.build_context_menu(index)
        menu.exec(self.tree_view.viewport().mapToGlobal(position))

    def build_context_menu(self, index: QModelIndex) -> QMenu:
        """Build the node/blank-area context menu (separate for testability)."""
        menu = QMenu(self)
        node_id = self.model.node_id_from_index(index) if index.isValid() else None

        if node_id is None:
            root_action = menu.addAction("新建根节点…")
            root_action.setData(None)
            root_action.triggered.connect(self._create_root_node)
            menu.addSeparator()
            refresh_action = menu.addAction("刷新")
            refresh_action.triggered.connect(self.refresh)
            return menu

        child_action = menu.addAction("新建子节点…")
        child_action.setData(node_id)
        child_action.triggered.connect(lambda: self._create_child_node(node_id))
        menu.addSeparator()

        edit_action = menu.addAction("编辑属性…")
        edit_action.setData(node_id)
        edit_action.triggered.connect(lambda: self._edit_node(node_id))
        style_action = menu.addAction("设置样式…")
        style_action.setData(node_id)
        style_action.triggered.connect(lambda: self._edit_node(node_id, True))
        menu.addSeparator()

        item = self.model.item_from_index(index)
        pdf_count = (
            len(item.node.pdf_paths)
            if item is not None and item.node is not None
            else 0
        )

        manage_action = menu.addAction("管理 PDF…")
        manage_action.setData(node_id)
        manage_action.triggered.connect(lambda: self._manage_pdfs(node_id))

        open_action = menu.addAction("打开 PDF")
        open_action.setData(node_id)
        open_action.setEnabled(pdf_count > 0)
        open_action.triggered.connect(lambda: self._open_pdf_for_node(node_id))

        open_all_action = menu.addAction("打开全部 PDF")
        open_all_action.setData(node_id)
        open_all_action.setEnabled(pdf_count > 1)
        open_all_action.triggered.connect(lambda: self._open_all_pdfs(node_id))

        missing_paths = self.model.missing_pdf_paths(node_id)
        relink_action = menu.addAction("重新定位缺失 PDF…")
        relink_action.setData(node_id)
        relink_action.setEnabled(bool(missing_paths))
        relink_action.triggered.connect(
            lambda: self._manage_pdfs(
                node_id,
                select_path=missing_paths[0] if missing_paths else None,
            )
        )
        menu.addSeparator()

        expand_action = menu.addAction("展开")
        expand_action.triggered.connect(lambda: self.tree_view.expand(index))
        collapse_action = menu.addAction("折叠")
        collapse_action.triggered.connect(lambda: self.tree_view.collapse(index))
        return menu

    # --------------------------------------------------------------------------
    # Interaction
    # --------------------------------------------------------------------------
    def _on_double_clicked(self, index: QModelIndex) -> None:
        """
        Handle double-click: expand/collapse for parent nodes, PDF opening for
        childless nodes that carry PDFs (plan.md section 19.1).
        """
        item: Optional[TreeItem] = self.model.item_from_index(index)
        if item is None or item.node is None:
            return

        # "Has children" is decided on the projected tree, not on the database,
        # because a cycle could have been skipped while building.
        if not item.children and item.node.pdf_paths:
            self._open_pdf_for_node(item.node_id)
            return

        self._toggle_expanded(index)

    def _toggle_expanded(self, index: QModelIndex) -> None:
        if self.tree_view.isExpanded(index):
            self.tree_view.collapse(index)
        else:
            self.tree_view.expand(index)

    # --------------------------------------------------------------------------
    # Qt events
    # --------------------------------------------------------------------------
    def closeEvent(self, event: QCloseEvent) -> None:  # noqa: N802 - Qt naming
        self.controller.shutdown()
        super().closeEvent(event)


# ==============================================================================
# End of main_window.py
# ==============================================================================
