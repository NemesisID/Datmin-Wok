from __future__ import annotations

from app.person_names import normalize_person_name


def test_strips_titles_and_degrees() -> None:
    assert normalize_person_name("Prof. Dr. Ir. Budi Santoso, S.Kom., M.Kom.") == "budi santoso"
    assert normalize_person_name("Dra. Hj. Siti Aminah, M.Pd.") == "siti aminah"
    assert normalize_person_name("Budi Santoso S.Kom.") == "budi santoso"
    assert normalize_person_name("Nur Cahyo Wibowo, S.T., M.T.") == "nur cahyo wibowo"


def test_keeps_initial_and_name_tokens() -> None:
    assert normalize_person_name("M. Fajar Ramadhan, S.T.") == "m fajar ramadhan"
    assert normalize_person_name("  Dewi   Lestari  ") == "dewi lestari"
    assert normalize_person_name("Budi Santoso (S.Kom.)") == "budi santoso"


def test_degree_only_is_empty() -> None:
    assert normalize_person_name("S.Kom.") == ""
    assert normalize_person_name("") == ""
