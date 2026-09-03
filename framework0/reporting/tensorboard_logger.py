from __future__ import annotations

import time
from dataclasses import dataclass
from pathlib import Path


@dataclass
class TensorBoardLogger:
    log_dir: Path

    def __post_init__(self) -> None:
        from tensorboard.compat.proto.event_pb2 import Event
        from tensorboard.compat.proto.summary_pb2 import Summary
        from tensorboard.summary.writer.event_file_writer import EventFileWriter

        self._event_cls = Event
        self._summary_cls = Summary
        self._writer = EventFileWriter(str(self.log_dir))

    def add_scalar(self, tag: str, value: float, step: int) -> None:
        summary = self._summary_cls(value=[self._summary_cls.Value(tag=tag, simple_value=float(value))])
        event = self._event_cls(wall_time=time.time(), step=step, summary=summary)
        self._writer.add_event(event)
        self._writer.flush()

    def close(self) -> None:
        self._writer.close()


def create_tensorboard_logger(log_dir: Path) -> TensorBoardLogger:
    log_dir.mkdir(parents=True, exist_ok=True)
    return TensorBoardLogger(log_dir=log_dir)