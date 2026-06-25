"""
Learn the smallest public awx.core surface.
Prerequisite: none.
This example only uses Logger and Config.
"""

from awx.core import Logger, Config

def main():
    print("=== AWX Core Usage Example ===\n")
    print("무엇을 배우나: Logger 생성과 Config 읽기\n")
    
    logger = Logger()
    logger.info("Core Logger initialized.")
    
    print(f"Project ID from Config: {Config.PROJECT_ID}")
    print(f"MLDL Base URL: {Config.MLDL_BASE_URL}")
    
    logger.info(f"STATUS=SUCCESS|ACTION=CORE_TEST|PROJECT={Config.PROJECT_ID}")
    
    print("\n다음 예제: example_resources/credentials_example.py")

if __name__ == "__main__":
    main()
