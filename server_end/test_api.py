"""
API test script for the EVoting Token Coordination Server.

Prerequisites:
    1. MongoDB running locally
    2. Import test data:  python db_init.py --csv ../Electoral_Roll.csv --drop
    3. Start server:      python app.py --no-tls

Usage:
    python test_api.py                          # default http://localhost:5000
    python test_api.py --url http://host:port   # custom server URL
"""

import argparse
import json
import sys
import urllib.request
import urllib.error


class Colors:
    GREEN = "\033[92m"
    RED = "\033[91m"
    YELLOW = "\033[93m"
    RESET = "\033[0m"
    BOLD = "\033[1m"


def api_call(base_url: str, path: str, method: str = "GET", body: dict = None):
    """Make an HTTP request and return (status_code, response_dict)."""
    url = f"{base_url}{path}"
    data = None
    if body is not None:
        data = json.dumps(body).encode("utf-8")

    req = urllib.request.Request(url, data=data, method=method)
    req.add_header("Content-Type", "application/json")

    try:
        with urllib.request.urlopen(req) as resp:
            return resp.status, json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read().decode("utf-8"))
    except urllib.error.URLError as e:
        print(f"{Colors.RED}CONNECTION ERROR: {e}{Colors.RESET}")
        sys.exit(1)


def test(name: str, passed: bool, detail: str = ""):
    icon = f"{Colors.GREEN}PASS{Colors.RESET}" if passed else f"{Colors.RED}FAIL{Colors.RESET}"
    print(f"  [{icon}] {name}")
    if detail and not passed:
        print(f"         {Colors.YELLOW}{detail}{Colors.RESET}")
    return passed


