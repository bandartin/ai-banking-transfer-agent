"""
Learn the basic Metering.collect flow.
Prerequisite: collector reachability if you want live delivery.
This example focuses on payload shape, not backend setup.
"""

from awx.observability import Metering
import datetime

def main():
    print("=== AWX Observability - Metering Example ===\n")
    print("무엇을 배우나: input/output text와 credential 정보로 metering 보내기\n")
    
    # Create Metering client
    metering = Metering()
    
    # Example 1: Collect LLM usage metrics
    print("1. Collecting LLM usage metrics...")
    
    try:
        input_output_texts = [
            {
                "input_text": "What is machine learning?",
                "output_text": "Machine learning is a subset of artificial intelligence..."
            }
        ]
        
        credential = {
            "serviceId": "10161",  # Your service ID
            "credentialId": "123"  # Credential ID used
        }
        
        result = metering.collect(
            input_output_texts=input_output_texts,
            model_name="gpt-4",
            credential=credential,
            model_type="LLM",
            platform_code="BUILDER"
        )
        
        print("✓ Metering data collected successfully")
        print(f"  Result: {result}")
        
    except Exception as e:
        print(f"✗ Error collecting metering data: {e}")

    # Example 2: Advanced metering with timestamps
    print("\n2. Advanced metering with timestamps...")
    try:
        start_time = datetime.datetime.now()
        # Simulate some processing
        end_time = datetime.datetime.now()
        
        input_output_texts = [
            {
                "input_text": "Explain gradient descent in simple terms.",
                "output_text": "Gradient descent is an optimization algorithm used to minimize..."
            },
            {
                "input_text": "What are neural networks?",
                "output_text": "Neural networks are computing systems inspired by biological..."
            }
        ]
        
        credential = {
            "serviceId": "10161",
            "credentialId": "123"
        }
        
        result = metering.collect(
            input_output_texts=input_output_texts,
            model_name="gpt-4-turbo",
            credential=credential,
            process_start_time=start_time.strftime("%Y-%m-%d %H:%M:%S"),
            process_end_time=end_time.strftime("%Y-%m-%d %H:%M:%S"),
            model_type="LLM",
            platform_code="BUILDER"
        )
        
        print("✓ Advanced metering data collected")
        
    except Exception as e:
        print(f"✗ Error: {e}")


if __name__ == "__main__":
    main()
