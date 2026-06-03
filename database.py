"""
SQLite 数据库模块 — 电影日记的持久化存储
"""
import sqlite3
import os

# 支持环境变量指定数据目录（部署用），默认本地目录
DATA_DIR = os.environ.get("DATA_DIR", os.path.dirname(__file__))
DB_PATH = os.path.join(DATA_DIR, "movies.db")


def get_db():
    """获取数据库连接（row_factory 设置为 Row 以支持字典式访问）"""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_db():
    """初始化数据库表结构"""
    conn = get_db()
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS movies (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            title           TEXT    NOT NULL,          -- 电影名
            original_title  TEXT,                      -- 原名称
            my_rating       REAL    DEFAULT 0,         -- 评分 (用户自己打的)
            watch_time      TEXT,                      -- 观影时间
            diary           TEXT,                      -- 电影日记
            director        TEXT,                      -- 导演
            release_date    TEXT,                      -- 上映日期
            year            TEXT,                      -- 年份
            country         TEXT,                      -- 国家
            douban_rating   TEXT,                      -- 豆瓣评分
            cast_info       TEXT,                      -- 主演
            summary         TEXT,                      -- 简介
            duration        TEXT,                      -- 片长
            language        TEXT,                      -- 语言
            genre           TEXT,                      -- 影片类型
            writer          TEXT,                      -- 编剧
            tags            TEXT,                      -- 标签
            cover_url       TEXT,                      -- 封面图片URL
            cover_local     TEXT,                      -- 本地封面路径
            created_at      TEXT    DEFAULT (datetime('now','localtime'))
        );

        CREATE INDEX IF NOT EXISTS idx_movies_year ON movies(year);
        CREATE INDEX IF NOT EXISTS idx_movies_watch_time ON movies(watch_time);
        CREATE INDEX IF NOT EXISTS idx_movies_douban_rating ON movies(douban_rating);
    """)
    conn.commit()
    conn.close()


def insert_movie(data: dict):
    """插入一部电影"""
    conn = get_db()
    conn.execute("""
        INSERT INTO movies (title, original_title, my_rating, watch_time, diary,
                           director, release_date, year, country, douban_rating,
                           cast_info, summary, duration, language, genre, writer, tags)
        VALUES (?,?,?,?,?, ?,?,?,?,?, ?,?,?,?,?, ?,?)
    """, (
        data.get("title"),
        data.get("original_title"),
        data.get("my_rating", 0),
        data.get("watch_time"),
        data.get("diary"),
        data.get("director"),
        data.get("release_date"),
        data.get("year"),
        data.get("country"),
        data.get("douban_rating"),
        data.get("cast_info"),
        data.get("summary"),
        data.get("duration"),
        data.get("language"),
        data.get("genre"),
        data.get("writer"),
        data.get("tags"),
    ))
    conn.commit()
    conn.close()


def get_all_movies(sort_by="watch_time", order="DESC", limit=None, offset=0):
    """获取所有电影，支持排序和分页"""
    allowed_sort = {
        "watch_time", "douban_rating", "year", "title",
        "my_rating", "release_date", "country"
    }
    if sort_by not in allowed_sort:
        sort_by = "watch_time"
    if order.upper() not in ("ASC", "DESC"):
        order = "DESC"

    conn = get_db()
    query = f"SELECT * FROM movies ORDER BY {sort_by} {order}"
    if limit is not None:
        query += f" LIMIT {limit} OFFSET {offset}"
    rows = conn.execute(query).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_movie_by_id(movie_id: int):
    """根据 ID 获取单部电影"""
    conn = get_db()
    row = conn.execute("SELECT * FROM movies WHERE id = ?", (movie_id,)).fetchone()
    conn.close()
    return dict(row) if row else None


def search_movies(keyword: str = None, year: str = None, country: str = None,
                  genre: str = None, min_rating: float = None, tags: str = None,
                  sort_by: str = "watch_time", order: str = "DESC"):
    """多条件搜索电影"""
    allowed_sort = {"watch_time", "douban_rating", "year", "title", "my_rating", "release_date", "country"}
    if sort_by not in allowed_sort:
        sort_by = "watch_time"
    if order.upper() not in ("ASC", "DESC"):
        order = "DESC"

    conn = get_db()
    conditions = []
    params = []

    if keyword:
        conditions.append("(title LIKE ? OR original_title LIKE ? OR director LIKE ? OR cast_info LIKE ?)")
        kw = f"%{keyword}%"
        params.extend([kw, kw, kw, kw])
    if year:
        conditions.append("strftime('%Y', watch_time) = ?")
        params.append(year)
    if country:
        conditions.append("country LIKE ?")
        params.append(f"%{country}%")
    if genre:
        conditions.append("genre LIKE ?")
        params.append(f"%{genre}%")
    if min_rating is not None:
        conditions.append("CAST(douban_rating AS REAL) >= ?")
        params.append(min_rating)
    if tags:
        for tag in tags.split():
            conditions.append("tags LIKE ?")
            params.append(f"%{tag}%")

    where = " AND ".join(conditions) if conditions else "1=1"
    query = f"SELECT * FROM movies WHERE {where} ORDER BY {sort_by} {order}"
    rows = conn.execute(query, params).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_all_tags():
    """获取所有标签（用于筛选）"""
    conn = get_db()
    rows = conn.execute("SELECT tags FROM movies WHERE tags != '' AND tags IS NOT NULL").fetchall()
    conn.close()
    tag_set = set()
    for r in rows:
        if r["tags"]:
            for t in r["tags"].split("/"):
                t = t.strip()
                if t:
                    tag_set.add(t)
    return sorted(tag_set, key=lambda x: x.lower())


def get_all_years():
    """获取所有观影年份（从 watch_time 提取）"""
    conn = get_db()
    rows = conn.execute(
        "SELECT DISTINCT strftime('%Y', watch_time) as y FROM movies "
        "WHERE watch_time != '' AND watch_time IS NOT NULL ORDER BY y DESC"
    ).fetchall()
    conn.close()
    return [r["y"] for r in rows]


def get_all_countries():
    """获取所有国家"""
    conn = get_db()
    rows = conn.execute("SELECT DISTINCT country FROM movies WHERE country != '' AND country IS NOT NULL").fetchall()
    conn.close()
    countries = set()
    for r in rows:
        for c in r["country"].split("/"):
            c = c.strip()
            if c:
                countries.add(c)
    return sorted(countries)


def get_all_genres():
    """获取所有类型"""
    conn = get_db()
    rows = conn.execute("SELECT DISTINCT genre FROM movies WHERE genre != '' AND genre IS NOT NULL").fetchall()
    conn.close()
    genres = set()
    for r in rows:
        for g in r["genre"].split("/"):
            g = g.strip()
            if g:
                genres.add(g)
    return sorted(genres)


def get_stats():
    """获取统计信息"""
    conn = get_db()
    total = conn.execute("SELECT COUNT(*) as c FROM movies").fetchone()["c"]

    # 年份分布
    year_dist = conn.execute("""
        SELECT year, COUNT(*) as c FROM movies
        WHERE year != '' AND year IS NOT NULL
        GROUP BY year ORDER BY year DESC
    """).fetchall()

    # 国家分布
    country_dist = conn.execute("""
        SELECT country, COUNT(*) as c FROM movies
        WHERE country != '' AND country IS NOT NULL
        GROUP BY country ORDER BY c DESC
    """).fetchall()

    # 类型分布
    genre_dist = conn.execute("""
        SELECT genre, COUNT(*) as c FROM movies
        WHERE genre != '' AND genre IS NOT NULL
        GROUP BY genre ORDER BY c DESC
    """).fetchall()

    # 评分分布
    rating_dist = conn.execute("""
        SELECT
            CASE
                WHEN CAST(douban_rating AS REAL) >= 9.0 THEN '9分+'
                WHEN CAST(douban_rating AS REAL) >= 8.0 THEN '8-9分'
                WHEN CAST(douban_rating AS REAL) >= 7.0 THEN '7-8分'
                WHEN CAST(douban_rating AS REAL) >= 6.0 THEN '6-7分'
                ELSE '6分以下'
            END as rating_range,
            COUNT(*) as c
        FROM movies WHERE douban_rating != '' AND douban_rating IS NOT NULL
        GROUP BY rating_range ORDER BY rating_range
    """).fetchall()

    # 平均评分
    avg_rating = conn.execute(
        "SELECT AVG(CAST(douban_rating AS REAL)) as avg FROM movies WHERE douban_rating != '' AND douban_rating IS NOT NULL"
    ).fetchone()["avg"]

    conn.close()
    return {
        "total": total,
        "avg_rating": round(avg_rating or 0, 1),
        "year_dist": [dict(r) for r in year_dist],
        "country_dist": [dict(r) for r in country_dist],
        "genre_dist": [dict(r) for r in genre_dist],
        "rating_dist": [dict(r) for r in rating_dist],
    }


def update_cover(movie_id: int, cover_url: str, cover_local: str):
    """更新电影封面信息"""
    conn = get_db()
    conn.execute("UPDATE movies SET cover_url = ?, cover_local = ? WHERE id = ?",
                 (cover_url, cover_local, movie_id))
    conn.commit()
    conn.close()


def get_movies_without_covers():
    """获取还没有封面的电影"""
    conn = get_db()
    rows = conn.execute(
        "SELECT id, title, original_title, year FROM movies "
        "WHERE cover_local IS NULL OR cover_local = ''"
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_time_stats(granularity: str = "year", year: str = None, month: str = None):
    """
    按时间粒度统计观影数量

    Args:
        granularity: 'year' | 'month' | 'week' | 'day'
        year: 指定年份 (仅 month/week 粒度需要)
        month: 指定月份 (仅 week 粒度需要)
    """
    conn = get_db()

    if granularity == "year":
        # 每年看了多少部
        rows = conn.execute("""
            SELECT
                strftime('%Y', watch_time) as period,
                COUNT(*) as count
            FROM movies
            WHERE watch_time IS NOT NULL AND watch_time != ''
            GROUP BY period
            ORDER BY period ASC
        """).fetchall()

    elif granularity == "month":
        # 指定年份每月看了多少部，不指定则全部月份
        if year:
            rows = conn.execute("""
                SELECT
                    strftime('%Y-%m', watch_time) as period,
                    strftime('%m', watch_time) as month_num,
                    COUNT(*) as count
                FROM movies
                WHERE watch_time IS NOT NULL AND watch_time != ''
                  AND strftime('%Y', watch_time) = ?
                GROUP BY period
                ORDER BY period ASC
            """, (str(year),)).fetchall()
        else:
            rows = conn.execute("""
                SELECT
                    strftime('%Y-%m', watch_time) as period,
                    COUNT(*) as count
                FROM movies
                WHERE watch_time IS NOT NULL AND watch_time != ''
                GROUP BY period
                ORDER BY period ASC
            """).fetchall()

    elif granularity == "week":
        # 某年某月的每周，或某年的每周
        conditions = []
        params = []
        if year:
            conditions.append("strftime('%Y', watch_time) = ?")
            params.append(str(year))
        if month:
            conditions.append("strftime('%m', watch_time) = ?")
            params.append(str(month).zfill(2))

        where = " AND ".join(conditions) if conditions else "1=1"
        rows = conn.execute(f"""
            SELECT
                strftime('%Y-W%W', watch_time) as period,
                COUNT(*) as count
            FROM movies
            WHERE watch_time IS NOT NULL AND watch_time != ''
              AND {where}
            GROUP BY period
            ORDER BY period ASC
        """, params).fetchall()

    elif granularity == "day":
        # 每日观看趋势（最近90天）
        rows = conn.execute("""
            SELECT
                strftime('%Y-%m-%d', watch_time) as period,
                COUNT(*) as count
            FROM movies
            WHERE watch_time IS NOT NULL AND watch_time != ''
              AND watch_time >= date('now', '-90 days')
            GROUP BY period
            ORDER BY period ASC
        """).fetchall()

    else:
        rows = []

    conn.close()

    return {
        "granularity": granularity,
        "labels": [r["period"] for r in rows],
        "counts": [r["count"] for r in rows],
        "cumulative": _cumulative([r["count"] for r in rows]),
        "data": [dict(r) for r in rows],
    }


def get_heatmap_data():
    """获取观影热力图数据（按星期+月份聚合）"""
    conn = get_db()
    rows = conn.execute("""
        SELECT
            strftime('%w', watch_time) as weekday,  -- 0=Sun, 6=Sat
            strftime('%m', watch_time) as month,
            COUNT(*) as count
        FROM movies
        WHERE watch_time IS NOT NULL AND watch_time != ''
        GROUP BY weekday, month
        ORDER BY month, weekday
    """).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def _cumulative(counts: list) -> list:
    """计算累计值"""
    result = []
    total = 0
    for c in counts:
        total += c
        result.append(total)
    return result


def add_movie(data: dict) -> int:
    """
    新增一部电影，返回新电影的 ID

    data 中需包含 title，其他可选：
    original_title, my_rating, watch_time, director, release_date,
    year, country, douban_rating, cast_info, summary, duration,
    language, genre, writer, tags
    """
    conn = get_db()
    conn.execute("""
        INSERT INTO movies (title, original_title, my_rating, watch_time, diary,
                           director, release_date, year, country, douban_rating,
                           cast_info, summary, duration, language, genre, writer, tags)
        VALUES (?,?,?,?,?, ?,?,?,?,?, ?,?,?,?,?, ?,?)
    """, (
        data.get("title"),
        data.get("original_title", ""),
        data.get("my_rating", 0),
        data.get("watch_time", ""),
        data.get("diary", ""),
        data.get("director", ""),
        data.get("release_date", ""),
        data.get("year", ""),
        data.get("country", ""),
        data.get("douban_rating", ""),
        data.get("cast_info", ""),
        data.get("summary", ""),
        data.get("duration", ""),
        data.get("language", ""),
        data.get("genre", ""),
        data.get("writer", ""),
        data.get("tags", ""),
    ))
    movie_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
    conn.commit()
    conn.close()
    return movie_id


def update_movie(movie_id: int, data: dict) -> bool:
    """更新电影字段（只更新传入的字段）"""
    allowed = {
        "title", "original_title", "my_rating", "watch_time", "diary",
        "director", "release_date", "year", "country", "douban_rating",
        "cast_info", "summary", "duration", "language", "genre", "writer", "tags",
    }
    updates = {}
    for k, v in data.items():
        if k in allowed and v is not None:
            updates[k] = v
    if not updates:
        return False

    conn = get_db()
    set_clause = ", ".join(f"{k} = ?" for k in updates)
    conn.execute(
        f"UPDATE movies SET {set_clause} WHERE id = ?",
        list(updates.values()) + [movie_id],
    )
    conn.commit()
    conn.close()
    return True


def delete_movie(movie_id: int) -> bool:
    """删除一部电影"""
    conn = get_db()
    conn.execute("DELETE FROM movies WHERE id = ?", (movie_id,))
    conn.commit()
    affected = conn.total_changes
    conn.close()
    return affected > 0
