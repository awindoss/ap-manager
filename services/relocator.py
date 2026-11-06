# ==============================================================================
# services/relocator.py
# Batch re-location of missing PDFs (plan.md §22, stage.md Phase 7).
#
# "文件检查" lists every reference whose file is gone. Fixing them one by one is
# slow after moving a whole books directory, so this service scans a chosen
# folder (optionally recursive) and matches files by name:
#
#   * exactly one same-named PDF    -> automatic match;
#   * several same-named PDFs       -> pick the one whose path suffix is
#                                      closest to the stored reference, or
#                                      report the entry as ambiguous;
#   * no same-named PDF             -> report it as not found.
#
# The service only *plans* the changes. The controller applies the matched
# entries through the normal ``relink_pdf`` path, so path policy (relative vs
# absolute, optional copy to books/) stays in one place.
# ==============================================================================
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

from utils import constants
from utils.logger import log_debug, log_warning


@dataclass(frozen=True)
class RelinkRequest:
    """One missing reference that should be pointed at a new file."""

    node_id: int
    stored_path: str

    @property
    def file_name(self) -> str:
        return _file_name(self.stored_path)


@dataclass(frozen=True)
class RelinkDecision:
    """What the planner found for one request."""

    request: RelinkRequest
    status: str
    new_path: Optional[Path] = None
    detail: str = ""

    @property
    def matched(self) -> bool:
        return self.status == constants.RELINK_STATUS_MATCHED and self.new_path is not None

    @property
    def status_label(self) -> str:
        return constants.RELINK_STATUS_LABELS.get(self.status, self.status)


@dataclass(frozen=True)
class RelinkPlan:
    """The complete, side-effect-free result of scanning one folder."""

    search_root: Path
    decisions: Tuple[RelinkDecision, ...]

    @property
    def matched(self) -> Tuple[RelinkDecision, ...]:
        return tuple(decision for decision in self.decisions if decision.matched)

    @property
    def ambiguous(self) -> Tuple[RelinkDecision, ...]:
        return tuple(
            decision
            for decision in self.decisions
            if decision.status == constants.RELINK_STATUS_AMBIGUOUS
        )

    @property
    def not_found(self) -> Tuple[RelinkDecision, ...]:
        return tuple(
            decision
            for decision in self.decisions
            if decision.status == constants.RELINK_STATUS_NOT_FOUND
        )

    @property
    def has_matches(self) -> bool:
        return bool(self.matched)


def plan_batch_relink(
    requests: Iterable[RelinkRequest],
    search_root: str | Path,
    *,
    recursive: bool = True,
) -> RelinkPlan:
    """
    Build a relocation plan by scanning ``search_root`` for same-named PDFs.

    Raises ``ValueError`` when the folder does not exist or is not a directory;
    unreadable sub-directories are skipped with a log warning instead of
    aborting the whole batch.
    """
    root = _require_directory(search_root)
    index = build_filename_index(root, recursive=recursive)

    requests_list = list(requests or ())
    decisions: List[RelinkDecision] = []
    for request in requests_list:
        decisions.append(_decide(request, index, root))

    matched = sum(1 for decision in decisions if decision.matched)
    log_debug(
        f"Batch relocation scan of {root}: {len(decisions)} request(s), "
        f"{matched} matched."
    )
    return RelinkPlan(search_root=root, decisions=tuple(decisions))


def build_filename_index(
    search_root: str | Path,
    *,
    recursive: bool = True,
) -> Dict[str, Tuple[Path, ...]]:
    """
    Map ``filename.casefold() -> candidate PDF paths`` below ``search_root``.

    ``os.walk`` is used instead of ``Path.rglob`` so an unreadable directory
    can be skipped without aborting the scan.
    """
    root = _require_directory(search_root)
    index: Dict[str, List[Path]] = {}

    def _on_error(error: OSError) -> None:
        log_warning(f"Skipping unreadable directory during relocation scan: {error}")

    for dir_path, dir_names, file_names in os.walk(str(root), onerror=_on_error):
        if not recursive:
            dir_names[:] = []
        for file_name in file_names:
            candidate = Path(dir_path) / file_name
            if candidate.suffix.lower() not in constants.VALID_PDF_EXTENSIONS:
                continue
            key = file_name.casefold()
            index.setdefault(key, []).append(candidate)

    # Stable candidate order keeps the "closest suffix" heuristic deterministic.
    return {
        key: tuple(sorted(paths, key=lambda item: str(item).casefold()))
        for key, paths in index.items()
    }


