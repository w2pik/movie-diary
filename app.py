"""
Flask 应用 — 电影日记 Web 服务
"""
import os
import sys
sys.path.insert(0, os.path.dirname(__file__))

from flask import Flask, render_template, request, jsonify, send_from_directory
from database import (
    init_db, get_all_movies, get_movie_by_id, search_movies,
    get_all_tags, get_all_years, get_all_countries, get_all_genres,
    get_stats, get_time_stats, get_heatmap_data, add_movie, update_movie, delete_movie
)
from fetch_covers import search_cover, _download_image, _safe_filename, fetch_movie_metadata

app = Flask(__name__)
app.config["JSON_AS_ASCII"] = False  # 确保中文正常显示
app.config["JSONIFY_PRETTYPRINT_REGULAR"] = False
POSTER_DIR = os.path.join(os.environ.get("DATA_DIR", os.path.dirname(__file__)), "posters")


@app.route("/")
def index():
    """主页"""
    return render_template("index.html")


# ── API 路由 ────────────────────────────────────────────

@app.route("/api/movies")
def api_movies():
    """获取电影列表（支持搜索、筛选、排序、分页）"""
    keyword = request.args.get("q", "").strip()
    year = request.args.get("year", "").strip()
    country = request.args.get("country", "").strip()
    genre = request.args.get("genre", "").strip()
    tags = request.args.get("tags", "").strip()
    min_rating = request.args.get("min_rating", "").strip()
    sort_by = request.args.get("sort_by", "watch_time")
    order = request.args.get("order", "DESC")
    page = int(request.args.get("page", 1))
    per_page = int(request.args.get("per_page", 50))

    # 如果有搜索条件，用 search_movies
    has_filter = any([keyword, year, country, genre, tags, min_rating])

    if has_filter:
        movies = search_movies(
            keyword=keyword or None,
            year=year or None,
            country=country or None,
            genre=genre or None,
            min_rating=float(min_rating) if min_rating else None,
            tags=tags or None,
            sort_by=sort_by,
            order=order,
        )
    else:
        movies = get_all_movies(sort_by=sort_by, order=order)

    # 分页
    total = len(movies)
    start = (page - 1) * per_page
    end = start + per_page
    page_movies = movies[start:end]

    return jsonify({
        "movies": page_movies,
        "total": total,
        "page": page,
        "per_page": per_page,
        "total_pages": (total + per_page - 1) // per_page if per_page else 0,
    })


@app.route("/api/movie/<int:movie_id>")
def api_movie_detail(movie_id):
    """获取单部电影详情"""
    movie = get_movie_by_id(movie_id)
    if not movie:
        return jsonify({"error": "Not found"}), 404
    return jsonify(movie)


@app.route("/api/stats")
def api_stats():
    """获取统计信息"""
    return jsonify(get_stats())


@app.route("/api/stats/time")
def api_stats_time():
    """按时间粒度统计观影数量
    Query params:
        granularity: year | month | week | day (default: year)
        year: 指定年份
        month: 指定月份
    """
    granularity = request.args.get("granularity", "year")
    year = request.args.get("year", None)
    month = request.args.get("month", None)
    return jsonify(get_time_stats(granularity, year, month))


@app.route("/api/stats/heatmap")
def api_stats_heatmap():
    """获取观影热力图数据"""
    return jsonify(get_heatmap_data())


@app.route("/api/movies/add", methods=["POST"])
def api_add_movie():
    """新增电影"""
    data = request.get_json()
    if not data or not data.get("title"):
        return jsonify({"error": "电影名不能为空"}), 400

    movie_id = add_movie(data)

    # 自动获取封面和元数据（多源策略）
    cover_result = search_cover(
        data["title"],
        data.get("year", ""),
        data.get("original_title", ""),
    )
    if cover_result and cover_result["cover_url"]:
        filename = _safe_filename(data["title"])
        filepath = os.path.join(POSTER_DIR, filename)
        if _download_image(cover_result["cover_url"], filepath):
            from database import update_cover, get_db
            update_cover(movie_id, cover_result["cover_url"], filename)

            # 自动填充元数据（仅当用户未填写时）
            meta = cover_result.get("metadata", {})
            if meta:
                _apply_metadata(movie_id, meta, data)

    return jsonify({"id": movie_id, "message": "添加成功"})


@app.route("/api/movie/<int:movie_id>/enrich", methods=["POST"])
def api_enrich_movie(movie_id):
    """补全电影元数据（从 TMDb + Wikipedia 抓取）"""
    movie = get_movie_by_id(movie_id)
    if not movie:
        return jsonify({"error": "Not found"}), 404

    result = search_cover(
        movie["title"],
        movie.get("year") or "",
        movie.get("original_title") or "",
    )

    if not result:
        return jsonify({"error": "未能找到该电影的信息"}), 404

    # 下载封面（如果有的话）
    if result.get("cover_url") and not movie.get("cover_local"):
        filename = _safe_filename(movie["title"])
        filepath = os.path.join(POSTER_DIR, filename)
        if _download_image(result["cover_url"], filepath):
            from database import update_cover
            update_cover(movie_id, result["cover_url"], filename)

    # 补全元数据
    meta = result.get("metadata", {})
    filled = _apply_metadata(movie_id, meta, movie, force_fill=True)

    return jsonify({
        "message": "补全完成",
        "filled": filled,
    })


