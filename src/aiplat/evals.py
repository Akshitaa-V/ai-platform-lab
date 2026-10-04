"""Compare models served through the gateway on a fixed task set.

Each task has a prompt and one deterministic check, so two runs on the same
models are directly comparable. Results are written as JSON and as a Markdown
leaderboard.
"""

from __future__ import annotations

import json
import re
import statistics
from dataclasses import asdict, dataclass, field
from pathlib import Path

from aiplat.gateway import GatewayClient, GatewayError

CHECKS = ("contains", "exact", "regex", "json_keys")
_FENCE = re.compile(r"^```(?:json)?\s*|\s*```$", re.IGNORECASE)


@dataclass(frozen=True)
class Task:
    id: str
    prompt: str
    check: str
    expected: object
    system: str | None = None

    def __post_init__(self) -> None:
        if self.check not in CHECKS:
            raise ValueError(f"task {self.id}: unknown check {self.check!r}")


def load_tasks(path: str | Path) -> list[Task]:
    tasks = []
    for line_no, line in enumerate(Path(path).read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            raw = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ValueError(f"{path}:{line_no}: invalid JSON") from exc
        tasks.append(Task(**raw))
    ids = [t.id for t in tasks]
    if len(ids) != len(set(ids)):
        raise ValueError(f"{path}: duplicate task ids")
    return tasks


def _extract_json(text: str) -> object:
    cleaned = _FENCE.sub("", text.strip())
    start, end = cleaned.find("{"), cleaned.rfind("}")
    if start == -1 or end < start:
        raise ValueError("no JSON object in answer")
    return json.loads(cleaned[start : end + 1])


def score(task: Task, answer: str) -> bool:
    text = answer.strip()
    if task.check == "contains":
        needles = task.expected if isinstance(task.expected, list) else [task.expected]
        return all(str(n).lower() in text.lower() for n in needles)
    if task.check == "exact":
        return text.strip(" .\n").lower() == str(task.expected).strip().lower()
    if task.check == "regex":
        return re.search(str(task.expected), text, re.IGNORECASE | re.DOTALL) is not None
    try:
        obj = _extract_json(text)
    except ValueError:
        return False
    if not isinstance(obj, dict):
        return False
    expected = task.expected
    if isinstance(expected, dict):
        return all(str(obj.get(k, "")).lower() == str(v).lower() for k, v in expected.items())
    return all(k in obj for k in expected)


@dataclass
class TaskResult:
    task_id: str
    passed: bool
    latency_s: float | None
    tokens: int
    error: str | None = None
    answer: str = ""


@dataclass
class ModelReport:
    model: str
    results: list[TaskResult] = field(default_factory=list)

    @property
    def total(self) -> int:
        return len(self.results)

    @property
    def passed(self) -> int:
        return sum(r.passed for r in self.results)

    @property
    def errors(self) -> int:
        return sum(r.error is not None for r in self.results)

    @property
    def pass_rate(self) -> float:
        return self.passed / self.total if self.total else 0.0

    @property
    def latencies(self) -> list[float]:
        return [r.latency_s for r in self.results if r.latency_s is not None]

    @property
    def p50_latency(self) -> float | None:
        return statistics.median(self.latencies) if self.latencies else None

    @property
    def total_tokens(self) -> int:
        return sum(r.tokens for r in self.results)

    def summary(self) -> dict:
        return {
            "model": self.model,
            "passed": self.passed,
            "total": self.total,
            "pass_rate": round(self.pass_rate, 3),
            "errors": self.errors,
            "p50_latency_s": round(self.p50_latency, 3) if self.p50_latency is not None else None,
            "total_tokens": self.total_tokens,
        }


def run_eval(
    client: GatewayClient, models: list[str], tasks: list[Task], max_tokens: int = 200
) -> list[ModelReport]:
    reports = []
    for model in models:
        report = ModelReport(model)
        for task in tasks:
            try:
                result = client.chat(model, task.prompt, max_tokens=max_tokens, system=task.system)
            except GatewayError as exc:
                report.results.append(TaskResult(task.id, False, None, 0, error=str(exc)))
                continue
            report.results.append(
                TaskResult(
                    task.id,
                    score(task, result.text),
                    result.latency_s,
                    result.total_tokens,
                    answer=result.text[:500],
                )
            )
        reports.append(report)
    return leaderboard(reports)


def leaderboard(reports: list[ModelReport]) -> list[ModelReport]:
    def key(r: ModelReport) -> tuple:
        return (-r.pass_rate, r.p50_latency if r.p50_latency is not None else float("inf"))

    return sorted(reports, key=key)


def to_markdown(reports: list[ModelReport], tasks: list[Task]) -> str:
    lines = [
        "# Model leaderboard",
        "",
        f"{len(tasks)} tasks, one deterministic check per task, temperature 0.",
        "",
        "| Rank | Model | Passed | Pass rate | Errors | p50 latency (s) | Tokens |",
        "|---:|---|---:|---:|---:|---:|---:|",
    ]
    for rank, r in enumerate(reports, 1):
        s = r.summary()
        p50 = f"{s['p50_latency_s']:.2f}" if s["p50_latency_s"] is not None else "-"
        lines.append(
            f"| {rank} | {r.model} | {r.passed}/{r.total} | {r.pass_rate:.0%} | {r.errors} "
            f"| {p50} | {r.total_tokens} |"
        )
    lines += ["", "## Failed tasks", ""]
    for r in reports:
        failed = [t.task_id for t in r.results if not t.passed]
        lines.append(f"- **{r.model}**: {', '.join(failed) if failed else 'none'}")
    return "\n".join(lines) + "\n"


def write_reports(reports: list[ModelReport], tasks: list[Task], out_dir: str | Path) -> Path:
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    payload = {
        "leaderboard": [r.summary() for r in reports],
        "results": {r.model: [asdict(t) for t in r.results] for r in reports},
    }
    (out / "results.json").write_text(json.dumps(payload, indent=2), encoding="utf-8")
    md_path = out / "leaderboard.md"
    md_path.write_text(to_markdown(reports, tasks), encoding="utf-8")
    return md_path
