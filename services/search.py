# ==============================================================================
# services/search.py
# Library search (Phase 7 / plan.md §28).
#
# Scope: node names and stored PDF references (file name and path — the same
# reference may be stored relative or absolute). Each hit is returned once, with
# *every* root-to-node position attached, because a node can live in several
# categories at the same time (plan.md §16 / §28). The UI can therefore show
# "马克思 — 经济政治 > 马列 > 马克思" and jump to the exact instance.
# ==============================================================================
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

from models.library import LibraryService
from models.node import Node
from utils import constants


@dataclass(frozen=True)
class SearchLocation:
    """One root-to-node position of a matching node."""

    path: Tuple[int, ...]
    names: Tuple[str, ...]

    @property
    def label(self) -> str:
        """Breadcrumb such as ``经济政治 > 马列 > 马克思``."""
        return " > ".join(self.names)

    @property
    def depth(self) -> int:
        return len(self.path)


@dataclass(frozen=True)
class SearchHit:
    """A matching node with its match sources and all of its positions."""

    node: Node
    match_kinds: Tuple[str, ...]
    matched_pdf_paths: Tuple[str, ...]
    locations: Tuple[SearchLocation, ...]

    @property
    def node_id(self) -> int:
        assert self.node.id is not None
        return self.node.id

    @property
    def name(self) -> str:
        return self.node.name

    @property
    def icon(self) -> str:
        return self.node.icon or ""

    @property
    def name_matched(self) -> bool:
        return constants.SEARCH_MATCH_NAME in self.match_kinds

    @property
    def pdf_matched(self) -> bool:
        return constants.SEARCH_MATCH_PDF in self.match_kinds

    @property
    def match_label(self) -> str:
        """Short description of what matched, for the result list."""
        labels: List[str] = []
        if self.name_matched:
            labels.append(constants.SEARCH_MATCH_LABELS[constants.SEARCH_MATCH_NAME])
        if self.pdf_matched:
            names = self.matched_pdf_names
            if names:
                labels.append(f"PDF：{'、'.join(names[:2])}" + ("…" if len(names) > 2 else ""))
            else:
                labels.append(constants.SEARCH_MATCH_LABELS[constants.SEARCH_MATCH_PDF])
        return " + ".join(labels)

    @property
    def matched_pdf_names(self) -> Tuple[str, ...]:
        """File names of the matched PDF references (full paths kept separately)."""
        names: List[str] = []
        for stored in self.matched_pdf_paths:
            name = Path(stored).name
            if name and name not in names:
                names.append(name)
        return tuple(names)


@dataclass(frozen=True)
class SearchResult:
    """Outcome of one search query."""

    query: str
    hits: Tuple[SearchHit, ...]
    limit: int
    truncated: bool = False

    @property
    def hit_count(self) -> int:
        return len(self.hits)

    @property
    def location_count(self) -> int:
        return sum(len(hit.locations) for hit in self.hits)

    @property
    def is_empty(self) -> bool:
        return not self.hits

    @classmethod
    def empty(cls, query: str = "", *, limit: int = constants.SEARCH_DEFAULT_LIMIT) -> "SearchResult":
        return cls(query=query, hits=(), limit=limit, truncated=False)


