# ==============================================================================
# utils/icon_utils.py
# Node icon loading / caching / importing.
#
# A node icon is stored in the database as one of two things:
#   * a built-in emoji string (``📚``, ``👤`` ...), or
#   * a path relative to the application root (``icons/marx_1a2b3c4d.png``).
#
# The database never stores the user's original absolute path: custom images are
# copied into ``icons/`` first, so the library stays portable (plan.md §13.2).
# ==============================================================================
import hashlib
import re
import shutil
from pathlib import Path
from typing import Dict, Optional, Tuple

from PySide6.QtCore import QRect, Qt
from PySide6.QtGui import (
    QColor,
    QFont,
    QGuiApplication,
    QIcon,
    QPainter,
    QPalette,
    QPixmap,
)

from utils import constants
from utils.logger import log_debug, log_info, log_warning

# Icons are requested once per painted row per frame, so the decoded result is
# cached. The cache is keyed by (icon string, pixel size) and cleared whenever
# the tree is rebuilt, which also picks up re-imported or deleted image files.
_icon_cache: Dict[Tuple[str, int], QIcon] = {}

# Defensive limits: an "icon" should never be a multi-megabyte file.
MAX_ICON_FILE_BYTES = 10 * 1024 * 1024
_MAX_STEM_LENGTH = 40
_SAFE_STEM_PATTERN = re.compile(r"[^\w.-]+", re.UNICODE)
_MIN_ICON_SIZE = 8
_MAX_ICON_SIZE = 256


# ------------------------------------------------------------------------------
# Public helpers
# ------------------------------------------------------------------------------
def clear_icon_cache() -> None:
    """Drop every cached icon (called when the tree projection is rebuilt)."""
    _icon_cache.clear()


def is_custom_icon(icon_str: object) -> bool:
    """True if the value points at a supported image file rather than an emoji."""
    if not icon_str:
        return False
    return Path(str(icon_str)).suffix.lower() in constants.VALID_ICON_EXTENSIONS


def get_icon_path(
    icon_str: object,
    *,
    base_root: Optional[Path] = None,
    icons_dir: Optional[Path] = None,
) -> Optional[Path]:
    """
    Resolve a custom icon reference to an existing file inside ``icons/``.

    Returns ``None`` for emoji, missing files, unsupported extensions and paths
    that escape the icons directory (``../../secret.png``). The containment check
    is what keeps a hand-edited database from reading arbitrary local files.
    """
    if not is_custom_icon(icon_str):
        return None

    root = Path(base_root) if base_root is not None else Path(constants.BASE_ROOT)
    icons_root = Path(icons_dir) if icons_dir is not None else Path(constants.ICONS_PATH)

    candidate = Path(str(icon_str))
    if not candidate.is_absolute():
        candidate = root / candidate

    try:
        resolved = candidate.resolve()
        resolved_icons_root = icons_root.resolve()
    except OSError:
        return None

    try:
        resolved.relative_to(resolved_icons_root)
    except ValueError:
        log_warning(f"Rejected icon path outside the icons directory: {icon_str!r}")
        return None

    if not resolved.is_file():
        return None
    return resolved


def load_icon(icon_str: object, size: int = constants.TREE_ICON_SIZE) -> QIcon:
    """
    Return a ``QIcon`` for ``icon_str``.

    Always returns a ``QIcon``; failures (missing file, corrupt image, no GUI
    application) produce an empty icon and a log entry instead of raising. The
    view layer treats ``icon.isNull()`` as "draw nothing".
    """
    text = "" if icon_str is None else str(icon_str).strip()
    size = max(_MIN_ICON_SIZE, min(_MAX_ICON_SIZE, int(size)))

    key = (text, size)
    cached = _icon_cache.get(key)
    if cached is not None:
        return cached

    if not text:
        icon = QIcon()
    elif is_custom_icon(text):
        icon = _load_custom_icon(text, size)
    elif "\\" in text or "/" in text:
        # Looks like a path but has an unsupported/absent extension. Rendering
        # it as an emoji would produce a long literal string in the tree.
        log_warning(f"Unsupported icon reference ignored: {text!r}")
        icon = QIcon()
    else:
        icon = _render_emoji_icon(text, size)

    _icon_cache[key] = icon
    return icon


