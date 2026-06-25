"""
Learn the basic Prompt.list flow.
Prerequisite: a project with accessible prompts.
This example focuses on prompt structure and template inspection.
"""

from awx.resources import Prompt

def main():
    print("=== AWX Resources - Prompts Example ===\n")
    print("무엇을 배우나: 프로젝트 프롬프트 조회와 템플릿 구조 확인\n")
    
    # Create Prompt client
    prompt_client = Prompt()
    
    # Example 1: Get all prompts for the project
    print("1. Fetching all prompts...")
    
    try:
        prompts = prompt_client.list()
        
        if prompts and len(prompts) > 0:
            print(f"✓ Found {len(prompts)} prompt(s)")
            
            # Display first prompt
            first_prompt = prompts[0]
            print(f"\nFirst Prompt:")
            print(f"  - ID: {first_prompt.get('id')}")
            print(f"  - Name: {first_prompt.get('name')}")
            print(f"  - Variables: {first_prompt.get('variables')}")
            print(f"  - Meta Prompt: {first_prompt.get('meta_prompt')[:100] if first_prompt.get('meta_prompt') else 'N/A'}...")
        else:
            print("✗ No prompts found")
            
    except Exception as e:
        print(f"✗ Error fetching prompts: {e}")

    # Example 2: Use prompt template
    print("\n2. Using prompt template...")
    try:
        prompts = prompt_client.list()
        
        if prompts and len(prompts) > 0:
            prompt = prompts[0]
            
            print(f"✓ Using prompt: {prompt.get('name')}")
            print(f"  - User Prompt Template: {prompt.get('user_prompt')[:150]}...")
            
            # Display variables needed
            if prompt.get('variables'):
                print(f"  - Required variables: {prompt.get('variables')}")
            
    except Exception as e:
        print(f"✗ Error using prompt: {e}")

    # Example 3: Filter prompts by name
    print("\n3. Finding specific prompt...")
    try:
        prompts = prompt_client.list()
        
        if prompts:
            # Example: Find prompt containing specific keyword
            search_keyword = "summarize"  # Replace with your search term
            matching_prompts = [
                p for p in prompts 
                if search_keyword.lower() in p.get('name', '').lower()
            ]
            
            if matching_prompts:
                print(f"✓ Found {len(matching_prompts)} matching prompt(s):")
                for p in matching_prompts:
                    print(f"  - {p.get('name')} (ID: {p.get('id')})")
            else:
                print(f"✗ No prompts matching '{search_keyword}' found")
            
    except Exception as e:
        print(f"✗ Error: {e}")


if __name__ == "__main__":
    main()
