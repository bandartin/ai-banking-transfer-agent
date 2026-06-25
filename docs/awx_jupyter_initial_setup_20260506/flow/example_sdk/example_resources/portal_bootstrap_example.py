"""
Portal-backed AWX resource bootstrap example.
Prerequisite: optional MLDL_PROJ_ID / portal-bound resources in development mode.
This is the recommended startup helper when an app needs cache artifacts for
Credential / ExternalResource / Prompt / MCP at once.
"""

from awx.resources import bootstrap_portal_runtime


def main():
    print("=== AWX Resources - Portal Bootstrap Example ===\n")
    print("무엇을 배우나: portal 연계 resource를 startup 한 번에 prefetch하는 최소 패턴\n")

    result = bootstrap_portal_runtime(
        credential_requests=[
            {
                "service_id": 30,
                "provider_alias": "OpenAI",
                "service_type_name": "LLM",
            }
        ],
        external_resource_requests=[
            {
                "provider_alias": "OpenAI",
                "solution_id": "BUILDER",
                "service_type_name": "LLM",
            }
        ],
        prompt_requests=[{}],
        prefetch_mcp=True,
    )

    print("Bootstrap Result:")
    print(f"  - Credentials: {result.get('credentials', [])}")
    print(f"  - External Resources: {result.get('external_resources', [])}")
    print(f"  - Prompts: {result.get('prompts', [])}")
    print(f"  - MCP: {result.get('mcp')}")
    print("\nNext step: example_app 쪽에서는 launcher가 같은 API를 사용해 artifact를 준비합니다.")


if __name__ == "__main__":
    main()