def import_custom_icon(
    source_path: str | Path,
    *,
    base_root: Optional[Path] = None,
    icons_dir: Optional[Path] = None,
) -> str:
    """
    Copy ``source_path`` into ``icons/`` and return the database-relative path.

    The file name is ``<sanitised-stem>_<sha256[:8]><ext>``: content-addressed, so
    importing the same picture twice does not create duplicates, and the stored
    path can never depend on the user's original folder. Raises ``FileNotFoundError``
    or ``ValueError`` for input the caller should report to the user.
    """
    source = Path(source_path)
    if not source.is_file():
        raise FileNotFoundError(f"Icon file does not exist: {source}")

    extension = source.suffix.lower()
    if extension not in constants.VALID_ICON_EXTENSIONS:
        supported = "/".join(ext.lstrip(".") for ext in constants.VALID_ICON_EXTENSIONS)
        raise ValueError(f"Unsupported icon format {extension or '(none)'}; expected {supported}.")

    if source.stat().st_size > MAX_ICON_FILE_BYTES:
        raise ValueError("Icon file is too large (limit: 10 MB).")

    root = Path(base_root) if base_root is not None else Path(constants.BASE_ROOT)
    icons_root = Path(icons_dir) if icons_dir is not None else Path(constants.ICONS_PATH)
    icons_root.mkdir(parents=True, exist_ok=True)

    digest = hashlib.sha256(source.read_bytes()).hexdigest()[:8]
    stem = _SAFE_STEM_PATTERN.sub("_", source.stem)
    stem = re.sub(r"_+", "_", stem).strip("._")[:_MAX_STEM_LENGTH] or "icon"
    # The file may already be a content-addressed export (``star_1a2b3c4d.png``).
    # In that case keep the existing name instead of appending the digest again,
    # so exporting and re-importing an icon is stable rather than growing the
    # file name on every migration.
    digest_suffix = f"_{digest}"
    if stem.endswith(digest_suffix) and len(stem) > len(digest_suffix):
        stem = stem[: -len(digest_suffix)] or "icon"
    destination = icons_root / f"{stem}_{digest}{extension}"

    if not destination.exists():
        shutil.copyfile(source, destination)
        log_info(f"Imported custom icon {source.name!r} as {destination.name!r}.")
    else:
        log_debug(f"Custom icon already imported: {destination.name!r}")

    try:
        relative = destination.resolve().relative_to(root.resolve())
    except ValueError:
        # Only possible when a caller overrides icons_dir with a directory that
        # is not below base_root; keep a deterministic, portable reference.
        log_warning(
            f"Icons directory {icons_root} is outside the application root "
            f"{root}; storing the file by name only."
        )
        relative = Path(constants.ICONS_DIR_NAME) / destination.name
    return relative.as_posix()


# ------------------------------------------------------------------------------
# Internals
# ------------------------------------------------------------------------------
def compose_warning_icon(
    base_icon: Optional[QIcon],
    size: int = constants.TREE_ICON_SIZE,
    color: str = "#D32F2F",
) -> QIcon:
    """
    Overlay a small warning badge on a node icon.

    Used when at least one PDF attached to the node is missing (plan.md §22 /
    §35 Phase 3). If the node has no icon, the warning badge is drawn on its own
    so the missing file is still visible.
    """
    if QGuiApplication.instance() is None:
        return base_icon if base_icon is not None else QIcon()

    size = max(_MIN_ICON_SIZE, min(_MAX_ICON_SIZE, int(size)))
    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.GlobalColor.transparent)

    has_base = base_icon is not None and not base_icon.isNull()
    if has_base:
        badge_size = max(7, round(size * 0.55))
        badge_x = size - badge_size
        badge_y = size - badge_size
    else:
        badge_size = max(7, round(size * 0.9))
        badge_x = (size - badge_size) // 2
        badge_y = (size - badge_size) // 2

    painter = QPainter(pixmap)
    try:
        if has_base:
            painter.drawPixmap(0, 0, base_icon.pixmap(size, size))

        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(color))
        painter.drawEllipse(badge_x, badge_y, badge_size, badge_size)

        font = QFont()
        font.setPixelSize(max(6, round(badge_size * 0.75)))
        font.setBold(True)
        painter.setFont(font)
        painter.setPen(QColor("#ffffff"))
        painter.drawText(
            QRect(badge_x, badge_y, badge_size, badge_size),
            int(Qt.AlignmentFlag.AlignCenter),
            "!",
        )
    finally:
        painter.end()

    return QIcon(pixmap)


def _load_custom_icon(icon_str: str, size: int) -> QIcon:
    path = get_icon_path(icon_str)
    if path is None:
        log_warning(f"Custom icon not found or not allowed: {icon_str!r}")
        return QIcon()

    if QGuiApplication.instance() is None:
        # QPixmap needs a GUI application; QIcon can stay lazy and still work
        # once the real application exists.
        return QIcon(str(path))

    pixmap = QPixmap(str(path))
    if pixmap.isNull():
        log_warning(f"Custom icon could not be decoded and was ignored: {icon_str!r}")
        return QIcon()

    if pixmap.width() > size or pixmap.height() > size:
        pixmap = pixmap.scaled(
            size,
            size,
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
    return QIcon(pixmap)


def _render_emoji_icon(emoji: str, size: int) -> QIcon:
    if QGuiApplication.instance() is None:
        log_debug(f"No QGuiApplication yet; emoji icon {emoji!r} cannot be rasterised.")
        return QIcon()

    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.GlobalColor.transparent)

    painter = QPainter(pixmap)
    try:
        font = QFont()
        # Qt performs glyph fallback, but naming the usual emoji fonts first makes
        # colour-emoji rendering much more reliable across Windows/macOS/Linux.
        font.setFamilies(
            [
                "Segoe UI Emoji",
                "Apple Color Emoji",
                "Noto Color Emoji",
                "Segoe UI Symbol",
            ]
        )
        font.setPixelSize(max(1, round(size * 0.9)))
        painter.setFont(font)

        application = QGuiApplication.instance()
        color = (
            application.palette().color(QPalette.ColorRole.WindowText)
            if application is not None
            else QColor("#000000")
        )
        painter.setPen(color)
        painter.drawText(pixmap.rect(), int(Qt.AlignmentFlag.AlignCenter), emoji)
    finally:
        painter.end()

    return QIcon(pixmap)


# ==============================================================================
# End of icon_utils.py
# ==============================================================================
