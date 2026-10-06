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


def main():
    entries = json.loads((RESULTS / "circuitpython_compile_commands.json").read_text())
    owned = {"PWMOut.c", "pwm_timing.c"}
    preprocessed = []
    for entry in entries:
        source = Path(entry["file"])
        if source.name not in owned:
            continue
        arguments = list(entry["arguments"])
        for flag in ("-c", "-o", "-MF"):
            if flag in arguments:
                index = arguments.index(flag)
                del arguments[index : index + 2]
        arguments = [value for value in arguments if value != "-MMD"]
        output = RESULTS / (source.stem + ".pre.c")
        subprocess.run(
            arguments + ["-E", str(source), "-o", str(output)], cwd=entry["directory"], check=True
        )
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
    if len(preprocessed) != 2:
        raise RuntimeError("The build did not capture both owned backend compilation units")
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
        "translation_units": sorted(owned),
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
