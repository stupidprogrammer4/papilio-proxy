from dataclasses import dataclass
from typing import Literal

from papilio.schemas.inputs import BaseDTO
from pydantic import Field


class QrPolicy(BaseDTO):
    enabled: bool
    error_correction: Literal["L", "M", "Q", "H"]
    box_size: int = Field(gt=0)
    border_modules: int = Field(ge=4)


@dataclass(frozen=True, slots=True)
class QrImage:
    content: bytes
    filename: str
