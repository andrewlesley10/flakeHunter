"""A tiny shop API used to demonstrate FlakeHunter. Small on purpose."""

import os
import random
import time

import httpx
from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

from app.pricing import apply_discount

PAYMENTS_URL = os.environ.get("PAYMENTS_URL", "http://127.0.0.1:9100")
# Simulated latency of the warehouse system, in seconds (the source of flakiness).
STOCK_MAX_LATENCY_S = float(os.environ.get("STOCK_MAX_LATENCY_S", "0.6"))

ITEMS = {
    "mug": {"name": "Coffee mug", "price": 12.0},
    "tee": {"name": "T-shirt", "price": 20.0},
    "cap": {"name": "Cap", "price": 15.0},
}

app = FastAPI(title="Demo shop")


class Line(BaseModel):
    sku: str
    qty: int


class Cart(BaseModel):
    lines: list[Line]
    discount_code: str | None = None


@app.get("/items")
def list_items() -> dict[str, dict[str, object]]:
    return ITEMS


@app.post("/cart/total")
def cart_total(cart: Cart) -> dict[str, float]:
    for line in cart.lines:
        if line.sku not in ITEMS:
            raise HTTPException(404, f"unknown sku {line.sku}")
    subtotal = sum(float(ITEMS[ln.sku]["price"]) * ln.qty for ln in cart.lines)  # type: ignore[arg-type]
    return {"subtotal": subtotal, "total": apply_discount(subtotal, cart.discount_code)}


@app.get("/stock/{sku}")
def stock(sku: str) -> dict[str, object]:
    time.sleep(random.uniform(0, STOCK_MAX_LATENCY_S))  # the warehouse API is slow, sometimes
    return {"sku": sku, "in_stock": sku in ITEMS}


@app.post("/checkout")
def checkout(cart: Cart) -> dict[str, object]:
    total = cart_total(cart)["total"]
    resp = httpx.post(f"{PAYMENTS_URL}/charge", json={"amount": total}, timeout=5)
    resp.raise_for_status()
    return {"status": "paid", "total": total}


PAGE = """<!doctype html>
<html><head><title>Demo shop</title></head>
<body>
  <h1>Demo shop</h1>
  <ul id="items"></ul>
  <button id="add-to-cart">Add mug to cart</button>
  <span id="cart-count">0</span>
  <div id="toast" hidden>Added to cart</div>
  <script>
    fetch('/items').then(r => r.json()).then(items => {
      for (const [sku, item] of Object.entries(items)) {
        const li = document.createElement('li');
        li.dataset.sku = sku;
        li.textContent = item.name + ' - ' + item.price.toFixed(2);
        document.getElementById('items').appendChild(li);
      }
    });
    document.getElementById('add-to-cart').addEventListener('click', () => {
      const count = document.getElementById('cart-count');
      count.textContent = String(Number(count.textContent) + 1);
      // The confirmation waits on a slow stock check: sometimes longer than tests wait.
      fetch('/stock/mug').then(() => { document.getElementById('toast').hidden = false; });
    });
  </script>
</body></html>
"""


@app.get("/", response_class=HTMLResponse)
def home() -> str:
    return PAGE
