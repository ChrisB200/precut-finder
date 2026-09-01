from dataclasses import dataclass, fields
from datetime import datetime
from enum import Enum
from typing import Self

import numpy as np
from numpy._typing import NDArray


@dataclass
class FromRow:
    @classmethod
    def from_row(cls, row) -> Self:
        data = dict(row)

        for field in fields(cls):
            field_type = field.type

            if isinstance(field_type, type) and issubclass(field_type, Enum):
                data[field.name] = field_type(data[field.name])

        return cls(**data)


@dataclass(slots=True)
class Channel(FromRow):
    id: int


@dataclass(slots=True)
class Precut(FromRow):
    id: int
    message_id: int
    channel_id: int
    user_id: int
    created_at: datetime


@dataclass(slots=True)
class Scene(FromRow):
    id: int
    precut_id: int
    scene_index: int
    start_time: float
    end_time: float


@dataclass(slots=True)
class FrameEmbedding(FromRow):
    frame_id: int
    scene_id: int
    embedding: NDArray[np.float32]
