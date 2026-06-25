"""
Learn the basic MCP discovery flow.
Prerequisite: a flow with available MCP metadata or cached MCP info.
This example focuses on list/find/get_client patterns.
"""

from awx.resources import Mcp

def main():
    print("=== AWX Resources - MCP Usage Example ===\n")
    print("무엇을 배우나: MCP 서버 목록 조회, 특정 서버 찾기, client 진입점 확인\n")

    try:
        # MCP 클라이언트 생성
        mcp_resource = Mcp()
        
        print("1. Listing MCP servers...")
        mcps = mcp_resource.get()  # force_refresh=False (기본값)

        if not mcps:
            print("! No MCP servers were returned.")
            print("  - Development mode: check GENAI_TEXT_FLOW_ID and Portal access")
            print("  - Inference mode: check cached MCP metadata file")
            return

        for mcp_server in mcps:
            print(f"Name: {mcp_server.name}")
            print(f"ID: {mcp_server.id}")
            print(f"Endpoint: {mcp_server.endpoint}")

        # 특정 MCP 서버 찾기
        print("\n2. Finding specific MCP server...")
        found_mcp = mcps.find(lambda m: m.name == "MyMCPService")
        
        if found_mcp:
            print(f"Found MCP server: {found_mcp.name}")
            # MCP 클라이언트 생성
            client = found_mcp.get_client()

            # 도구 목록 조회
            print("\n3. Listing tools...")
            tools = client.list_tools()
            for tool in tools:
                print(f"Tool: {tool.get('name')} - {tool.get('description')}")

            # 도구 호출
            print("\n4. Calling tool...")
            try:
                result = client.call_tool(
                    name="tool_name",
                    arguments={"arg1": "value1"}
                )
                print(f"Tool Result: {result}")
            except Exception as e:
                print(f"Tool call failed (expected if tool doesn't exist): {e}")

            # 리소스 목록 조회
            print("\n5. Listing resources...")
            resources = client.list_resources()
            print(f"Resources: {resources}")

            # 리소스 읽기
            print("\n6. Reading resource...")
            try:
                resource_data = client.read_resource(uri="resource_uri")
                print(f"Resource Data: {resource_data}")
            except Exception as e:
                print(f"Resource read failed (expected if resource doesn't exist): {e}")

            # 프롬프트 목록 조회
            print("\n7. Listing prompts...")
            prompts = client.list_prompts()
            print(f"Prompts: {prompts}")

            # 프롬프트 가져오기
            print("\n8. Getting prompt...")
            try:
                prompt = client.get_prompt(
                    name="prompt_name",
                    arguments={"var1": "value1"}
                )
                print(f"Prompt: {prompt}")
            except Exception as e:
                print(f"Get prompt failed (expected if prompt doesn't exist): {e}")
        else:
            print("Note: 'MyMCPService' not found. This is expected when no matching MCP server is configured.")
            print("The discovery flow still succeeded. Next step is checking the actual MCP server names above.")

    except Exception as e:
        print(f"Error in MCP example: {e}")

if __name__ == "__main__":
    main()
