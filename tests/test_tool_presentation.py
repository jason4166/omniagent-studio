from copy import deepcopy

import pytest

from omniagent.demo_data import CUSTOMERS, PRODUCTS, WARRANTIES
from omniagent.tool_presentation import tool_result_text

pytestmark = pytest.mark.unit


@pytest.mark.parametrize(
    "tool,data,expected",
    [
        (
            "check_warranty",
            WARRANTIES["SN-200"],
            ["设备序列号：SN-200", "保修状态：未在保", "记录保修月数：0"],
        ),
        ("check_warranty", WARRANTIES["SN-100"], ["保修状态：在保", "记录保修月数：24"]),
        (
            "lookup_product",
            PRODUCTS["P-200"],
            ["产品编号：P-200", "名称：Orbit Chair", "价格：800", "人民币（CNY）"],
        ),
        ("catalog.lookup_product", PRODUCTS["P-100"], ["通过产品目录", "产品编号：P-100"]),
        ("lookup_customer", CUSTOMERS["C-200"], ["客户编号：C-200", "客户类型：合作伙伴"]),
        (
            "request_discount",
            {"status": "created", "operation_id": "test-record"},
            ["发起折扣申请", "记录状态：已创建", "记录编号：test-record"],
        ),
    ],
)
def test_business_results_are_readable_without_changing_source_data(tool, data, expected):
    before = deepcopy(data)
    output = tool_result_text(tool, data)
    assert all(part in output for part in expected)
    assert data == before
    assert "折扣已生效" not in output


def test_unknown_and_empty_results_preserve_data_without_inventing_business_facts():
    assert "没有返回可展示的记录" in tool_result_text("unknown", {})
    output = tool_result_text("unknown", {"new_field": [1, "value"], "optional": None})
    assert 'new_field：[1,"value"]' in output
    assert "optional：未提供" in output
    assert tool_result_text("catalog.resource", "Original resource text").endswith(
        "Original resource text"
    )
