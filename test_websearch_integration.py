# test_websearch_integration.py
"""
웹서치 → VP2 연동 테스트 스크립트

사용법:
1. VP2 서버 실행 (localhost:8000)
2. VP-Web-Search 서버 실행 (localhost:8001)
3. python test_websearch_integration.py
"""

import requests
import time
import json

VP2_URL = "http://localhost:8000"
WEB_SEARCH_URL = "http://localhost:8001"

# 테스트용 case_id
TEST_CASE_ID = "test-case-" + str(int(time.time()))


def test_1_health_check():
    """1. 서버 상태 확인"""
    print("\n=== 1. 서버 상태 확인 ===")

    try:
        r = requests.get(f"{VP2_URL}/health", timeout=5)
        print(f"VP2: {r.status_code} - {r.json()}")
    except Exception as e:
        print(f"VP2 연결 실패: {e}")
        return False

    try:
        r = requests.get(f"{WEB_SEARCH_URL}/health", timeout=5)
        print(f"Web Search: {r.status_code} - {r.json()}")
    except Exception as e:
        print(f"Web Search 연결 실패: {e}")
        return False

    return True


def test_2_send_to_websearch():
    """2. 웹서치 시스템에 데이터 전송"""
    print("\n=== 2. 웹서치 시스템에 데이터 전송 ===")

    payload = {
        "case_id": TEST_CASE_ID,
        "round_no": 1,
        "turns": [
            {"role": "offender", "text": "안녕하세요, 서울중앙지검 수사관입니다."},
            {"role": "victim", "text": "네? 검찰이요?"},
            {"role": "offender", "text": "고객님 명의 계좌가 범죄에 연루되어 조사가 필요합니다."},
            {"role": "victim", "text": "제가요? 무슨 범죄요?"},
        ],
        "judgement": {
            "phishing": False,
            "risk": {"score": 30, "level": "medium"},
            "evidence": "피해자가 의심하고 있으나 아직 개인정보 제공 안함",
        },
        "scenario": {"purpose": "검찰 사칭 보이스피싱"},
        "victim_profile": {"meta": {"age": 50}},
    }

    try:
        r = requests.post(
            f"{WEB_SEARCH_URL}/api/v1/judgements",
            json=payload,
            params={"auto_analyze": "true"},
            timeout=10
        )
        print(f"전송 결과: {r.status_code}")
        print(json.dumps(r.json(), indent=2, ensure_ascii=False))
        return r.status_code == 200
    except Exception as e:
        print(f"전송 실패: {e}")
        return False


def test_3_wait_for_webhook():
    """3. VP2에서 webhook 수신 대기"""
    print("\n=== 3. Webhook 수신 대기 (최대 120초) ===")

    start = time.time()
    timeout = 120

    while (time.time() - start) < timeout:
        try:
            r = requests.get(
                f"{VP2_URL}/api/external/webhook/reports/case/{TEST_CASE_ID}",
                timeout=5
            )
            if r.status_code == 200:
                data = r.json()
                if data.get("count", 0) > 0:
                    print(f"\n✅ Webhook 수신 완료! ({time.time() - start:.1f}초)")
                    print(json.dumps(data, indent=2, ensure_ascii=False)[:2000])
                    return True
        except:
            pass

        elapsed = int(time.time() - start)
        print(f"\r대기 중... {elapsed}초", end="", flush=True)
        time.sleep(2)

    print(f"\n❌ 타임아웃 ({timeout}초)")
    return False


def test_4_check_reports_store():
    """4. external_reports_store 확인"""
    print("\n=== 4. Reports Store 확인 ===")

    try:
        # 전체 리포트 목록
        r = requests.get(f"{VP2_URL}/api/external/webhook/reports", timeout=5)
        data = r.json()
        print(f"총 저장된 리포트: {data.get('count', 0)}건")

        if data.get("items"):
            latest = data["items"][-1]
            print(f"최신 리포트 case_id: {latest.get('case_id')}")
            print(f"최신 리포트 analysis_id: {latest.get('analysis_id')}")

        return True
    except Exception as e:
        print(f"조회 실패: {e}")
        return False


def test_5_simulate_guidance_polling():
    """5. guidance_generator의 polling 시뮬레이션"""
    print("\n=== 5. Polling 시뮬레이션 ===")

    # external_reports_store의 get_latest_report_by_case와 동일한 로직
    try:
        r = requests.get(
            f"{VP2_URL}/api/external/webhook/reports/case/{TEST_CASE_ID}",
            timeout=5
        )
        if r.status_code == 200:
            data = r.json()
            if data.get("items"):
                print(f"✅ case_id={TEST_CASE_ID}로 리포트 조회 성공")
                report = data["items"][0]
                techniques = report.get("techniques", [])
                print(f"   - techniques: {len(techniques)}개")
                return True

        print(f"❌ 리포트 없음")
        return False
    except Exception as e:
        print(f"조회 실패: {e}")
        return False


if __name__ == "__main__":
    print("=" * 50)
    print("웹서치 → VP2 연동 테스트")
    print(f"TEST_CASE_ID: {TEST_CASE_ID}")
    print("=" * 50)

    if not test_1_health_check():
        print("\n서버가 실행 중인지 확인하세요.")
        exit(1)

    if not test_2_send_to_websearch():
        print("\n웹서치 전송 실패")
        exit(1)

    if not test_3_wait_for_webhook():
        print("\nWebhook 수신 실패 - 웹서치 로그 확인 필요")
        exit(1)

    test_4_check_reports_store()
    test_5_simulate_guidance_polling()

    print("\n" + "=" * 50)
    print("테스트 완료!")
    print("=" * 50)
