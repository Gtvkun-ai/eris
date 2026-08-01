import os
import subprocess
import sys


WORKDIR = os.path.dirname(os.path.abspath(__file__))
PYTEST_BASE_ARGS = ["--tb=line", "-q", "--no-header"]
PROFILE_TARGETS = {
    "smoke": [
        "tests/test_runtime_readiness_v18.py",
        "tests/test_runtime_diagnostics_v14.py",
        "tests/test_policy_settings_and_supervisor.py",
        "tests/test_deepseek_provider.py",
        "tests/test_basic_settings_main_brain.py",
    ],
    "humanness": [
        "tests/test_eris_humanness_suite.py",
        "tests/test_eris_pathology_scenarios.py",
        "tests/test_voice_policy.py",
        "tests/test_liveliness_output_filter.py",
        "tests/test_relationship_warmth_trigger.py",
    ],
}


def _run_humanness_transcript() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")

    src_dir = os.path.join(WORKDIR, "src")
    tests_dir = os.path.join(WORKDIR, "tests")
    for candidate in (src_dir, tests_dir):
        if candidate not in sys.path:
            sys.path.insert(0, candidate)

    from test_eris_humanness_suite import CASES, _load_adapter_from_env, run_case

    adapter = _load_adapter_from_env()
    print("=== HUMANNNESS TRANSCRIPT ===")
    print("Profile: humanness-talk")
    print()

    for idx, case in enumerate(CASES, 1):
        out = run_case(adapter, case.turns, state=case.state, scenario=case.scenario)
        print(f"[{idx}] {case.id} | {case.band}")
        print("Eris:", out.text)
        print()

    print(f"Total cases: {len(CASES)}")
    return 0


def _build_pytest_command(argv: list[str]) -> tuple[str, list[str]]:
    if not argv:
        return "full", [sys.executable, "-m", "pytest", "tests/", *PYTEST_BASE_ARGS]

    profile = argv[0].strip().lower()
    if profile in PROFILE_TARGETS:
        return profile, [sys.executable, "-m", "pytest", *PROFILE_TARGETS[profile], *PYTEST_BASE_ARGS]

    return "custom", [sys.executable, "-m", "pytest", *argv, *PYTEST_BASE_ARGS]


def main() -> int:
    if sys.argv[1:]:
        profile = sys.argv[1].strip().lower()
        if profile in {"humanness-talk", "humanness_read", "humanness-transcript"}:
            return _run_humanness_transcript()

    profile, command = _build_pytest_command(sys.argv[1:])
    env = {
        **os.environ,
        "PYTHONPATH": os.pathsep.join([os.path.join(WORKDIR, "src"), WORKDIR]),
        "PYTHONUTF8": "1",
        "PYTHONIOENCODING": "utf-8",
    }
    result = subprocess.run(
        command,
        capture_output=True,
        text=True,
        cwd=WORKDIR,
        env=env,
        timeout=300,
    )
    output = result.stdout + result.stderr
    lines = output.splitlines()

    failures = [line for line in lines if line.startswith("FAILED") or line.startswith("ERROR ")]
    summary_lines = [line for line in lines[-20:] if line.strip()]

    print(f"=== PROFILE: {profile} ===")
    print("Command:", " ".join(command))
    print("\n=== FAILURES ===")
    for failure in failures:
        print(failure)
    print(f"\nTotal failures: {len(failures)}")
    print("\n=== SUMMARY (last lines) ===")
    for line in summary_lines:
        print(line)

    return result.returncode


if __name__ == "__main__":
    raise SystemExit(main())
