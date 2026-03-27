"""
seed.py — Populate the SQLite database with realistic Korean demo data.

Run directly:
    python seed.py

Or import and call ``run()`` programmatically (used by the admin reset endpoint).
"""

from __future__ import annotations

import sys
from datetime import date, datetime, timedelta
from pathlib import Path

# Make sure the project root is on the path
sys.path.insert(0, str(Path(__file__).parent))


def run(app=None):
    """Seed all tables.  Creates the Flask app if not provided."""
    if app is None:
        from app import create_app
        app = create_app()

    with app.app_context():
        from src.models.database import (
            db,
            User,
            Account,
            Recipient,
            Favorite,
            RecurringTransfer,
            TransferHistory,
            TransferLimit,
        )

        # ── Clear existing data (keep schema) ─────────────────────────────────
        db.session.query(TransferHistory).delete()
        db.session.query(RecurringTransfer).delete()
        db.session.query(Favorite).delete()
        db.session.query(TransferLimit).delete()
        db.session.query(Account).delete()
        db.session.query(Recipient).delete()
        db.session.query(User).delete()
        db.session.commit()

        # ── Demo user ─────────────────────────────────────────────────────────
        user = User(
            username="kimcs",
            display_name="이병민",
            phone="010-1234-5678",
            email="kimcs@bankingdemo.kr",
        )
        db.session.add(user)
        db.session.flush()

        # ── Accounts ──────────────────────────────────────────────────────────
        acc_main = Account(
            user_id=user.id,
            account_number="024-01-0123456",
            account_name="주계좌",
            bank_name="으뜸은행",
            account_type="입출금",
            balance=8_250_000,   # Enough for OTP scenario (≥3M) and normal demos
            is_active=True,
            is_primary=True,
        )
        acc_savings = Account(
            user_id=user.id,
            account_number="024-02-0654321",
            account_name="저축계좌",
            bank_name="으뜸은행",
            account_type="저축",
            balance=5_250_000,
            is_active=True,
            is_primary=False,
        )
        db.session.add_all([acc_main, acc_savings])
        db.session.flush()

        # ── Recipients ────────────────────────────────────────────────────────
        recipients_data = [
            # (name, bank, account_number)
            ("이순자", "한빛은행",    "1002-123-456789"),   # 엄마
            ("김영수", "나라은행",    "456789-01-012345"),  # 아빠
            ("박민수", "새벽은행",    "110-234-567890"),    # 민수1
            ("이민수", "구름뱅크",  "3333-01-2345678"),   # 민수2 (ambiguity)
            ("장태호", "하늘은행",    "12345-67-890123"),   # 집주인
            ("관리사무소", "으뜸은행", "024-89-0001234"), # 관리비
            ("박지연", "바람뱅크",    "100041-23-456789"), # 친구
            ("이서준", "들판은행",    "352-1234-5678-03"),  # 동생
            ("미래적금", "으뜸은행","024-33-0099999"),    # 적금
        ]
        recips = []
        for name, bank, acct in recipients_data:
            r = Recipient(name=name, bank_name=bank, account_number=acct)
            db.session.add(r)
            recips.append(r)
        db.session.flush()

        r_mom, r_dad, r_minsoo1, r_minsoo2, r_landlord, \
        r_mgmt, r_friend, r_brother, r_savings = recips

        # ── Favorites ─────────────────────────────────────────────────────────
        now = datetime.utcnow()
        favs_data = [
            # (recipient, alias, send_count, days_ago, is_favorite)
            (r_mom,      "엄마",    12, 5,  True),
            (r_dad,      "아빠",     8, 20, True),
            (r_minsoo1,  "민수",     5, 10, True),   # 민수1
            (r_minsoo2,  "민수",     3, 15, True),   # 민수2 — same alias → ambiguity!
            (r_landlord, "집주인",   12, 2,  True),
            (r_mgmt,     "관리사무소", 12, 2, False),
            (r_friend,   "지연",     6, 30, True),
            (r_brother,  "동생",     4, 45, True),
            (r_savings,  "적금",     12, 3,  False),
        ]
        favs = []
        for r, alias, cnt, days, is_fav in favs_data:
            f = Favorite(
                user_id=user.id,
                recipient_id=r.id,
                alias=alias,
                send_count=cnt,
                last_sent_at=now - timedelta(days=days),
                is_favorite=is_fav,
            )
            db.session.add(f)
            favs.append(f)
        db.session.flush()

        f_mom, f_dad, f_minsoo1, f_minsoo2, f_landlord, \
        f_mgmt, f_friend, f_brother, f_savings = favs

        # ── Transfer limits ───────────────────────────────────────────────────
        tl = TransferLimit(
            user_id=user.id,
            single_transfer_limit=10_000_000,
            daily_limit=30_000_000,
            daily_used=0,
            last_reset_date=date.today(),
        )
        db.session.add(tl)

        # ── Recurring transfers ───────────────────────────────────────────────
        today = date.today()

        def next_monthly(day: int) -> date:
            """Next occurrence of *day* of month."""
            candidate = today.replace(day=day)
            if candidate <= today:
                # Advance to next month
                month = today.month + 1
                year = today.year
                if month > 12:
                    month = 1
                    year += 1
                candidate = candidate.replace(year=year, month=month)
            return candidate

        recurring_data = [
            # (alias, favorite, default_amount, day, memo)
            ("월세",    f_landlord, 550_000,  10, "월세"),
            ("관리비",  f_mgmt,     80_000,   25, "아파트 관리비"),
            ("용돈",    f_mom,      200_000,   1, "엄마 용돈"),
            ("적금",    f_savings,  500_000,   5, "자유적금"),
        ]
        for alias, fav, amount, day, memo in recurring_data:
            rt = RecurringTransfer(
                user_id=user.id,
                favorite_id=fav.id,
                alias=alias,
                default_amount=amount,
                recurrence_type="monthly",
                day_of_month=day,
                next_due_date=next_monthly(day),
                is_active=True,
                memo=memo,
            )
            db.session.add(rt)

        # ── Transfer history (realistic past transactions) ────────────────────
        history_data = [
            # (favorite, amount, fee, memo, days_ago, status)
            (f_landlord, 550_000, 500, "4월 월세",         2,  "completed"),
            (f_mom,      200_000,   0, "엄마 용돈",         3,  "completed"),
            (f_savings,  500_000,   0, "자유적금",      5,  "completed"),
            (f_mgmt,      80_000,   0, "4월 관리비",         7,  "completed"),
            (f_friend,    50_000, 500, "밥값 더치페이",     10,  "completed"),
            (f_mom,      100_000,   0, "생일 용돈",         15,  "completed"),
            (f_dad,      300_000, 500, "아버지 병원비",     20,  "completed"),
            (f_minsoo1,   30_000, 500, "커피값",            25,  "completed"),
            (f_brother,  150_000, 500, "동생 교통비",       30,  "completed"),
            (f_landlord, 550_000, 500, "3월 월세",          33,  "completed"),
            (f_mom,      200_000,   0, "3월 엄마 용돈",     33,  "completed"),
            (f_friend,   70_000, 500, "축의금",             40,  "completed"),
        ]
        for fav, amount, fee, memo, days_ago, status in history_data:
            th = TransferHistory(
                user_id=user.id,
                source_account_id=acc_main.id,
                recipient_id=fav.recipient_id,
                favorite_id=fav.id,
                amount=amount,
                fee=fee,
                memo=memo,
                status=status,
                transferred_at=now - timedelta(days=days_ago, hours=1),
            )
            db.session.add(th)

        db.session.commit()
        print(f"✅ 시드 데이터 완료 — 사용자: {user.display_name} (ID={user.id})")


if __name__ == "__main__":
    run()
