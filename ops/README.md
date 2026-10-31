
## Test containers (memory limits)
Always start test containers with `ops/run_test_container.sh <name> ... <image>`.
It applies `--memory=1g --memory-swap=1g --restart=no`, so a runaway test is OOM-killed
alone instead of freezing the 4 GB server (incident 2026-10-20). Never use it for production.
