from __future__ import annotations


EXPECTED_CASE_IDS = (
    *(f"SEM-REL-{number:03d}" for number in range(1, 13)),
    *(f"SEM-NET-{number:03d}" for number in range(13, 21)),
    *(f"SEM-CAL-{number:03d}" for number in range(21, 31)),
    *(f"SEM-MIL-{number:03d}" for number in range(31, 35)),
    *(f"SEM-CON-{number:03d}" for number in range(35, 39)),
    *(f"SEM-STA-{number:03d}" for number in range(39, 47)),
    *(f"SEM-FLT-{number:03d}" for number in range(47, 49)),
    *(f"SEM-DET-{number:03d}" for number in range(49, 51)),
)

EXPECTED_FILENAME_BY_ID = {
    case_id: f"{case_id.lower()}.json" for case_id in EXPECTED_CASE_IDS
}
EXPECTED_ID_BY_FILENAME = {
    filename: case_id for case_id, filename in EXPECTED_FILENAME_BY_ID.items()
}
