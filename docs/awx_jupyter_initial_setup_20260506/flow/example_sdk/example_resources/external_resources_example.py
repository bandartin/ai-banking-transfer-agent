"""
Learn the basic ExternalResource.get flow.
Prerequisite: provider and solution IDs that exist in your environment.
This example compares LLM and embedding resource lookups.
"""

from awx.resources import ExternalResource

def main():
    print("=== AWX Resources - External Resources Example ===\n")
    print("무엇을 배우나: provider/service type 조합으로 외부 리소스 조회하기\n")
    
    # Create ExternalResource client
    ext_res_client = ExternalResource()
    
    # Example 1: Get OpenAI LLM resources
    print("1. Fetching OpenAI LLM resources...")
    
    try:
        resources = ext_res_client.get(
            provider_alias="OpenAI",
            solution_id="BUILDER",
            service_type_name="LLM"
        )
        
        if resources:
            print(f"✓ Found {len(resources)} resource(s)")
            
            # Display first resource
            first_resource = resources[0]
            print(f"\nFirst Resource:")
            print(f"  - Provider: {first_resource.get('providerAlias')}")
            print(f"  - Endpoint: {first_resource.get('endpoint')}")
            print(f"  - Model Alias: {first_resource.get('modelAlias')}")
            print(f"  - Actual Model: {first_resource.get('actualModelName')}")
        else:
            print("✗ No resources found")
            
    except Exception as e:
        print(f"✗ Error fetching resources: {e}")

    # Example 2: Get Azure OpenAI resources
    print("\n2. Fetching Azure OpenAI resources...")
    try:
        resources = ext_res_client.get(
            provider_alias="AzureOpenAI",
            solution_id="BUILDER",
            service_type_name="LLM"
        )
        
        if resources:
            print(f"✓ Found {len(resources)} Azure resource(s)")
            
            for idx, resource in enumerate(resources, 1):
                print(f"\nResource {idx}:")
                print(f"  - Deployment: {resource.get('deploymentName')}")
                print(f"  - Endpoint: {resource.get('endpoint')}")
                print(f"  - API Version: {resource.get('apiVersion')}")
        else:
            print("✗ No Azure resources found")
            
    except Exception as e:
        print(f"✗ Error: {e}")

    # Example 3: Get embedding service resources
    print("\n3. Fetching embedding service resources...")
    try:
        resources = ext_res_client.get(
            provider_alias="OpenAI",
            solution_id="BUILDER",
            service_type_name="EMBEDDING"
        )
        
        if resources:
            print(f"✓ Found {len(resources)} embedding resource(s)")
            
            for resource in resources:
                print(f"  - Model: {resource.get('modelAlias')}")
                print(f"  - Dimensions: {resource.get('dimensions')}")
        else:
            print("✗ No embedding resources found")
            
    except Exception as e:
        print(f"✗ Error: {e}")

    # Example 4: Filter resources by specific criteria
    print("\n4. Filtering resources by model type...")
    try:
        all_resources = ext_res_client.get(
            provider_alias="OpenAI",
            solution_id="BUILDER",
            service_type_name="LLM"
        )
        
        # Filter for GPT-4 models
        gpt4_resources = [
            r for r in all_resources 
            if 'gpt-4' in r.get('actualModelName', '').lower()
        ]
        
        print(f"✓ Found {len(gpt4_resources)} GPT-4 resource(s)")
        
        for resource in gpt4_resources:
            print(f"  - {resource.get('modelAlias')}: {resource.get('actualModelName')}")
            
    except Exception as e:
        print(f"✗ Error: {e}")


if __name__ == "__main__":
    main()