# ------------------------------------------------------------------------------
# Matching internals
# ------------------------------------------------------------------------------
def _decide(
    request: RelinkRequest,
    index: Dict[str, Tuple[Path, ...]],
    root: Path,
) -> RelinkDecision:
    name = request.file_name
    if not name:
        return RelinkDecision(
            request,
            constants.RELINK_STATUS_NOT_FOUND,
            detail="存储路径为空，无法按文件名匹配。",
        )

    candidates = index.get(name.casefold(), ())
    if not candidates:
        return RelinkDecision(
            request,
            constants.RELINK_STATUS_NOT_FOUND,
            detail="所选文件夹中没有同名 PDF。",
        )
    if len(candidates) == 1:
        return RelinkDecision(
            request,
            constants.RELINK_STATUS_MATCHED,
            new_path=candidates[0],
            detail="找到唯一的同名 PDF。",
        )

    best, best_score, tied = _closest_candidate(request.stored_path, candidates, root)
    if best is not None and not tied:
        return RelinkDecision(
            request,
            constants.RELINK_STATUS_MATCHED,
            new_path=best,
            detail=(
                f"有 {len(candidates)} 个同名 PDF；已按原路径选择最接近的一个。"
            ),
        )

    preview = "、".join(str(path) for path in candidates[:3])
    if len(candidates) > 3:
        preview += "…"
    return RelinkDecision(
        request,
        constants.RELINK_STATUS_AMBIGUOUS,
        detail=f"有 {len(candidates)} 个同名 PDF，无法确定要使用哪一个：{preview}",
    )


def _closest_candidate(
    stored_path: str,
    candidates: Sequence[Path],
    root: Path,
) -> Tuple[Optional[Path], int, bool]:
    """
    Pick the candidate whose path suffix best matches ``stored_path``.

    Returns ``(candidate, score, tied)``. A tie means the choice is ambiguous
    and the caller must ask the user instead of guessing.
    """
    stored_parts = _path_parts(stored_path)
    scored: List[Tuple[int, Path]] = []
    for candidate in candidates:
        try:
            relative = candidate.relative_to(root)
            candidate_parts = [part.casefold() for part in relative.parts]
        except ValueError:
            candidate_parts = [part.casefold() for part in candidate.parts]
        scored.append((_common_suffix_length(stored_parts, candidate_parts), candidate))

    if not scored:
        return None, 0, False
    highest = max(score for score, _ in scored)
    if highest <= 0:
        return None, 0, True
    winners = [candidate for score, candidate in scored if score == highest]
    if len(winners) != 1:
        return None, highest, True
    return winners[0], highest, False


def _common_suffix_length(left: Sequence[str], right: Sequence[str]) -> int:
    score = 0
    for left_part, right_part in zip(reversed(left), reversed(right)):
        if left_part != right_part:
            break
        score += 1
    return score


def _path_parts(path_text: str) -> List[str]:
    return [part.casefold() for part in re.split(r"[\\/]+", str(path_text)) if part]


def _file_name(stored_path: str) -> str:
    text = str(stored_path or "").strip().replace("\\", "/")
    return text.rsplit("/", 1)[-1]


def _require_directory(search_root: str | Path) -> Path:
    raw = "" if search_root is None else str(search_root).strip()
    if not raw:
        raise ValueError("请选择包含 PDF 文件的文件夹。")
    try:
        root = Path(raw).expanduser()
    except (OSError, ValueError) as error:
        raise ValueError(f"文件夹路径无效：{raw}") from error
    if not root.is_dir():
        raise ValueError(f"文件夹不存在：{root}")
    return root


# ==============================================================================
# End of relocator.py
# ==============================================================================
