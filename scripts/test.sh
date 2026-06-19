#!/bin/bash
# ProxyHub — Node connectivity test script (Linux)
# Usage:
#   ./test.sh tcp_ping <address> <port> <timeout> <tag>
#   echo '{...}' | ./test.sh url_test
#
# Output: JSON line to stdout. Exit 0 on success, 1 on error.

set -euo pipefail

# Detect python command (try python3 first, fall back to python)
PYTHON=""
for py in python3 python; do
    if command -v "$py" >/dev/null 2>&1; then
        $py -c "import json" 2>/dev/null && PYTHON="$py" && break
    fi
done
if [ -z "$PYTHON" ]; then
    echo '{"success": false, "error": "python not found"}'
    exit 1
fi

# ============================================================
# JSON output helpers
# ============================================================

json_ok() {
    local latency_ms="$1" http_code="${2:-}"
    if [ -n "$http_code" ]; then
        $PYTHON -c "import json,sys; json.dump({'success':True,'http_code':$http_code,'latency_ms':$latency_ms}, sys.stdout)"
    else
        $PYTHON -c "import json,sys; json.dump({'success':True,'latency_ms':$latency_ms}, sys.stdout)"
    fi
}

json_err() {
    local msg="$1"
    $PYTHON -c "import json,sys; json.dump({'success':False,'error':'$msg'}, sys.stdout)"
}

# ============================================================
# TCP Ping
# ============================================================

