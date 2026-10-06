# SPDX-FileCopyrightText: 2026 Embedder contributors
# SPDX-License-Identifier: MIT

import atexit
import importlib.util
import json
import os
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[4]


def load_module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def cpbuild(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    # test_zephyr2cp installs a global mock; load the real module under a separate name.
    # Import must not register writers that run when the pytest process exits.
    with monkeypatch.context() as importing:
        importing.setattr(atexit, "register", lambda function: None)
        importing.setenv("MAKEFLAGS", "")
        module = load_module(
            "compile_commands_cpbuild", ROOT / "ports/zephyr-cp/cptools/cpbuild.py"
        )
    return module


@pytest.fixture
def analyze(monkeypatch, tmp_path):
    module = load_module("pwm_compile_commands_analyze", ROOT / "examples/nrf54_pwm/analyze.py")
    root = tmp_path / "checkout"
    port = root / "ports/zephyr-cp"
    build = port / "build-pwm-nrf54lm20"
    results = tmp_path / "results"
    results.mkdir()
    for name, value in (("ROOT", root), ("PORT", port), ("BUILD", build), ("RESULTS", results)):
        monkeypatch.setattr(module, name, value)
    return module


def compile_entry(directory, source, output, *, relative=False, extra=()):
    return {
        "directory": str(directory),
        "file": os.path.relpath(source, directory) if relative else str(source),
        "arguments": [
            "arm-gcc",
            "-Iinclude",
            "-DCIRCUITPY_PWMIO=1",
            "-MMD",
            "-MF",
            os.path.relpath(output.with_suffix(".d"), directory),
            "-c",
            os.path.relpath(source, directory) if relative else str(source),
            *extra,
            "-o",
            os.path.relpath(output, directory) if relative else str(output),
        ],
    }


def owned_entries(analyze, *, directory=None, relative=False):
    directory = directory or analyze.ROOT
    return [
        compile_entry(
            directory,
            analyze.PORT / "common-hal/pwmio" / name,
            analyze.BUILD / "objects" / Path(name).with_suffix(".o"),
            relative=relative,
        )
        for name in ("PWMOut.c", "pwm_timing.c")
    ]


def assert_main_rejects(analyze, monkeypatch, entries, message):
    database = analyze.RESULTS / "circuitpython_compile_commands.json"
    database.write_text(json.dumps(entries))
    for name in ("PWMOut.pre.c", "pwm_timing.pre.c", "analysis.json", "cppcheck-preprocessed.log"):
        (analyze.RESULTS / name).write_text("previous evidence\n")
    before = {path.name: path.read_bytes() for path in analyze.RESULTS.iterdir()}

    def unexpected(*args, **kwargs):
        pytest.fail("Invalid compilation database must not start any subprocess")

    monkeypatch.setattr(analyze.subprocess, "run", unexpected)
    monkeypatch.setattr(analyze.subprocess, "check_output", unexpected)
    with pytest.raises(RuntimeError, match=message):
        analyze.main()
    assert {path.name: path.read_bytes() for path in analyze.RESULTS.iterdir()} == before


@pytest.mark.parametrize("relative", [False, True])
@pytest.mark.parametrize("from_build_directory", [False, True])
def test_select_exact_sources_and_build(analyze, relative, from_build_directory):
    directory = analyze.BUILD if from_build_directory else analyze.ROOT
    wanted = owned_entries(analyze, directory=directory, relative=relative)
    other_build = analyze.PORT / "build-other"
    unrelated = [
        compile_entry(
            analyze.ROOT,
            analyze.PORT / "common-hal/pwmio/PWMOut.c",
            other_build / "PWMOut.o",
        ),
        compile_entry(
            analyze.ROOT,
            analyze.ROOT / "ports/nrf/common-hal/pwmio/PWMOut.c",
            analyze.BUILD / "nrf/PWMOut.o",
        ),
        compile_entry(
            analyze.ROOT,
            analyze.ROOT / "shared-bindings/pwmio/PWMOut.c",
            analyze.BUILD / "bindings/PWMOut.o",
        ),
        compile_entry(
            analyze.ROOT,
            analyze.PORT / "common-hal/pwmio/pwm_timing.c",
            analyze.PORT / "build-pwm-nrf54lm20-other/pwm_timing.o",
        ),
    ]
    selected = analyze.select_compile_commands(unrelated + wanted, analyze.RESULTS)
    assert [(source.name, cwd, arguments) for source, cwd, arguments in selected] == [
        (Path(entry["file"]).name, directory, entry["arguments"]) for entry in wanted
    ]
    assert all(source.is_absolute() for source, _, _ in selected)


def test_relative_directory_uses_database_location(analyze):
    entries = owned_entries(analyze, relative=True)
    for entry in entries:
        entry["directory"] = os.path.relpath(analyze.ROOT, analyze.RESULTS)
    selected = analyze.select_compile_commands(entries, analyze.RESULTS)
    assert all(directory == analyze.ROOT for _, directory, _ in selected)


@pytest.mark.parametrize("missing", [0, 1, 2])
def test_missing_owned_entries_fail_before_effects(analyze, monkeypatch, missing):
    entries = owned_entries(analyze)
    del entries[:missing]
    if missing == 0:
        entries[0]["file"] = str(analyze.ROOT / "ports/nrf/common-hal/pwmio/PWMOut.c")
    assert_main_rejects(analyze, monkeypatch, entries, "Expected exactly one compilation")


def test_other_build_is_not_a_missing_source_fallback(analyze, monkeypatch):
    entries = owned_entries(analyze)
    entries[1]["arguments"][-1] = str(analyze.PORT / "build-other/pwm_timing.o")
    assert_main_rejects(analyze, monkeypatch, entries, "found 0")


@pytest.mark.parametrize("same_output", [False, True])
def test_duplicates_and_build_ambiguity_fail_before_effects(analyze, monkeypatch, same_output):
    entries = owned_entries(analyze)
    duplicate = owned_entries(analyze, relative=True)[0]
    if not same_output:
        duplicate["arguments"][-1] = str(analyze.BUILD / "other/PWMOut.o")
    entries.append(duplicate)
    assert_main_rejects(analyze, monkeypatch, entries, "found 2")


@pytest.mark.parametrize("malformation", ["missing", "trailing", "duplicate"])
def test_unidentifiable_build_output_fails_before_effects(analyze, monkeypatch, malformation):
    entries = owned_entries(analyze)
    arguments = entries[1]["arguments"]
    if malformation == "missing":
        del arguments[-2:]
    elif malformation == "trailing":
        arguments.pop()
    else:
        arguments.extend(["-o", str(analyze.BUILD / "another.o")])
    assert_main_rejects(analyze, monkeypatch, entries, "Cannot identify build output")


def test_all_arguments_are_validated_before_preprocessing(analyze, monkeypatch):
    entries = owned_entries(analyze)
    entries[1]["arguments"].append("-MF")
    assert_main_rejects(analyze, monkeypatch, entries, "Missing operand for -MF")


@pytest.mark.parametrize("malformation", ["mismatch", "missing", "duplicate", "extra"])
@pytest.mark.parametrize("relative", [False, True])
def test_source_operands_fail_before_any_effects(analyze, monkeypatch, malformation, relative):
    entries = owned_entries(analyze, relative=relative)
    arguments = entries[1]["arguments"]
    source_index = arguments.index("-c") + 1
    if malformation == "mismatch":
        arguments[source_index] = entries[0]["file"]
        message = "Unexpected input"
    elif malformation == "missing":
        del arguments[source_index]
        message = "found 0"
    elif malformation == "duplicate":
        arguments.append(str(analyze.PORT / "common-hal/pwmio/pwm_timing.c"))
        message = "found 2"
    else:
        arguments.append("ports/nrf/common-hal/pwmio/PWMOut.c")
        message = "Unexpected input"
    assert_main_rejects(analyze, monkeypatch, entries, message)


@pytest.mark.parametrize("option", ["-include", "-imacros", "-MT", "-MQ"])
def test_option_operand_cannot_replace_missing_source(analyze, monkeypatch, option):
    entries = owned_entries(analyze)
    arguments = entries[1]["arguments"]
    source = arguments.pop(arguments.index("-c") + 1)
    arguments.extend([option, source])
    assert_main_rejects(analyze, monkeypatch, entries, "found 0")


@pytest.mark.parametrize("operand_is_source", [False, True])
def test_preserve_gcc_option_operands_and_compiler_path(analyze, operand_is_source):
    entry = owned_entries(analyze, relative=True)[0]
    source = analyze.PORT / "common-hal/pwmio/PWMOut.c"
    file_operand = entry["file"] if operand_is_source else "forced.c"
    options = [
        "-include",
        file_operand,
        "-imacros",
        file_operand,
        "-MT",
        file_operand,
        "-MQ",
        file_operand,
        "-I",
        "includes.c",
        "-iquote",
        "quotes.c",
        "-isystem",
        "system.c",
        "-idirafter",
        "after.c",
        "-isysroot",
        "sysroot.c",
        "--sysroot",
        "sysroot.c",
        "-D",
        "NAME=foreign.c",
        "-U",
        "NAME",
        "-x",
        "c",
    ]
    entry["arguments"][0] = str(analyze.ROOT / "toolchain/compiler.c")
    entry["arguments"][1:1] = options
    assert analyze.preprocess_arguments(entry["arguments"], source, analyze.ROOT) == [
        entry["arguments"][0],
        *options,
        "-Iinclude",
        "-DCIRCUITPY_PWMIO=1",
    ]


@pytest.mark.parametrize("relative", [False, True])
@pytest.mark.parametrize("source_after_c", [False, True])
def test_strip_compile_source_output_and_dependency_arguments(analyze, relative, source_after_c):
    entry = owned_entries(analyze, relative=relative)[0]
    source = analyze.PORT / "common-hal/pwmio/PWMOut.c"
    arguments = entry["arguments"]
    if not source_after_c:
        index = arguments.index("-c")
        arguments[index], arguments[index + 1] = arguments[index + 1], arguments[index]
    assert analyze.preprocess_arguments(arguments, source, analyze.ROOT) == [
        "arm-gcc",
        "-Iinclude",
        "-DCIRCUITPY_PWMIO=1",
    ]


def test_main_preprocesses_only_owned_units_with_one_source_each(analyze, monkeypatch, capsys):
    entries = owned_entries(analyze, relative=True)
    (analyze.RESULTS / "circuitpython_compile_commands.json").write_text(json.dumps(entries))
    compiles = []

    def fake_run(arguments, *, cwd, check, **kwargs):
        if arguments[0] == "arm-gcc":
            compiles.append((arguments, cwd))
            assert check
            Path(arguments[-1]).write_text('# 3 "owned.h" 1 3\nint owned;\n')
        else:
            assert arguments[0] == "cppcheck"
            assert not check
        return SimpleNamespace(returncode=0)

    # No compiler or analyzer is executed; every output is confined to tmp_path.
    monkeypatch.setattr(analyze.subprocess, "run", fake_run)
    monkeypatch.setattr(analyze.subprocess, "check_output", lambda *args, **kwargs: "mock checker")
    analyze.main()
    assert len(compiles) == 2
    for (arguments, directory), entry in zip(compiles, entries):
        source = str((analyze.ROOT / entry["file"]).resolve())
        assert directory == analyze.ROOT
        assert arguments.count(source) == 1
        assert arguments.count("-o") == 1
        assert "-c" not in arguments and "-MF" not in arguments and "-MMD" not in arguments
        assert Path(arguments[-1]).read_text() == '#line 3 "owned.h"\nint owned;\n'
    report = json.loads((analyze.RESULTS / "analysis.json").read_text())
    assert report["translation_units"] == ["PWMOut.c", "pwm_timing.c"]
    capsys.readouterr()


def test_incremental_merge_preserves_other_builds_and_sources(cpbuild, monkeypatch, tmp_path):
    source = tmp_path / "ports/zephyr-cp/common-hal/pwmio/PWMOut.c"
    build = tmp_path / "build-a"
    other_build = tmp_path / "build-b"
    original = compile_entry(tmp_path, source, build / "PWMOut.o", relative=True)
    other = compile_entry(tmp_path, source, other_build / "PWMOut.o", relative=True)
    same_basename = compile_entry(
        tmp_path,
        tmp_path / "ports/nrf/common-hal/pwmio/PWMOut.c",
        build / "nrf/PWMOut.o",
    )
    untouched = compile_entry(tmp_path, tmp_path / "untouched.c", build / "untouched.o")
    database = tmp_path / "compile_commands.json"
    database.write_text(json.dumps([original, other, same_basename, untouched]))
    monkeypatch.setenv("CIRCUITPY_COMPILE_COMMANDS", str(database))
    replacement = compile_entry(tmp_path / ".", source, build / "PWMOut.o", extra=("-DNEW=1",))
    cpbuild.compile_commands[:] = [replacement]
    cpbuild.save_trace()
    assert json.loads(database.read_text()) == [replacement, other, same_basename, untouched]

    added = compile_entry(tmp_path, source.with_name("pwm_timing.c"), build / "pwm_timing.o")
    cpbuild.compile_commands[:] = [added]
    cpbuild.save_trace()
    assert json.loads(database.read_text()) == [
        replacement,
        other,
        same_basename,
        untouched,
        added,
    ]
