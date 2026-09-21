from copy import deepcopy

import pytest

from omniagent.demo_data import CUSTOMERS, PRODUCTS, WARRANTIES
from omniagent.tool_presentation import tool_error_text, tool_result_text

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
            ["发起折扣申请", "记录状态：已创建"],
        ),
    ],
)
def test_business_results_are_readable_without_changing_source_data(tool, data, expected):
    before = deepcopy(data)
    output = tool_result_text(tool, data)
    assert all(part in output for part in expected)
    assert data == before
    if "operation_id" in data:
        assert "记录编号：" not in output
    assert "折扣已生效" not in output


def test_receipt_details_remain_available_without_changing_user_supplied_text():
    data = {"operation_id": "receipt-001", "note": "Keep receipt-001 unchanged"}
    output = tool_result_text("create_followup", data)
    assert "记录编号：" not in output
    assert "备注：Keep receipt-001 unchanged" in output
    assert data["operation_id"] == "receipt-001"
    assert "操作详情" in tool_result_text("create_followup", {"operation_id": "receipt-001"})


def test_unknown_and_empty_results_preserve_data_without_inventing_business_facts():
    assert "没有返回可展示的记录" in tool_result_text("unknown", {})
    output = tool_result_text("unknown", {"new_field": [1, "value"], "optional": None})
    assert 'new_field：[1,"value"]' in output
    assert "optional：未提供" in output
    assert tool_result_text("catalog.resource", "Original resource text").endswith(
        "Original resource text"
    )


@pytest.mark.parametrize("serial", ["SN-100", "SN-200"])
def test_warranty_record_does_not_imply_a_remaining_coverage_countdown(serial):
    output = tool_result_text("check_warranty", WARRANTIES[serial])
    assert "不表示从今天起的剩余保修时长" in output
    assert "未提供保修起止日期或到期时间" in output
    assert "不表示" not in tool_result_text("unknown", {"months": 24})


def test_mcp_resource_uses_public_content_label_and_preserves_source_notice():
    notice = "Synthetic catalog v1. Product warranty lasts 24 months. No real customer data."
    output = tool_result_text("catalog.resource", {"text": notice})
    assert f"内容：{notice}" in output
    assert "text：" not in output


@pytest.mark.parametrize(
    "tool,arguments,label,identifier",
    [
        ("lookup_product", {"sku": "P-999"}, "产品编号", "P-999"),
        ("catalog.lookup_product", {"sku": "P-999"}, "产品编号", "P-999"),
        ("check_warranty", {"serial_number": "SN-999"}, "设备序列号", "SN-999"),
        ("lookup_customer", {"customer_id": "C-999"}, "客户编号", "C-999"),
    ],
)
def test_missing_record_has_actionable_feedback_without_fabricated_records(
    tool, arguments, label, identifier
):
    output = tool_error_text(tool, "record_not_found", arguments=arguments)
    assert "未找到" in output and label in output and identifier in output
    assert f"请核对{label}后重新提供" in output
    assert "未找到" not in tool_error_text(tool, "http_404", arguments=arguments)
    assert "未找到" not in tool_error_text("unknown", "record_not_found", arguments=arguments)
