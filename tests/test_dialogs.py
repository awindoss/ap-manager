# ==============================================================================
# tests/test_dialogs.py
# Phase 3 dialogs: value collection, validation, change detection, icon picker.
# ==============================================================================
import pytest

pytest.importorskip("PySide6")

from PySide6.QtGui import QColor, QImage
from PySide6.QtWidgets import QDialog

from models.node import Node
from utils import constants
from views.dialogs import (
    add_node_dialog,
    icon_selector_dialog,
    node_properties_dialog,
    node_style_editor,
)
from views.dialogs.add_node_dialog import AddNodeDialog
from views.dialogs.icon_selector_dialog import IconSelectorDialog
from views.dialogs.node_properties_dialog import NodePropertiesDialog
from views.dialogs.node_style_editor import NodeStyleEditor

pytestmark = pytest.mark.usefixtures("qapp")


@pytest.fixture
def icons_env(tmp_path, monkeypatch):
    root = tmp_path / "app"
    icons = root / constants.ICONS_DIR_NAME
    icons.mkdir(parents=True)
    monkeypatch.setattr(constants, "BASE_ROOT", root)
    monkeypatch.setattr(constants, "ICONS_PATH", icons)
    return root, icons


def write_png(path, color: str = "#ff0000") -> None:
    image = QImage(8, 8, QImage.Format.Format_ARGB32)
    image.fill(QColor(color))
    assert image.save(str(path))


# ------------------------------------------------------------------------------
# NodeStyleEditor
# ------------------------------------------------------------------------------
def test_style_editor_returns_normalised_values() -> None:
    editor = NodeStyleEditor(icon=None, bold=False, color="#ABC")

    assert editor.values() == {
        "icon": "",
        "style_bold": False,
        "style_color": "#aabbcc",
    }

    editor.set_icon("  ⭐  ")
    editor.set_bold(True)
    editor.set_color("not-a-colour")

    assert editor.values() == {
        "icon": "⭐",
        "style_bold": True,
        "style_color": constants.DEFAULT_TEXT_COLOR,
    }


def test_style_editor_checkbox_and_reset_button_stay_in_sync() -> None:
    editor = NodeStyleEditor(bold=True, color="#123456")

    assert editor.bold_check.isChecked() is True
    assert editor.color_button.text() == "#123456"

    editor.bold_check.setChecked(False)
    assert editor.is_bold() is False

    editor.reset_color_button.click()
    assert editor.color() == constants.DEFAULT_TEXT_COLOR


def test_style_editor_choose_icon_uses_selector(monkeypatch) -> None:
    class FakeSelector:
        def __init__(self, current_icon="", parent=None) -> None:
            self.current_icon = current_icon

        def exec(self):
            return QDialog.DialogCode.Accepted

        def selected_icon(self) -> str:
            return "📌"

    monkeypatch.setattr(node_style_editor, "IconSelectorDialog", FakeSelector)
    editor = NodeStyleEditor(icon="📚")

    editor.choose_icon()

    assert editor.icon() == "📌"


def test_style_editor_choose_icon_cancel_keeps_value(monkeypatch) -> None:
    class CancelSelector:
        def __init__(self, current_icon="", parent=None) -> None:
            pass

        def exec(self):
            return QDialog.DialogCode.Rejected

        def selected_icon(self) -> str:
            return "📌"

    monkeypatch.setattr(node_style_editor, "IconSelectorDialog", CancelSelector)
    editor = NodeStyleEditor(icon="📚")

    editor.choose_icon()

    assert editor.icon() == "📚"


# ------------------------------------------------------------------------------
# AddNodeDialog
# ------------------------------------------------------------------------------
def test_add_node_dialog_collects_values() -> None:
    dialog = AddNodeDialog(parent_name="马列")

    assert "新建子节点" in dialog.windowTitle()
    assert "马列" in dialog.windowTitle()
    assert dialog.parent_label.text() == "马列"

    dialog.name_edit.setText("  资本论  ")
    dialog.style_editor.set_icon("📖")
    dialog.style_editor.set_bold(True)
    dialog.style_editor.set_color("#B22222")

    assert dialog.node_values() == {
        "name": "资本论",
        "icon": "📖",
        "style_bold": True,
        "style_color": "#b22222",
    }


def test_add_node_dialog_root_title() -> None:
    dialog = AddNodeDialog()

    assert dialog.windowTitle() == "新建根节点"
    assert dialog.parent_label.text() == "（根节点）"


def test_add_node_dialog_rejects_empty_name(monkeypatch) -> None:
    warnings = []
    monkeypatch.setattr(
        add_node_dialog.QMessageBox,
        "warning",
        staticmethod(lambda *args, **kwargs: warnings.append(args)),
    )
    dialog = AddNodeDialog()
    dialog.name_edit.setText("   ")

    dialog._on_accept()

    assert dialog.result() != int(QDialog.DialogCode.Accepted)
    assert warnings


def test_add_node_dialog_accepts_valid_name() -> None:
    dialog = AddNodeDialog()
    dialog.name_edit.setText("新节点")

    dialog._on_accept()

    assert dialog.result() == int(QDialog.DialogCode.Accepted)


def test_add_node_dialog_name_length_is_limited() -> None:
    dialog = AddNodeDialog()
    dialog.name_edit.setText("x" * (constants.MAX_NODE_NAME_LENGTH + 50))

    assert len(dialog.name_edit.text()) == constants.MAX_NODE_NAME_LENGTH


