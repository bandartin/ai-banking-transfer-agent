"""
Learn the basic guardrail APIs.
Prerequisite: a flow with accessible guardrail policies.
This example shows get_policies, apply, and check in one path.
"""

from awx.resources import Guardrail


def _print_policy_summary(policies: object) -> None:
    if not isinstance(policies, dict):
        print("  - Policy response type:", type(policies).__name__)
        return

    mandatory = policies.get("mandatory", {})
    optional = policies.get("optional", {})
    mandatory_input = mandatory.get("input", []) if isinstance(mandatory, dict) else []
    mandatory_output = mandatory.get("output", []) if isinstance(mandatory, dict) else []
    optional_input = optional.get("input", []) if isinstance(optional, dict) else []
    optional_output = optional.get("output", []) if isinstance(optional, dict) else []

    print("  - mandatory.input:", len(mandatory_input))
    print("  - mandatory.output:", len(mandatory_output))
    print("  - optional.input:", len(optional_input))
    print("  - optional.output:", len(optional_output))


def main() -> None:
    print("=== AWX Resources - Guardrails Example ===\n")
    print("이 예제는 정책 조회 -> 입력 적용 -> 출력 적용 -> 안전성 확인 순서로 진행합니다.\n")

    guardrail = Guardrail()

    print("1. Loading policy summary...")
    try:
        policies = guardrail.get_policies()
        print("✓ Loaded policy summary")
        _print_policy_summary(policies)
    except Exception as exc:
        print(f"! Failed to load policies: {exc}")

    raw_input = "고객 전화번호는 010-1234-5678 입니다."
    print("\n2. Applied input guardrail...")
    try:
        filtered_input, input_status = guardrail.apply(
            input_text=raw_input,
            policy_id=0,
            mode="input",
        )
        print("✓ Applied input guardrail")
        print("  - status:", input_status)
        print("  - before:", raw_input)
        print("  - after:", filtered_input)
    except Exception as exc:
        filtered_input = raw_input
        print(f"! Failed to apply input guardrail: {exc}")

    llm_output = f"모델 응답: {filtered_input}"
    print("\n3. Applied output guardrail...")
    try:
        filtered_output, output_status = guardrail.apply(
            input_text=llm_output,
            policy_id=0,
            mode="output",
        )
        print("✓ Applied output guardrail")
        print("  - status:", output_status)
        print("  - before:", llm_output)
        print("  - after:", filtered_output)
    except Exception as exc:
        filtered_output = llm_output
        print(f"! Failed to apply output guardrail: {exc}")

    print("\n4. Checked output safety...")
    try:
        checked = guardrail.check(
            text=filtered_output,
            mode="output",
            policy_id=0,
        )
        print("✓ Checked output safety")
        print("  - is_safe:", checked.get("is_safe", True))
        print("  - severity:", checked.get("severity", "unknown"))
        print("  - violations:", checked.get("violations", []))
    except Exception as exc:
        print(f"! Failed to check output safety: {exc}")


if __name__ == "__main__":
    main()
