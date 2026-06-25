"""
Learn the public AWX telemetry API.
Prerequisite: none.
This example uses awx.observability.telemetry.Tracer only.
"""

from awx.observability.telemetry import Tracer


def main() -> None:
    print("=== AWX Observability - Telemetry Example ===\n")

    tracer = Tracer()

    print("1. Creating a trace with nested spans...")
    with tracer.trace("llm-request") as current_trace:
        current_trace.attributes(model="gpt-4o-mini", operation="demo")
        current_trace.add_label("tutorial")
        print("✓ Created trace 'llm-request'")

        with current_trace.span("prepare-prompt") as prompt_span:
            prompt_span.attributes(prompt_length=42, prompt_template="summary")
            print("  ✓ Created nested span 'prepare-prompt'")

        with current_trace.span("call-llm") as llm_span:
            llm_span.attributes(provider="OpenAI", temperature=0.0)
            llm_span.add_event("request.sent", "Simulated outbound LLM request")
            print("  ✓ Created nested span 'call-llm'")

        current_trace.set_metric("latency_ms", 42, "ms")
        print("✓ Recorded trace metric 'latency_ms'")

    print("\n2. Capturing an error on a second trace...")
    try:
        with tracer.trace("training-job") as training_trace:
            training_trace.attributes(job_id="job-12345")
            print("✓ Created trace 'training-job'")

            with training_trace.span("validate-config") as config_span:
                config_span.attributes(config_version="demo")
                config_span.add_event("validation.started", "Checking required fields")
                print("  ✓ Created nested span 'validate-config'")

            raise ValueError("demo validation failure")
    except ValueError as exc:
        print(f"✓ Captured error metadata: {exc}")


if __name__ == "__main__":
    main()
