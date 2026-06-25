"""
Learn the InferenceCollector callback pattern.
Use the collector env injected by the runtime when available.
Set local overrides outside this script only when you intentionally want a custom collector target.
"""

import time
from datetime import datetime

from awx.observability import InferenceCollector


def main():
    print("=== AWX Observability - InferenceCollector Example ===\n")
    if InferenceCollector is None:
        print("! InferenceCollector is unavailable in this environment.")
        return

    # Example 1: Basic usage
    print("1. Initializing InferenceCollector...")
    ic = InferenceCollector()
    print(f"✓ InferenceCollector initialized (use_yn={ic.use_yn})")

    # Example 2: Get model info
    print("\n2. Getting model information...")
    model_info = ic.get_model_info()
    print(f"✓ Model info: {model_info}")

    # Example 3: Push inference results
    print("\n3. Pushing inference results to queue...")
    for i in range(5):
        start_time = datetime.now()
        time.sleep(0.1)  # Simulate processing
        end_time = datetime.now()

        ic.push_result_to_queue(
            model_id="gpt-4",
            model_ver="1.0",
            request_body={"question": f"Test question {i}"},
            response_body={"result": f"Test answer {i}"},
            process_start_time=start_time,
            process_end_time=end_time,
            api_url="/api/chat",
            client_ip="127.0.0.1",
            request_header={"content-type": "application/json"},
            response_header={"content-type": "application/json"},
        )
        print(f"  ✓ Pushed result {i+1}/5")

    print("\n4. Waiting for queue to flush...")
    time.sleep(6)  # Wait for auto-flush (interval is 5 seconds)
    print("✓ Queue should have been flushed")

    # Example 4: Using with an application callback pattern
    print("\n5. Callback pattern example...")

    def simulate_generator(message, callback=None, callback_data=None):
        """Simulate a generator that yields tokens."""
        response = "This is a simulated response"
        tokens = response.split()

        for token in tokens:
            yield f'data: {{"token": "{token}"}}\n\n'

        # Send final result to callback
        if callback and callback.use_yn:
            callback.push_result_to_queue(
                model_id=callback_data.get("model_id"),
                model_ver=callback_data.get("model_ver"),
                process_start_time=callback_data.get("start_time"),
                process_end_time=datetime.now(),
                request_header=callback_data.get("request_header"),
                request_body=callback_data.get("request_body"),
                response_header={"content-type": "text/event-stream"},
                response_body={"result": response},
                client_ip=callback_data.get("client_ip"),
                api_url=callback_data.get("api_url"),
            )

    # Prepare callback data
    callback_data = {
        "start_time": datetime.now(),
        "model_id": "gpt-4",
        "model_ver": "1.0",
        "request_header": {"content-type": "application/json"},
        "request_body": {"question": "Hello"},
        "client_ip": "127.0.0.1",
        "api_url": "/api/chat",
    }

    # Use generator with callback
    for _ in simulate_generator("test", callback=ic, callback_data=callback_data):
        pass

    print("✓ Callback pattern executed")

    print("\n6. Cleaning up...")
    time.sleep(6)  # Wait for final flush
    print("✓ Done")

    print("\n" + "=" * 50)
    print("Example completed successfully!")
    print("=" * 50)


if __name__ == "__main__":
    main()
