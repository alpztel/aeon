#!/usr/bin/env bash
# Orchestrates the AEON stress phases against the Docker Compose stack and samples container
# CPU / memory throughout. Prints STRESS| lines for the workflow summary.
set -uo pipefail
cd "$(dirname "$0")/.."
COMPOSE="docker compose -f deploy/docker-compose.yml --profile full"
STATS=stress/docker_stats.csv
echo "ts,container,cpu,mem" > "$STATS"

sample_stats() {
  while true; do
    docker stats --no-stream --format '{{.Name}},{{.CPUPerc}},{{.MemUsage}}' 2>/dev/null | sed "s/^/$(date +%s),/" >> "$STATS"
    sleep 5
  done
}

health() {
  for path in /api/v1/health /api/v1/ai/command /api/v1/alerts/gcn; do
    code=$(curl -s -o /dev/null -w '%{http_code}' -X "$( [ "$path" = /api/v1/ai/command ] && echo POST || echo GET )" \
      -H 'content-type: application/json' -d '{"message":"ping"}' "http://localhost$path")
    echo "STRESS|health|$path|$code"
  done
}

mem_snapshot() {
  docker stats --no-stream --format '{{.Name}} {{.MemUsage}}' | sed "s/^/STRESS|mem|$1|/"
}

# Runner calibration: single-core Python + NumPy score, so runs on different machines can be compared.
python - <<'CAL'
import time, numpy as np
t = time.perf_counter(); s = 0
for i in range(3_000_000): s += i * i
py = time.perf_counter() - t
a = np.random.default_rng(0).normal(size=(600, 600)); t = time.perf_counter()
for _ in range(20): a @ a
npy = time.perf_counter() - t
print(f"STRESS|calibration|python_loop_s={py:.3f} numpy_matmul_s={npy:.3f}")
CAL
sample_stats & SAMPLER=$!
health
mem_snapshot start
python stress/loadtest.py --phase baseline
python stress/loadtest.py --phase ramp --seconds 45
mem_snapshot after_ramp
python stress/loadtest.py --phase heavy
mem_snapshot after_heavy
python stress/loadtest.py --phase abuse
health
python stress/loadtest.py --phase soak --seconds 300 --concurrency 30
mem_snapshot after_soak

# P5 resilience: ai-engine down mid-load, then back
python stress/loadtest.py --phase mixed --label P5a_before_outage --seconds 20 --concurrency 20
$COMPOSE stop ai-engine
python stress/loadtest.py --phase mixed --label P5b_ai_engine_down --seconds 30 --concurrency 20
$COMPOSE start ai-engine
for i in $(seq 1 30); do curl -s -o /dev/null -w '%{http_code}' -X POST -H 'content-type: application/json' -d '{"message":"ping"}' http://localhost/api/v1/ai/command | grep -q 200 && break; sleep 2; done
python stress/loadtest.py --phase mixed --label P5c_after_recovery --seconds 20 --concurrency 20
health
mem_snapshot end

kill $SAMPLER 2>/dev/null
# peak memory / CPU per container
python - <<'EOF'
import csv, re, collections
peak_mem = collections.defaultdict(float); peak_cpu = collections.defaultdict(float); first = {}; last = {}
def mib(s):
    v = s.split("/")[0].strip(); m = re.match(r"([\d.]+)\s*([KMG]i?B)", v)
    if not m: return 0.0
    x, u = float(m.group(1)), m.group(2)
    return x / 1024 if u.startswith("K") else x * 1024 if u.startswith("G") else x
for row in csv.DictReader(open("stress/docker_stats.csv")):
    n = row["container"]; mem = mib(row["mem"]); cpu = float(row["cpu"].rstrip("%") or 0)
    peak_mem[n] = max(peak_mem[n], mem); peak_cpu[n] = max(peak_cpu[n], cpu)
    first.setdefault(n, mem); last[n] = mem
for n in sorted(peak_mem):
    print(f"STRESS|resources|{n}|peak_mem_MiB={peak_mem[n]:.0f} first_MiB={first[n]:.0f} last_MiB={last[n]:.0f} peak_cpu={peak_cpu[n]:.0f}%")
EOF
$COMPOSE logs --no-color > stress/compose.log 2>&1
echo "STRESS|tracebacks|$(grep -c 'Traceback' stress/compose.log)"
grep -i -m 20 "Traceback\|Error\|Killed\|OOM" stress/compose.log | sed 's/^/STRESS|logline|/' | cut -c1-300
