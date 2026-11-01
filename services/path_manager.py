# ==============================================================================
# services/path_manager.py
# PDF path resolution and storage against the portable application root.
#
# The library stores PDF paths relative to the application directory whenever
# possible (plan.md §21), so moving the whole folder keeps the collection
# working. Phase 4 adds the write side of that policy:
#
#   * user-picked files can be referenced in place (relative when inside the
#     application root, absolute when outside it), or
#   * copied into ``books/`` first and stored as ``books/<name>.pdf``.
#
# Missing files are never removed from the database (plan.md §22); they are
# reported as ``PdfFile(missing=True)`` so the UI can offer re-location.
# ==============================================================================
import hashlib
import os
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, List, Optional

from utils import constants
from utils.logger import log_debug, log_info, log_warning


@dataclass(frozen=True)
class PdfFile:
    """One PDF reference stored on a node, resolved against the current root."""

    stored_path: str
    absolute_path: Optional[Path]
    exists: bool

    @property
    def missing(self) -> bool:
        """True when the referenced file cannot be found on disk."""
        return not self.exists

    @property
    def file_name(self) -> str:
        """The final path component, used as the list label in dialogs."""
        name = Path(self.stored_path).name
        return name or self.stored_path

    @property
    def display_path(self) -> str:
        """Absolute path when resolvable, otherwise the stored value."""
        return str(self.absolute_path) if self.absolute_path is not None else self.stored_path


def normalize_path(path: str | Path, *, base_root: Optional[Path] = None) -> Path:
    """Resolve a stored path to an absolute path (relative to ``base_root``)."""
    candidate = Path(path).expanduser()
    if candidate.is_absolute():
        return candidate
    root = Path(base_root) if base_root is not None else Path(constants.BASE_ROOT)
    return root / candidate


def normalize_stored_path(pdf_path: object) -> str:
    """
    Normalise a value that is about to be stored in ``nodes.pdf_paths``.

    Only the representation changes: surrounding whitespace is dropped and
    relative Windows separators become ``/`` (the portable form used by the
    JSON export in phase 6). Absolute paths keep their original form because
    they are user-chosen references outside the portable tree.
    """
    text = "" if pdf_path is None else str(pdf_path).strip()
    if not text:
        return ""
    try:
        is_absolute = Path(text).expanduser().is_absolute()
    except (OSError, ValueError):
        is_absolute = False
    if is_absolute:
        return text
    return text.replace("\\", "/")


def pdf_path_key(pdf_path: object) -> str:
    """
    Comparison key for duplicate detection.

    Windows paths are case-insensitive, so two differently-cased spellings must
    count as the same file. The key is only used for comparison; the original
    spelling is what gets stored.
    """
    text = normalize_stored_path(pdf_path)
    if not text:
        return ""
    return os.path.normcase(os.path.normpath(text))


def resolve_pdf_path(
    pdf_path: str | Path,
    *,
    base_root: Optional[Path] = None,
) -> Optional[Path]:
    """Return the absolute path if the PDF exists on disk, otherwise ``None``."""
    if not pdf_path:
        return None
    try:
        candidate = normalize_path(pdf_path, base_root=base_root)
    except (TypeError, ValueError, OSError):
        return None
    return candidate if candidate.is_file() else None


def is_pdf_exists(pdf_path: str | Path, *, base_root: Optional[Path] = None) -> bool:
    """True when the stored PDF path currently points at a file."""
    return resolve_pdf_path(pdf_path, base_root=base_root) is not None


def missing_pdf_paths(
    pdf_paths: Iterable[str | Path],
    *,
    base_root: Optional[Path] = None,
) -> List[str]:
    """
    Return the stored paths that cannot be found, keeping the original order.

    Missing files never remove the database reference (plan.md §22); they only
    produce a warning marker so the user can re-locate them later.
    """
    missing: List[str] = []
    for pdf_path in pdf_paths or ():
        if not is_pdf_exists(pdf_path, base_root=base_root):
            missing.append(str(pdf_path))
    return missing


def describe_pdf(
    pdf_path: object,
    *,
    base_root: Optional[Path] = None,
) -> PdfFile:
    """Resolve one stored reference into a :class:`PdfFile` description."""
    stored = normalize_stored_path(pdf_path)
    absolute: Optional[Path] = None
    if stored:
        try:
            absolute = normalize_path(stored, base_root=base_root)
        except (OSError, ValueError):
            absolute = None
    return PdfFile(
        stored_path=stored,
        absolute_path=absolute,
        exists=bool(absolute is not None and absolute.is_file()),
    )


