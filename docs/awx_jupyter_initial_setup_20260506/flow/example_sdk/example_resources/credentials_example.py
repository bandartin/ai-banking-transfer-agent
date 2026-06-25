"""
Learn the basic Credential.get flow.
Prerequisite: MLDL_USER_ID and MLDL_PROJ_ID in development mode.
Credential.get automatically prefetches external resource metadata by default.
"""

from awx.resources import Credential
from awx.common import config

def main():
    print("=== AWX Resources - Credentials Example ===\n")
    print("무엇을 배우나: 필수 파라미터, 개발/추론 모드 차이, 기본 credential 구조\n")
    
    # Check required environment variables
    if not config.USER_ID:
        print("⚠️  MLDL_USER_ID environment variable is not set.")
        print("   Please set it before running this example:")
        print("   export MLDL_USER_ID=your_user_id\n")
        return
    
    if not config.PROJECT_ID:
        print("⚠️  MLDL_PROJ_ID environment variable is not set.")
        print("   Please set it before running this example:")
        print("   export MLDL_PROJ_ID=your_project_id\n")
        return
    
    print(f"✓ USER_ID: {config.USER_ID}")
    print(f"✓ PROJECT_ID: {config.PROJECT_ID}\n")
    
    service_id = 29  # Replace with your actual service ID
    provider_alias = "OpenAI"  # REQUIRED: Provider (e.g., "OpenAI", "Anthropic", "Azure")
    service_type_name = "LLM"  # REQUIRED: Service type (e.g., "LLM", "EMBEDDING")
    
    # Get credentials (automatically fetches external resources)
    print("1. Fetching credentials for service ID...")
    print(f"   - Service ID: {service_id}")
    print(f"   - Provider: {provider_alias} (REQUIRED)")
    print(f"   - Service Type: {service_type_name} (REQUIRED)")
    print(f"   - Solution ID: {config.PLATFORM_CODE} (from MLDL_PLATFORM_CODE)\n")
    
    cred_client = Credential()
    
    try:
        # provider_alias and service_type_name are REQUIRED
        credentials = cred_client.get(
            service_id=service_id,
            provider_alias=provider_alias,
            service_type_name=service_type_name
        )
        
        if credentials:
            print(f"✓ Found {len(credentials)} credential(s)")
            
            # Display first credential details
            first_cred = credentials[0]
            print(f"\nFirst Credential:")
            print(f"  - Credential ID: {first_cred.get('credentialId')}")
            print(f"  - Service ID: {first_cred.get('serviceId')}")
            print(f"  - Token Limit: {first_cred.get('tokenLimit')}")
            
            # Display variables (environment variables, API keys, etc.)
            if 'variables' in first_cred and first_cred['variables']:
                print(f"  - Variables:")
                for var in first_cred['variables']:
                    attr_name = var.get('attributeName')
                    attr_type = var.get('attributeType')
                    auth_type = var.get('authType')
                    # Mask sensitive values
                    attr_value = var.get('attributeValue', '')
                    masked_value = f"{attr_value[:10]}..." if len(attr_value) > 10 else attr_value
                    print(f"    * {attr_name} ({attr_type}, {auth_type}): {masked_value}")
        else:
            print("✗ No credentials found")
            
    except Exception as e:
        print(f"✗ Error fetching credentials: {e}")
        return

    # Extract and use API key
    print("\n2. Extracting API key from credentials...")
    try:
        credentials = cred_client.get(
            service_id=service_id,
            provider_alias=provider_alias,
            service_type_name=service_type_name
        )
        
        if credentials:
            first_cred = credentials[0]
            
            # Find OPENAI_API_KEY in variables
            if 'variables' in first_cred:
                api_key_var = next(
                    (v for v in first_cred['variables'] 
                     if v.get('attributeName') == 'OPENAI_API_KEY'),
                    None
                )
                
                if api_key_var:
                    api_key = api_key_var.get('attributeValue')
                    print(f"✓ OpenAI API Key found")
                    print(f"  - Key (masked): {api_key[:20]}..." if api_key else "  - No API key value")
                    print(f"  - Auth Type: {api_key_var.get('authType')}")
                    
                    # In development mode, the SDK may materialize internal cache state.
                    if not config.IS_INFERENCE:
                        print("\n✓ Credentials resolved for local development mode")
                        print("  Do not depend on or commit any local credential cache artifacts.")
                        print("  External resource metadata is available on the fetched credential payload.")
                else:
                    print("✗ No OPENAI_API_KEY found in variables")
            else:
                print("✗ No variables found in credential")
                
    except Exception as e:
        print(f"✗ Error: {e}")

    # Example: Skip auto-fetch if needed
    print("\n3. Advanced: Skip auto-fetch of external resources...")
    try:
        credentials = cred_client.get(
            service_id=service_id,
            provider_alias=provider_alias,
            service_type_name=service_type_name,
            auto_fetch_external_resources=False  # Skip auto-fetch
        )
        print(f"✓ Fetched {len(credentials)} credential(s) without external resources")
        print("  Local cache artifacts, if any, may omit external metadata in this mode.")
    except Exception as e:
        print(f"✗ Error: {e}")

    # Example: Use different provider or service type
    print("\n4. Advanced: Use different provider or service type...")
    print("   Examples:")
    print("   - Anthropic LLM:")
    print("     credentials = cred.get(service_id=29, provider_alias='Anthropic', service_type_name='LLM')")
    print("   - OpenAI EMBEDDING:")
    print("     credentials = cred.get(service_id=29, provider_alias='OpenAI', service_type_name='EMBEDDING')")
    print("   - Azure LLM:")
    print("     credentials = cred.get(service_id=29, provider_alias='Azure', service_type_name='LLM')")


if __name__ == "__main__":
    main()
