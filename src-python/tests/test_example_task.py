"""Tests for example_task script."""

from app.scripts import example_task


def test_run_counts_lines():
    params = example_task.Params(input_path="hello", threshold=0.5)
    result = example_task.run(params)
    assert isinstance(result, example_task.Result)
    assert result.count == 10
    assert result.output_path == "hello.out"


def test_progress_callback_receives_events():
    seen: list = []
    params = example_task.Params(input_path="x")
    example_task.run(params, progress=lambda pct, msg="": seen.append((pct, msg)))
    assert seen[0][0] == 10.0
    assert seen[-1][0] == 100.0
