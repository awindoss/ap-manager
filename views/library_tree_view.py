# ==============================================================================
# views/library_tree_view.py
# QTreeView subclass that implements the Phase 5 drag-and-drop interactions.
#
# Qt's built-in internal move would try to rewrite the model; this view instead
# translates a drop into one of two *graph* operations:
#   * drop on a node  -> "associate with this location" / "move to this location"
#     (the main window asks which one, plan.md §31.2);
#   * drop between siblings of the same parent -> reorder edges.sort_order.
#
# A completely custom drop indicator is painted because the model has no
# dropMimeData() (the database, not the view, owns relation semantics).
# ==============================================================================
from __future__ import annotations

import json
from dataclasses import dataclass
from typing import TYPE_CHECKING, Iterable, List, Optional, Sequence, Tuple

from PySide6.QtCore import QMimeData, QModelIndex, QPoint, Qt, Signal
from PySide6.QtGui import QColor, QDrag, QPainter, QPen
from PySide6.QtWidgets import QAbstractItemView, QTreeView, QWidget

from utils import constants
from utils.logger import log_debug

if TYPE_CHECKING:  # pragma: no cover - type checking only
    from controllers.app_controller import AppController
    from views.tree_model import DisplayPath, TreeModel


def encode_drag_payload(paths: Iterable[Sequence[int]]) -> bytes:
    """Serialise display paths into the custom drag MIME payload."""
    return json.dumps(
        {"paths": [list(int(part) for part in path) for path in paths]}
    ).encode("utf-8")


def decode_drag_payload(mime: Optional[QMimeData]) -> Tuple[DisplayPath, ...]:
    """Read display paths from drag MIME data; return () for foreign drags."""
    if mime is None or not mime.hasFormat(constants.NODE_DRAG_MIME_TYPE):
        return ()
    raw = bytes(mime.data(constants.NODE_DRAG_MIME_TYPE).data())
    if not raw:
        return ()
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        log_debug("Ignoring drag payload that is not valid JSON.")
        return ()
    paths = payload.get("paths") if isinstance(payload, dict) else None
    if not isinstance(paths, list):
        return ()

    decoded: List[DisplayPath] = []
    for raw_path in paths:
        if not isinstance(raw_path, list) or not raw_path:
            continue
        try:
            path = tuple(int(part) for part in raw_path)
        except (TypeError, ValueError):
            continue
        if path and path not in decoded:
            decoded.append(path)
    return tuple(decoded)


@dataclass(frozen=True)
class DropDecision:
    """What a drag at the current position would do, before the user chooses."""

    accepted: bool
    kind: str = "reject"  # "associate" | "reorder" | "reject"
    target_node_id: Optional[int] = None
    target_path: DisplayPath = ()
    before: bool = False
    sources: Tuple[DisplayPath, ...] = ()
    reason: str = ""

    @classmethod
    def rejected(cls, reason: str, sources: Sequence[Sequence[int]] = ()) -> "DropDecision":
        return cls(
            accepted=False,
            kind="reject",
            reason=reason,
            sources=tuple(tuple(int(part) for part in path) for path in sources),
        )


