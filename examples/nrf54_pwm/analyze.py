# SPDX-FileCopyrightText: 2026 Embedder contributors
# SPDX-License-Identifier: MIT
"""Capture target compilation context and run available checks without claiming full MISRA."""

import json
import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
RESULTS = Path(__file__).with_name("results")
PORT = ROOT / "ports/zephyr-cp"
BUILD = PORT / "build-pwm-nrf54lm20"


def select_compile_commands(entries, database_directory):
    owned = [(PORT / "common-hal/pwmio" / name).resolve() for name in ("PWMOut.c", "pwm_timing.c")]
    selected = {source: [] for source in owned}
    for entry in entries:
        directory = (database_directory / entry["directory"]).resolve()
        source = (directory / entry["file"]).resolve()
        if source not in selected:
            continue
        arguments = entry["arguments"]
        if arguments.count("-o") != 1 or arguments[-1] == "-o":
            raise RuntimeError(f"Cannot identify build output for {source}")
        output = (directory / arguments[arguments.index("-o") + 1]).resolve()
        if output.is_relative_to(BUILD.resolve()):
            selected[source].append((source, directory, arguments))
    for source, matches in selected.items():
        if len(matches) != 1:
            raise RuntimeError(
                f"Expected exactly one compilation of {source} in {BUILD}; found {len(matches)}"
            )
    return [matches[0] for matches in selected.values()]


def preprocess_arguments(arguments, source, directory):
    # GCC option operands are not translation-unit inputs, even when named *.c.
    operand_options = {
        "-o",
        "-MF",
        "-MT",
        "-MQ",
        "-include",
        "-imacros",
        "-I",
        "-iquote",
        "-isystem",
        "-idirafter",
        "-isysroot",
        "--sysroot",
        "-D",
        "-U",
        "-x",
    }
    filtered = [arguments[0]]
    source_count = 0
    index = 1
    while index < len(arguments):
        value = arguments[index]
        if value in operand_options:
            if index + 1 == len(arguments) or arguments[index + 1].startswith("-"):
                raise RuntimeError(f"Missing operand for {value} in compilation of {source}")
            if value not in ("-o", "-MF"):
                filtered.extend(arguments[index : index + 2])
            index += 2
            continue
        if not value.startswith("-"):
            if (directory / value).resolve() != source:
                raise RuntimeError(f"Unexpected input {value} in compilation of {source}")
            source_count += 1
        elif value not in ("-c", "-MMD"):
            filtered.append(value)
        index += 1
    if source_count != 1:
        raise RuntimeError(
            f"Expected exactly one source operand for {source}; found {source_count}"
        )
    return filtered


def main():
    database = RESULTS / "circuitpython_compile_commands.json"
    entries = json.loads(database.read_text())
    selected = select_compile_commands(entries, database.parent)
    commands = []
    for source, directory, arguments in selected:
        output = RESULTS / (source.stem + ".pre.c")
        commands.append(
            (
                preprocess_arguments(arguments, source, directory)
                + ["-E", str(source), "-o", str(output)],
                directory,
                output,
            )
        )
    preprocessed = []
    for arguments, directory, output in commands:
        subprocess.run(arguments, cwd=directory, check=True)
        # Cppcheck does not reliably parse GCC's trailing include-state flags.
        # Normalize only line directives; preserve every C token and source location.
        output.write_text(
            re.sub(
                r'^#[ \t]+(\d+)[ \t]+("[^"\n]*")(?:[ \t]+\d+)*[ \t]*$',
                lambda match: f"#line {max(1, int(match[1]))} {match[2]}",
                output.read_text(),
                flags=re.MULTILINE,
            )
        )
        preprocessed.append(output)
    command = [
        "cppcheck",
        "--addon=misra",
        "--enable=warning,style,performance,portability",
        "--language=c",
        "--std=c17",
        "--platform=unix32",
        "--error-exitcode=1",
        "--checkers-report=" + str(RESULTS / "checkers-preprocessed.txt"),
        *(str(path) for path in preprocessed),
    ]
    with (RESULTS / "cppcheck-preprocessed.log").open("w") as output:
        status = subprocess.run(
            command, cwd=ROOT, stdout=output, stderr=subprocess.STDOUT, check=False
        ).returncode
    report = {
        "standard_requested": "MISRA C:2025",
        "checker": subprocess.check_output(["cppcheck", "--version"], text=True).strip(),
        "addon": "MISRA C:2012 subset, not full C:2025 enforcement",
        "preprocessing": "Actual ARM compiler and captured firmware flags; line markers retained",
        "translation_units": sorted(source.name for source, _, _ in selected),
        "exit_code": status,
        "compliance_claim": False,
        "remaining": [
            "Licensed C:2025 reference/manual coverage unavailable",
            "Review adopted-header and framework-boundary findings",
            "Checked-release broker code requires separate scoped review",
        ],
    }
    (RESULTS / "analysis.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report, indent=2))
    if status != 0:
        raise SystemExit(status)


if __name__ == "__main__":
    main()
