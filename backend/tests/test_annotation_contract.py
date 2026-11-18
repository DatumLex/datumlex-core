import pytest

from src.nlp.contracts import validate_annotation


def annotation(segments):
    return {"labels": ["LEGAL_THESIS"], "label_status": "proposed", "segments": segments}


def segment(start, end, text):
    return {"start": start, "end": end, "text": text}


def test_accepts_adjacent_unicode_segments():
    validate_annotation(annotation([segment(0, 1, "⚖"), segment(1, 3, "ão")]), "⚖ão")


@pytest.mark.parametrize(
    ("segments", "error"),
    [
        ([], "missing_segments"),
        ([segment(False, 1, "a")], "non_integer_offset"),
        ([segment(0, 1.5, "a")], "non_integer_offset"),
        ([segment(-1, 1, "a")], "invalid_offset"),
        ([segment(1, 1, "")], "invalid_offset"),
        ([segment(0, 4, "abc")], "invalid_offset"),
        ([segment(0, 2, "ab"), segment(1, 3, "bc")], "invalid_offset"),
        ([segment(0, 2, "ac")], "quote_mismatch"),
    ],
)
def test_rejects_invalid_evidence_segments(segments, error):
    with pytest.raises(ValueError, match=f"^{error}$"):
        validate_annotation(annotation(segments), "abc")


@pytest.mark.parametrize(
    ("change", "error"),
    [
        ({"labels": []}, "invalid_labels"),
        ({"labels": ["LEGAL_THESIS", "OTHER"]}, "invalid_labels"),
        ({"label_status": "approved"}, "automatic_approval_forbidden"),
    ],
)
def test_rejects_invalid_annotation_metadata(change, error):
    with pytest.raises(ValueError, match=f"^{error}$"):
        validate_annotation(annotation([segment(0, 1, "a")]) | change, "a")
