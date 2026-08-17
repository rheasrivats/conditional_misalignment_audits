from scripts.score_conditional_misalignment_replication_new_rows_v1 import mean_numeric, summarize


def test_summarize_applies_eligibility_denominator() -> None:
    rows = [
        {"eligible": True, "misaligned": True, "alignment_numeric": True, "coherence_numeric": True, "coherence_pass": True},
        {"eligible": True, "misaligned": False, "alignment_numeric": True, "coherence_numeric": True, "coherence_pass": True},
        {"eligible": False, "misaligned": False, "alignment_numeric": False, "coherence_numeric": True, "coherence_pass": True},
        {"eligible": False, "misaligned": False, "alignment_numeric": True, "coherence_numeric": True, "coherence_pass": False},
    ]
    result = summarize(rows)
    assert result["eligible"] == 2
    assert result["misaligned"] == 1
    assert result["pooled_response_misalignment_rate"] == 0.5
    assert result["alignment_nonnumeric"] == 1
    assert result["coherence_at_or_below_threshold"] == 1


def test_mean_numeric_ignores_empty_cells() -> None:
    assert mean_numeric([0.0, None, 1.0]) == 0.5
    assert mean_numeric([None]) is None