class LibraryTreeView(QTreeView):
    """
    Tree view with graph-aware drag and drop.

    Signals are emitted instead of mutating the database directly:
    ``associateDropped`` asks the window to prompt for attach/move, while
    ``reorderDropped`` carries an unambiguous sibling-order request.
    """

    associateDropped = Signal(object, int)       # list[(node_id, ...)], target id
    reorderDropped = Signal(object, object, bool)  # source path, target path, before
    dropRejected = Signal(str)

    def __init__(
        self,
        model: "TreeModel",
        controller: Optional["AppController"] = None,
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self._tree_model = model
        self._controller = controller
        self._drop_index = QModelIndex()
        self._drop_decision: Optional[DropDecision] = None
        self._last_rejection = ""

        self.setModel(model)
        self.setDragEnabled(True)
        self.setAcceptDrops(True)
        self.setDropIndicatorShown(False)
        self.setDragDropMode(QAbstractItemView.DragDropMode.DragDrop)
        self.setDefaultDropAction(Qt.DropAction.MoveAction)
        self.setDragDropOverwriteMode(False)

    # --------------------------------------------------------------------------
    # Drag source
    # --------------------------------------------------------------------------
    def startDrag(self, supported_actions) -> None:  # noqa: N802 - Qt naming
        paths = self.selected_display_paths()
        if not paths:
            return

        mime = QMimeData()
        mime.setData(constants.NODE_DRAG_MIME_TYPE, encode_drag_payload(paths))
        drag = QDrag(self)
        drag.setMimeData(mime)
        drag.exec(
            Qt.DropAction.CopyAction | Qt.DropAction.MoveAction,
            Qt.DropAction.MoveAction,
        )
        self._clear_drop_state()

    def selected_display_paths(self) -> List[DisplayPath]:
        """Display paths of the selected rows, in view order."""
        paths: List[DisplayPath] = []
        for index in self.selectedIndexes():
            if index.column() != 0 or not index.isValid():
                continue
            item = self._tree_model.item_from_index(index)
            if item is None:
                continue
            if item.display_path not in paths:
                paths.append(item.display_path)
        if not paths:
            item = self._tree_model.item_from_index(self.currentIndex())
            if item is not None:
                paths.append(item.display_path)
        return paths

    # --------------------------------------------------------------------------
    # Drag destination
    # --------------------------------------------------------------------------
    def dragEnterEvent(self, event) -> None:  # noqa: N802 - Qt naming
        if decode_drag_payload(event.mimeData()):
            event.acceptProposedAction()
        else:
            event.ignore()

    def dragMoveEvent(self, event) -> None:  # noqa: N802 - Qt naming
        sources = decode_drag_payload(event.mimeData())
        if not sources:
            event.ignore()
            return

        index = self.indexAt(event.position().toPoint())
        decision = self.evaluate_drop(sources, index, event.position().toPoint())
        self._set_drop_state(index, decision)
        if decision.accepted:
            self._last_rejection = ""
            event.setDropAction(Qt.DropAction.MoveAction)
            event.accept()
        else:
            # A rejected drag never receives dropEvent in Qt, so surface the
            # cycle/sorting reason *while hovering* (plan.md §7.2 / §31.2).
            if decision.reason and decision.reason != self._last_rejection:
                self._last_rejection = decision.reason
                self.dropRejected.emit(decision.reason)
            event.ignore()

    def dropEvent(self, event) -> None:  # noqa: N802 - Qt naming
        sources = decode_drag_payload(event.mimeData())
        index = self.indexAt(event.position().toPoint())
        decision = self.evaluate_drop(sources, index, event.position().toPoint())
        self._clear_drop_state()

        if not decision.accepted:
            if decision.reason:
                self.dropRejected.emit(decision.reason)
            event.ignore()
            return

        if decision.kind == "reorder":
            self.reorderDropped.emit(
                decision.sources[0], decision.target_path, decision.before
            )
        else:
            target_id = int(decision.target_node_id) if decision.target_node_id else 0
            self.associateDropped.emit(list(decision.sources), target_id)
        event.acceptProposedAction()

    def dragLeaveEvent(self, event) -> None:  # noqa: N802 - Qt naming
        self._clear_drop_state()
        super().dragLeaveEvent(event)

    # --------------------------------------------------------------------------
    # Drop semantics (pure logic, unit-testable without a real QDropEvent)
    # --------------------------------------------------------------------------
    def evaluate_drop(
        self,
        sources: Sequence[Sequence[int]],
        index: QModelIndex,
        position: Optional[QPoint] = None,
        zone: Optional[str] = None,
    ) -> DropDecision:
        """
        Decide what dropping ``sources`` on ``index`` means.

        ``zone`` may be "before"/"after"/"on"; when omitted it is derived from
        ``position`` (top 30% => before, bottom 30% => after, else on).
        """
        normalized = self._normalize_sources(sources)
        if not normalized:
            return DropDecision.rejected("没有可拖动的节点。")

        model = self._tree_model
        item = model.item_from_index(index) if index.isValid() else None
        if item is None:
            return DropDecision.rejected(
                "请把节点拖到目标节点上（拖到空白处不会创建位置）。", normalized
            )

        target_path: DisplayPath = item.display_path
        target_id = item.node_id
        zone = zone or self._drop_zone(index, position)
        target_name = item.name

        if zone in ("before", "after"):
            return self._evaluate_reorder(normalized, target_path, target_name, zone)

        if any(path[-1] == target_id for path in normalized):
            return DropDecision.rejected("不能把节点关联到它自己。", normalized)

        for path in normalized:
            source_id = path[-1]
            if self._controller is not None and self._controller.would_create_cycle(
                target_id, source_id
            ):
                source = self._controller.get_node(source_id)
                source_name = source.name if source is not None else f"#{source_id}"
                return DropDecision.rejected(
                    f"不能关联：把「{source_name}」放到「{target_name}」下面会形成循环引用。",
                    normalized,
                )

        return DropDecision(
            accepted=True,
            kind="associate",
            target_node_id=target_id,
            target_path=target_path,
            sources=normalized,
        )

    def _evaluate_reorder(
        self,
        sources: Tuple[DisplayPath, ...],
        target_path: DisplayPath,
        target_name: str,
        zone: str,
    ) -> DropDecision:
        if len(sources) != 1:
            return DropDecision.rejected(
                "排序一次只能拖动一个节点；多选拖动请放到目标节点上建立关联。",
                sources,
            )
        source_path = sources[0]
        if source_path[-1] == target_path[-1]:
            return DropDecision.rejected("节点已经在这个位置。", sources)
        if len(source_path) < 2 or len(target_path) < 2:
            return DropDecision.rejected(
                "顶层节点不支持拖拽排序；请放到目标节点上建立关联。", sources
            )
        if source_path[:-1] != target_path[:-1]:
            return DropDecision.rejected(
                f"只能在同一个父级下调整顺序；要关联到「{target_name}」所在的分组，"
                "请拖到该分组的节点上。",
                sources,
            )
        return DropDecision(
            accepted=True,
            kind="reorder",
            target_node_id=target_path[-1],
            target_path=target_path,
            before=(zone == "before"),
            sources=sources,
        )

    @staticmethod
    def _normalize_sources(
        sources: Sequence[Sequence[int]],
    ) -> Tuple[DisplayPath, ...]:
        normalized: List[DisplayPath] = []
        for raw_path in sources or ():
            try:
                path = tuple(int(part) for part in raw_path)
            except (TypeError, ValueError):
                continue
            if path and path not in normalized:
                normalized.append(path)
        return tuple(normalized)

    def _drop_zone(self, index: QModelIndex, position: Optional[QPoint]) -> str:
        if position is None:
            return "on"
        rect = self.visualRect(index)
        if not rect.isValid() or rect.height() <= 0:
            return "on"
        ratio = (position.y() - rect.top()) / float(rect.height())
        if ratio < 0.30:
            return "before"
        if ratio > 0.70:
            return "after"
        return "on"

    # --------------------------------------------------------------------------
    # Drop feedback painting
    # --------------------------------------------------------------------------
    def _set_drop_state(
        self, index: QModelIndex, decision: Optional[DropDecision]
    ) -> None:
        self._drop_index = index
        self._drop_decision = decision
        self.viewport().update()

    def _clear_drop_state(self) -> None:
        if self._drop_decision is None and not self._drop_index.isValid():
            return
        self._drop_decision = None
        self._drop_index = QModelIndex()
        self._last_rejection = ""
        self.viewport().update()

    def paintEvent(self, event) -> None:  # noqa: N802 - Qt naming
        super().paintEvent(event)
        decision = self._drop_decision
        if (
            decision is None
            or not decision.accepted
            or not self._drop_index.isValid()
        ):
            return

        rect = self.visualRect(self._drop_index)
        if not rect.isValid():
            return

        highlight = QColor(self.palette().highlight().color())
        painter = QPainter(self.viewport())
        try:
            if decision.kind == "reorder":
                highlight.setAlpha(constants.DRAG_HIGHLIGHT_ALPHA + 100)
                y = rect.top() if decision.before else rect.bottom()
                painter.fillRect(
                    rect.left(),
                    y - constants.DRAG_REORDER_LINE_HEIGHT // 2,
                    rect.width(),
                    constants.DRAG_REORDER_LINE_HEIGHT,
                    highlight,
                )
            else:
                highlight.setAlpha(constants.DRAG_HIGHLIGHT_ALPHA)
                painter.setBrush(highlight)
                pen = QPen(self.palette().highlight().color())
                pen.setWidth(2)
                painter.setPen(pen)
                painter.drawRoundedRect(rect.adjusted(1, 1, -1, -1), 3, 3)
        finally:
            painter.end()


# ==============================================================================
# End of library_tree_view.py
# ==============================================================================
