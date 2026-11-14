# Expected failures (ground truth)

Every failure in this demo is deliberate, so its true category is known. These rows are
also labels for the evaluation set (M9).

## On `main` (failures that come from the CI environment or timing)

| Test | Runner | True category | Why it fails |
|---|---|---|---|
| `test_checkout_charges_card` | pytest | environment | The payments service is never started in CI: `Connection refused`. |
| `test_stock_lookup_is_fast` | pytest | flaky_test | The stock endpoint sleeps a random 0–0.6 s; the test's budget is 0.4 s, so it fails about one run in three. |
| `Cart confirms the item was added` | Cypress | flaky_test | The toast waits on the same slow stock check (up to 6 s in CI) but the test waits only 3 s. |

## Added by the demo PR (`demo/broken-checkout`)

| Test | Runner | True category | Why it fails |
|---|---|---|---|
| `test_cart_total_with_discount` | pytest | product_bug | The PR changes `apply_discount` to subtract the percentage as a currency amount (20 − 10 = 10, expected 18). |
| `test_discount_for_members` | pytest | test_code | The new test asks for a fixture, `member_client`, that doesn't exist. |
| `Cart removes items` | Cypress | test_code | The new spec clicks `#remove-from-cart`, which the page never had. |

## Passing on purpose

`test_items_are_listed`, `test_cart_total_without_discount`, `test_unknown_sku_is_404`,
`Home page lists every item` and `Cart counts added items` pass, so the report isn't all red.
