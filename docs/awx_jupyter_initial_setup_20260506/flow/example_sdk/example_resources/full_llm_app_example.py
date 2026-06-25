"""
Canonical end-to-end AWX SDK example.
Prerequisite: optional MLDL_USER_ID and MLDL_PROJ_ID for live resource access.
This sample is the recommended single-file integration path.
"""

import datetime
import time
from awx.core import Config, Logger
from awx.observability import LLMLog, LogInput, Metering
from awx.resources import Credential, Guardrail, Prompt


def run_llm_app():
    print("=== AWX SDK Full Application Example ===\n")
    print("무엇을 배우나: core + resources + observability를 한 흐름으로 연결하는 최소 패턴\n")

    # 1. 초기화 (Logger)
    logger = Logger("FullLLMApp")
    logger.info("Starting AWX Integrated LLM Application...")
    logger.info(f"Environment: {'Inference' if Config.IS_INFERENCE else 'Development'}")

    # Guard examples against local runs without platform runtime metadata.
    if not Config.PROJECT_ID:
        logger.warning("PROJECT_ID not set. Set MLDL_PROJ_ID for development mode.")
        logger.info("Skipping resource operations that require PROJECT_ID...")
    if not Config.USER_ID:
        logger.warning("USER_ID not set. Set MLDL_USER_ID environment variable.")

    try:
        # 2. 프롬프트 로드 (Resources) - Skip if PROJECT_ID not available
        if Config.PROJECT_ID:
            try:
                prompt_client = Prompt()
                prompts = prompt_client.list()
                target_prompt = (
                    prompts[0]
                    if prompts
                    else {"name": "Default", "user_prompt": "Hello, {user_input}"}
                )
                logger.info(f"Prompt Loaded: {target_prompt.get('name')}")
            except Exception as e:
                logger.warning(f"Could not load prompts: {e}")
                target_prompt = {"name": "Default", "user_prompt": "Hello, {user_input}"}
        else:
            target_prompt = {"name": "Default", "user_prompt": "Hello, {user_input}"}
            logger.info("Using default prompt template")
        _ = target_prompt

        # 3. 인증 정보 및 리소스 획득 (Resources) - Skip if PROJECT_ID not available
        if Config.PROJECT_ID:
            try:
                cred_client = Credential()
                credentials = cred_client.get(
                    service_id=29,
                    provider_alias="OpenAI",
                    service_type_name="LLM",
                    tag="gpt-4",
                )
                selected_cred = credentials[0]
                logger.info(
                    "Credential Secured: %s (Tag: %s)",
                    selected_cred.get("credentialId"),
                    selected_cred.get("tag"),
                )
            except Exception as e:
                logger.warning(f"Could not load credentials: {e}")
                selected_cred = {"credentialId": "demo-cred-001", "tag": "gpt-4"}
        else:
            selected_cred = {"credentialId": "demo-cred-001", "tag": "gpt-4"}
            logger.info("Using demo credential")

        # 4. 입력 가드레일 적용 (Resources) - Skip if PROJECT_ID not available
        user_input = "안녕, 너는 누구니?"
        if Config.PROJECT_ID:
            try:
                guardrail = Guardrail()
                _ = guardrail.get_policies()
                filtered_input, input_status = guardrail.apply(
                    input_text=user_input,
                    policy_id=0,
                    mode="input",
                )

                if input_status == "blocked":
                    logger.warning("Guardrail blocked input text.")
                    return
                logger.info("Input Guardrail Passed.")
            except Exception as e:
                logger.warning(f"Could not apply guardrail: {e}")
                logger.info("Proceeding without guardrail check...")
                filtered_input = user_input
        else:
            logger.info("Skipping guardrail check (PROJECT_ID not set)")
            filtered_input = user_input

        # 5. LLM 추론 시뮬레이션
        start_time = datetime.datetime.now()
        logger.info("Simulating LLM Inference...")
        time.sleep(0.5)  # 실제 호출 대신 지연 시뮬레이션
        ai_response = "안녕하세요! 저는 AWX 플랫폼을 통해 서빙되는 AI 모델입니다."
        finish_time = datetime.datetime.now()

        # 6. 사용량 측정 전송 (Observability - Metering)
        try:
            metering = Metering()
            metering.collect(
                input_output_texts=[{"input_text": filtered_input, "output_text": ai_response}],
                model_name="gpt-4",
                credential={"serviceId": "29", "credentialId": selected_cred.get("credentialId")},
                process_start_time=start_time.strftime("%Y-%m-%d %H:%M:%S"),
                process_end_time=finish_time.strftime("%Y-%m-%d %H:%M:%S"),
            )
            logger.info("Metering data sent to collector.")
        except Exception as e:
            logger.warning(f"Could not send metering data: {e}")

        # 7. 상세 실행 로그 전송 (Observability - LLM Log)
        try:
            llm_log_client = LLMLog()
            log_data = LogInput(
                start_time=start_time.strftime("%Y-%m-%d %H:%M:%S.%f"),
                finish_time=finish_time.strftime("%Y-%m-%d %H:%M:%S.%f"),
                input_message=filtered_input,
                output_message=ai_response,
                elapsed_time=int((finish_time - start_time).total_seconds() * 1000),
                custom01="IntegratedAppExample",
            )
            llm_log_client.log(log_data)
            logger.info("Detailed LLM Log sent successfully.")
        except Exception as e:
            logger.warning(f"Could not send LLM log: {e}")

        print("\n" + "=" * 50)
        print("Application Execution Completed Successfully!")
        print(f"AI Response: {ai_response}")
        print("Next step: example_app/guardrail-sdk-auto for stream guardrail integration.")
        print("=" * 50)

    except Exception as e:
        logger.error(f"Application Error: {str(e)}")
        raise


if __name__ == "__main__":
    run_llm_app()