# ------------------------------------------------------------------------------
# NodePropertiesDialog
# ------------------------------------------------------------------------------
def test_properties_dialog_prefills_and_detects_changes() -> None:
    node = Node(
        id=7,
        name="Old",
        icon="📚",
        style_bold=False,
        style_color="#000000",
        pdf_paths=["books/a.pdf", "books/b.pdf"],
    )
    dialog = NodePropertiesDialog(node)

    assert dialog.name_edit.text() == "Old"
    assert dialog.style_editor.icon() == "📚"
    assert dialog.style_editor.is_bold() is False
    assert dialog.pdf_list.count() == 2
    assert "PDF（2）" in dialog.pdf_group.title()
    assert dialog.changes() == {}

    dialog.name_edit.setText("  New  ")
    dialog.style_editor.set_icon("⭐")
    dialog.style_editor.set_bold(True)
    dialog.style_editor.set_color("#123456")

    assert dialog.changes() == {
        "name": "New",
        "icon": "⭐",
        "style_bold": True,
        "style_color": "#123456",
    }


def test_properties_dialog_only_reports_changed_fields() -> None:
    node = Node(id=1, name="Same", icon="📚", style_bold=True, style_color="#b22222")
    dialog = NodePropertiesDialog(node)

    dialog.style_editor.set_icon("📚")
    dialog.style_editor.set_bold(True)
    dialog.style_editor.set_color("#B22222")  # normalised to the same value

    assert dialog.changes() == {}


def test_properties_dialog_empty_pdf_hint() -> None:
    dialog = NodePropertiesDialog(Node(id=1, name="Empty"))

    assert dialog.pdf_list.count() == 0
    assert hasattr(dialog, "pdf_group")


def test_properties_dialog_rejects_empty_name(monkeypatch) -> None:
    warnings = []
    monkeypatch.setattr(
        node_properties_dialog.QMessageBox,
        "warning",
        staticmethod(lambda *args, **kwargs: warnings.append(args)),
    )
    dialog = NodePropertiesDialog(Node(id=1, name="Old"))
    dialog.name_edit.setText("  ")

    dialog._on_accept()

    assert dialog.result() != int(QDialog.DialogCode.Accepted)
    assert warnings


def test_properties_dialog_focus_style_does_not_raise() -> None:
    dialog = NodePropertiesDialog(Node(id=1, name="Node"))
    dialog.focus_style()
    assert isinstance(dialog.style_editor.icon_button, object)


# ------------------------------------------------------------------------------
# IconSelectorDialog
# ------------------------------------------------------------------------------
def test_icon_selector_lists_built_in_emoji() -> None:
    dialog = IconSelectorDialog("")

    assert dialog.list_widget.count() == len(constants.DEFAULT_ICON_EMOJIS)
    dialog.list_widget.setCurrentRow(2)
    assert dialog.selected_icon() == constants.DEFAULT_ICON_EMOJIS[2]


def test_icon_selector_preselects_current_emoji() -> None:
    dialog = IconSelectorDialog("📌")

    assert dialog.list_widget.currentItem() is not None
    assert dialog.selected_icon() == "📌"


def test_icon_selector_preselects_custom_image(icons_env) -> None:
    root, icons = icons_env
    write_png(icons / "mark.png")

    dialog = IconSelectorDialog("icons/mark.png")

    assert dialog.list_widget.count() == len(constants.DEFAULT_ICON_EMOJIS) + 1
    assert dialog.selected_icon() == "icons/mark.png"


def test_icon_selector_browse_adds_imported_icon(icons_env, tmp_path, monkeypatch) -> None:
    source = tmp_path / "source.png"
    write_png(source)
    dialog = IconSelectorDialog("")

    monkeypatch.setattr(
        icon_selector_dialog.QFileDialog,
        "getOpenFileName",
        staticmethod(lambda *args, **kwargs: (str(source), "")),
    )
    monkeypatch.setattr(
        icon_selector_dialog,
        "import_custom_icon",
        lambda path: "icons/source_abcd1234.png",
    )

    dialog.browse_custom()

    assert dialog.selected_icon() == "icons/source_abcd1234.png"
    assert dialog.list_widget.count() == len(constants.DEFAULT_ICON_EMOJIS) + 1


def test_icon_selector_browse_cancel_keeps_selection(monkeypatch) -> None:
    dialog = IconSelectorDialog("📚")
    monkeypatch.setattr(
        icon_selector_dialog.QFileDialog,
        "getOpenFileName",
        staticmethod(lambda *args, **kwargs: ("", "")),
    )

    dialog.browse_custom()

    assert dialog.selected_icon() == "📚"


def test_icon_selector_import_failure_is_reported(monkeypatch) -> None:
    warnings = []
    dialog = IconSelectorDialog("📚")

    monkeypatch.setattr(
        icon_selector_dialog.QFileDialog,
        "getOpenFileName",
        staticmethod(lambda *args, **kwargs: ("broken.bmp", "")),
    )

    def failing_import(path):
        raise ValueError("Unsupported icon format .bmp")

    monkeypatch.setattr(icon_selector_dialog, "import_custom_icon", failing_import)
    monkeypatch.setattr(
        icon_selector_dialog.QMessageBox,
        "warning",
        staticmethod(lambda *args, **kwargs: warnings.append(args)),
    )

    dialog.browse_custom()

    assert warnings
    assert dialog.selected_icon() == "📚"
    assert dialog.list_widget.count() == len(constants.DEFAULT_ICON_EMOJIS)


def test_icon_selector_clear_returns_empty_icon() -> None:
    dialog = IconSelectorDialog("📚")

    dialog.clear_selection()

    assert dialog.selected_icon() == ""
    assert dialog.result() == int(QDialog.DialogCode.Accepted)
