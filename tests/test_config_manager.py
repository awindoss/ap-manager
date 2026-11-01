# ==============================================================================
# tests/test_config_manager.py
# config.json loading/saving behind the PDF reader setting (Phase 4).
# ==============================================================================
import json

from utils import constants
from utils.config_manager import ConfigManager


def write_config(path, data) -> None:
    path.write_text(json.dumps(data, ensure_ascii=False, indent=4), encoding="utf-8")


def test_missing_config_uses_defaults(tmp_path) -> None:
    config = ConfigManager(tmp_path / "config.json")

    assert config.get_pdf_reader_path() == ""
    assert config.get_pdf_reader_args() == ""
    assert config.get_library_db_path() == constants.DEFAULT_DB_PATH_RELATIVE
    assert config.get(constants.SECTION_UI, constants.KEY_WINDOW_WIDTH) == (
        constants.DEFAULT_WINDOW_WIDTH
    )


def test_existing_config_is_merged_with_defaults_and_unknown_keys_kept(tmp_path) -> None:
    path = tmp_path / "config.json"
    write_config(
        path,
        {
            "pdf_reader": {"path": "C:/Tools/reader.exe"},
            "library": {"database_path": "custom/library.db"},
            "theme": "dark",
        },
    )

    config = ConfigManager(path)

    assert config.get_pdf_reader_path() == "C:/Tools/reader.exe"
    assert config.get_library_db_path() == "custom/library.db"
    assert config.get("theme", "name", "dark") == "dark"
    # Missing keys from a known section still get their default.
    assert config.get(constants.SECTION_UI, constants.KEY_WINDOW_HEIGHT) == (
        constants.DEFAULT_WINDOW_HEIGHT
    )

    config.save()

    reloaded = json.loads(path.read_text(encoding="utf-8"))
    assert reloaded["theme"] == "dark"
    assert reloaded["pdf_reader"]["path"] == "C:/Tools/reader.exe"


def test_set_persists_and_round_trips(tmp_path) -> None:
    path = tmp_path / "config.json"
    config = ConfigManager(path)

    config.set_pdf_reader_path("  C:/Apps/SumatraPDF.exe  ")

    assert config.get_pdf_reader_path() == "C:/Apps/SumatraPDF.exe"
    assert not (tmp_path / "config.json.tmp").exists()

    reloaded = ConfigManager(path)
    assert reloaded.get_pdf_reader_path() == "C:/Apps/SumatraPDF.exe"


def test_clearing_the_reader_path_round_trips(tmp_path) -> None:
    path = tmp_path / "config.json"
    config = ConfigManager(path)
    config.set_pdf_reader_path("reader.exe")

    config.set_pdf_reader_path(None)

    assert ConfigManager(path).get_pdf_reader_path() == ""


def test_invalid_json_falls_back_and_is_backed_up_on_save(tmp_path) -> None:
    path = tmp_path / "config.json"
    path.write_text("{ this is not json", encoding="utf-8")

    config = ConfigManager(path)
    assert config.get_pdf_reader_path() == ""

    config.set_pdf_reader_path("C:/reader.exe")

    backup = tmp_path / "config.json.bak"
    assert backup.is_file()
    assert backup.read_text(encoding="utf-8") == "{ this is not json"
    assert json.loads(path.read_text(encoding="utf-8"))["pdf_reader"]["path"] == (
        "C:/reader.exe"
    )


def test_non_object_json_is_treated_as_invalid(tmp_path) -> None:
    path = tmp_path / "config.json"
    path.write_text("[1, 2, 3]", encoding="utf-8")

    config = ConfigManager(path)

    assert config.get_pdf_reader_path() == ""
    assert config.get_library_db_path() == constants.DEFAULT_DB_PATH_RELATIVE


def test_wrong_type_for_known_section_keeps_default(tmp_path) -> None:
    path = tmp_path / "config.json"
    write_config(path, {"pdf_reader": "not a section"})

    config = ConfigManager(path)

    assert config.get(constants.SECTION_PDF_READER, constants.KEY_PDF_READER_PATH) == ""
    assert config.get_pdf_reader_path() == ""
