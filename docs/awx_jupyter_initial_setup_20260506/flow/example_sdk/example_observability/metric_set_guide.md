# OTel trace로 AWX operation attribute 붙이는 예제

```python
from opentelemetry import trace


tracer = trace.get_tracer(__name__)

with tracer.start_as_current_span("llm-request") as span:
    span.set_attribute("awx.credential.id", "7")
    span.set_attribute("awx.ext.provider.id", "1")
    span.set_attribute("awx.ext.service.id", "29")
    span.set_attribute("awx.ext.service.type", "SERVICE_TYPE_01")
```

`provider alias(OpenAI)`나 `service type name(LLM)`이 아니라 `providerId/serviceId/serviceType` 값을 넣습니다.
