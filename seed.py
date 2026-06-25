"""
seed.py — Populate the SQLite database with realistic Korean PERSONAL-banking demo data.

설계 포인트 (카카오뱅크 AI이체 Beta 사례 참고):
  · 사용자 3명 — 나이대가 달라 Dynamic Prompting(맞춤 말투)이 비교 시연됨
      1) 이병민(20대, young)  2) 김은숙(60대, senior)  3) 박준혁(30대, VIP·보안강화)
  · 수신자 20+명 — 전부 개인 관계 기반 (가족/친구/모임/집주인 등)
  · 동명이인: "민수" 2명 (모호성 되묻기), "서연" — '여친' 호칭 학습 시나리오 대상
  · 이체내역 120+건 / 6개월 — 월세·관리비·용돈의 월별 반복 패턴 포함
  · 메모는 전체의 약 10%만 채움 (실제 앱 사용 패턴 반영)
  · alias_memories — 호칭 학습 테이블. 사용자3에 시드 1건("와이프"),
    사용자1의 "여친"은 *라이브 데모에서 학습*되도록 비워둔다.

Run directly:
    python seed.py
"""

from __future__ import annotations

import random
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

MEMO_RATIO = 0.10  # 이체 메모 채움 비율


def run(app=None):
    """Seed all tables.  Creates the Flask app if not provided."""
    if app is None:
        from app import create_app
        app = create_app()

    rng = random.Random(20260611)  # 결정론적 시드 — 항상 같은 데모 데이터

    with app.app_context():
        from src.models.database import (
            db,
            AliasMemory,
            User,
            Account,
            Recipient,
            Favorite,
            RecurringTransfer,
            TransferHistory,
            TransferLimit,
            TransferRequest,
            TransferEvent,
            ExternalCallLog,
            RagRetrievalLog,
        )

        # ── Clear existing data (keep schema) ─────────────────────────────────
        for model in (
            RagRetrievalLog,
            ExternalCallLog,
            TransferEvent,
            TransferRequest,
            AliasMemory,
            TransferHistory,
            RecurringTransfer,
            Favorite,
            TransferLimit,
            Account,
            Recipient,
            User,
        ):
            db.session.query(model).delete()
        db.session.commit()

        now = datetime.utcnow()
        today = date.today()

        # ═════════════════════════════════════════════════════════════════════
        # Users — 나이/등급/리스크 프로필이 Dynamic Prompting 의 입력이 된다
        # ═════════════════════════════════════════════════════════════════════
        u1 = User(username="kimcs", display_name="이병민", phone="010-1234-5678",
                  email="kimcs@bankingdemo.kr", birth_year=1997,
                  customer_tier="standard", risk_profile="normal")
        u2 = User(username="eunsook", display_name="김은숙", phone="010-2345-6789",
                  email="eunsook@bankingdemo.kr", birth_year=1959,
                  customer_tier="standard", risk_profile="normal")
        u3 = User(username="junhyuk", display_name="박준혁", phone="010-3456-7890",
                  email="junhyuk@bankingdemo.kr", birth_year=1988,
                  customer_tier="vip", risk_profile="high")
        db.session.add_all([u1, u2, u3])
        db.session.flush()

        # ═════════════════════════════════════════════════════════════════════
        # Accounts
        # ═════════════════════════════════════════════════════════════════════
        def acc(user, num, name, type_, balance, primary=False):
            a = Account(user_id=user.id, account_number=num, account_name=name,
                        bank_name="으뜸은행", account_type=type_, balance=balance,
                        is_active=True, is_primary=primary)
            db.session.add(a)
            return a

        a1_main = acc(u1, "024-01-0123456", "주계좌", "입출금", 8_250_000, True)
        acc(u1, "024-02-0654321", "비상금통장", "저축", 5_250_000)
        a2_main = acc(u2, "024-01-0223344", "주계좌", "입출금", 12_400_000, True)
        acc(u2, "024-03-0998877", "연금통장", "저축", 34_000_000)
        a3_main = acc(u3, "024-01-0334455", "주계좌", "입출금", 52_700_000, True)
        acc(u3, "024-02-0445566", "투자대기자금", "저축", 120_000_000)
        db.session.flush()

        # ═════════════════════════════════════════════════════════════════════
        # Recipients — 전부 개인 관계 (법인/기업 없음)
        # ═════════════════════════════════════════════════════════════════════
        def recip(name, bank, acct):
            r = Recipient(name=name, bank_name=bank, account_number=acct)
            db.session.add(r)
            return r

        # — 사용자1 (이병민, 20대) 의 사람들 —
        r_mom      = recip("이순자", "한빛은행",  "1002-123-456789")    # 엄마
        r_dad      = recip("김영수", "나라은행",  "456789-01-012345")   # 아빠
        r_minsoo1  = recip("박민수", "새벽은행",  "110-234-567890")     # 민수 (모호성 1)
        r_minsoo2  = recip("이민수", "구름뱅크",  "3333-01-2345678")    # 민수 (모호성 2)
        r_landlord = recip("장태호", "하늘은행",  "12345-67-890123")    # 집주인
        r_mgmt     = recip("관리사무소", "으뜸은행", "024-89-0001234")  # 아파트 관리비
        r_jiyeon   = recip("박지연", "바람뱅크",  "100041-23-456789")   # 친구
        r_brother  = recip("이서준", "들판은행",  "352-1234-5678-03")   # 동생
        r_savings  = recip("미래적금", "으뜸은행", "024-33-0099999")    # 본인 적금
        r_seoyeon  = recip("김서연", "한빛은행",  "1002-987-654321")    # ★ '여친' 학습 대상
        r_grandma  = recip("최복례", "들판은행",  "352-9876-5432-01")   # 할머니
        r_sister   = recip("이수진", "한빛은행",  "1002-555-123456")    # 누나
        r_aunt     = recip("박명자", "나라은행",  "456789-02-098765")   # 이모
        r_moim     = recip("한지민", "바람뱅크",  "100042-11-223344")   # 동기모임 총무
        r_pt       = recip("강현우", "새벽은행",  "110-555-667788")     # 헬스장 PT쌤
        r_roommate = recip("김도현", "구름뱅크",  "3333-02-9876543")    # 룸메이트
        r_donggi   = recip("윤세영", "하늘은행",  "12345-88-112233")    # 대학동창
        r_cousin   = recip("이정도", "들판은행",  "352-4567-8910-02")   # 사촌형

        # — 사용자2 (김은숙, 60대) 의 사람들 —
        r_son      = recip("김대성", "으뜸은행",  "024-77-1112223")     # 큰아들
        r_daughter = recip("김미경", "한빛은행",  "1002-333-789012")    # 딸
        r_grandkid = recip("박서윤", "나라은행",  "456789-03-456789")   # 손녀
        r_sister2  = recip("이은자", "바람뱅크",  "100043-99-887766")   # 여동생
        r_gye      = recip("정말순", "하늘은행",  "12345-99-554433")    # 계모임 총무

        # — 사용자3 (박준혁, VIP) 의 사람들 —
        r_wife     = recip("최예린", "한빛은행",  "1002-777-888999")    # 아내
        r_father3  = recip("박철민", "나라은행",  "456789-04-111222")   # 아버지
        r_friend3  = recip("정우성", "새벽은행",  "110-777-889900")     # 친구
        r_golf     = recip("서장훈", "구름뱅크",  "3333-03-1357913")    # 골프모임 총무
        db.session.flush()

        # ═════════════════════════════════════════════════════════════════════
        # Favorites (별칭 등록 수신자)
        # ═════════════════════════════════════════════════════════════════════
        def fav(user, r, alias, cnt, days_ago, is_fav=True):
            f = Favorite(user_id=user.id, recipient_id=r.id, alias=alias,
                         send_count=cnt, last_sent_at=now - timedelta(days=days_ago),
                         is_favorite=is_fav)
            db.session.add(f)
            return f

        # 사용자1 — 18명 (동명이인 '민수' 포함)
        f_mom      = fav(u1, r_mom,      "엄마",      24, 3)
        f_dad      = fav(u1, r_dad,      "아빠",      11, 20)
        f_minsoo1  = fav(u1, r_minsoo1,  "민수",       7, 10)
        f_minsoo2  = fav(u1, r_minsoo2,  "민수",       4, 15)
        f_landlord = fav(u1, r_landlord, "집주인",    13, 2)
        f_mgmt     = fav(u1, r_mgmt,     "관리사무소", 13, 2, False)
        f_jiyeon   = fav(u1, r_jiyeon,   "지연",      9, 8)
        f_brother  = fav(u1, r_brother,  "동생",      6, 25)
        f_savings  = fav(u1, r_savings,  "적금",      13, 5, False)
        f_seoyeon  = fav(u1, r_seoyeon,  "서연",      8, 1)    # ★ '여친' ≠ '서연' — 학습 필요
        f_grandma  = fav(u1, r_grandma,  "할머니",    5, 40)
        f_sister   = fav(u1, r_sister,   "누나",      6, 18)
        f_aunt     = fav(u1, r_aunt,     "이모",      2, 90)
        f_moim     = fav(u1, r_moim,     "동기모임",  10, 12, False)
        f_pt       = fav(u1, r_pt,       "피티쌤",    6, 14)
        f_roommate = fav(u1, r_roommate, "룸메",      12, 4)
        f_donggi   = fav(u1, r_donggi,   "세영",      3, 55)
        f_cousin   = fav(u1, r_cousin,   "사촌형",    2, 120)

        # 사용자2 — 5명
        f_son      = fav(u2, r_son,      "큰아들",    18, 5)
        f_daughter = fav(u2, r_daughter, "딸",        14, 9)
        f_grandkid = fav(u2, r_grandkid, "손녀",      10, 1)
        f_sister2  = fav(u2, r_sister2,  "동생",      6, 30)
        f_gye      = fav(u2, r_gye,      "계모임",    12, 7, False)

        # 사용자3 — 4명
        f_wife     = fav(u3, r_wife,     "아내",      30, 1)
        f_father3  = fav(u3, r_father3,  "아버지",    8, 15)
        f_friend3  = fav(u3, r_friend3,  "우성이",    5, 22)
        f_golf     = fav(u3, r_golf,     "골프모임",  9, 6, False)
        db.session.flush()

        # ═════════════════════════════════════════════════════════════════════
        # 호칭 학습 메모리 — 사용자3 시드 1건, 사용자1 '여친'은 라이브 학습용으로 비움
        # ═════════════════════════════════════════════════════════════════════
        db.session.add(AliasMemory(
            user_id=u3.id, alias="와이프", recipient_id=r_wife.id,
            hit_count=14, source="seed",
            last_used_at=now - timedelta(days=1),
        ))

        # ═════════════════════════════════════════════════════════════════════
        # Transfer limits (VIP 는 한도 상향)
        # ═════════════════════════════════════════════════════════════════════
        db.session.add_all([
            TransferLimit(user_id=u1.id, single_transfer_limit=10_000_000,
                          daily_limit=30_000_000, daily_used=0, last_reset_date=today),
            TransferLimit(user_id=u2.id, single_transfer_limit=5_000_000,
                          daily_limit=10_000_000, daily_used=0, last_reset_date=today),
            TransferLimit(user_id=u3.id, single_transfer_limit=50_000_000,
                          daily_limit=100_000_000, daily_used=0, last_reset_date=today),
        ])

        # ═════════════════════════════════════════════════════════════════════
        # Recurring transfers
        # ═════════════════════════════════════════════════════════════════════
        def next_monthly(day: int) -> date:
            candidate = today.replace(day=min(day, 28))
            if candidate <= today:
                month, year = today.month + 1, today.year
                if month > 12:
                    month, year = 1, year + 1
                candidate = candidate.replace(year=year, month=month)
            return candidate

        recurring_data = [
            (u1, "월세",     f_landlord, 550_000, 10, "월세"),
            (u1, "관리비",   f_mgmt,      80_000, 25, "아파트 관리비"),
            (u1, "용돈",     f_mom,      200_000,  1, "엄마 용돈"),
            (u1, "적금",     f_savings,  500_000,  5, "자유적금"),
            (u1, "피티",     f_pt,       300_000, 15, "PT 10회"),
            (u1, "모임회비", f_moim,      30_000, 20, "동기모임 회비"),
            (u2, "손녀용돈", f_grandkid, 100_000,  1, "서윤이 용돈"),
            (u2, "계모임",   f_gye,      100_000,  7, "계모임 곗돈"),
            (u3, "부모님",   f_father3, 1_000_000, 1, "부모님 생활비"),
        ]
        for user, alias, fv, amount, day, memo in recurring_data:
            db.session.add(RecurringTransfer(
                user_id=user.id, favorite_id=fv.id, alias=alias,
                default_amount=amount, recurrence_type="monthly",
                day_of_month=day, next_due_date=next_monthly(day),
                is_active=True, memo=memo,
            ))

        # ═════════════════════════════════════════════════════════════════════
        # Transfer history — 6개월 / 120+건, 메모는 약 10%만
        # ═════════════════════════════════════════════════════════════════════
        MONTH_NAMES = {0: "6월", 1: "5월", 2: "4월", 3: "3월", 4: "2월", 5: "1월"}

        def hist(user, account, fv, amount, days_ago, memo=None, hour=14):
            fee = 0 if fv.recipient.bank_name == "으뜸은행" else 500
            db.session.add(TransferHistory(
                user_id=user.id, source_account_id=account.id,
                recipient_id=fv.recipient_id, favorite_id=fv.id,
                amount=amount, fee=fee, memo=memo, status="completed",
                transferred_at=now - timedelta(days=days_ago, hours=(24 - hour) % 24),
            ))

        history_count = 0

        # ── 사용자1: 월별 반복 패턴 (월세/관리비/용돈/적금/피티/회비 × 6개월) ──
        for m in range(6):
            base = m * 30
            month = MONTH_NAMES[m]
            hist(u1, a1_main, f_landlord, 550_000, base + 2,
                 memo=f"{month} 월세" if m < 2 else None, hour=9)
            hist(u1, a1_main, f_mgmt, 80_000, base + 7, hour=10)
            hist(u1, a1_main, f_mom, 200_000, base + 3,
                 memo=f"{month} 용돈" if m == 0 else None, hour=19)
            hist(u1, a1_main, f_savings, 500_000, base + 5, hour=8)
            hist(u1, a1_main, f_pt, 300_000, base + 14, hour=20)
            hist(u1, a1_main, f_moim, 30_000, base + 19, hour=21)
            history_count += 6

        # ── 사용자1: 비정기 소액 이체 (더치페이/선물/축의금 등) ──────────────
        casual_pool = [
            (f_seoyeon,  [12_000, 23_500, 35_000, 48_000, 89_000, 15_500, 27_000, 64_000]),
            (f_jiyeon,   [15_000, 27_000, 33_000, 52_000, 19_000, 44_000]),
            (f_roommate, [18_000, 22_000, 41_000, 65_000, 12_500, 38_000]),
            (f_minsoo1,  [14_000, 30_000, 45_000, 26_000]),
            (f_minsoo2,  [20_000, 36_000, 17_000]),
            (f_brother,  [50_000, 100_000, 150_000, 30_000]),
            (f_sister,   [40_000, 70_000, 55_000]),
            (f_donggi,   [25_000, 100_000, 35_000]),
            (f_dad,      [100_000, 300_000, 150_000]),
            (f_grandma,  [100_000, 200_000, 100_000]),
            (f_aunt,     [50_000, 80_000]),
            (f_cousin,   [60_000, 45_000]),
            (f_mom,      [50_000, 80_000, 120_000]),
        ]
        memo_samples = ["밥값 더치페이", "커피값", "축의금", "생일선물", "택시비 반띵",
                        "병원비 보탬", "여행 경비", "치킨값"]
        for fv, amounts in casual_pool:
            for amount in amounts:
                days_ago = rng.randint(1, 178)
                memo = rng.choice(memo_samples) if rng.random() < MEMO_RATIO else None
                hist(u1, a1_main, fv, amount, days_ago, memo=memo, hour=rng.randint(9, 22))
                history_count += 1

        # ── 사용자2: 가족 중심 패턴 (월 3~4건 × 6개월) ──────────────────────
        for m in range(6):
            base = m * 30
            hist(u2, a2_main, f_grandkid, 100_000, base + 1,
                 memo="서윤이 용돈" if m == 0 else None, hour=10)
            hist(u2, a2_main, f_gye, 100_000, base + 6, hour=11)
            if m % 2 == 0:
                hist(u2, a2_main, f_son, 300_000, base + 12, hour=15)
            else:
                hist(u2, a2_main, f_daughter, 200_000, base + 16, hour=16)
            history_count += 3
        hist(u2, a2_main, f_sister2, 500_000, 30, memo="동생 환갑 축하", hour=12)
        history_count += 1

        # ── 사용자3: VIP 고액 패턴 ───────────────────────────────────────────
        for m in range(6):
            base = m * 30
            hist(u3, a3_main, f_father3, 1_000_000, base + 1, hour=9)
            hist(u3, a3_main, f_wife, 2_000_000, base + 9,
                 memo="생활비" if m == 0 else None, hour=18)
            if m % 2 == 0:
                hist(u3, a3_main, f_golf, 250_000, base + 5, hour=20)
            history_count += 2 + (1 if m % 2 == 0 else 0)
        hist(u3, a3_main, f_friend3, 5_000_000, 22, memo="전세금 빌려줌", hour=23)
        history_count += 1

        db.session.commit()

        memo_filled = (
            db.session.query(TransferHistory)
            .filter(TransferHistory.memo != None)
            .count()
        )
        print(f"✅ 시드 데이터 완료 — 사용자 3명 / 이체내역 {history_count}건 "
              f"(메모 채움 {memo_filled}건, {memo_filled / history_count:.0%})")
        print(f"   데모 사용자: {u1.display_name}({u1.age}세) / "
              f"{u2.display_name}({u2.age}세) / {u3.display_name}({u3.age}세, VIP·보안강화)")


if __name__ == "__main__":
    run()
