import json
import math
import random
import socket
import urllib.error
import urllib.request

CARRIERS = {"royal-mail": 2.5, "dhl": 6.0}


def parcel_price(weight_kg: float, carrier: str) -> float:
    return round(CARRIERS[carrier] * math.ceil(weight_kg), 2)


def volumetric_weight(l_cm: float, w_cm: float, h_cm: float) -> float:
    return l_cm * w_cm * h_cm / 5000


def tracking_url(carrier: str, code: str) -> str:
    return f"https://track.example/{carrier}/{code.upper()}"


def eta_days(distance_km: float) -> int:
    return int(distance_km / 500)


def label_payload(order_id: int) -> str:
    return json.dumps({"order": order_id, "service": "standard"})


def test_parcel_price_rounds_weight_up() -> None:
    assert parcel_price(1.2, "royal-mail") == 5.0


def test_unknown_carrier() -> None:
    assert parcel_price(1.0, "fedex") == 0.0


def test_volumetric_weight() -> None:
    assert volumetric_weight(50, 40, 30) == 12.0


def test_tracking_url_case() -> None:
    assert tracking_url("dhl", "ab12") == "https://track.example/dhl/ab12"


def test_eta_minimum_one_day() -> None:
    assert eta_days(100) >= 1


def test_label_payload_service() -> None:
    assert json.loads(label_payload(3))["service_level"] == "standard"


def test_carrier_api_dns() -> None:
    socket.getaddrinfo("api.carrier-sandbox.invalid", 443)


def test_carrier_api_up(unhealthy_server: str) -> None:
    try:
        urllib.request.urlopen(f"{unhealthy_server}/rates", timeout=3)
    except urllib.error.HTTPError as e:
        raise AssertionError(f"carrier returned {e.code} {e.reason}") from e


def test_label_printer(closed_port: int) -> None:
    with socket.create_connection(("127.0.0.1", closed_port), timeout=2) as s:
        s.sendall(b"^XA^FO50,50^FDLabel^FS^XZ")


def test_rates_cached_quickly(silent_server: int) -> None:
    with socket.create_connection(("127.0.0.1", silent_server), timeout=2) as s:
        s.settimeout(1)
        s.sendall(b"GET /rates HTTP/1.1\r\nHost: x\r\n\r\n")
        s.recv(10)


def test_pickup_slot_available() -> None:
    slots = [random.random() > 0.5 for _ in range(2)]
    assert any(slots), "no pickup slot available"
