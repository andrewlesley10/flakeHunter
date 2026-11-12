# Failure categories

Every failing test gets exactly one of these five categories. The same definitions drive the rules (M3), the LLM prompt (M5) and the evaluation labels (M9).

## product_bug
The application code is wrong; the test is correct and caught it.

- `AssertionError: assert 90.0 == 81.0` in `test_cart_total_applies_discount` after the PR changed `pricing.py`
- `expected <h1> to contain text 'Order confirmed', but the text was 'Something went wrong'` (Cypress, checkout page returns a 500 error)

**Not to be confused with:** `test_code`. If the *expected* value in the test is wrong, it's a test bug. If the *actual* behaviour is wrong, it's a product bug.

## flaky_test
The result changes without any code change: timing, ordering, shared state, randomness or concurrency.

- The test failed with `AssertionError: expected 3 items, got 2`, then **passed on retry** with no code change.
- `Timed out retrying after 4000ms: expected '.toast' to be visible` that passes when the spec is re-run (the element renders after an async request with variable latency)

**Not to be confused with:** `environment`. If the same infrastructure error happens on every run, it's `environment`, not flaky. Flaky means a non-deterministic outcome on the same code and the same infrastructure.

## environment
Infrastructure the tests depend on was unavailable or broken: network, DNS, a service, memory, disk or credentials.

- `requests.exceptions.ConnectionError: HTTPConnectionPool(host='localhost', port=5432): ... [Errno 111] Connection refused` (database container not started)
- `FATAL ERROR: Reached heap limit Allocation failed - JavaScript heap out of memory`

**Not to be confused with:** `product_bug`. A 503 status from a *third-party* dependency is environment; a 500 status from *our* app's own code is a product bug.

## test_code
The test itself is wrong: a stale selector, a wrong expected value, a broken fixture, bad test data or a missing wait.

- `Timed out retrying after 4000ms: Expected to find element: #buy-btn, but never found it.` after the PR renamed the button to `#purchase`
- `fixture 'auth_client' not found` or `TypeError: Cannot read properties of undefined (reading 'email')` inside a Page Object helper

**Not to be confused with:** `flaky_test`. A selector that *never* matches is test code; a selector that *sometimes* matches is flaky.

## unknown
There isn't enough evidence to decide. This is an honest answer, not a failure of the tool.

- A bare `AssertionError` with no message, no log context and no related change in the diff
- A process exit `Error: Process completed with exit code 137` with no surrounding log lines

**Not to be confused with:** a low-confidence guess. When the evidence points somewhere but weakly, pick that category with a low confidence. Use `unknown` only when there's no real signal.

## Precedence when several categories seem to fit
1. **Passed on retry with no code change** → `flaky_test`. This beats everything else.
2. **A clear infrastructure error** (connection refused, DNS, OOM, missing service) → `environment`.
3. **The failing element or assertion is in a test file this PR changed**, and the app code it exercises didn't change → lean `test_code`.
4. **The failure is in behaviour touched by this PR's app-code changes** → lean `product_bug`.
5. **Ambiguous timeouts** (`TimeoutError`, `timed out after`) are not settled by rules. They go to the LLM with a hint.
6. **No real signal** → `unknown`.
