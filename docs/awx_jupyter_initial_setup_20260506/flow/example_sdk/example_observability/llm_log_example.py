"""
Learn the basic LLMLog.log flow.
Prerequisite: collector reachability if you want live delivery.
This example compares simple, detailed, and minimal log payloads.
"""

from awx.observability import LLMLog, LogInput
import datetime

def main():
    print("=== AWX Observability - LLM Log Example ===\n")
    print("무엇을 배우나: LogInput 필드 구성과 단계별 로그 전송 패턴\n")
    
    # Create LLMLog client
    llm_log = LLMLog()
    
    # Example 1: Log a simple LLM interaction
    print("1. Logging simple LLM interaction...")
    try:
        current_time = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        
        log_input = LogInput(
            start_time=current_time,
            finish_time=current_time,
            project_id="PJT20240515",
            service_id="INF2024110705",
            input_tokens=10,
            output_tokens=50,
            token_usage=60,
            input_message="What is machine learning?",
            output_message="Machine learning is a subset of AI..."
        )
        
        llm_log.log(log_input)
        print("✓ LLM interaction logged successfully")
        
    except Exception as e:
        print(f"✗ Error logging interaction: {e}")

    # Example 2: Log with detailed metadata
    print("\n2. Logging LLM interaction with full metadata...")
    try:
        start = datetime.datetime.now()
        # Simulate processing time
        finish = datetime.datetime.now()
        
        log_input = LogInput(
            start_time=start.strftime("%Y-%m-%d %H:%M:%S.%f"),
            finish_time=finish.strftime("%Y-%m-%d %H:%M:%S.%f"),
            project_id="PJT20240515",
            service_id="INF2024110705",
            input_tokens=25,
            output_tokens=100,
            token_usage=125,
            elapsed_time=int((finish - start).total_seconds() * 1000),
            input_message="Explain gradient descent in simple terms.",
            output_message="Gradient descent is an optimization algorithm...",
            flow_his_in_out=["user query", "assistant response"],
            gpt_response_content=["response part 1", "response part 2"],
            gpt_start_time=[start.strftime("%Y-%m-%d %H:%M:%S.%f")],
            gpt_finish_time=[finish.strftime("%Y-%m-%d %H:%M:%S.%f")],
            gpt_elapsed_time=[100],
            custom01="model_version:gpt-4",
            custom02="temperature:0.7"
        )
        
        llm_log.log(log_input)
        print("✓ Detailed LLM log recorded")
        
    except Exception as e:
        print(f"✗ Error: {e}")

    # Example 3: Log minimal required fields only
    print("\n3. Logging with minimal fields...")
    try:
        current_time = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        
        log_input = LogInput(
            start_time=current_time,
            finish_time=current_time
            # project_id and service_id will use defaults from config
        )
        
        llm_log.log(log_input)
        print("✓ Minimal log recorded")
        
    except Exception as e:
        print(f"✗ Error: {e}")

    # Example 4: Logging with status
    print("\n4. Logging with status...")
    try:
        current_time = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        
        log_input = LogInput(
            start_time=current_time,
            finish_time=current_time,
            input_message="Status check",
            output_message="All good",
            status="completed"
        )
        
        llm_log.log(log_input)
        print("✓ Log with status recorded")
        
    except Exception as e:
        print(f"✗ Error: {e}")


if __name__ == "__main__":
    main()
