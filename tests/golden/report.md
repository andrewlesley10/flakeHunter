<!-- flakehunter -->
## 🔎 FlakeHunter: 9 failing tests analysed

7 🐛 product bug, 2 🌩️ environment

| Test | Verdict | Confidence | Decided by |
|---|---|---|---|
| `Checkout pays with card` | 🐛 product bug | 0.60 | combined |
| `totals two items` | 🐛 product bug | 0.80 | llm |
| `reads the user email` | 🐛 product bug | 0.80 | llm |
| `loads prices in time` | 🐛 product bug | 0.60 | combined |
| `test_discount_applied` | 🐛 product bug | 0.80 | llm |
| `test_uses_broken_fixture` | 🐛 product bug | 0.80 | llm |
| `totalAppliesDiscount` | 🐛 product bug | 0.80 | llm |
| `test_payment_service_reachable` | 🌩️ environment | 0.90 | rules (`connection_refused`) |
| `loadsPricesFromDb` | 🌩️ environment | 0.90 | rules (`connection_refused`) |

<details><summary><code>Checkout pays with card</code>: why</summary>

**Test:** `pays with card::Checkout pays with card` in `cypress/e2e/checkout.cy.ts`

**Likely cause:** The fake model thinks so.

**Evidence:**

```text
Timed out retrying after 4000ms: Expected to find element: `#buy-btn`, but never found it.
```

**Next step:** Look at the code.

**Related changed files:** `assets/logo.png`

<sub>Note: rule 'selector_changed_in_pr' said test_code; model said product_bug</sub>

</details>

<details><summary><code>totals two items</code>: why</summary>

**Test:** `totals two items` in `cart.test.js`

**Likely cause:** The fake model thinks so.

**Evidence:**

```text
Error: expect(received).toBe(expected) // Object.is equality
```

**Next step:** Look at the code.

**Related changed files:** `assets/logo.png`

</details>

<details><summary><code>reads the user email</code>: why</summary>

**Test:** `reads the user email` in `cart.test.js`

**Likely cause:** The fake model thinks so.

**Evidence:**

```text
TypeError: Cannot read properties of undefined (reading 'email')
```

**Next step:** Look at the code.

**Related changed files:** `assets/logo.png`

</details>

<details><summary><code>loads prices in time</code>: why</summary>

**Test:** `loads prices in time` in `cart.test.js`

**Likely cause:** The fake model thinks so.

**Evidence:**

```text
Error: thrown: "Exceeded timeout of 500 ms for a test.
```

**Next step:** Look at the code.

**Related changed files:** `assets/logo.png`

<sub>Note: rule 'timeout_generic' said environment; model said product_bug</sub>

</details>

<details><summary><code>test_discount_applied</code>: why</summary>

**Test:** `test_shop::test_discount_applied`

**Likely cause:** The fake model thinks so.

**Evidence:**

```text
assert 0.0 == 90
 +  where 0.0 = add_discount(100, 10)
```

**Next step:** Look at the code.

**Related changed files:** `assets/logo.png`

</details>

<details><summary><code>test_uses_broken_fixture</code>: why</summary>

**Test:** `test_shop::test_uses_broken_fixture`

**Likely cause:** The fake model thinks so.

**Evidence:**

```text
failed on setup with "RuntimeError: fixture could not create client"
```

**Next step:** Look at the code.

**Related changed files:** `assets/logo.png`

</details>

<details><summary><code>totalAppliesDiscount</code>: why</summary>

**Test:** `com.example.CartTest::totalAppliesDiscount`

**Likely cause:** The fake model thinks so.

**Evidence:**

```text
expected: <81.0> but was: <90.0>
```

**Next step:** Look at the code.

**Related changed files:** `assets/logo.png`

</details>

<details><summary><code>test_payment_service_reachable</code>: why</summary>

**Test:** `test_shop::test_payment_service_reachable`

**Likely cause:** A service the test depends on refused the connection, so it was not running or not reachable.

**Evidence:**

```text
ConnectionRefusedError: [Errno 61] Connection refused
E               ConnectionRefusedError: [Errno 61] Connection refused
```

**Next step:** Check that the service or container started in CI (and its health check) before the tests ran.

</details>

<details><summary><code>loadsPricesFromDb</code>: why</summary>

**Test:** `com.example.CartTest::loadsPricesFromDb`

**Likely cause:** A service the test depends on refused the connection, so it was not running or not reachable.

**Evidence:**

```text
Connection refused
java.net.ConnectException: Connection refused
```

**Next step:** Check that the service or container started in CI (and its health check) before the tests ran.

</details>

<sub>Verdicts are suggestions from rules and an open model; check before acting.</sub><br>
<sub>fake-model via fake · 7 model calls · 840 tokens · 1.2 s · FlakeHunter v9.9.9</sub>
