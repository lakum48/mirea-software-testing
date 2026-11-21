import os
import random
import shutil
import subprocess
import sys
from pathlib import Path
from tempfile import TemporaryDirectory

ROOT = Path(__file__).resolve().parent


class RandomOrder:
    def pytest_collection_modifyitems(self, items: list) -> None:
        random.Random(2026).shuffle(items)


def run_copy(relative: str, original: str, replacement: str, tests: list[str]) -> None:
    with TemporaryDirectory() as directory:
        target = Path(directory)
        for name in ["app", "warmup", "conftest.py", "test_bikes.py"]:
            source = ROOT / name
            if source.is_dir():
                shutil.copytree(source, target / name)
            else:
                shutil.copyfile(source, target / name)
        path = target / relative
        content = path.read_text(encoding="utf-8")
        assert content.count(original) == 1
        path.write_text(content.replace(original, replacement), encoding="utf-8")
        print(f"\n{relative} | {original} -> {replacement}", flush=True)
        result = subprocess.run(
            [sys.executable, "-m", "pytest", "-p", "no:cacheprovider", "-q", "--tb=short", *tests],
            cwd=target,
            env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
            check=False,
        )
        if result.returncode != 1:
            raise RuntimeError(f"Ожидалось падение проверки. Код завершения {result.returncode}")


if __name__ == "__main__":
    import pytest

    run_copy("warmup/app_v0.py", "next(sequence)", "len(ITEMS) + 1", ["warmup/test_id.py"])
    run_copy("app/main.py", "new_value.between(0, 25)", "new_value.between(0, 24)",
             ["test_bikes.py::test_stock_can_reach_both_boundaries"])
    run_copy("app/main.py", "bike.price * provider(currency)", "bike.price / provider(currency)",
             ["test_bikes.py::test_currency_conversion"])
    raise SystemExit(pytest.main(["-q", "-p", "no:cacheprovider", "--tb=short"], plugins=[RandomOrder()]))
