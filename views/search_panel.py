# ==============================================================================
# views/search_panel.py
# Search result sidebar (Phase 7).
#
# One row per matching node; its children are every root-to-node position the
# node currently has (multi-parent libraries therefore show all locations,
# plan.md §28). A single click on a location asks the main window to reveal that
# exact display instance; a click on the node row reveals its first instance.
# ==============================================================================
from typing import Optional, Sequence, Tuple

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QAbstractItemView,
    QHeaderView,
    QLabel,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from services.search import SearchHit, SearchResult
from utils import constants
from utils.icon_utils import load_icon


class SearchResultsView(QTreeWidget):
    """Two-column tree: node/position breadcrumb and match source."""

    # Payload of a display instance, as the node-id path accepted by MainWindow.
    locationActivated = Signal(object)
    nodeActivated = Signal(int)

    LocationPathRole = int(Qt.ItemDataRole.UserRole) + 1
    NodeIdRole = int(Qt.ItemDataRole.UserRole) + 2

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setObjectName("searchResults")
        self.setColumnCount(2)
        self.setHeaderHidden(True)
        self.setRootIsDecorated(True)
        self.setAlternatingRowColors(True)
        self.setUniformRowHeights(True)
        self.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.header().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.header().setSectionResizeMode(1, QHeaderView.ResizeMode.Fixed)
        self.header().resizeSection(1, 96)
        self.setColumnWidth(1, 96)
        self.itemClicked.connect(self.activate_item)
        self.itemActivated.connect(self.activate_item)
        self._result: Optional[SearchResult] = None

    # --------------------------------------------------------------------------
    # Presentation
    # --------------------------------------------------------------------------
    def set_result(self, result: SearchResult) -> None:
        """Rebuild the tree from a search result."""
        self.clear()
        self._result = result

        for hit in result.hits:
            top = QTreeWidgetItem([hit.name, hit.match_label])
            top.setData(0, self.NodeIdRole, hit.node_id)
            top.setToolTip(0, self._hit_tooltip(hit))
            top.setToolTip(1, hit.match_label)
            if hit.icon:
                icon = load_icon(hit.icon, constants.TREE_ICON_SIZE)
                if not icon.isNull():
                    top.setIcon(0, icon)

            for location in hit.locations:
                child = QTreeWidgetItem([location.label, ""])
                child.setData(0, self.NodeIdRole, hit.node_id)
                child.setData(0, self.LocationPathRole, list(location.path))
                child.setToolTip(0, f"点击定位到此位置：\n{location.label}")
                top.addChild(child)

            if not hit.locations:
                child = QTreeWidgetItem([constants.SEARCH_NO_LOCATION_TEXT, ""])
                child.setDisabled(True)
                child.setToolTip(
                    0,
                    "该节点不在任何根节点下（通常表示数据中存在循环引用）。",
                )
                top.addChild(child)

            self.addTopLevelItem(top)
            # Spanning is applied once the item is inside the view: adding a
            # detached top-level item resets the span flag of its children.
            for child_index in range(top.childCount()):
                top.child(child_index).setFirstColumnSpanned(True)
            # Positions are the actionable part of the result; show them.
            top.setExpanded(True)

        if not result.hits:
            empty = QTreeWidgetItem(["没有找到匹配的节点。", ""])
            empty.setDisabled(True)
            self.addTopLevelItem(empty)

        if self.topLevelItemCount():
            self.setCurrentItem(self.topLevelItem(0))

    def clear_result(self) -> None:
        self.clear()
        self._result = None

    def result(self) -> Optional[SearchResult]:
        return self._result

    # --------------------------------------------------------------------------
    # Activation
    # --------------------------------------------------------------------------
    def activate_item(self, item: Optional[QTreeWidgetItem], column: int = 0) -> None:
        """Emit the node/location request carried by ``item``."""
        if item is None:
            return
        path = item.data(0, self.LocationPathRole)
        if path:
            try:
                display_path: Tuple[int, ...] = tuple(int(part) for part in path)
            except (TypeError, ValueError):
                return
            self.locationActivated.emit(display_path)
            return

        node_id = item.data(0, self.NodeIdRole)
        if isinstance(node_id, int):
            self.nodeActivated.emit(node_id)

    def activate_first_location(self) -> bool:
        """Convenience for keyboard/automation: activate the first real path."""
        for row in range(self.topLevelItemCount()):
            top = self.topLevelItem(row)
            for child_index in range(top.childCount()):
                child = top.child(child_index)
                if child.data(0, self.LocationPathRole):
                    self.activate_item(child, 0)
                    return True
        return False

    # --------------------------------------------------------------------------
    # Internals
    # --------------------------------------------------------------------------
    @staticmethod
    def _hit_tooltip(hit: SearchHit) -> str:
        lines = [hit.name, f"匹配：{hit.match_label}", f"位置：{len(hit.locations)} 个"]
        if hit.matched_pdf_paths:
            lines.append("匹配的 PDF：")
            for path in hit.matched_pdf_paths[:5]:
                lines.append(f"  {path}")
            if len(hit.matched_pdf_paths) > 5:
                lines.append("  …")
        return "\n".join(lines)


class SearchResultsPanel(QWidget):
    """Header text + result tree, ready to be placed in a dock or a dialog."""

    locationActivated = Signal(object)
    nodeActivated = Signal(int)

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 4, 0, 0)
        layout.setSpacing(4)

        self.header_label = QLabel("输入关键词搜索节点名称或 PDF 文件名。", self)
        self.header_label.setObjectName("searchHeader")
        self.header_label.setWordWrap(True)
        layout.addWidget(self.header_label)

        self.results = SearchResultsView(self)
        self.results.locationActivated.connect(self._forward_location)
        self.results.nodeActivated.connect(self._forward_node)
        layout.addWidget(self.results, 1)

    # --------------------------------------------------------------------------
    # Presentation
    # --------------------------------------------------------------------------
    def show_result(
        self,
        result: SearchResult,
        *,
        elapsed_ms: Optional[int] = None,
    ) -> None:
        self.results.set_result(result)
        if not result.query:
            self.header_label.setText("输入关键词搜索节点名称或 PDF 文件名。")
            return
        if not result.hits:
            self.header_label.setText(f"没有找到与「{result.query}」匹配的节点。")
            return

        text = f"找到 {result.hit_count} 个节点，共 {result.location_count} 个位置。"
        if result.truncated:
            text += f" 结果较多，只显示前 {result.limit} 个节点。"
        if elapsed_ms is not None:
            text += f" 用时 {max(0, int(elapsed_ms))} ms。"
        self.header_label.setText(text)

    def show_message(self, text: str) -> None:
        self.header_label.setText(text)
        self.results.clear_result()

    def clear(self) -> None:
        self.show_message("输入关键词搜索节点名称或 PDF 文件名。")

    def focus_results(self) -> None:
        self.results.setFocus()

    @property
    def result(self) -> Optional[SearchResult]:
        return self.results.result()

    def activate_first_location(self) -> bool:
        return self.results.activate_first_location()

    # --------------------------------------------------------------------------
    # Signal relay
    # --------------------------------------------------------------------------
    def _forward_location(self, path: Sequence[int]) -> None:
        self.locationActivated.emit(tuple(path))

    def _forward_node(self, node_id: int) -> None:
        self.nodeActivated.emit(int(node_id))


# ==============================================================================
# End of search_panel.py
# ==============================================================================