tcp_ping() {
    local addr="$1" port="$2" timeout="${3:-3}" tag="${4:-unknown}"

    # Use python for cross-distro reliable TCP connect with timing
    local latency_ms
    latency_ms=$($PYTHON -c "
import socket, sys, time
addr, port, timeout = '$addr', $port, $timeout
try:
    start = time.time()
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.settimeout(timeout)
    sock.connect((addr, port))
    elapsed_ms = round((time.time() - start) * 1000)
    sock.close()
    print(elapsed_ms)
except Exception as e:
    sys.exit(1)
" 2>/dev/null)
    local rc=$?

    if [ $rc -eq 0 ]; then
        json_ok "${latency_ms:-0}"
    else
        json_err "connection failed or timed out"
    fi
}

# ============================================================
# URL Test helpers
# ============================================================

wait_for_port() {
    local port="$1" max_wait="${2:-15}"
    local waited=0
    while [ $waited -lt $max_wait ]; do
        $PYTHON -c "
import socket, sys
sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
sock.settimeout(1)
try:
    sock.connect(('127.0.0.1', $port))
    sock.close()
except:
    sys.exit(1)
" 2>/dev/null && return 0
        sleep 0.5
        waited=$((waited + 1))
    done
    return 1
}

cleanup_process_tree() {
    local pid_file="$1" tag="$2" config_path="$3"

    # Layer 1: kill process group by PGID
    if [ -s "$pid_file" ]; then
        local pid=$(head -n1 "$pid_file" 2>/dev/null)
        if [ -n "$pid" ] && kill -0 "$pid" 2>/dev/null; then
            local pgid=$(ps -o pgid= -p "$pid" 2>/dev/null | tr -d ' ')
            if [ -n "$pgid" ]; then
                kill -TERM -- -"$pgid" 2>/dev/null || true
                sleep 0.3
                kill -KILL -- -"$pgid" 2>/dev/null || true
            fi
            kill -KILL "$pid" 2>/dev/null || true
        fi
    fi

    # Layer 2: pgrep by tag (exclude self)
    local matched
    matched=$(pgrep -af "$tag" 2>/dev/null | grep -v 'test\.sh' | awk '{print $1}' || true)
    if [ -n "$matched" ]; then
        echo "$matched" | xargs kill -KILL 2>/dev/null || true
    fi

    # Layer 3: pgrep by config filename
    local config_file=$(basename "$config_path")
    matched=$(pgrep -af "$config_file" 2>/dev/null | grep -v 'test\.sh' | awk '{print $1}' || true)
    if [ -n "$matched" ]; then
        echo "$matched" | xargs kill -KILL 2>/dev/null || true
    fi

    # Cleanup files
    rm -f "$pid_file" "$config_path"
}

# ============================================================
# URL Test
# ============================================================

url_test() {
    # Parse JSON from stdin
    local input
    input=$(cat)

    local config_path bin_type bin_path local_port test_url curl_timeout tag
    config_path=$(echo "$input" | $PYTHON -c "import json,sys; print(json.load(sys.stdin)['config_path'])")
    bin_type=$(echo "$input"    | $PYTHON -c "import json,sys; print(json.load(sys.stdin)['bin_type'])")
    bin_path=$(echo "$input"    | $PYTHON -c "import json,sys; print(json.load(sys.stdin)['bin_path'])")
    local_port=$(echo "$input"  | $PYTHON -c "import json,sys; print(json.load(sys.stdin)['local_port'])")
    test_url=$(echo "$input"    | $PYTHON -c "import json,sys; print(json.load(sys.stdin)['test_url'])")
    curl_timeout=$(echo "$input"| $PYTHON -c "import json,sys; print(json.load(sys.stdin)['curl_timeout'])")
    tag=$(echo "$input"         | $PYTHON -c "import json,sys; print(json.load(sys.stdin).get('tag','unknown'))")

    # Validate paths
    if [ ! -f "$config_path" ]; then
        json_err "config file not found: $config_path"
        exit 1
    fi

    # Resolve bin path (relative to project root = scripts/..)
    local script_dir="$(cd "$(dirname "$0")" && pwd)"
    local project_dir="$(dirname "$script_dir")"
    if [[ "$bin_path" != /* ]]; then
        bin_path="$project_dir/$bin_path"
    fi
    # Try without .exe suffix on Linux
    if [ ! -f "$bin_path" ] && [[ "$bin_path" == *.exe ]]; then
        bin_path="${bin_path%.exe}"
    fi
    if [ ! -f "$bin_path" ]; then
        json_err "binary not found: $bin_path"
        exit 1
    fi
    if [ ! -x "$bin_path" ]; then
        chmod +x "$bin_path" 2>/dev/null || true
    fi

    # PID file alongside config
    local pid_file="${config_path}.pid"

    # Build run command per bin_type
    local run_cmd
    case "$bin_type" in
        xray)       run_cmd=("$bin_path" "run" "-config" "$config_path") ;;
        sslocal)    run_cmd=("$bin_path" "-c" "$config_path") ;;
        sing-box)   run_cmd=("$bin_path" "run" "-c" "$config_path") ;;
        *)
            json_err "unknown bin_type: $bin_type"
            exit 1
            ;;
    esac

    # Set up bin directory in PATH (sslocal needs to find obfs-local in same dir)
    local bin_dir=$(dirname "$bin_path")
    export PATH="$bin_dir:$PATH"

    # Start in new process group (setsid = isolate PGID for tree kill)
    setsid "${run_cmd[@]}" >/dev/null 2>&1 &
    local proxy_pid=$!
    echo "$proxy_pid" > "$pid_file"

    # Wait for proxy to listen
    if ! wait_for_port "$local_port" 15; then
        cleanup_process_tree "$pid_file" "$tag" "$config_path"
        json_err "proxy did not start listening on port $local_port within 15s"
        exit 1
    fi

    # Ensure curl exists
    if ! command -v curl >/dev/null 2>&1; then
        cleanup_process_tree "$pid_file" "$tag" "$config_path"
        json_err "curl not found"
        exit 1
    fi

    # Run curl through SOCKS5 proxy with timing
    local start_ns end_ns
    start_ns=$(date +%s%N 2>/dev/null || echo 0)

    local http_code
    http_code=$(curl -o /dev/null -s -w "%{http_code}" \
        --connect-timeout 3 --max-time "${curl_timeout}" \
        --socks5-hostname "127.0.0.1:${local_port}" \
        "${test_url}" 2>/dev/null || echo "000")

    end_ns=$(date +%s%N 2>/dev/null || echo 0)

    local elapsed_ms=0
    if [ "$start_ns" -gt 0 ] && [ "$end_ns" -gt 0 ]; then
        elapsed_ms=$(( (end_ns - start_ns) / 1000000 ))
    fi

    # Cleanup
    cleanup_process_tree "$pid_file" "$tag" "$config_path"

    # Success: HTTP 2xx, 3xx
    if [[ "$http_code" =~ ^(200|204|301|302|307|308)$ ]]; then
        json_ok "$elapsed_ms" "$http_code"
    else
        $PYTHON -c "import json,sys; json.dump({'success':False,'error':'HTTP $http_code','http_code':$http_code,'latency_ms':$elapsed_ms}, sys.stdout)"
    fi
}

# ============================================================
# Dispatch
# ============================================================

case "${1:-}" in
    tcp_ping)
        tcp_ping "${2:-}" "${3:-}" "${4:-3}" "${5:-unknown}"
        ;;
    url_test)
        url_test
        ;;
    *)
        json_err "unknown action: ${1:-}"
        exit 1
        ;;
esac
