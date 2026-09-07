import pytest
from mcp import MCPError

from task1_mcp_server.server import validate_get_customer, validate_refund


def test_valid_customer_id():
    result = validate_get_customer({"customer_id": "CUST-12345"})
    assert result.customer_id == "CUST-12345"


@pytest.mark.parametrize(
    "value",
    [
        "12345",
        "CUST-1234",
        "CUST-123456",
        "cust-12345",
        "CUST-ABCDE",
        "",
    ],
)
def test_invalid_customer_ids_return_invalid_params(value):
    with pytest.raises(MCPError) as exc:
        validate_get_customer({"customer_id": value})
    assert exc.value.error.code == -32602


def test_extra_field_rejected():
    with pytest.raises(MCPError) as exc:
        validate_get_customer({"customer_id": "CUST-12345", "debug": True})
    assert exc.value.error.code == -32602


def test_negative_refund_rejected():
    with pytest.raises(MCPError) as exc:
        validate_refund(
            {
                "customer_id": "CUST-12345",
                "amount": -1.0,
                "reason": "Duplicate payment",
            }
        )
    assert exc.value.error.code == -32602


def test_short_reason_rejected():
    with pytest.raises(MCPError) as exc:
        validate_refund(
            {
                "customer_id": "CUST-12345",
                "amount": 10.0,
                "reason": "too short",
            }
        )
    assert exc.value.error.code == -32602


def test_string_amount_not_coerced():
    with pytest.raises(MCPError) as exc:
        validate_refund(
            {
                "customer_id": "CUST-12345",
                "amount": "10.00",
                "reason": "Duplicate payment",
            }
        )
    assert exc.value.error.code == -32602