def _apply_metadata(movie_id: int, meta: dict, existing: dict, force_fill: bool = False) -> list[str]:
    """将元数据写入数据库，返回被填充的字段列表"""
    from database import get_db

    conn = get_db()
    updates = {}
    field_map = [
        ("year", "year", "year"),
        ("douban_rating", "douban_rating", "douban_rating"),
        ("genre", "genre", "genre"),
        ("duration", "duration", "duration"),
        ("original_title", "original_title", "original_title"),
        ("summary", "summary", "summary"),
        ("director", "director", "director"),
        ("cast_info", "cast_info", "cast_info"),
        ("writer", "writer", "writer"),
        ("country", "country", "country"),
        ("language", "language", "language"),
        ("release_date", "release_date", "release_date"),
        ("tags", "tags", "tags"),
    ]

    for meta_key, db_col in [(f[0], f[1]) for f in field_map]:
        val = meta.get(meta_key, "")
        if val and (force_fill or not existing.get(db_col)):
            updates[db_col] = val

    if updates:
        set_clause = ", ".join(f"{k} = ?" for k in updates)
        conn.execute(
            f"UPDATE movies SET {set_clause} WHERE id = ?",
            list(updates.values()) + [movie_id],
        )
        conn.commit()

    filled_fields = list(updates.keys())
    conn.close()
    return filled_fields


@app.route("/api/movie/<int:movie_id>", methods=["PUT"])
def api_update_movie(movie_id):
    """更新电影字段"""
    data = request.get_json()
    if not data:
        return jsonify({"error": "No data"}), 400
    ok = update_movie(movie_id, data)
    if not ok:
        return jsonify({"error": "Not found"}), 404
    return jsonify({"message": "已更新"})


@app.route("/api/movie/<int:movie_id>", methods=["DELETE"])
def api_delete_movie(movie_id):
    """删除电影"""
    ok = delete_movie(movie_id)
    if not ok:
        return jsonify({"error": "Not found"}), 404
    return jsonify({"message": "已删除"})


@app.route("/api/filters")
def api_filters():
    """获取筛选选项"""
    return jsonify({
        "tags": get_all_tags(),
        "years": get_all_years(),
        "countries": get_all_countries(),
        "genres": get_all_genres(),
    })


# ── 静态文件 ────────────────────────────────────────────

@app.route("/posters/<path:filename>")
def serve_poster(filename):
    """提供海报图片"""
    if os.path.exists(os.path.join(POSTER_DIR, filename)):
        return send_from_directory(POSTER_DIR, filename)
    # 返回默认占位图
    return send_from_directory(
        os.path.join(os.path.dirname(__file__), "static", "img"),
        "no-poster.svg",
    )


# ── 部署初始化 ────────────────────────────────────────────

def _ensure_data_dir():
    """确保数据目录存在。部署时 DATA_DIR 环境变量指向持久磁盘。"""
    data_dir = os.environ.get("DATA_DIR", os.path.dirname(__file__))
    os.makedirs(os.path.join(data_dir, "posters"), exist_ok=True)
    # 如果是首次部署（磁盘为空），从本目录复制初始数据
    if data_dir != os.path.dirname(__file__):
        db_path = os.path.join(data_dir, "movies.db")
        posters_dir = os.path.join(data_dir, "posters")
        src_db = os.path.join(os.path.dirname(__file__), "movies.db")
        src_posters = os.path.join(os.path.dirname(__file__), "posters")
        import shutil
        if not os.path.exists(db_path) and os.path.exists(src_db):
            shutil.copy2(src_db, db_path)
        if not os.listdir(posters_dir) and os.path.exists(src_posters):
            for f in os.listdir(src_posters):
                if f.endswith(".jpg"):
                    shutil.copy2(os.path.join(src_posters, f), os.path.join(posters_dir, f))

# ── 启动 ────────────────────────────────────────────────

_ensure_data_dir()
init_db()

if __name__ == "__main__":
    import os as _os
    port = int(_os.environ.get("PORT", 5000))
    import socket
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("8.8.8.8", 80))
        local_ip = s.getsockname()[0]
    finally:
        s.close()
    print(f"🎬 电影日记启动!")
    print(f"   本机访问: http://127.0.0.1:{port}")
    print(f"   手机访问: http://{local_ip}:{port}")
    app.run(debug=False, host="0.0.0.0", port=port)
