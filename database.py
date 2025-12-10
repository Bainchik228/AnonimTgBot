import aiosqlite
from datetime import datetime, timedelta
from typing import Optional
import secrets
import string

DB_PATH = "anticensura.db"
ALPHABET = string.ascii_letters + string.digits


def generate_code(length: int = 8) -> str:
    return ''.join(secrets.choice(ALPHABET) for _ in range(length))


async def init_db():
    async with aiosqlite.connect(DB_PATH) as db:
        await db.executescript("""
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER UNIQUE NOT NULL,
                code TEXT UNIQUE NOT NULL,
                username TEXT,
                is_active INTEGER DEFAULT 1,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            );
            
            CREATE TABLE IF NOT EXISTS messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                sender_id INTEGER NOT NULL,
                receiver_id INTEGER NOT NULL,
                content TEXT,
                media_type TEXT,
                media_file_id TEXT,
                caption TEXT,
                status TEXT DEFAULT 'pending',
                is_read INTEGER DEFAULT 0,
                read_at TEXT,
                reply_to_id INTEGER,
                channel_message_id INTEGER,
                sentiment TEXT,
                is_urgent INTEGER DEFAULT 0,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (sender_id) REFERENCES users(user_id),
                FOREIGN KEY (receiver_id) REFERENCES users(user_id),
                FOREIGN KEY (reply_to_id) REFERENCES messages(id)
            );
            
            CREATE TABLE IF NOT EXISTS pending_replies (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                hash TEXT UNIQUE NOT NULL,
                sender_id INTEGER NOT NULL,
                receiver_id INTEGER NOT NULL,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            );
            
            CREATE INDEX IF NOT EXISTS idx_users_code ON users(code);
            CREATE INDEX IF NOT EXISTS idx_users_user_id ON users(user_id);
            CREATE INDEX IF NOT EXISTS idx_messages_receiver ON messages(receiver_id);
            CREATE INDEX IF NOT EXISTS idx_pending_hash ON pending_replies(hash);
            
            CREATE TABLE IF NOT EXISTS mod_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                moderator_id INTEGER NOT NULL,
                action TEXT NOT NULL,
                message_id INTEGER,
                target_user_id INTEGER,
                details TEXT,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            );
            
            CREATE TABLE IF NOT EXISTS rate_limits (
                user_id INTEGER PRIMARY KEY,
                message_count INTEGER DEFAULT 0,
                window_start TEXT DEFAULT CURRENT_TIMESTAMP,
                is_blocked INTEGER DEFAULT 0,
                blocked_until TEXT
            );
            
            CREATE TABLE IF NOT EXISTS alerts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                alert_type TEXT NOT NULL,
                user_id INTEGER,
                details TEXT,
                is_resolved INTEGER DEFAULT 0,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            );
            
            CREATE INDEX IF NOT EXISTS idx_mod_log_time ON mod_log(created_at);
            CREATE INDEX IF NOT EXISTS idx_alerts_type ON alerts(alert_type, is_resolved);
        """)
        await db.commit()


async def get_or_create_user(user_id: int, username: Optional[str] = None) -> dict:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute("SELECT * FROM users WHERE user_id = ?", (user_id,))
        user = await cursor.fetchone()
        
        if user:
            if username and user['username'] != username:
                await db.execute("UPDATE users SET username = ? WHERE user_id = ?", (username, user_id))
                await db.commit()
            return dict(user)
        
        code = generate_code()
        while True:
            cursor = await db.execute("SELECT 1 FROM users WHERE code = ?", (code,))
            if not await cursor.fetchone():
                break
            code = generate_code()
        
        await db.execute(
            "INSERT INTO users (user_id, code, username) VALUES (?, ?, ?)",
            (user_id, code, username)
        )
        await db.commit()
        
        cursor = await db.execute("SELECT * FROM users WHERE user_id = ?", (user_id,))
        return dict(await cursor.fetchone())


