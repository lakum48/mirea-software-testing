import pytest

from calculator import Calculator


@pytest.fixture
def calc() -> Calculator:
    return Calculator()


@pytest.mark.parametrize(
    ("a", "b", "expected"),
    [(2, 3, 5), (-8, 5, -3), (0, 0, 0), (10**40, 1, 10**40 + 1)],
    ids=["positive", "mixed", "zero", "large-int"],
)
def test_add(calc: Calculator, a: int, b: int, expected: int) -> None:
    result = calc.add(a, b)
    assert result == expected


@pytest.mark.parametrize(
    ("a", "b", "expected"),
    [(8, 3, 5), (0, -3, 3), (-8, -3, -5)],
)
def test_subtract(calc: Calculator, a: int, b: int, expected: int) -> None:
    result = calc.subtract(a, b)
    assert result == expected


@pytest.mark.parametrize(
    ("a", "b", "expected"),
    [(4, 5, 20), (10**40, 0, 0), (-6, -2, 12)],
)
def test_multiply(calc: Calculator, a: int, b: int, expected: int) -> None:
    result = calc.multiply(a, b)
    assert result == expected


@pytest.mark.parametrize(
    ("a", "b", "expected"),
    [(10, 2, 5.0), (-1.0, 3.0, -0.3333333333333333), (0.0, 2.5, 0.0)],
)
def test_divide(calc: Calculator, a: float, b: float, expected: float) -> None:
    result = calc.divide(a, b)
    assert result == pytest.approx(expected)


@pytest.mark.parametrize("zero", [0, -0.0])
def test_divide_by_zero(calc: Calculator, zero: float) -> None:
    with pytest.raises(ValueError, match="Деление на ноль"):
        calc.divide(5, zero)
