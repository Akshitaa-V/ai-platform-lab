import json

import pytest

from aiplat.evals import Task, load_tasks, run_eval, score, to_markdown, write_reports


def t(check, expected):
    return Task(id="x", prompt="p", check=check, expected=expected)


@pytest.mark.parametrize(
    ("task", "answer", "ok"),
    [
        (t("contains", "munich"), "It is Munich.", True),
        (t("contains", ["a", "b"]), "a only", False),
        (t("exact", "high"), "HIGH.", True),
        (t("exact", "high"), "very high", False),
        (t("regex", r"^\s*32\.?\s*$"), "32", True),
        (t("regex", r"^\s*32\.?\s*$"), "The answer is 32", False),
        (t("json_keys", ["a", "b"]), '```json\n{"a": 1, "b": 2}\n```', True),
        (t("json_keys", ["a", "b"]), '{"a": 1}', False),
        (
            t("json_keys", {"part": "VLV-220", "qty": "4"}),
            'Sure: {"part": "vlv-220", "qty": 4}',
            True,
        ),
        (t("json_keys", ["a"]), "no json here", False),
        (t("json_keys", ["a"]), "{not valid}", False),
    ],
)
def test_score(task, answer, ok):
    assert score(task, answer) is ok


def test_unknown_check_is_rejected():
    with pytest.raises(ValueError, match="unknown check"):
        Task(id="x", prompt="p", check="vibes", expected="")


def test_shipped_task_set_loads_and_is_well_formed():
    tasks = load_tasks("evals/tasks.jsonl")
    assert len(tasks) >= 10
    assert len({task.id for task in tasks}) == len(tasks)


def test_duplicate_ids_are_rejected(tmp_path):
    path = tmp_path / "tasks.jsonl"
    row = json.dumps({"id": "a", "prompt": "p", "check": "exact", "expected": "x"})
    path.write_text(f"{row}\n{row}\n")
    with pytest.raises(ValueError, match="duplicate"):
        load_tasks(path)


def test_run_eval_ranks_models_and_records_errors(client, fake_gateway, tmp_path):
    tasks = [
        Task(id="capital", prompt="Capital of Bavaria?", check="contains", expected="munich"),
        Task(id="ready", prompt="Say ready", check="contains", expected="ready"),
    ]
    fake_gateway.answers["broken"] = {"default": ""}
    fake_gateway.fail_models.add("broken")
    reports = run_eval(client, ["qwen2.5-0.5b", "llama3.2-1b", "broken"], tasks)

    assert [r.model for r in reports] == ["llama3.2-1b", "qwen2.5-0.5b", "broken"]
    assert (reports[0].passed, reports[1].passed, reports[2].passed) == (2, 1, 0)
    assert reports[2].errors == 2 and reports[2].p50_latency is None

    md_path = write_reports(reports, tasks, tmp_path)
    md = md_path.read_text()
    assert "| 1 | llama3.2-1b | 2/2 | 100% |" in md
    assert "**qwen2.5-0.5b**: capital" in md
    data = json.loads((tmp_path / "results.json").read_text())
    assert data["leaderboard"][0]["model"] == "llama3.2-1b"
    assert to_markdown(reports, tasks) == md
