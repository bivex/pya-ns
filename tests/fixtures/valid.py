"""Valid Python module for testing."""

from dataclasses import dataclass
from typing import List


MY_CONSTANT = 42


def greet(name: str) -> str:
    return f"Hello, {name}!"


@dataclass
class Person:
    name: str
    age: int

    def is_adult(self) -> bool:
        return self.age >= 18
