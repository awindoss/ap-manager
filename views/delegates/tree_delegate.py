# ==============================================================================
# views/delegates/tree_delegate.py
# Paints the multi-parent badge on top of the standard item rendering.
#
# Phase 3 deliberately keeps the default QStyledItemDelegate painting (icon,
# bold font, colour, selection, alternating rows) and only adds a small "×N"
# marker on the right edge. Icon / font / colour come from the model roles, so
# this delegate has a very small surface and cannot regress text eliding.
# ==============================================================================
from PySide6.QtCore import QModelIndex, QRect, Qt
from PySide6.QtGui import QColor, QFont, QFontMetricsF, QIcon, QPainter, QPalette
from PySide6.QtWidgets import QApplication, QStyle, QStyleOptionViewItem, QStyledItemDelegate

from views.tree_model import TreeModel

# Gap between the badge and the right/top edge of the item rectangle.
BADGE_MARGIN = 4


class TreeDelegate(QStyledItemDelegate):
    """
    Standard item painting plus the "×N" multi-parent badge.

    A node with more than one parent is displayed once per path (plan.md §10);
    the badge tells the user that this row is not the only place the node lives.
    """

    def paint(self, painter: QPainter, option: QStyleOptionViewItem, index: QModelIndex) -> None:
        parent_count = index.data(TreeModel.ParentCountRole)
        if (
            index.column() != 0
            or not isinstance(parent_count, int)
            or parent_count <= 1
        ):
            super().paint(painter, option, index)
            return

        badge_text = f"×{parent_count}"

        # Initialise a copy so we can query the effective font/palette/state.
        opt = QStyleOptionViewItem(option)
        self.initStyleOption(opt, index)

        badge_font = self._badge_font(opt.font)
        badge_width = int(QFontMetricsF(badge_font).horizontalAdvance(badge_text)) + 2 * BADGE_MARGIN

        # Paint the background over the whole row first: the content below is
        # drawn into a narrower rectangle so a long name elides before reaching
        # the badge, and the reserved strip keeps the row colour.
        background_opt = QStyleOptionViewItem(opt)
        background_opt.text = ""
        background_opt.icon = QIcon()
        style = option.widget.style() if option.widget is not None else QApplication.style()
        style.drawControl(
            QStyle.ControlElement.CE_ItemViewItem,
            background_opt,
            painter,
            option.widget,
        )

        content_width = max(0, opt.rect.width() - badge_width)
        content_opt = QStyleOptionViewItem(opt)
        content_opt.rect = QRect(opt.rect.x(), opt.rect.y(), content_width, opt.rect.height())
        super().paint(painter, content_opt, index)

        painter.save()
        try:
            painter.setFont(badge_font)
            if opt.state & QStyle.StateFlag.State_Selected:
                painter.setPen(opt.palette.color(QPalette.ColorRole.HighlightedText))
            else:
                color = QColor(opt.palette.color(QPalette.ColorRole.Text))
                color.setAlpha(150)
                painter.setPen(color)

            badge_rect = QRect(
                opt.rect.right() - badge_width + BADGE_MARGIN,
                opt.rect.y(),
                max(0, badge_width - BADGE_MARGIN),
                opt.rect.height(),
            )
            painter.drawText(
                badge_rect,
                int(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight),
                badge_text,
            )
        finally:
            painter.restore()

    def sizeHint(self, option: QStyleOptionViewItem, index: QModelIndex):  # type: ignore[override]
        size = super().sizeHint(option, index)
        parent_count = index.data(TreeModel.ParentCountRole)
        if isinstance(parent_count, int) and parent_count > 1:
            badge_font = self._badge_font(option.font)
            width = int(QFontMetricsF(badge_font).horizontalAdvance(f"×{parent_count}"))
            size.setWidth(size.width() + width + 2 * BADGE_MARGIN)
        return size

    @staticmethod
    def _badge_font(base_font: QFont) -> QFont:
        """Slightly smaller copy of the row font, for the badge."""
        font = QFont(base_font)
        point_size = base_font.pointSizeF()
        if point_size > 0:
            font.setPointSizeF(max(7.0, point_size * 0.8))
        else:
            pixel_size = base_font.pixelSize()
            font.setPixelSize(max(8, int(pixel_size * 0.8)) if pixel_size > 0 else 10)
        return font


# ==============================================================================
# End of tree_delegate.py
# ==============================================================================
