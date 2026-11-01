"""ITE family choices; model-specific experiments stay outside the GUI."""
from dataclasses import dataclass


@dataclass(frozen=True)
class Family:
    name: str
    read_protocol: bool = False


FAMILIES = (
    Family("IT51xx"),
    Family("IT55xx"),
    Family("IT8xxx", True),
)

FAMILIES_BY_MANUFACTURER = {"ITE": FAMILIES}
