def test_leave_one_out_change_identity() -> None:
    full = 0.029123069990425424
    excluded = 0.15789473684210525
    leave_one_out = (26 * full - excluded) / 25
    assert abs(leave_one_out - 0.02397220331635823) < 1e-15
    assert abs((leave_one_out - full) - (full - excluded) / 25) < 1e-15