async def get_user_by_code(code: str) -> Optional[dict]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute("SELECT * FROM users WHERE code = ?", (code,))
        user = await cursor.fetchone()
        return dict(user) if user else None


async def save_message(
    sender_id: int,
    receiver_id: int,
    content: Optional[str] = None,
    media_type: Optional[str] = None,
    media_file_id: Optional[str] = None,
    caption: Optional[str] = None,
    status: str = 'pending',
    reply_to_id: Optional[int] = None
) -> int:
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute(
            """INSERT INTO messages 
               (sender_id, receiver_id, content, media_type, media_file_id, caption, status, reply_to_id)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (sender_id, receiver_id, content, media_type, media_file_id, caption, status, reply_to_id)
        )
        await db.commit()
        return cursor.lastrowid


async def set_channel_message_id(message_id: int, channel_message_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "UPDATE messages SET channel_message_id = ? WHERE id = ?",
            (channel_message_id, message_id)
        )
        await db.commit()


async def update_message_status(message_id: int, status: str):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("UPDATE messages SET status = ? WHERE id = ?", (status, message_id))
        await db.commit()


async def mark_message_read(message_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "UPDATE messages SET is_read = 1, read_at = ? WHERE id = ?",
            (datetime.now().isoformat(), message_id)
        )
        await db.commit()


async def get_message(message_id: int) -> Optional[dict]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute("SELECT * FROM messages WHERE id = ?", (message_id,))
        msg = await cursor.fetchone()
        return dict(msg) if msg else None


async def get_user_messages(user_id: int, limit: int = 20, offset: int = 0) -> list[dict]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            """SELECT * FROM messages 
               WHERE receiver_id = ? AND status = 'approved'
               ORDER BY created_at DESC LIMIT ? OFFSET ?""",
            (user_id, limit, offset)
        )
        rows = await cursor.fetchall()
        return [dict(row) for row in rows]


async def get_user_stats(user_id: int) -> dict:
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute(
            "SELECT COUNT(*) FROM messages WHERE receiver_id = ? AND status = 'approved'",
            (user_id,)
        )
        received = (await cursor.fetchone())[0]
        
        cursor = await db.execute(
            "SELECT COUNT(*) FROM messages WHERE sender_id = ? AND status = 'approved'",
            (user_id,)
        )
        sent = (await cursor.fetchone())[0]
        
        return {"received": received, "sent": sent}


async def save_pending_reply(hash_code: str, sender_id: int, receiver_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT OR REPLACE INTO pending_replies (hash, sender_id, receiver_id) VALUES (?, ?, ?)",
            (hash_code, sender_id, receiver_id)
        )
        await db.commit()


async def get_pending_reply(hash_code: str) -> Optional[dict]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            "SELECT * FROM pending_replies WHERE hash = ?", (hash_code,)
        )
        row = await cursor.fetchone()
        return dict(row) if row else None


async def get_pending_messages_count() -> int:
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute("SELECT COUNT(*) FROM messages WHERE status = 'pending'")
        return (await cursor.fetchone())[0]


# === MOD LOG ===

async def log_mod_action(moderator_id: int, action: str, message_id: int = None, 
                         target_user_id: int = None, details: str = None):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            """INSERT INTO mod_log (moderator_id, action, message_id, target_user_id, details)
               VALUES (?, ?, ?, ?, ?)""",
            (moderator_id, action, message_id, target_user_id, details)
        )
        await db.commit()


async def get_mod_log(limit: int = 50) -> list[dict]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            "SELECT * FROM mod_log ORDER BY created_at DESC LIMIT ?", (limit,)
        )
        rows = await cursor.fetchall()
        return [dict(row) for row in rows]


# === RATE LIMITING ===

async def check_rate_limit(user_id: int, max_messages: int = 10, window_minutes: int = 60) -> dict:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute("SELECT * FROM rate_limits WHERE user_id = ?", (user_id,))
        row = await cursor.fetchone()
        
        now = datetime.now()
        
        if row:
            if row['is_blocked'] and row['blocked_until']:
                blocked_until = datetime.fromisoformat(row['blocked_until'])
                if now < blocked_until:
                    return {"allowed": False, "blocked": True, "until": blocked_until}
                else:
                    await db.execute(
                        "UPDATE rate_limits SET is_blocked = 0, blocked_until = NULL, message_count = 1, window_start = ? WHERE user_id = ?",
                        (now.isoformat(), user_id)
                    )
                    await db.commit()
                    return {"allowed": True, "blocked": False, "count": 1}
            
            window_start = datetime.fromisoformat(row['window_start'])
            if (now - window_start).total_seconds() > window_minutes * 60:
                await db.execute(
                    "UPDATE rate_limits SET message_count = 1, window_start = ? WHERE user_id = ?",
                    (now.isoformat(), user_id)
                )
                await db.commit()
                return {"allowed": True, "blocked": False, "count": 1}
            
            new_count = row['message_count'] + 1
            if new_count > max_messages:
                return {"allowed": False, "blocked": False, "count": row['message_count'], "limit": max_messages}
            
            await db.execute(
                "UPDATE rate_limits SET message_count = ? WHERE user_id = ?",
                (new_count, user_id)
            )
            await db.commit()
            return {"allowed": True, "blocked": False, "count": new_count}
        else:
            await db.execute(
                "INSERT INTO rate_limits (user_id, message_count, window_start) VALUES (?, 1, ?)",
                (user_id, now.isoformat())
            )
            await db.commit()
            return {"allowed": True, "blocked": False, "count": 1}


async def block_user(user_id: int, hours: int = 24):
    async with aiosqlite.connect(DB_PATH) as db:
        blocked_until = (datetime.now() + timedelta(hours=hours)).isoformat()
        await db.execute(
            """INSERT INTO rate_limits (user_id, is_blocked, blocked_until) 
               VALUES (?, 1, ?)
               ON CONFLICT(user_id) DO UPDATE SET is_blocked = 1, blocked_until = ?""",
            (user_id, blocked_until, blocked_until)
        )
        await db.commit()


async def unblock_user(user_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "UPDATE rate_limits SET is_blocked = 0, blocked_until = NULL WHERE user_id = ?",
            (user_id,)
        )
        await db.commit()


# === ALERTS ===

async def create_alert(alert_type: str, user_id: int = None, details: str = None) -> int:
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute(
            "INSERT INTO alerts (alert_type, user_id, details) VALUES (?, ?, ?)",
            (alert_type, user_id, details)
        )
        await db.commit()
        return cursor.lastrowid


async def get_unresolved_alerts() -> list[dict]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            "SELECT * FROM alerts WHERE is_resolved = 0 ORDER BY created_at DESC"
        )
        rows = await cursor.fetchall()
        return [dict(row) for row in rows]


async def resolve_alert(alert_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("UPDATE alerts SET is_resolved = 1 WHERE id = ?", (alert_id,))
        await db.commit()


async def get_user_message_count_today(user_id: int) -> int:
    async with aiosqlite.connect(DB_PATH) as db:
        today = datetime.now().date().isoformat()
        cursor = await db.execute(
            "SELECT COUNT(*) FROM messages WHERE sender_id = ? AND date(created_at) = ?",
            (user_id, today)
        )
        return (await cursor.fetchone())[0]


# === ANALYTICS ===

async def get_hourly_activity(days: int = 7) -> dict[int, int]:
    async with aiosqlite.connect(DB_PATH) as db:
        since = (datetime.now() - timedelta(days=days)).isoformat()
        cursor = await db.execute(
            """SELECT strftime('%H', created_at) as hour, COUNT(*) as cnt
               FROM messages WHERE created_at > ? 
               GROUP BY hour ORDER BY hour""",
            (since,)
        )
        rows = await cursor.fetchall()
        return {int(row[0]): row[1] for row in rows}


async def get_weekly_hourly_activity(days: int = 30) -> dict[int, dict[int, int]]:
    async with aiosqlite.connect(DB_PATH) as db:
        since = (datetime.now() - timedelta(days=days)).isoformat()
        cursor = await db.execute(
            """SELECT strftime('%w', created_at) as dow, 
                      strftime('%H', created_at) as hour, 
                      COUNT(*) as cnt
               FROM messages WHERE created_at > ?
               GROUP BY dow, hour""",
            (since,)
        )
        rows = await cursor.fetchall()
        result = {}
        for row in rows:
            dow = (int(row[0]) + 6) % 7  # Convert Sunday=0 to Monday=0
            hour = int(row[1])
            if dow not in result:
                result[dow] = {}
            result[dow][hour] = row[2]
        return result


async def get_daily_activity(days: int = 30) -> list[tuple[str, int]]:
    async with aiosqlite.connect(DB_PATH) as db:
        since = (datetime.now() - timedelta(days=days)).isoformat()
        cursor = await db.execute(
            """SELECT date(created_at) as day, COUNT(*) as cnt
               FROM messages WHERE created_at > ?
               GROUP BY day ORDER BY day""",
            (since,)
        )
        rows = await cursor.fetchall()
        return [(row[0], row[1]) for row in rows]


async def get_sentiment_stats() -> dict[str, int]:
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute(
            """SELECT sentiment, COUNT(*) as cnt
               FROM messages WHERE sentiment IS NOT NULL
               GROUP BY sentiment"""
        )
        rows = await cursor.fetchall()
        return {row[0]: row[1] for row in rows}


async def update_message_sentiment(message_id: int, sentiment: str, is_urgent: bool = False):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "UPDATE messages SET sentiment = ?, is_urgent = ? WHERE id = ?",
            (sentiment, 1 if is_urgent else 0, message_id)
        )
        await db.commit()


async def get_urgent_messages() -> list[dict]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            """SELECT * FROM messages 
               WHERE is_urgent = 1 AND status = 'pending'
               ORDER BY created_at DESC"""
        )
        rows = await cursor.fetchall()
        return [dict(row) for row in rows]


async def get_analytics_summary() -> dict:
    async with aiosqlite.connect(DB_PATH) as db:
        # Total messages
        cursor = await db.execute("SELECT COUNT(*) FROM messages")
        total = (await cursor.fetchone())[0]
        
        # Today
        today = datetime.now().date().isoformat()
        cursor = await db.execute(
            "SELECT COUNT(*) FROM messages WHERE date(created_at) = ?", (today,)
        )
        today_count = (await cursor.fetchone())[0]
        
        # This week
        week_ago = (datetime.now() - timedelta(days=7)).isoformat()
        cursor = await db.execute(
            "SELECT COUNT(*) FROM messages WHERE created_at > ?", (week_ago,)
        )
        week_count = (await cursor.fetchone())[0]
        
        # Pending
        cursor = await db.execute("SELECT COUNT(*) FROM messages WHERE status = 'pending'")
        pending = (await cursor.fetchone())[0]
        
        # Urgent pending
        cursor = await db.execute(
            "SELECT COUNT(*) FROM messages WHERE status = 'pending' AND is_urgent = 1"
        )
        urgent_pending = (await cursor.fetchone())[0]
        
        # Sentiment breakdown
        cursor = await db.execute(
            """SELECT sentiment, COUNT(*) FROM messages 
               WHERE sentiment IS NOT NULL GROUP BY sentiment"""
        )
        sentiment_rows = await cursor.fetchall()
        sentiments = {row[0]: row[1] for row in sentiment_rows}
        
        # Peak hour
        cursor = await db.execute(
            """SELECT strftime('%H', created_at) as hour, COUNT(*) as cnt
               FROM messages GROUP BY hour ORDER BY cnt DESC LIMIT 1"""
        )
        peak_row = await cursor.fetchone()
        peak_hour = int(peak_row[0]) if peak_row else None
        
        return {
            "total": total,
            "today": today_count,
            "week": week_count,
            "pending": pending,
            "urgent_pending": urgent_pending,
            "sentiments": sentiments,
            "peak_hour": peak_hour
        }