class SearchService:
    """
    Search the library on behalf of the controller.

    The service keeps no cache: every call reflects the current database, which
    matters because refresh/edit operations can change names and PDF lists at
    any time.
    """

    def __init__(self, library: LibraryService) -> None:
        self._library = library

    # --------------------------------------------------------------------------
    # Public API
    # --------------------------------------------------------------------------
    def search(
        self,
        query: object,
        *,
        limit: Optional[int] = None,
    ) -> SearchResult:
        """
        Search node names and PDF references for ``query``.

        Whitespace-separated tokens are ANDed. A token that occurs in a node
        name or in any stored PDF path qualifies; the returned hit records which
        source(s) matched and every position of the node.
        """
        normalized = normalize_query(query)
        effective_limit = _clamp_limit(limit)
        if not normalized:
            return SearchResult.empty(limit=effective_limit)

        tokens = tuple(normalized.split())
        # Fetch one extra row to detect truncation without a second COUNT query.
        candidates = self._library.search_nodes(tokens, limit=effective_limit + 1)
        truncated = len(candidates) > effective_limit
        candidates = candidates[:effective_limit]

        name_cache: Dict[int, str] = {}
        hits: List[SearchHit] = []
        for node in candidates:
            if node.id is None:
                continue
            match = _classify_match(node, tokens)
            if match is None:
                # The SQL LIKE pre-filter is ASCII-case-insensitive; a
                # non-ASCII mismatch is re-checked here so the result never
                # contains a false positive.
                continue
            match_kinds, matched_pdf_paths = match
            hits.append(
                SearchHit(
                    node=node,
                    match_kinds=match_kinds,
                    matched_pdf_paths=matched_pdf_paths,
                    locations=_locations_for(node.id, self._library, name_cache),
                )
            )

        # Name matches are more intuitive than PDF-only matches; the secondary
        # keys keep the order stable and predictable.
        hits.sort(
            key=lambda hit: (
                0 if hit.name_matched else 1,
                hit.name.casefold(),
                hit.node_id,
            )
        )
        return SearchResult(
            query=normalized,
            hits=tuple(hits),
            limit=effective_limit,
            truncated=truncated,
        )


# ------------------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------------------
def normalize_query(query: object) -> str:
    """Trim and collapse whitespace; long queries are safely truncated."""
    if query is None:
        return ""
    text = " ".join(str(query).split())
    if len(text) > constants.SEARCH_MAX_QUERY_LENGTH:
        text = text[: constants.SEARCH_MAX_QUERY_LENGTH].rstrip()
    return text


def _clamp_limit(limit: Optional[int]) -> int:
    if limit is None:
        return constants.SEARCH_DEFAULT_LIMIT
    try:
        value = int(limit)
    except (TypeError, ValueError):
        return constants.SEARCH_DEFAULT_LIMIT
    return max(1, min(value, constants.SEARCH_MAX_LIMIT))


def _classify_match(
    node: Node,
    tokens: Sequence[str],
) -> Optional[Tuple[Tuple[str, ...], Tuple[str, ...]]]:
    """
    Return ``(match_kinds, matched_pdf_paths)`` when every token matches, else None.

    Both the node name and every stored PDF reference are compared casefolded.
    """
    name = node.name.casefold()
    pdf_paths = [str(path) for path in node.pdf_paths if str(path).strip()]
    pdf_paths_folded = [path.casefold() for path in pdf_paths]

    name_matched = False
    matched_pdf_paths: List[str] = []

    for token in tokens:
        needle = token.casefold()
        in_name = needle in name
        in_pdfs = False
        for path, path_folded in zip(pdf_paths, pdf_paths_folded):
            if needle in path_folded:
                in_pdfs = True
                if path not in matched_pdf_paths:
                    matched_pdf_paths.append(path)
        if not (in_name or in_pdfs):
            return None
        name_matched = name_matched or in_name

    kinds: List[str] = []
    if name_matched:
        kinds.append(constants.SEARCH_MATCH_NAME)
    if matched_pdf_paths:
        kinds.append(constants.SEARCH_MATCH_PDF)
    return tuple(kinds), tuple(matched_pdf_paths)


def _locations_for(
    node_id: int,
    library: LibraryService,
    name_cache: Dict[int, str],
) -> Tuple[SearchLocation, ...]:
    """Resolve every root-to-node path with node names for display."""
    locations: List[SearchLocation] = []
    seen = set()

    for raw_path in library.get_node_paths(node_id):
        try:
            path = tuple(int(part) for part in raw_path)
        except (TypeError, ValueError):
            continue
        if not path or path in seen:
            continue
        seen.add(path)

        names: List[str] = []
        for part_id in path:
            name = name_cache.get(part_id)
            if name is None:
                part = library.get_node(part_id)
                name = part.name if part is not None else f"#{part_id}"
                name_cache[part_id] = name
            names.append(name)
        locations.append(SearchLocation(path=path, names=tuple(names)))

    return tuple(locations)


# ==============================================================================
# End of search.py
# ==============================================================================
