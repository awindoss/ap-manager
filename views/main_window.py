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
from PySide6.QtGui import QAction, QCloseEvent, QCursor, QKeySequence
from PySide6.QtWidgets import (
    QAbstractItemView,
    QDialog,
    QLabel,
    QMainWindow,
    QMenu,
    QMessageBox,
)

from controllers.app_controller import AppController, AttachResult, MoveOutcome
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
from views.dialogs.choose_parent_dialog import ChooseParentDialog
from views.dialogs.missing_files_dialog import MissingFilesDialog
from views.dialogs.node_positions_dialog import NodePositionsDialog
from views.dialogs.node_properties_dialog import NodePropertiesDialog
from views.dialogs.pdf_management_dialog import PdfManagementDialog
from views.dialogs.pdf_selector_dialog import PdfSelectorDialog
from views.dialogs.settings_dialog import SettingsDialog
from views.library_tree_view import LibraryTreeView
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

        self.tree_view = LibraryTreeView(self.model, self.controller, self)
        self.tree_view.setItemDelegate(self.tree_delegate)
        self.tree_view.setHeaderHidden(True)
        self.tree_view.setUniformRowHeights(True)
        self.tree_view.setAlternatingRowColors(True)
        # Extended selection enables dragging several nodes at once (plan.md
        # §31.2); all single-node actions keep using the current index.
        self.tree_view.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.tree_view.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        # Double-click is handled explicitly below: an expandable node toggles,
        # a childless node with PDFs opens them (one directly, several through
        # the selector).
        self.tree_view.setExpandsOnDoubleClick(False)
        self.tree_view.doubleClicked.connect(self._on_double_clicked)
        self.tree_view.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.tree_view.customContextMenuRequested.connect(self._show_context_menu)
        # Phase 5 drag and drop: drops produce relation/sorting signals, the
        # database is only written by the handlers below.
        self.tree_view.associateDropped.connect(self._on_nodes_dropped)
        self.tree_view.reorderDropped.connect(self._on_reorder_dropped)
        self.tree_view.dropRejected.connect(self._on_drop_rejected)

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

        self._attach_action = QAction("关联到其他位置(&L)…", self)
        self._attach_action.setShortcut(QKeySequence("Ctrl+Shift+A"))
        self._attach_action.setStatusTip("把节点额外关联到其他父级位置")
        self._attach_action.triggered.connect(self._attach_for_selection)
        edit_menu.addAction(self._attach_action)

        self._move_action = QAction("移动到其他位置(&M)…", self)
        self._move_action.setShortcut(QKeySequence("Ctrl+Shift+M"))
        self._move_action.setStatusTip("从当前父级移除该位置，并放到另一个父级下")
        self._move_action.triggered.connect(self._move_for_selection)
        edit_menu.addAction(self._move_action)

        self._positions_action = QAction("查看所有位置(&P)…", self)
        self._positions_action.setShortcut(QKeySequence("Ctrl+Shift+L"))
        self._positions_action.setStatusTip("列出节点的全部位置并跳转到选中位置")
        self._positions_action.triggered.connect(self._show_positions_for_selection)
        edit_menu.addAction(self._positions_action)

        edit_menu.addSeparator()

        self._detach_action = QAction("从当前父级移除(&R)", self)
        self._detach_action.setShortcut(QKeySequence("Ctrl+Shift+D"))
        self._detach_action.setStatusTip("只删除当前位置，不删除节点本身")
        self._detach_action.triggered.connect(self._detach_for_selection)
        edit_menu.addAction(self._detach_action)

        self._delete_action = QAction("彻底删除节点(&X)…", self)
        self._delete_action.setShortcut(QKeySequence("Ctrl+Delete"))
        self._delete_action.setStatusTip("删除节点及其全部位置（磁盘 PDF 不受影响）")
        self._delete_action.triggered.connect(self._delete_for_selection)
        edit_menu.addAction(self._delete_action)

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
            self._attach_action,
            self._move_action,
            self._positions_action,
            self._detach_action,
            self._delete_action,
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

        has_parent = item is not None and item.parent_item is not None
        # A root has no position to remove/move from; associating it with a new
        # parent is still meaningful.
        self._detach_action.setEnabled(has_selection and has_parent)
        self._move_action.setEnabled(has_selection and has_parent)

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
        self._reveal_display_path(instances[0].display_path)

    def _reveal_display_path(self, display_path: Sequence[int]) -> bool:
        """
        Expand every ancestor and select one exact display instance.

        Sorting and moving keep the node-id path unchanged, so restoring by
        path is stable; if the instance disappeared (for example the selected
        position was detached) the method reports it instead of selecting an
        arbitrary duplicate.
        """
        path = tuple(int(part) for part in display_path)
        if not path:
            return False

        for depth in range(1, len(path) + 1):
            ancestor = self.model.find_index_by_display_path(path[:depth])
            if not ancestor.isValid():
                self.statusBar().showMessage(
                    "该位置已不存在，请刷新后重试。", 4000
                )
                return False
            self.tree_view.expand(ancestor)

        index = self.model.find_index_by_display_path(path)
        if not index.isValid():
            self.statusBar().showMessage("该位置已不存在，请刷新后重试。", 4000)
            return False

        self.tree_view.setCurrentIndex(index)
        self.tree_view.scrollTo(
            index, QAbstractItemView.ScrollHint.PositionAtCenter
        )
        self.tree_view.setFocus()
        return True

    def _reveal_node_under_parent(self, node_id: int, parent_id: int) -> bool:
        """Reveal the instance of ``node_id`` whose direct parent is ``parent_id``."""
        for instance in self.model.find_items_by_node_id(node_id):
            path = instance.display_path
            if len(path) > 1 and path[-2] == parent_id:
                if self._reveal_display_path(path):
                    return True
        self._reveal_node(node_id)
        return True

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
    # Multi-parent relations (Phase 5)
    # --------------------------------------------------------------------------
    def _current_item(self) -> Optional[TreeItem]:
        return self.model.item_from_index(self.tree_view.currentIndex())

    def _node_name(self, node_id: int) -> str:
        node = self.controller.get_node(node_id)
        return node.name if node is not None else f"#{node_id}"

    # --- view all positions ---------------------------------------------------
    def _show_positions_for_selection(self) -> None:
        item = self._current_item()
        if item is None:
            self.statusBar().showMessage("请先选择一个节点。", 3000)
            return
        self._show_positions(item.node_id, item.display_path)

    def _show_positions(
        self,
        node_id: int,
        current_path: Optional[Sequence[int]] = None,
    ) -> None:
        node = self.controller.get_node(node_id)
        if node is None:
            QMessageBox.warning(self, "无法查看位置", "节点不存在，请刷新后重试。")
            self.refresh()
            return

        try:
            positions = self.controller.get_node_positions(node_id)
        except ValueError as error:
            QMessageBox.warning(self, "无法查看位置", str(error))
            return

        dialog = NodePositionsDialog(
            node.name,
            positions,
            self,
            current_path=tuple(current_path) if current_path else None,
        )
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        selected = dialog.selected_path()
        if selected:
            self._reveal_display_path(selected)
            self.statusBar().showMessage(
                f"已定位「{node.name}」的一个位置。", 4000
            )

    # --- attach to other locations -------------------------------------------
    def _attach_for_selection(self) -> None:
        item = self._current_item()
        if item is None:
            self.statusBar().showMessage("请先选择一个节点。", 3000)
            return
        self._attach_node(item.node_id)

    def _attach_node(self, node_id: int) -> None:
        node = self.controller.get_node(node_id)
        if node is None:
            QMessageBox.warning(self, "无法关联", "节点不存在，请刷新后重试。")
            self.refresh()
            return

        excluded = set(self.controller.get_parent_ids(node_id))
        dialog = ChooseParentDialog(
            self.controller,
            node_id,
            self,
            excluded_parent_ids=excluded,
            mode="attach",
        )
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        targets = dialog.selected_parent_ids()
        if targets:
            self._attach_node_to_parents(node_id, targets)

    def _attach_node_to_parents(self, node_id: int, parent_ids: Sequence[int]) -> None:
        try:
            result = self.controller.attach_node_to_parents(node_id, list(parent_ids))
        except (ValueError, sqlite3.Error) as error:
            log_error(f"Could not attach node {node_id}: {error}")
            QMessageBox.warning(self, "无法关联", str(error))
            return
        self._apply_attach_result(result)

    def _attach_nodes_to_parent(self, node_ids: Sequence[int], parent_id: int) -> None:
        try:
            result = self.controller.attach_nodes_to_parent(list(node_ids), parent_id)
        except (ValueError, sqlite3.Error) as error:
            log_error(f"Could not attach nodes to parent {parent_id}: {error}")
            QMessageBox.warning(self, "无法关联", str(error))
            return
        self._apply_attach_result(result)

    def _apply_attach_result(self, result: AttachResult) -> None:
        """Refresh once, reveal the first new position, report all rejections."""
        if result.has_changes:
            self.refresh()

        if result.attached:
            parent_id, child_id = result.attached[0]
            if result.has_changes:
                self._reveal_node_under_parent(child_id, parent_id)
            message = f"已关联 {len(result.attached)} 个新位置。"
            if result.already:
                message += f" 跳过 {len(result.already)} 个已存在的位置。"
            self.statusBar().showMessage(message, 5000)
        elif result.already:
            self.statusBar().showMessage(
                f"所选位置已经包含该节点（{len(result.already)} 个），无需重复关联。",
                5000,
            )
        elif not result.errors:
            self.statusBar().showMessage("没有可关联的新位置。", 4000)

        if result.errors:
            lines = []
            for (parent_id, child_id), message in result.errors[:5]:
                lines.append(
                    f"• {self._node_name(child_id)} → {self._node_name(parent_id)}\n"
                    f"  {message}"
                )
            if len(result.errors) > 5:
                lines.append("…")
            QMessageBox.warning(
                self,
                "部分位置未能关联",
                f"{len(result.errors)} 个位置未能关联：\n\n" + "\n\n".join(lines),
            )

    # --- move to another location --------------------------------------------
    def _move_for_selection(self) -> None:
        item = self._current_item()
        if item is None:
            self.statusBar().showMessage("请先选择一个节点。", 3000)
            return
        if item.parent_item is None:
            self.statusBar().showMessage(
                "根节点没有原位置；请使用「关联到其他位置」。", 4000
            )
            return
        self._move_node_from_path(item.display_path)

    def _move_node_from_path(
        self,
        source_path: Sequence[int],
        target_parent_id: Optional[int] = None,
    ) -> None:
        path = tuple(int(part) for part in source_path)
        if not path:
            return
        node_id = path[-1]
        old_parent_id = path[-2] if len(path) > 1 else None
        node = self.controller.get_node(node_id)
        if node is None:
            QMessageBox.warning(self, "无法移动", "节点不存在，请刷新后重试。")
            self.refresh()
            return

        if old_parent_id is None and target_parent_id is None:
            self._attach_node(node_id)
            return

        if target_parent_id is None:
            excluded = {old_parent_id} if old_parent_id is not None else set()
            dialog = ChooseParentDialog(
                self.controller,
                node_id,
                self,
                excluded_parent_ids=excluded,
                mode="move",
            )
            if dialog.exec() != QDialog.DialogCode.Accepted:
                return
            targets = dialog.selected_parent_ids()
            if not targets:
                return
            target_parent_id = targets[0]

        target_parent_id = int(target_parent_id)
        old_name = self._node_name(old_parent_id) if old_parent_id is not None else ""
        new_name = self._node_name(target_parent_id)

        try:
            outcome: MoveOutcome = self.controller.move_node(
                old_parent_id, node_id, target_parent_id
            )
        except (ValueError, sqlite3.Error) as error:
            log_error(f"Could not move node {node_id}: {error}")
            QMessageBox.warning(self, "无法移动", str(error))
            return

        self.refresh()
        self._reveal_node_under_parent(node_id, target_parent_id)

        if outcome.kind == "moved":
            message = f"已将「{node.name}」从「{old_name}」移动到「{new_name}」。"
        elif outcome.kind == "merged":
            message = (
                f"「{new_name}」已经包含「{node.name}」，已移除原位置「{old_name}」。"
            )
        elif outcome.kind == "attached":
            message = f"已将根节点「{node.name}」关联到「{new_name}」。"
        elif outcome.kind == "already":
            message = f"「{new_name}」已经包含「{node.name}」。"
        else:
            message = "位置没有变化。"
        self.statusBar().showMessage(message, 5000)

    # --- remove from current parent ------------------------------------------
    def _detach_for_selection(self) -> None:
        item = self._current_item()
        if item is None:
            self.statusBar().showMessage("请先选择一个节点。", 3000)
            return
        if item.parent_item is None:
            self.statusBar().showMessage("根节点没有父级位置，无法移除。", 4000)
            return
        self._detach_item(item)

    def _confirm_detach(self, node_id: int, parent_id: int) -> bool:
        node_name = self._node_name(node_id)
        parent_name = self._node_name(parent_id)
        other_positions = max(
            0, len(self.controller.get_parent_ids(node_id)) - 1
        )
        text = (
            f"确定从「{parent_name}」中移除「{node_name}」吗？\n\n"
            "只删除这个位置，不会删除节点本身。"
        )
        if other_positions:
            text += f"\n该节点还保留在另外 {other_positions} 个位置。"
        else:
            text += (
                "\n该节点没有其他位置，移除后会成为根节点并显示在顶层。"
            )
        text += "\n磁盘上的 PDF 文件不会被删除。"
        answer = QMessageBox.question(
            self,
            "从当前父级移除",
            text,
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.Yes,
        )
        return answer == QMessageBox.StandardButton.Yes

    def _detach_item(self, item: TreeItem) -> None:
        if item.parent_item is None:
            self.statusBar().showMessage("根节点没有父级位置，无法移除。", 4000)
            return
        parent_id = item.parent_item.node_id
        node_id = item.node_id
        if not self._confirm_detach(node_id, parent_id):
            return

        try:
            removed = self.controller.detach_node(parent_id, node_id)
        except (ValueError, sqlite3.Error) as error:
            log_error(f"Could not detach node {node_id} from {parent_id}: {error}")
            QMessageBox.warning(self, "无法移除位置", str(error))
            return

        if not removed:
            self.statusBar().showMessage("该位置已不存在，请刷新后重试。", 4000)
            self.refresh()
            return

        self.refresh()
        self._reveal_node(node_id)
        self.statusBar().showMessage(
            f"已从「{self._node_name(parent_id)}」中移除「{self._node_name(node_id)}」。",
            5000,
        )

    # --- delete completely ----------------------------------------------------
    def _delete_for_selection(self) -> None:
        item = self._current_item()
        if item is None:
            self.statusBar().showMessage("请先选择一个节点。", 3000)
            return
        self._delete_node(item.node_id)

    def _confirm_delete_node(self, node_id: int) -> bool:
        node = self.controller.get_node(node_id)
        if node is None:
            return False
        parents = self.controller.get_node_parents(node_id)
        child_count = len(self.controller.get_node_children(node_id))

        lines = [f"确定要彻底删除节点「{node.name}」吗？", ""]
        if parents:
            lines.append(
                f"该节点当前被 {len(parents)} 个位置引用，"
                "彻底删除后所有位置中的该节点都会消失："
            )
            for parent in parents[:5]:
                lines.append(f"• {parent.name} > {node.name}")
            if len(parents) > 5:
                lines.append("…")
        else:
            lines.append("该节点位于顶层（没有父级），彻底删除后会从书库中消失。")
        if child_count:
            lines.append(
                f"该节点还有 {child_count} 个子节点；子节点本身不会被删除，"
                "但会失去这个父级位置。"
            )
        lines.extend(["", "磁盘上的 PDF 文件不会被删除。", "此操作不可撤销。"])

        answer = QMessageBox.question(
            self,
            "彻底删除节点",
            "\n".join(lines),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        return answer == QMessageBox.StandardButton.Yes

    def _delete_node(self, node_id: int) -> None:
        node = self.controller.get_node(node_id)
        if node is None:
            QMessageBox.warning(self, "无法删除", "节点不存在，请刷新后重试。")
            self.refresh()
            return
        if not self._confirm_delete_node(node_id):
            return

        try:
            self.controller.delete_node_completely(node_id)
        except (ValueError, sqlite3.Error) as error:
            log_error(f"Could not delete node {node_id}: {error}")
            QMessageBox.warning(self, "无法删除节点", str(error))
            return

        self.refresh()
        self.statusBar().showMessage(f"已彻底删除节点「{node.name}」。", 5000)

    # --- drag and drop --------------------------------------------------------
    def _on_drop_rejected(self, reason: str) -> None:
        self.statusBar().showMessage(reason, 6000)

    def _on_nodes_dropped(
        self,
        source_paths,
        target_node_id: int,
    ) -> None:
        paths = [
            tuple(int(part) for part in path)
            for path in source_paths or ()
            if path
        ]
        if not paths:
            return
        target = self.controller.get_node(int(target_node_id))
        if target is None:
            self.statusBar().showMessage("目标节点不存在，请刷新后重试。", 5000)
            return

        action = self._prompt_drop_action(paths, target)
        if action == "attach":
            node_ids: List[int] = []
            for path in paths:
                if path[-1] not in node_ids:
                    node_ids.append(path[-1])
            self._attach_nodes_to_parent(node_ids, target.id)
        elif action == "move":
            if len(paths) != 1:
                self.statusBar().showMessage(
                    "一次只能移动一个位置；多选拖动请选择「关联到此位置」。", 5000
                )
                return
            self._move_node_from_path(paths[0], target.id)

    def _prompt_drop_action(self, source_paths, target) -> Optional[str]:
        """
        Ask whether the drop creates an additional position or moves one.

        ``plan.md §31.2`` requires the two operations to stay visibly distinct:
        associating adds an edge, moving also deletes the source edge.
        """
        menu = QMenu(self.tree_view)

        if len(source_paths) == 1:
            source_name = self._node_name(source_paths[0][-1])
            menu.setTitle(f"{source_name} → {target.name}")
        else:
            menu.setTitle(f"{len(source_paths)} 个节点 → {target.name}")

        attach_action = menu.addAction("关联到此位置")
        attach_action.setStatusTip("新增一个父级位置，原位置保留")

        move_action = menu.addAction("移动到此位置")
        move_action.setStatusTip("删除原位置，再放到这个父级下")
        move_action.setEnabled(len(source_paths) == 1 and len(source_paths[0]) > 1)

        menu.addSeparator()
        cancel_action = menu.addAction("取消")

        chosen = menu.exec(QCursor.pos())
        if chosen is attach_action:
            return "attach"
        if chosen is move_action:
            return "move"
        if chosen is cancel_action:
            return None
        return None

    def _on_reorder_dropped(
        self,
        source_path,
        target_path,
        before: bool,
    ) -> None:
        source = tuple(int(part) for part in source_path)
        target = tuple(int(part) for part in target_path)
        if len(source) < 2 or len(target) < 2:
            return
        if source[:-1] != target[:-1]:
            self.statusBar().showMessage(
                "只能在同一个父级下调整顺序。", 5000
            )
            return

        parent_id = source[-2]
        try:
            changed = self.controller.reorder_relative(
                parent_id, source[-1], target[-1], before=before
            )
        except (ValueError, sqlite3.Error) as error:
            log_error(f"Could not reorder nodes below {parent_id}: {error}")
            QMessageBox.warning(self, "无法调整顺序", str(error))
            return

        self.refresh()
        self._reveal_display_path(source)
        self.statusBar().showMessage(
            "已调整节点顺序。" if changed else "顺序没有变化。", 4000
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

        item = self.model.item_from_index(index)
        display_path = item.display_path if item is not None else (node_id,)
        has_parent = item is not None and item.parent_item is not None

        child_action = menu.addAction("新建子节点…")
        child_action.setData(node_id)
        child_action.triggered.connect(lambda: self._create_child_node(node_id))
        menu.addSeparator()

        attach_action = menu.addAction("关联到其他位置…")
        attach_action.setData(node_id)
        attach_action.triggered.connect(lambda: self._attach_node(node_id))

        move_action = menu.addAction("移动到其他位置…")
        move_action.setData(node_id)
        move_action.setEnabled(has_parent)
        move_action.triggered.connect(
            lambda: self._move_node_from_path(display_path)
        )

        positions_action = menu.addAction("查看所有位置…")
        positions_action.setData(node_id)
        positions_action.triggered.connect(
            lambda: self._show_positions(node_id, display_path)
        )
        menu.addSeparator()

        edit_action = menu.addAction("编辑属性…")
        edit_action.setData(node_id)
        edit_action.triggered.connect(lambda: self._edit_node(node_id))
        style_action = menu.addAction("设置样式…")
        style_action.setData(node_id)
        style_action.triggered.connect(lambda: self._edit_node(node_id, True))
        menu.addSeparator()

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

        detach_action = menu.addAction("从当前父级移除")
        detach_action.setData(node_id)
        detach_action.setEnabled(has_parent)
        detach_action.triggered.connect(lambda: self._detach_item(item))

        delete_action = menu.addAction("彻底删除节点…")
        delete_action.setData(node_id)
        delete_action.triggered.connect(lambda: self._delete_node(node_id))
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
