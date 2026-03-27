"""Python control flow examples for testing."""


def simple_if(x: int) -> int:
    if x > 0:
        return x
    else:
        return -x


def nested_if(x: int, y: int) -> int:
    if x > 0:
        if y > 0:
            return x + y
        else:
            return x - y
    else:
        return 0


def while_loop(n: int) -> int:
    result = 0
    i = 0
    while i < n:
        result += i
        i += 1
    return result


def for_loop(items: List[int]) -> int:
    result = 0
    for item in items:
        result += item
    return result


def try_except(value: str) -> int:
    try:
        return int(value)
    except ValueError:
        return 0
    finally:
        print("done")


def with_statement(path: str) -> str:
    with open(path) as f:
        return f.read()


async def async_function(x: int) -> int:
    await some_async_operation()
    return x * 2