def describe_pdfs(
    pdf_paths: Iterable[object],
    *,
    base_root: Optional[Path] = None,
) -> List[PdfFile]:
    """Describe every stored PDF reference of a node, preserving its order."""
    return [describe_pdf(path, base_root=base_root) for path in (pdf_paths or ())]


def is_within_root(path: str | Path, root: str | Path) -> bool:
    """True when ``path`` is ``root`` or one of its descendants."""
    try:
        Path(path).resolve().relative_to(Path(root).resolve())
        return True
    except (OSError, ValueError):
        return False


def relative_to_root(path: str | Path, root: str | Path) -> Optional[str]:
    """Return the POSIX relative form of ``path`` under ``root``, if any."""
    try:
        relative = Path(path).resolve().relative_to(Path(root).resolve())
    except (OSError, ValueError):
        return None
    return relative.as_posix()


def make_stored_path(
    source_path: str | Path,
    *,
    base_root: Optional[Path] = None,
    copy_to_books: bool = False,
) -> str:
    """
    Convert a user-picked PDF file into the value stored in the database.

    Rules (plan.md §21):

    * inside the application root -> relative POSIX path (``books/a.pdf``);
    * outside the application root -> absolute path (the file stays where it
      is, so the library is no longer fully portable for that entry);
    * ``copy_to_books=True`` -> copy into ``books/`` first and always store a
      relative path. Identical files are reused instead of duplicated.

    Raises ``FileNotFoundError`` / ``ValueError`` with a user-readable message.
    """
    root = Path(base_root) if base_root is not None else Path(constants.BASE_ROOT)

    source = Path(source_path).expanduser()
    if not source.is_absolute():
        source = root / source
    source = Path(os.path.abspath(source))

    if not source.is_file():
        raise FileNotFoundError(f"PDF 文件不存在：{source}")

    extension = source.suffix.lower()
    if extension not in constants.VALID_PDF_EXTENSIONS:
        supported = "/".join(ext.lstrip(".") for ext in constants.VALID_PDF_EXTENSIONS)
        raise ValueError(
            f"不支持的文件类型：{extension or '(无扩展名)'}；仅支持 {supported} 文件。"
        )

    if copy_to_books:
        books_root = root / constants.BOOKS_DIR_NAME
        if not is_within_root(source, books_root):
            source = copy_into_books(source, books_root)

    relative = relative_to_root(source, root)
    if relative is not None:
        return relative
    return source.as_posix()


def copy_into_books(
    source_path: str | Path,
    books_root: str | Path,
    *,
    chunk_size: int = constants.PDF_COPY_CHUNK_SIZE,
) -> Path:
    """
    Copy a PDF into ``books_root`` and return the destination path.

    The original file name is kept when possible. If a different file already
    owns that name, a ``_<sha256[:8]>`` suffix disambiguates it; re-adding the
    exact same file reuses the existing copy.
    """
    source = Path(source_path)
    destination_dir = Path(books_root)
    destination_dir.mkdir(parents=True, exist_ok=True)

    target = destination_dir / source.name
    if target.exists() and target.resolve() == source.resolve():
        return target
    if target.exists() and not _same_content(source, target, chunk_size):
        digest = _file_digest(source, chunk_size)[:8]
        target = destination_dir / constants.PDF_COPY_NAME_SUFFIX_FORMAT.format(
            stem=source.stem,
            digest=digest,
            suffix=source.suffix.lower(),
        )
        counter = 2
        while target.exists() and not _same_content(source, target, chunk_size):
            target = destination_dir / (
                f"{source.stem}_{digest}_{counter}{source.suffix.lower()}"
            )
            counter += 1

    if not target.exists():
        shutil.copy2(source, target)
        log_info(f"Copied PDF {source.name!r} into {destination_dir.name}/.")
    else:
        log_debug(f"PDF {source.name!r} already present in {destination_dir.name}/.")
    return target


# ------------------------------------------------------------------------------
# Internals
# ------------------------------------------------------------------------------
def _same_content(left: Path, right: Path, chunk_size: int) -> bool:
    """Cheap size check first, then a streamed digest comparison."""
    try:
        if left.stat().st_size != right.stat().st_size:
            return False
    except OSError:
        return False
    left_digest = _file_digest(left, chunk_size)
    right_digest = _file_digest(right, chunk_size)
    if not left_digest or not right_digest:
        return False
    return left_digest == right_digest


def _file_digest(path: Path, chunk_size: int) -> str:
    digest = hashlib.sha256()
    try:
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(max(1, chunk_size)), b""):
                digest.update(chunk)
    except OSError as error:
        log_warning(f"Could not hash {path}: {error}")
        return ""
    return digest.hexdigest()


# ==============================================================================
# End of path_manager.py
# ==============================================================================
