"""Deterministic offline demonstration provider, not a model-quality benchmark."""

import json
import re

from omniagent.llm import LLMRequest, LLMResponse, LLMUsage


def lexical_terms(value: str) -> set[str]:
    words = set(re.findall(r"[a-z0-9-]+", value.lower())) - {
        "what",
        "is",
        "the",
        "a",
        "an",
        "and",
        "of",
        "for",
        "please",
        "policy",
        "how",
        "to",
    }
    for group in re.findall(r"[\u4e00-\u9fff]+", value):
        words.update(group[index : index + 2] for index in range(len(group) - 1))
    return words


class DemoProvider:
    def generate(self, request: LLMRequest) -> LLMResponse:
        output: dict[str, object]
        evidence = next(
            (
                m.content
                for m in request.messages
                if m.content.startswith("UNTRUSTED EVIDENCE DATA\n")
            ),
            None,
        )
        query = request.messages[-2].content if evidence else request.messages[-1].content
        if evidence:
            pack = json.loads(evidence.split("\n", 1)[1])
            candidates = pack["context_pack"]["evidence"]
            ranked = sorted(
                candidates,
                key=lambda item: (
                    -len(lexical_terms(query) & lexical_terms(item["content"])),
                    item["citation_label"],
                ),
            )
            if ranked and lexical_terms(query) & lexical_terms(ranked[0]["content"]):
                item = ranked[0]
                output = {
                    "answer_draft": {
                        "claims": [
                            {
                                "claim_id": "CL1",
                                "text": item["content"],
                                "citation_labels": [item["citation_label"]],
                            }
                        ]
                    }
                }
            else:
                output = {"abstention_reason": "No relevant authorized evidence was found."}
        else:
            output = self.route(request.messages[0].content, query)
        content = json.dumps(output, ensure_ascii=False)
        incoming = sum(len(m.content.encode("utf-8")) for m in request.messages)
        outgoing = len(content.encode("utf-8"))
        return LLMResponse(
            model=request.model,
            content=content,
            usage=LLMUsage(
                input_tokens=incoming, output_tokens=outgoing, total_tokens=incoming + outgoing
            ),
            finish_reason="stop",
        )

    def route(self, instruction: str, query: str) -> dict[str, object]:
        if query.strip().lower() in {"hello", "hi", "你好"}:
            return {
                "route": "direct",
                "reason": "Greeting",
                "confidence": 1,
                "output_text": "你好，请查询此助手授权的知识或工具。",
            }
        result: dict[str, object] = {
            "route": "retrieve",
            "reason": "Knowledge request",
            "confidence": 1.0,
        }
        if query.strip().startswith("{"):
            try:
                proposal = json.loads(query)
                if isinstance(proposal.get("tool"), str) and isinstance(
                    proposal.get("arguments"), dict
                ):
                    return {
                        "route": "tool",
                        "reason": "Explicit untrusted tool proposal",
                        "confidence": 1,
                        "tool_name": proposal["tool"],
                        "args": proposal["arguments"],
                    }
            except (ValueError, AttributeError):
                pass
        if re.search(r"\bpolicy\b|政策|制度|流程|规定", query, re.IGNORECASE):
            return result
        match = re.search(r"<routing-config>(.*?)</routing-config>", instruction, re.DOTALL)
        rules = json.loads(match.group(1)) if match else []
        for rule in rules:
            if any(re.search(pattern, query, re.IGNORECASE) for pattern in rule["patterns"]):
                arguments: dict[str, object] = {}
                for name, field in rule["fields"].items():
                    matched = re.search(field["pattern"], query, re.IGNORECASE)
                    value = matched.group(1) if matched else field["default"]
                    arguments[name] = int(value) if field.get("type") == "integer" else value
                return {
                    "route": "tool",
                    "reason": "Configured offline routing rule",
                    "confidence": 1,
                    "tool_name": rule["tool"],
                    "args": arguments,
                }
        return result
