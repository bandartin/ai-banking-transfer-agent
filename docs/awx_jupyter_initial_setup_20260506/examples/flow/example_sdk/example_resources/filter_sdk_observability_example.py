"""
awx-resources Filter SDK + Observability Example

Scenario:
- One trace with two LLM spans.
- For each LLM, guardrail is applied to input and output.
- Guardrail application metadata is recorded on the corresponding guardrail span.
"""

from __future__ import annotations

from opentelemetry import trace

from awx.resources import Guardrail


def _trace_id_hex(span) -> str:
    ctx = span.get_span_context()
    if ctx is None or not getattr(ctx, "is_valid", False):
        return ""
    return f"{ctx.trace_id:032x}"


def _invoke_llm(*, model_name: str, prompt: str) -> str:
    # Example-only deterministic LLM simulation.
    return f"{model_name} response for: {prompt}"


def _safe_apply_guardrail(
    *,
    guardrail: Guardrail,
    input_text: str,
    policy_id: int,
    mode: str,
) -> tuple[str, str]:
    try:
        return guardrail.apply(
            input_text=input_text,
            policy_id=policy_id,
            mode=mode,
        )
    except Exception as exc:
        print(f"[warn] guardrail apply failed (mode={mode}): {exc}")
        return input_text, "error"


def _run_llm_with_guardrail(
    *,
    tracer,
    llm_idx: int,
    model_name: str,
    input_text: str,
) -> tuple[str, str, str]:
    guardrail = Guardrail()
    with tracer.start_as_current_span(f"llm{llm_idx}.guardrail.input"):
        guarded_input, input_status = _safe_apply_guardrail(
            guardrail=guardrail,
            input_text=input_text,
            policy_id=0,
            mode="input",
        )

    with tracer.start_as_current_span(f"llm{llm_idx}.invoke"):
        llm_output = _invoke_llm(model_name=model_name, prompt=guarded_input)

    with tracer.start_as_current_span(f"llm{llm_idx}.guardrail.output"):
        guarded_output, output_status = _safe_apply_guardrail(
            guardrail=guardrail,
            input_text=llm_output,
            policy_id=0,
            mode="output",
        )

    return guarded_output, input_status, output_status


def main() -> None:
    tracer = trace.get_tracer("awx.example.filter-sdk-observability")
    guardrail = Guardrail()

    print("=== Filter SDK Observability Scenario ===")
    try:
        policies = guardrail.get_policies()
    except Exception as exc:
        print(f"[warn] guardrail get_policies failed: {exc}")
        policies = []
    print(
        "loaded policies:",
        len(policies) if isinstance(policies, list) else "dict",
    )

    with tracer.start_as_current_span("two-llm.single-trace") as root_span:
        print("trace_id:", _trace_id_hex(root_span))

        llm1_output, llm1_input_status, llm1_output_status = _run_llm_with_guardrail(
            tracer=tracer,
            llm_idx=1,
            model_name="llm-1",
            input_text="first prompt with phone 010-1234-5678",
        )
        print(
            "llm1 statuses:",
            {"input": llm1_input_status, "output": llm1_output_status},
        )

        llm2_output, llm2_input_status, llm2_output_status = _run_llm_with_guardrail(
            tracer=tracer,
            llm_idx=2,
            model_name="llm-2",
            input_text=llm1_output,
        )
        print(
            "llm2 statuses:",
            {"input": llm2_input_status, "output": llm2_output_status},
        )
        print("final_output:", llm2_output)


if __name__ == "__main__":
    main()