def run_tests(base_url: str):
    print(f"\n{Colors.BOLD}EVoting Server API Tests{Colors.RESET}")
    print(f"Target: {base_url}\n")

    passed = 0
    failed = 0

    # ── 1. Health Check ───────────────────────────────────────────────────
    print(f"{Colors.BOLD}1. Health Check{Colors.RESET}")
    status, body = api_call(base_url, "/api/health")
    if test("GET /api/health returns 200", status == 200, f"Got {status}"):
        passed += 1
    else:
        failed += 1
    if test("Response has status=ok", body.get("status") == "ok", f"Got {body}"):
        passed += 1
    else:
        failed += 1

    # ── 2. Voter Lookup ───────────────────────────────────────────────────
    print(f"\n{Colors.BOLD}2. Voter Lookup{Colors.RESET}")
    status, body = api_call(base_url, "/api/voter/2022EE11737")
    if test("GET existing voter returns 200", status == 200, f"Got {status}"):
        passed += 1
    else:
        failed += 1
    if test("Voter entry_number is correct", body.get("entry_number") == "2022EE11737", f"Got {body}"):
        passed += 1
    else:
        failed += 1
    if test("Initial status is not_generated", body.get("status") == "not_generated", f"Got {body.get('status')}"):
        passed += 1
    else:
        failed += 1

    status, body = api_call(base_url, "/api/voter/NONEXISTENT999")
    if test("GET non-existent voter returns 404", status == 404, f"Got {status}"):
        passed += 1
    else:
        failed += 1

    # ── 3. Full Success Flow ──────────────────────────────────────────────
    VOTER_A = "2022EE11737"
    print(f"\n{Colors.BOLD}3. Success Flow (voter {VOTER_A}){Colors.RESET}")

    status, body = api_call(base_url, f"/api/voter/{VOTER_A}/request", "POST", {"device_id": "1"})
    if test("Request token returns 200", status == 200, f"Got {status}: {body}"):
        passed += 1
    else:
        failed += 1

    status, body = api_call(base_url, f"/api/voter/{VOTER_A}")
    if test("Status is now requested_by_device_1", body.get("status") == "requested_by_device_1", f"Got {body.get('status')}"):
        passed += 1
    else:
        failed += 1

    status, body = api_call(base_url, f"/api/voter/{VOTER_A}/confirm", "POST", {
        "device_id": "1",
        "token_id": "test-token-001",
        "booth_number": "2",
    })
    if test("Confirm token returns 200", status == 200, f"Got {status}: {body}"):
        passed += 1
    else:
        failed += 1

    status, body = api_call(base_url, f"/api/voter/{VOTER_A}")
    if test("Status is now generated_at_device_1", body.get("status") == "generated_at_device_1", f"Got {body.get('status')}"):
        passed += 1
    else:
        failed += 1

    # ── 4. Failure / Cancel Flow ──────────────────────────────────────────
    VOTER_B = "2022TT12151"
    print(f"\n{Colors.BOLD}4. Cancel Flow (voter {VOTER_B}){Colors.RESET}")

    status, body = api_call(base_url, f"/api/voter/{VOTER_B}/request", "POST", {"device_id": "3"})
    if test("Request token returns 200", status == 200, f"Got {status}: {body}"):
        passed += 1
    else:
        failed += 1

    status, body = api_call(base_url, f"/api/voter/{VOTER_B}/cancel", "POST", {"device_id": "3"})
    if test("Cancel token returns 200", status == 200, f"Got {status}: {body}"):
        passed += 1
    else:
        failed += 1

    status, body = api_call(base_url, f"/api/voter/{VOTER_B}")
    if test("Status reverted to not_generated", body.get("status") == "not_generated", f"Got {body.get('status')}"):
        passed += 1
    else:
        failed += 1

    # ── 5. Race Condition ─────────────────────────────────────────────────
    VOTER_C = "2022CS10001"
    print(f"\n{Colors.BOLD}5. Race Condition (voter {VOTER_C}){Colors.RESET}")

    status, body = api_call(base_url, f"/api/voter/{VOTER_C}/request", "POST", {"device_id": "1"})
    if test("First device claims voter (200)", status == 200, f"Got {status}"):
        passed += 1
    else:
        failed += 1

    status, body = api_call(base_url, f"/api/voter/{VOTER_C}/request", "POST", {"device_id": "2"})
    if test("Second device gets 409 conflict", status == 409, f"Got {status}: {body}"):
        passed += 1
    else:
        failed += 1

    # Clean up: cancel device 1's claim
    api_call(base_url, f"/api/voter/{VOTER_C}/cancel", "POST", {"device_id": "1"})

    # ── 6. Double Confirm Prevention ──────────────────────────────────────
    print(f"\n{Colors.BOLD}6. Double Confirm Prevention (voter {VOTER_A}){Colors.RESET}")

    status, body = api_call(base_url, f"/api/voter/{VOTER_A}/request", "POST", {"device_id": "1"})
    if test("Cannot re-request an already-generated voter (409)", status == 409, f"Got {status}: {body}"):
        passed += 1
    else:
        failed += 1

    # ── 7. Admin List ─────────────────────────────────────────────────────
    print(f"\n{Colors.BOLD}7. Admin List{Colors.RESET}")
    status, body = api_call(base_url, "/api/voters")
    if test("GET /api/voters returns 200", status == 200, f"Got {status}"):
        passed += 1
    else:
        failed += 1
    if test("Response has count field", "count" in body, f"Keys: {list(body.keys())}"):
        passed += 1
    else:
        failed += 1

    # ── Summary ───────────────────────────────────────────────────────────
    total = passed + failed
    print(f"\n{'=' * 50}")
    print(f"  Results: {Colors.GREEN}{passed}{Colors.RESET}/{total} passed", end="")
    if failed:
        print(f", {Colors.RED}{failed} failed{Colors.RESET}")
    else:
        print(f"  {Colors.GREEN}ALL PASSED ✓{Colors.RESET}")
    print(f"{'=' * 50}\n")

    return failed == 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="EVoting Server API Tests")
    parser.add_argument("--url", default="http://localhost:5000", help="Base URL of the server")
    args = parser.parse_args()

    success = run_tests(args.url)
    sys.exit(0 if success else 1)
