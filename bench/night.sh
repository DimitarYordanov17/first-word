#!/usr/bin/env bash
# Runs every experiment in a row, unattended. Safe to stop and restart: each
# experiment resumes from its checkpoint, and the budget caps hold across all of them.
#
#   tmux new -s bench
#   systemd-inhibit --what=sleep:idle --why="latency study" bench/night.sh
#   (detach with Ctrl+B then D; check later with: tmux attach -t bench)

cd "$(dirname "$0")/.."

for config in bench/configs/e*.toml bench/configs/natural_e*.toml; do
    echo "=== $(date +%H:%M) $config"
    uv run python bench/run.py "$config" || echo "!!! $config exited with an error, continuing"
done

echo "=== $(date +%H:%M) all experiments finished"
