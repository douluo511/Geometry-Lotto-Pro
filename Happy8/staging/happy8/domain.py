from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import date, datetime
import re


ISSUE_RE = re.compile(r"^\d{7}$")


@dataclass(frozen=True)
class Draw:
    issue: str
    draw_date: str
    numbers: tuple[int, ...]

    def validate(self) -> None:
        if not ISSUE_RE.fullmatch(str(self.issue)):
            raise ValueError(f"invalid Happy8 issue: {self.issue!r}")
        try:
            parsed = datetime.strptime(str(self.draw_date)[:10], "%Y-%m-%d").date()
        except ValueError as exc:
            raise ValueError(f"invalid draw date: {self.draw_date!r}") from exc
        if parsed > date.today():
            raise ValueError(f"draw date is in the future: {parsed.isoformat()}")
        if len(self.numbers) != 20 or len(set(self.numbers)) != 20:
            raise ValueError("Happy8 draw must contain exactly 20 unique numbers")
        if tuple(sorted(self.numbers)) != tuple(self.numbers):
            raise ValueError("Happy8 canonical numbers must be sorted")
        if any(n < 1 or n > 80 for n in self.numbers):
            raise ValueError("Happy8 numbers must be in 1..80")

    def to_dict(self) -> dict:
        self.validate()
        value = asdict(self)
        value["numbers"] = list(self.numbers)
        return value

    @classmethod
    def from_values(cls, issue: str, draw_date: str, numbers) -> "Draw":
        draw = cls(str(issue), str(draw_date)[:10], tuple(sorted(int(n) for n in numbers)))
        draw.validate()
        return draw
