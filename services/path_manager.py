# ==============================================================================
# services/path_manager.py
# PDF path resolution against the portable application root.
#
# The library stores PDF paths relative to the application directory whenever
# possible (plan.md §21), so moving the whole folder keeps the collection
# working. Phase 4 extends this module with the PDF-management workflows
# (re-locating missing files, optional books/ root); Phase 3 only needs the
# existence checks behind the "missing file" marker.
# ==============================================================================
from pathlib import Path
from typing import Iterable, List, Optional

from utils import constants


def normalize_path(path: str | Path, *, base_root: Optional[Path] = None) -> Path:
    """Resolve a stored path to an absolute path (relative to ``base_root``)."""
    candidate = Path(path).expanduser()
    if candidate.is_absolute():
        return candidate
    root = Path(base_root) if base_root is not None else Path(constants.BASE_ROOT)
    return root / candidate


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


# ==============================================================================
# End of path_manager.py
# ==============================================================================
