import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path
from tempfile import TemporaryDirectory

ROOT = Path(__file__).resolve().parent


def run_tests(folder: Path, targets: list[str], *, delay: int, channel: str | None, trace_dir: Path | None = None) -> int:
    command = [sys.executable, "-m", "pytest", "-p", "no:cacheprovider", "-q", "--tb=short", *targets]
    if channel:
        command.extend(["--browser-channel", channel])
    if trace_dir:
        command.extend(["--tracing", "retain-on-failure", "--output", str(trace_dir)])
    process = subprocess.run(
        command,
        cwd=folder,
        env={**os.environ, "TODO_DELAY_MS": str(delay), "PYTHONDONTWRITEBYTECODE": "1"},
        check=False,
    )
    return process.returncode


def experiment(*, channel: str | None, dest: Path) -> None:
    print("Разминка. Десять независимых прогонов без задержки.", flush=True)
    failures = 0
    for index in range(10):
        print(f"Прогон {index + 1}", flush=True)
        code = run_tests(ROOT, ["warmup_demo.py::test_flaky"], delay=0, channel=channel)
        if code not in (0, 1):
            raise RuntimeError(f"Ошибка запуска {code}")
        failures += code
    print(f"Без задержки: не прошли {failures} из 10.", flush=True)
    for name, expected in [("test_flaky", 1), ("test_stable", 0)]:
        print(f"Задержка 800 мс, {name}", flush=True)
        code = run_tests(ROOT, [f"warmup_demo.py::{name}"], delay=800, channel=channel)
        if code != expected:
            raise RuntimeError(f"Получено {code}, ожидалось {expected}")
    variants = [
        ("MAX_LEN = 100", "MAX_LEN = 99", "test_title_boundaries[chromium-100]"),
        ("todos.filter((t) => !t.done).length", "todos.length", "test_complete"),
    ]
    for index, (original, replacement, target) in enumerate(variants):
        with TemporaryDirectory() as directory:
            folder = Path(directory)
            for name in ("conftest.py", "test_todo.py", "pages.py"):
                shutil.copyfile(ROOT / name, folder / name)
            shutil.copytree(ROOT / "app", folder / "app")
            source = folder / "app" / "server.py"
            text = source.read_text(encoding="utf-8")
            assert text.count(original) == 1
            source.write_text(text.replace(original, replacement), encoding="utf-8")
            print(f"Модификация {index + 1}. {original} -> {replacement}", flush=True)
            code = run_tests(
                folder, [f"test_todo.py::{target}"], delay=0, channel=channel,
                trace_dir=dest / "trace-run" if index == 1 else None,
            )
            if code != 1:
                raise RuntimeError(f"Модификация {index + 1}: ожидаемое падение не обнаружено")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--channel", help="Например, msedge. По умолчанию используется установленный Chromium Playwright.")
    parser.add_argument("--dest", type=Path, default=ROOT / "evidence")
    args = parser.parse_args()
    experiment(channel=args.channel, dest=args.dest.resolve())
