import asyncio
import httpx
import sys


async def run_decision_test():
    url = "http://localhost:18080/v1/chat/completions"
    headers = {}

    test_cases = [
        ("MINI", "명령어 오타 수정 방안", "gpt-5.4-mini"),
        ("LUNA:LOW", "파이썬에서 단순 정렬 알고리즘 작성해줘", "gpt-5.6-luna"),
        ("LUNA:MEDIUM", "기존 입력 검증 로직을 리팩토링하고 중복을 줄여줘", "gpt-5.6-luna"),
        ("TERRA:MEDIUM", "서비스 간 호출 흐름을 정리하고 중간 난이도 아키텍처 수정안을 제시해줘", "gpt-5.6-terra"),
        ("TERRA:HIGH", "복잡한 알고리즘과 다중 컴포넌트 구조를 함께 설계해줘", "gpt-5.6-terra"),
        ("TERRA:EXTRA_HIGH", "사내 데이터 파이프라인의 메모리 누수 탐지 및 튜닝 최적화 방안 제시해줘", "gpt-5.6-terra"),
        ("TERRA:MAX", "대규모 동시성 분산 락(Lock) 이슈 해결 방안 설계해줘", "gpt-5.6-terra"),
    ]

    async with httpx.AsyncClient(timeout=10.0) as client:
        for label, prompt, model in test_cases:
            print(f"\n--- [DECISION TEST: {label}] ---")
            payload = {
                "model": model,
                "messages": [{"role": "user", "content": prompt}],
                "stream": True,
            }
            try:
                async with client.stream("POST", url, json=payload, headers=headers) as response:
                    print(f"Response Status: {response.status_code}")
                    decision = ""
                    async for line in response.aiter_lines():
                        if not line.startswith("data: "):
                            continue
                        data = line[6:].strip()
                        if not data or data == "[DONE]":
                            continue
                        try:
                            event = httpx.Response(200, text=data)
                        except Exception:
                            pass
                        if '"content"' in data:
                            decision += data
                        else:
                            decision = data
                        break
                    print(f"decision: {decision}")
            except Exception as exc:
                print(f"Error executing decision test {label}: {exc}")

async def run_test():
    url = "http://localhost:18080/v1/chat/completions"
    headers = {
        "Authorization": "Bearer enterprise_token_xyz987654321"
    }

    # Test Case 1: MINI (Simple typo / grammar prompt)
    print("\n--- [TEST CASE 1: MINI] ---")
    print("Prompt: '명령어 오타 수정 방안'")
    mini_payload = {
        "model": "gpt-5.4-mini",
        "messages": [
            {"role": "user", "content": "명령어 오타 수정 방안"}
        ],
        "stream": True
    }
    
    async with httpx.AsyncClient() as client:
        try:
            async with client.stream("POST", url, json=mini_payload, headers=headers, timeout=10.0) as response:
                print(f"Response Status: {response.status_code}")
                print("Streamed Output: ", end="", flush=True)
                async for chunk in response.aiter_text():
                    print(chunk, end="", flush=True)
                print()
        except Exception as e:
            print(f"Error executing Test Case 1: {e}")

    # Test Case 2: LUNA:LOW (Simple algorithm prompt)
    print("\n--- [TEST CASE 2: LUNA:LOW] ---")
    print("Prompt: '파이썬에서 단순 정렬 알고리즘 작성해줘'")
    simple_payload = {
        "model": "gpt-5.6-luna",
        "messages": [
            {"role": "user", "content": "파이썬에서 단순 정렬 알고리즘 작성해줘"}
        ],
        "stream": True
    }
    
    async with httpx.AsyncClient() as client:
        try:
            async with client.stream("POST", url, json=simple_payload, headers=headers, timeout=10.0) as response:
                print(f"Response Status: {response.status_code}")
                print("Streamed Output: ", end="", flush=True)
                async for chunk in response.aiter_text():
                    print(chunk, end="", flush=True)
                print()
        except Exception as e:
            print(f"Error executing Test Case 2: {e}")

    # Test Case 3: TERRA:EXTRA_HIGH (Optimization / tuning prompt)
    print("\n--- [TEST CASE 3: TERRA:EXTRA_HIGH] ---")
    print("Prompt: '사내 데이터 파이프라인의 메모리 누수 탐지 및 튜닝 최적화 방안 제시해줘'")
    extra_high_payload = {
        "model": "gpt-5.6-terra",
        "messages": [
            {"role": "user", "content": "사내 데이터 파이프라인의 메모리 누수 탐지 및 튜닝 최적화 방안 제시해줘"}
        ],
        "stream": True
    }
    
    async with httpx.AsyncClient() as client:
        try:
            async with client.stream("POST", url, json=extra_high_payload, headers=headers, timeout=10.0) as response:
                print(f"Response Status: {response.status_code}")
                print("Streamed Output: ", end="", flush=True)
                async for chunk in response.aiter_text():
                    print(chunk, end="", flush=True)
                print()
        except Exception as e:
            print(f"Error executing Test Case 3: {e}")

    # Test Case 4: TERRA:MAX (Complex concurrency / lock issue prompt)
    print("\n--- [TEST CASE 4: TERRA:MAX] ---")
    print("Prompt: '대규모 동시성 분산 락(Lock) 이슈 해결 방안 설계해줘'")
    complex_payload = {
        "model": "gpt-5.6-terra",
        "messages": [
            {"role": "user", "content": "대규모 동시성 분산 락(Lock) 이슈 해결 방안 설계해줘"}
        ],
        "stream": True
    }
    
    async with httpx.AsyncClient() as client:
        try:
            async with client.stream("POST", url, json=complex_payload, headers=headers, timeout=10.0) as response:
                print(f"Response Status: {response.status_code}")
                print("Streamed Output: ", end="", flush=True)
                async for chunk in response.aiter_text():
                    print(chunk, end="", flush=True)
                print()
        except Exception as e:
            print(f"Error executing Test Case 4: {e}")

if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "decision":
        asyncio.run(run_decision_test())
    else:
        asyncio.run(run_test())
