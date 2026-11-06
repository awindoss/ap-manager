# ==============================================================================
# tests/test_icon_utils.py
# Icon resolution, cache, import and failure fallbacks (Phase 3).
# ==============================================================================
import logging

import pytest

pytest.importorskip("PySide6")

from PySide6.QtGui import QColor, QImage, QIcon

from utils import constants, icon_utils

pytestmark = pytest.mark.usefixtures("qapp")


@pytest.fixture(autouse=True)
def _clear_cache():
    icon_utils.clear_icon_cache()
    yield
    icon_utils.clear_icon_cache()


@pytest.fixture
def icons_env(tmp_path, monkeypatch):
    """Point BASE_ROOT/ICONS_PATH at a throw-away application root."""
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
# Classification / resolution
# ------------------------------------------------------------------------------
def test_emoji_is_not_a_custom_icon(icons_env) -> None:
    assert icon_utils.is_custom_icon("📚") is False
    assert icon_utils.get_icon_path("📚") is None


def test_custom_icon_extensions_are_recognised() -> None:
    for name in ("icons/a.png", "icons/a.ico", "icons/a.SVG"):
        assert icon_utils.is_custom_icon(name) is True
    assert icon_utils.is_custom_icon("icons/a.bmp") is False
    assert icon_utils.is_custom_icon("") is False
    assert icon_utils.is_custom_icon(None) is False


def test_custom_png_is_resolved_inside_icons(icons_env) -> None:
    root, icons = icons_env
    write_png(icons / "star.png")
    relative = "icons/star.png"

    resolved = icon_utils.get_icon_path(relative)

    assert resolved is not None
    assert resolved == (icons / "star.png").resolve()


def test_path_outside_icons_is_rejected(icons_env, caplog) -> None:
    root, icons = icons_env
    write_png(root / "outside.png")

    with caplog.at_level(logging.WARNING, logger="ap_logger"):
        assert icon_utils.get_icon_path("outside.png") is None
        assert icon_utils.get_icon_path("../outside.png") is None

    assert "outside the icons directory" in caplog.text


def test_missing_custom_icon_returns_none(icons_env) -> None:
    assert icon_utils.get_icon_path("icons/missing.png") is None


# ------------------------------------------------------------------------------
# Loading
# ------------------------------------------------------------------------------
def test_load_builtin_emoji_returns_a_non_null_icon(icons_env) -> None:
    icon = icon_utils.load_icon("📚", 16)

    assert isinstance(icon, QIcon)
    assert icon.isNull() is False


def test_load_empty_icon_returns_empty_icon(icons_env) -> None:
    assert icon_utils.load_icon("").isNull()
    assert icon_utils.load_icon(None).isNull()


def test_load_custom_png_and_cache_identity(icons_env) -> None:
    root, icons = icons_env
    write_png(icons / "star.png")

    first = icon_utils.load_icon("icons/star.png", 16)
    second = icon_utils.load_icon("icons/star.png", 16)

    assert first.isNull() is False
    assert first is second

    icon_utils.clear_icon_cache()
    third = icon_utils.load_icon("icons/star.png", 16)
    assert third is not first


def test_load_svg_icon(icons_env) -> None:
    root, icons = icons_env
    (icons / "shape.svg").write_text(
        '<svg xmlns="http://www.w3.org/2000/svg" width="16" height="16">'
        '<rect width="16" height="16" fill="#00ff00"/></svg>',
        encoding="utf-8",
    )

    icon = icon_utils.load_icon("icons/shape.svg", 16)

    assert icon.isNull() is False


def test_missing_custom_icon_logs_and_returns_empty(icons_env, caplog) -> None:
    with caplog.at_level(logging.WARNING, logger="ap_logger"):
        icon = icon_utils.load_icon("icons/missing.png", 16)

    assert icon.isNull()
    assert "not found or not allowed" in caplog.text


def test_corrupt_image_is_rejected_without_raising(icons_env, caplog) -> None:
    root, icons = icons_env
    (icons / "broken.png").write_bytes(b"this is definitely not a png")

    with caplog.at_level(logging.WARNING, logger="ap_logger"):
        icon = icon_utils.load_icon("icons/broken.png", 16)

    assert icon.isNull()
    assert "could not be decoded" in caplog.text


def test_unsupported_extension_is_not_rendered_as_emoji(icons_env, caplog) -> None:
    with caplog.at_level(logging.WARNING, logger="ap_logger"):
        icon = icon_utils.load_icon("icons/book.bmp", 16)

    assert icon.isNull()
    assert "Unsupported icon reference" in caplog.text


# ------------------------------------------------------------------------------
# Import
# ------------------------------------------------------------------------------
def test_import_custom_icon_copies_and_deduplicates(icons_env, tmp_path) -> None:
    root, icons = icons_env
    source = tmp_path / "我的 图标.png"
    write_png(source, "#123456")

    relative = icon_utils.import_custom_icon(source)

    assert relative.startswith("icons/")
    assert relative.endswith(".png")
    copied = root / relative
    assert copied.is_file()

    # Same content -> same content-addressed path, no duplicate file.
    assert icon_utils.import_custom_icon(source) == relative
    assert len(list(icons.glob("*.png"))) == 1


def test_import_custom_icon_keeps_a_content_addressed_name(icons_env, tmp_path) -> None:
    """Re-importing an exported icon must not append a second content hash."""
    root, icons = icons_env
    source = tmp_path / "book.png"
    write_png(source)
    first = icon_utils.import_custom_icon(source)
    exported = root / first

    assert icon_utils.import_custom_icon(exported) == first
    assert len(list(icons.glob("*.png"))) == 1


def test_import_custom_icon_preserves_extension_and_sanitises_stem(icons_env, tmp_path) -> None:
    root, icons = icons_env
    source = tmp_path / "weird name (copy).png"
    write_png(source)

    relative = icon_utils.import_custom_icon(source)

    assert relative.startswith("icons/weird_name_copy_")
    assert icons.joinpath(relative.split("/", 1)[1]).is_file()


def test_import_custom_icon_rejects_unsupported_extension(icons_env, tmp_path) -> None:
    source = tmp_path / "notes.txt"
    source.write_text("nope", encoding="utf-8")

    with pytest.raises(ValueError, match="Unsupported icon format"):
        icon_utils.import_custom_icon(source)


def test_import_custom_icon_rejects_missing_source(icons_env, tmp_path) -> None:
    with pytest.raises(FileNotFoundError):
        icon_utils.import_custom_icon(tmp_path / "absent.png")


def test_imported_icon_can_be_loaded_back(icons_env, tmp_path) -> None:
    source = tmp_path / "book.png"
    write_png(source, "#654321")

    relative = icon_utils.import_custom_icon(source)

    assert icon_utils.load_icon(relative, 16).isNull() is False


def test_icon_size_is_clamped(icons_env) -> None:
    """The public API must not be able to request a giant raster by mistake."""
    icon = icon_utils.load_icon("📚", 10_000)
    assert icon.isNull() is False
    sizes = icon.availableSizes()
    assert sizes
    assert sizes[0].width() <= icon_utils._MAX_ICON_SIZE


def test_compose_warning_icon_without_and_with_a_base_icon(icons_env) -> None:
    bare = icon_utils.compose_warning_icon(QIcon(), 16)
    with_base = icon_utils.compose_warning_icon(icon_utils.load_icon("📚", 16), 16)

    assert bare.isNull() is False
    assert with_base.isNull() is False
