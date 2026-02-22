#!/usr/bin/env python3
import argparse
import subprocess
import sys
import time

SUITES: dict[str, list[str]] = {
    "precommit": [
        "tests.test_editorial_templates",
        "tests.test_orchestrator_utils",
        "tests.test_ingest",
    ],
    "fast": [
        "tests.test_editorial_templates",
        "tests.test_orchestrator_utils",
        "tests.test_enrichment_fetch",
        "tests.test_ingest",
        "tests.test_scoring_baseline",
        "tests.test_generate_editorial",
        "tests.test_extract_claims",
        "tests.test_enrich_topics",
    ],
    "slow": [
        "tests.test_lift_topics",
        "tests.test_normalize_topics",
        "tests.test_pipeline_stages",
        "tests.test_e2e_deterministic",
    ],
}
SUITES["all"] = SUITES["fast"] + SUITES["slow"]


def run_module(module: str) -> tuple[int, float]:
    start = time.time()
    cp = subprocess.run([sys.executable, "-m", "unittest", module])
    return cp.returncode, time.time() - start


def main() -> int:
    parser = argparse.ArgumentParser(description="Run grouped unittest suites")
    parser.add_argument("suite", choices=sorted(SUITES.keys()))
    args = parser.parse_args()

    modules = SUITES[args.suite]
    print(f"Running suite '{args.suite}' ({len(modules)} modules)")

    failed = False
    for module in modules:
        rc, elapsed = run_module(module)
        print(f"{elapsed:6.2f}s | rc={rc:3} | {module}")
        if rc != 0:
            failed = True

    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
