"""Keyword search over the platform runbooks (docs/runbooks/*.md).

Each Markdown file is split at its `##` headings, and sections are ranked with
TF-IDF so a question like "how do I rotate the gateway key" lands on the right
section of the right runbook.
"""

from __future__ import annotations

import math
import re
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

_TOKEN = re.compile(r"[a-z0-9]+")
_STOP = frozenset(
    (
        "a an and are as at be by do for from how i in is it of on or the to what when with "
        "you your"
    ).split()
)


def tokenize(text: str) -> list[str]:
    return [t for t in _TOKEN.findall(text.lower()) if t not in _STOP]


@dataclass(frozen=True)
class Section:
    doc: str
    heading: str
    text: str


@dataclass(frozen=True)
class Hit:
    doc: str
    heading: str
    score: float
    snippet: str

    def as_dict(self) -> dict:
        return {
            "doc": self.doc,
            "heading": self.heading,
            "score": round(self.score, 3),
            "snippet": self.snippet,
        }


def load_sections(directory: str | Path) -> list[Section]:
    sections = []
    for path in sorted(Path(directory).glob("*.md")):
        title, heading, buf = path.stem, path.stem, []
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.startswith("# "):
                title = heading = line[2:].strip()
            elif line.startswith("## "):
                if "".join(buf).strip():
                    sections.append(Section(path.name, heading, "\n".join(buf).strip()))
                heading, buf = f"{title} / {line[3:].strip()}", []
            else:
                buf.append(line)
        if "".join(buf).strip():
            sections.append(Section(path.name, heading, "\n".join(buf).strip()))
    return sections


class RunbookIndex:
    def __init__(self, sections: list[Section]) -> None:
        self.sections = sections
        self._tf = [Counter(tokenize(f"{s.heading} {s.text}")) for s in sections]
        df = Counter(term for tf in self._tf for term in tf)
        n = len(sections)
        self._idf = {term: math.log((1 + n) / (1 + count)) + 1 for term, count in df.items()}

    @classmethod
    def from_dir(cls, directory: str | Path) -> RunbookIndex:
        return cls(load_sections(directory))

    def search(self, query: str, top_k: int = 3) -> list[Hit]:
        terms = tokenize(query)
        if not terms:
            return []
        scored = []
        for section, tf in zip(self.sections, self._tf, strict=True):
            length = sum(tf.values()) or 1
            value = sum((tf[t] / length) * self._idf.get(t, 0.0) for t in terms)
            if value > 0:
                scored.append((value, section))
        scored.sort(key=lambda pair: pair[0], reverse=True)
        return [
            Hit(s.doc, s.heading, value, " ".join(s.text.split())[:400])
            for value, s in scored[: max(1, top_k)]
        ]
