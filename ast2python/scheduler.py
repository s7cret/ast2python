from __future__ import annotations

from dataclasses import dataclass, field

from ast2python.context import TranslationContext
from ast2python.emitter import CodeEmitter


@dataclass
class ScheduleEntry:
    """Single entry in the execution schedule."""

    kind: str  # 'init', 'calc', 'visual', 'strategy', 'input', 'function'
    name: str
    priority: int = 0
    dependencies: list[str] = field(default_factory=list)


class Scheduler:
    """Canonical scheduler for Pine Script execution model.

    Responsible for ordering initialization, calculation, and output
    phases in the generated Python code.
    """

    def __init__(self, ctx: TranslationContext, emitter: CodeEmitter) -> None:
        self.ctx = ctx
        self.emitter = emitter
        self.schedule: list[ScheduleEntry] = []
        self._phase: str = "init"

    def add_entry(self, entry: ScheduleEntry) -> None:
        """Add an entry to the schedule."""
        self.schedule.append(entry)

    def sort(self) -> None:
        """Topological sort by priority and dependencies."""
        # Simple sort by priority (higher first)
        self.schedule.sort(key=lambda e: (-e.priority, e.name))

    def emit_init_phase(self) -> None:
        """Emit initialization phase (var declarations, inputs)."""
        self._phase = "init"
        self.emitter.line("# --- Init phase ---")
        for entry in self.schedule:
            if entry.kind == "init":
                self.emitter.line(f"# init: {entry.name}")

    def emit_calc_phase(self) -> None:
        """Emit calculation phase (series updates, function calls)."""
        self._phase = "calc"
        self.emitter.line("# --- Calc phase ---")
        for entry in self.schedule:
            if entry.kind == "calc":
                self.emitter.line(f"# calc: {entry.name}")

    def emit_visual_phase(self) -> None:
        """Emit visual output phase (plot*, hline, etc)."""
        self._phase = "visual"
        self.emitter.line("# --- Visual phase ---")
        for entry in self.schedule:
            if entry.kind == "visual":
                self.emitter.line(f"# visual: {entry.name}")

    def emit_strategy_phase(self) -> None:
        """Emit strategy execution phase (entry, exit, etc)."""
        self._phase = "strategy"
        self.emitter.line("# --- Strategy phase ---")
        for entry in self.schedule:
            if entry.kind == "strategy":
                self.emitter.line(f"# strategy: {entry.name}")

    def emit_schedule(self) -> None:
        """Emit full schedule in canonical order."""
        self.sort()
        self.emit_init_phase()
        self.emitter.line()
        self.emit_calc_phase()
        self.emitter.line()
        if any(e.kind == "visual" for e in self.schedule):
            self.emit_visual_phase()
            self.emitter.line()
        if any(e.kind == "strategy" for e in self.schedule):
            self.emit_strategy_phase()
            self.emitter.line()
