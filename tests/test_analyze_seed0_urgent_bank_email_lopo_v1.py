def test_leave_one_out_mean_identity() -> None:
    prompt_effects = [0.15789473684210525] + [0.02397220331635823] * 25
    full = sum(prompt_effects) / 26
    lopo = sum(prompt_effects[1:]) / 25
    assert abs(full - 0.029123069990425424) < 1e-15
    assert abs(lopo - 0.02397220331635823) < 1e-15
