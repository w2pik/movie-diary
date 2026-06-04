"""
电影封面爬取 — 多源策略 (DuckDuckGo → TMDb / Wikipedia / Bing)
"""
import os
import re
import time
import json
import hashlib
import sys
sys.path.insert(0, os.path.dirname(__file__))

import requests
from bs4 import BeautifulSoup
from database import get_movies_without_covers, update_cover, get_db

POSTER_DIR = os.path.join(os.environ.get("DATA_DIR", os.path.dirname(__file__)), "posters")

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/125.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9,zh-CN;q=0.8",
}

# Wikipedia 要求特定 User-Agent (https://w.wiki/4wJS)
WIKI_HEADERS = {
    "User-Agent": "MovieTracker/1.0 (https://github.com/movie-tracker; movie-tracker@example.com)",
    "Accept": "application/json",
    "Accept-Language": "en-US,en;q=0.9,zh-CN;q=0.8",
}

SESSION = requests.Session()
SESSION.headers.update(HEADERS)

WIKI_SESSION = requests.Session()
WIKI_SESSION.headers.update(WIKI_HEADERS)

DELAY = 1.5  # 请求间隔


def _safe_filename(text: str) -> str:
    h = hashlib.md5(text.encode()).hexdigest()[:12]
    return f"{h}.jpg"


def _download_image(url: str, filepath: str) -> bool:
    """下载图片到本地"""
    try:
        if os.path.exists(filepath) and os.path.getsize(filepath) > 2000:
            return True
        resp = SESSION.get(url, timeout=30)
        if resp.status_code == 200 and len(resp.content) > 2000:
            with open(filepath, "wb") as f:
                f.write(resp.content)
            return True
    except Exception:
        pass
    return False


def _ddg_search(query: str) -> list[str]:
    """DuckDuckGo HTML 搜索，返回结果 URL 列表"""
    url = f"https://html.duckduckgo.com/html/?q={requests.utils.quote(query)}"
    resp = SESSION.get(url, timeout=15)
    if resp.status_code != 200:
        return []

    soup = BeautifulSoup(resp.text, "lxml")
    urls = []
    for a in soup.select("a[href*=\".themoviedb.org/movie/\"]"):
        href = a.get("href", "")
        # DDG wraps URLs: //duckduckgo.com/l/?uddg=REAL_URL
        match = re.search(r"uddg=([^&]+)", href)
        if match:
            real_url = requests.utils.unquote(match.group(1))
            urls.append(real_url.split("?")[0])

    # 如果没找到 TMDb 链接，返回所有链接
    if not urls:
        for a in soup.select("a.result__a"):
            href = a.get("href", "")
            match = re.search(r"uddg=([^&]+)", href)
            if match:
                urls.append(requests.utils.unquote(match.group(1)).split("?")[0])

    return urls


def _get_tmdb_poster_from_page(tmdb_url: str) -> str | None:
    """从 TMDb 页面提取海报 URL（通过 Open Graph 元标签）"""
    resp = SESSION.get(tmdb_url, timeout=15)
    if resp.status_code != 200:
        return None

    # 方法1: og:image meta tag
    match = re.search(
        r'<meta\s+[^>]*property\s*=\s*"og:image"[^>]*content\s*=\s*"([^"]+)"[^>]*/?>',
        resp.text, re.IGNORECASE,
    )
    if not match:
        match = re.search(
            r'<meta\s+[^>]*content\s*=\s*"([^"]+)"[^>]*property\s*=\s*"og:image"[^>]*/?>',
            resp.text, re.IGNORECASE,
        )
    if match:
        return match.group(1)

    # 方法2: 内嵌 JSON 中的 poster_path
    match = re.search(r'"poster_path"\s*:\s*"([^"]+)"', resp.text)
    if match:
        poster_path = match.group(1)
        return f"https://image.tmdb.org/t/p/w500{poster_path}"

    return None


def _get_tmdb_metadata(tmdb_url: str) -> dict:
    """从 TMDb 页面提取电影元数据"""
    metadata = {}

    cn_url = tmdb_url.split("?")[0] + "?language=zh-CN"
    resp = SESSION.get(cn_url, timeout=15)
    if resp.status_code != 200:
        return metadata

    text = resp.text

    # og:title (中文片名)
    match = re.search(
        r'<meta\s+[^>]*property\s*=\s*"og:title"[^>]*content\s*=\s*"([^"]+)"',
        text, re.IGNORECASE,
    )
    if match:
        metadata["title_cn"] = match.group(1)

    # og:description (简介)
    match = re.search(
        r'<meta\s+[^>]*property\s*=\s*"og:description"[^>]*content\s*=\s*"([^"]+)"',
        text, re.IGNORECASE,
    )
    if match:
        metadata["overview"] = match.group(1)

    # 年份
    match = re.search(r'release_date[^>]*>\s*\((\d{4})\)', text)
    if match:
        metadata["year"] = match.group(1)

    # 片长
    match = re.search(r'runtime[^>]*>\s*(\d+h\s*\d+m|\d+分钟)', text)
    if match:
        metadata["runtime"] = match.group(1).strip()

    # 类型
    genres = re.findall(r'/genre/\d+-([^/]+)/movie\?language=zh-CN[^>]*>([^<]+)</a>', text)
    if genres:
        metadata["genres"] = "/".join([g[1] for g in genres])

    # 原片名
    en_url = tmdb_url.split("?")[0] + "?language=en-US"
    resp_en = SESSION.get(en_url, timeout=15)
    if resp_en.status_code == 200:
        match = re.search(
            r'<meta\s+[^>]*property\s*=\s*"og:title"[^>]*content\s*=\s*"([^"]+)"',
            resp_en.text, re.IGNORECASE,
        )
        if match:
            title = match.group(1)
            # 清理年份后缀，如 "Inception (2010)" → "Inception"
            title = re.sub(r'\s*\(\d{4}\)\s*$', '', title).strip()
            # 也清理 "Movie Name (2010 film)" 格式
            title = re.sub(r'\s*\(\d{4}\s+film\)\s*$', '', title, flags=re.IGNORECASE).strip()
            metadata["original_title"] = title

    # Release date (完整日期)
    match = re.search(r'(\d{4}-\d{2}-\d{2})', text)
    if match:
        metadata["release_date"] = match.group(1)

    # 评分
    match = re.search(r'user_score_chart[^>]*data-percent="([\d.]+)"', text)
    if match:
        score = float(match.group(1)) / 10
        metadata["douban_rating"] = str(round(score, 1))

    return metadata


def _has_ascii_alpha(text: str) -> bool:
    """检查文本是否包含英文字母"""
    if not text:
        return False
    return bool(re.search(r'[A-Za-z]', text))


def _clean_wiki_text(text: str) -> str:
    """清理 Wikipedia 文本中的注释标记"""
    if not text:
        return ""
    # 删除引用标记 [1] [2] 等
    text = re.sub(r'\s*\[\d+\]\s*', ' ', text)
    # 删除 "（ 英语 ： ... ）" 这类语言标注（含各种变体）
    text = re.sub(r'\s*[（(]\s*(?:英语|英文)\s*[：:]\s*[^）)]*[）)]\s*', '', text)
    # 删除 " （ / 英语 / ： / NAME / ） " split 出的碎片
    text = re.sub(r'\s*[（(]\s*/\s*(?:英语|英文)\s*/\s*[：:]\s*/\s*[^）)]*/\s*[）)]\s*', '', text)
    text = re.sub(r'\s*/\s*英语\s*/\s*[：:][^/]*/\s*', '', text)
    text = re.sub(r'\s*/\s*（英语：[^）]*）', '', text)
    # 删除 "（ 维基数据 ： ... ）"
    text = re.sub(r'\s*[（(]\s*维基数据[^）)]*[）)]\s*', '', text)
    # 删除残留的 "/ / / / /" 模式
    text = re.sub(r'\s*/\s*$', '', text)
    text = re.sub(r'\(\s*/\s*/\s*\)\s*', '', text)
    text = re.sub(r'\s*/\s*\(\s*/\s*\)\s*', '', text)
    # 转全角分隔符
    text = text.replace('／', '/')
    # 压缩多余空格和多余斜线
    text = re.sub(r'\s*/\s*/\s*', '/', text)
    text = re.sub(r'\s+', ' ', text)
    text = text.strip().strip('，,、/ ')
    return text


def _get_wikipedia_metadata(title: str, year: str = "", original_title: str = "") -> dict:
    """从 Wikipedia 提取电影元数据 — 中英文双查，中文优先用于文本字段"""
    en_info = {}
    zh_info = {}

    # ── 英文 Wikipedia ──
    en_queries = []
    if original_title and original_title != title:
        en_queries.append(f"{original_title} {year} film")
    en_queries.append(f"{title} {year} film")
    if original_title:
        en_queries.append(original_title)

    for q in en_queries:
        api_url = (
            "https://en.wikipedia.org/w/api.php"
            f"?action=opensearch&search={requests.utils.quote(q)}&limit=5&format=json"
        )
        try:
            resp = WIKI_SESSION.get(api_url, timeout=10)
            if resp.status_code != 200:
                continue
            data = resp.json()
            for i, t in enumerate(data[1]):
                url = data[3][i] if i < len(data[3]) else ""
                if not url or any(x in url.lower() for x in [
                    "/wiki/list_of", "/wiki/category:", "(disambiguation)"
                ]):
                    continue
                info = _extract_wikipedia_infobox(url, "en")
                if info:
                    en_info = info
                    break
        except Exception:
            continue
        if en_info:
            break

    # ── 中文 Wikipedia ──
    zh_queries = [f"{title} 电影", title]
    if year:
        zh_queries.insert(0, f"{title} {year} 电影")
        zh_queries.insert(1, f"{title} ({year} 年电影)")

    for q in zh_queries:
        api_url = (
            "https://zh.wikipedia.org/w/api.php"
            f"?action=opensearch&search={requests.utils.quote(q)}&limit=10&format=json"
        )
        try:
            resp = WIKI_SESSION.get(api_url, timeout=10)
            if resp.status_code != 200:
                continue
            data = resp.json()
            # 按匹配度排序：标题含"电影"或URL含"电影"的优先
            candidates = []
            for i, t in enumerate(data[1]):
                url = data[3][i] if i < len(data[3]) else ""
                if not url:
                    continue
                if any(x in url for x in ["list_of", "/wiki/Category:", "(disambiguation)", "维基百科:"]):
                    continue
                score = 0
                if "电影" in t:
                    score += 10
                if "電影" in t:
                    score += 10
                if year and year in t:
                    score += 5
                if "杀手" in t or "殺手" in t:
                    score -= 20  # 排除杀手百科页
                if any(kw in t for kw in ["剧集", "电视剧", "歌曲", "小说", "游戏"]):
                    score -= 30  # 排除非电影页面
                candidates.append((score, url, t))
            candidates.sort(key=lambda x: x[0], reverse=True)

            for _, url, _ in candidates:
                info = _extract_wikipedia_infobox(url, "zh")
                if info:
                    zh_info = info
                    break
        except Exception:
            continue
        if zh_info:
            break

    # ── 合并：中文优先用于文本字段，英文补位 ──
    # 文本内容字段 — 中文优先（summary/cast_info/writer）
    # 结构化字段 — 英文为主+中文补缺（genre/tags 取并集）
    text_fields = ["summary", "cast_info", "writer"]
    structural_fields = ["director", "year", "duration", "country", "language", "release_date", "original_title", "genre"]

    merged = {}

    # 英文作为基础
    for f in structural_fields:
        if en_info.get(f):
            merged[f] = _clean_wiki_text(en_info[f])
    for f in text_fields:
        if en_info.get(f):
            merged[f] = _clean_wiki_text(en_info[f])

    # 中文覆盖文本字段
    for f in text_fields:
        if zh_info.get(f):
            merged[f] = _clean_wiki_text(zh_info[f])

    # 中文也覆盖导演名
    if zh_info.get("director"):
        merged["director"] = _clean_wiki_text(zh_info["director"])

    # 中文的结构字段补缺
    for f in structural_fields:
        if zh_info.get(f) and not merged.get(f):
            merged[f] = _clean_wiki_text(zh_info[f])

    # genre 中英文并集（避免中文覆盖掉英文更丰富的分类）
    en_genre = en_info.get("genre", "")
    zh_genre = zh_info.get("genre", "")
    all_genres = []
    for g in (en_genre + "/" + zh_genre).split("/"):
        g = g.strip()
        if g and g not in all_genres:
            all_genres.append(g)
    if all_genres:
        merged["genre"] = "/".join(all_genres)

    # ── 从最终合并数据重新生成 tags（确保 genre+country+year 完整）──
    tags = []
    if merged.get("genre"):
        for g in merged["genre"].split("/"):
            g = g.strip()
            if g and g not in tags:
                tags.append(g)
    if merged.get("country"):
        for c in merged["country"].split("/"):
            c = c.strip()
            if c and c not in tags:
                tags.append(c)
    if merged.get("year"):
        tags.append(merged["year"])
    if tags:
        merged["tags"] = "/".join(tags)

    return merged


def _extract_plot_summary(soup, lang: str = "en") -> str | None:
    """从 Wikipedia 页面提取剧情简介（Plot / 剧情章节），而非文章首段概述"""
    plot_ids_lower = {
        "en": ["plot", "synopsis", "plot summary"],
        "zh": ["剧情", "情節", "情节", "故事", "故事大纲", "故事大綱"],
    }
    ids = plot_ids_lower.get(lang, plot_ids_lower["en"])

    content = soup.select_one("#mw-content-text .mw-parser-output")
    if not content:
        return None

    plot_start = None
    for h2 in content.select("h2"):
        # id 可能在 <h2 id="Plot"> 上，也可能在 <span id="Plot">
        hid = (h2.get("id") or "").lower()
        span_id = ""
        span = h2.select_one("span[id]")
        if span:
            span_id = span.get("id", "").lower()
        h2_text = h2.get_text(strip=True).lower()

        if any(id in hid for id in ids) or any(id in span_id for id in ids) or any(id in h2_text for id in ids):
            plot_start = h2
            break

    if not plot_start:
        return None

    # 收集 Plot 章节下的段落，直到下一个 h2
    # 注意：新 Wikipedia 布局中 p 可能有空 class 属性，且不一定是 h2 的 sibling
    paragraphs = []
    current = plot_start.find_next()
    while current:
        if current.name == "h2":
            break
        if current.name == "p":
            cls = current.get("class") or []
            # 跳过有特殊 class 的 p（如 mw-empty-elt）
            if not cls or cls == [""]:
                text = current.get_text(separator=" ", strip=True)
                text = re.sub(r'\s*\[\d+\]\s*', ' ', text)
                text = re.sub(r'\s*\[.*?\]\s*', ' ', text)
                text = re.sub(r'\s+', ' ', text).strip()
                if len(text) > 30:
                    paragraphs.append(text)
        current = current.find_next()

    if paragraphs:
        return " ".join(paragraphs)
    return None


def _extract_wikipedia_infobox(page_url: str, lang: str = "en") -> dict | None:
    """从 Wikipedia 页面提取 infobox 结构化数据"""
    try:
        sess = WIKI_SESSION if "wikipedia.org" in page_url else SESSION
        resp = sess.get(page_url, timeout=15)
        if resp.status_code != 200:
            return None

        soup = BeautifulSoup(resp.text, "lxml")
        infobox = soup.select_one("table.infobox")
        if not infobox:
            return None

        rows = infobox.select("tr")
        raw = {}
        for row in rows:
            th = row.select_one("th")
            td = row.select_one("td")
            if th and td:
                raw[th.get_text(strip=True)] = td

        result = {}

        # 映射 Wikipedia 字段 → 数据库字段
        # 导演
        for key in ["Directed by", "导演"]:
            if key in raw:
                result["director"] = raw[key].get_text(" / ", strip=True).split("[")[0].strip()

        # 主演
        for key in ["Starring", "主演"]:
            if key in raw:
                cast = raw[key].get_text(" / ", strip=True)
                cast = re.sub(r'\[.*?\]', '', cast)  # 去掉引用标记
                result["cast_info"] = cast.strip()

        # 编剧
        for key in ["Screenplay by", "Written by", "编剧"]:
            if key in raw:
                result["writer"] = raw[key].get_text(" / ", strip=True).split("[")[0].strip()

        # 上映日期
        for key in ["Release dates", "Release date", "上映日期"]:
            if key in raw:
                date_text = raw[key].get_text(strip=True)
                # 提取第一个日期
                match = re.search(r'(\d{4}-\d{2}-\d{2})', date_text)
                if match:
                    result["release_date"] = match.group(1)
                else:
                    # 尝试中文格式: 1993年1月1日
                    match = re.search(r'(\d{4})年(\d{1,2})月(\d{1,2})日', date_text)
                    if match:
                        result["release_date"] = f"{match.group(1)}-{int(match.group(2)):02d}-{int(match.group(3)):02d}"

        # 片长
        for key in ["Running time", "片长"]:
            if key in raw:
                dur = raw[key].get_text(strip=True)
                match = re.search(r'(\d+)\s*分钟', dur)
                if match:
                    result["duration"] = f"{match.group(1)}分钟"
                else:
                    match = re.search(r'(\d+)\s*minutes?', dur, re.IGNORECASE)
                    if match:
                        result["duration"] = f"{match.group(1)}分钟"

        # 国家
        for key in ["Country", "Countries", "产地"]:
            if key in raw:
                country = raw[key].get_text(" / ", strip=True)
                country = re.sub(r'\[.*?\]', '', country)
                # 标准化
                country = country.replace("United States", "美国")
                country = country.replace("China", "中国大陆")
                country = country.replace("Hong Kong", "中国香港")
                country = country.replace("英属香港", "中国香港")
                country = country.replace("United Kingdom", "英国")
                country = country.replace(" / ", "/")
                # 合并连续多个斜杠
                country = re.sub(r'/+', '/', country)
                country = country.strip()
                if len(country) < 80:
                    result["country"] = country

        # 语言
        for key in ["Language", "语言"]:
            if key in raw:
                lang_val = raw[key].get_text(strip=True)
                lang_val = re.sub(r'\[.*?\]', '', lang_val)
                if len(lang_val) < 80:
                    # 标准化
                    lang_val = lang_val.replace("Mandarin", "汉语普通话")
                    lang_val = lang_val.replace("English", "英语")
                    lang_val = lang_val.replace(" / ", "/")
                    result["language"] = lang_val.strip()

        # 年份（从上映日期提取）
        if result.get("release_date"):
            match = re.search(r'(\d{4})', result["release_date"])
            if match:
                result["year"] = match.group(1)

        # ── 额外提取：不在 infobox 中的字段 ──

        # 剧情简介 — 从 Plot / 剧情 章节提取，而非文章首段（首段是概述不是剧情）
        if not result.get("summary"):
            summary_text = _extract_plot_summary(soup, lang)
            if summary_text:
                result["summary"] = summary_text[:600]

        # 原片名 — 优先从 infobox 字段提取
        if not result.get("original_title"):
            for key in ["Original title", "原名", "英文片名", "英语片名"]:
                if key in raw:
                    val = raw[key].get_text(strip=True)
                    val = re.sub(r'\s*\(\d{4}\)\s*$', '', val).strip()
                    val = re.sub(r'\s*\(\d{4}\s+film\)\s*$', '', val, flags=re.IGNORECASE).strip()
                    if val and len(val) < 120:
                        result["original_title"] = val
                        break

        # 原片名 — 仅从英文 Wikipedia 页面标题兜底提取
        if not result.get("original_title") and lang == "en":
            title_tag = soup.select_one("title")
            if title_tag:
                page_title = title_tag.get_text(strip=True)
                page_title = re.sub(r'\s*[-–—]\s*Wikipedia.*$', '', page_title).strip()
                clean = re.sub(r'\s*\(\d{4}\s+film\)\s*', '', page_title).strip()
                clean = re.sub(r'\s*\(\d{4}\)\s*', '', clean).strip()
                clean = re.sub(r'\s*\(film\)\s*', '', clean).strip()
                if clean and clean != result.get("title", ""):
                    result["original_title"] = clean

        # 类型 — 从页面分类提取（中英文关键字都支持）
        if not result.get("genre"):
            # 关键字 → 中文类型名
            genre_map = {
                # 英文关键字
                "crime thriller": "惊悚", "crime": "犯罪", "thriller": "惊悚",
                "mystery": "悬疑", "drama": "剧情", "comedy": "喜剧",
                "action": "动作", "horror": "恐怖", "science fiction": "科幻",
                "sci-fi": "科幻", "fantasy": "奇幻", "adventure": "冒险",
                "romance": "爱情", "romantic": "爱情",
                "historical": "历史", "history": "历史",
                "war": "战争", "military": "战争",
                "biography": "传记", "biographical": "传记",
                "documentary": "纪录片",
                "animation": "动画", "animated": "动画",
                "musical": "歌舞", "music": "音乐",
                "western": "西部",
                "noir": "黑色电影", "psychological": "心理",
                "superhero": "超级英雄", "disaster": "灾难", "survival": "生存",
                # 中文关键字（匹配中文 Wikipedia 的分类）
                "惊悚": "惊悚", "恐怖": "恐怖", "犯罪": "犯罪",
                "悬疑": "悬疑", "剧情": "剧情", "喜剧": "喜剧",
                "动作": "动作", "科幻": "科幻",
                "奇幻": "奇幻", "冒险": "冒险", "冒险片": "冒险",
                "爱情": "爱情", "历史": "历史",
                "战争": "战争", "战争片": "战争",
                "传记": "传记", "纪录": "纪录片",
                "动画": "动画", "歌舞": "歌舞",
                "音乐": "音乐", "西部": "西部",
                "灾难": "灾难", "家庭": "家庭", "儿童": "家庭",
                "武侠": "武侠", "古装": "古装", "间谍": "悬疑",
            }
            cats = soup.select("#mw-normal-catlinks ul li a")
            found = []
            for cat in cats:
                ctext = cat.get_text(strip=True).lower()
                for kw, cn in genre_map.items():
                    if kw in ctext and cn not in found:
                        found.append(cn)
                        break
            if found:
                result["genre"] = "/".join(found[:5])

        # 标签 — 从类型 + 国家 + 年份自动生成
        tags = []
        if result.get("genre"):
            for g in result["genre"].split("/"):
                g = g.strip()
                if g and g not in tags:
                    tags.append(g)
        if result.get("country"):
            for c in result["country"].split("/"):
                c = c.strip()
                if c and c not in tags:
                    tags.append(c)
        if result.get("year"):
            tags.append(result["year"])
        if tags:
            result["tags"] = "/".join(tags)

        return result if len(result) > 1 else None

    except Exception:
        return None


def _try_tmdb_direct(title: str, year: str = "") -> dict | None:
    """直接搜索 TMDb（不依赖 DDG），从搜索页提取电影 ID 和元数据"""
    queries = [title]
    if year:
        queries.insert(0, f"{title} {year}")

    for q in queries:
        try:
            url = f"https://www.themoviedb.org/search?query={requests.utils.quote(q)}"
            resp = SESSION.get(url, timeout=15)
            if resp.status_code != 200:
                continue

            # 提取第一个电影链接
            match = re.search(r'href="/(movie/\d+)', resp.text)
            if not match:
                continue

            tmdb_path = match.group(1)
            tmdb_url = f"https://www.themoviedb.org/{tmdb_path}"

            # 从搜索结果中提取 poster_path 和 vote_average
            poster_match = re.search(
                r'data-poster-path="([^"]+)".*?data-vote-average="([\d.]+)"',
                resp.text, re.DOTALL,
            )
            # 或者更宽松的匹配
            if not poster_match:
                poster_match = re.search(r'"vote_average":\s*([\d.]+)', resp.text)

            result = {}
            if poster_match:
                # Try to extract both
                m = re.search(r'data-vote-average="([\d.]+)"', resp.text)
                if m:
                    result["douban_rating"] = str(round(float(m.group(1)), 1))

            # 用 TMDb 页面获取更多信息
            meta = _get_tmdb_metadata(tmdb_url)
            if meta:
                result.update(meta)

            return result if result else None

        except Exception:
            continue

    return None


def fetch_movie_metadata(title: str, year: str = "", original_title: str = "") -> dict:
    """
    综合获取电影元数据：Wikipedia 优先(完整) + TMDb 补充(评分)
    返回可直接写入数据库的字段 dict
    """
    metadata = {}

    # 1. Wikipedia — 获取几乎所有字段 (含 summary, genre, original_title, tags)
    wiki_data = _get_wikipedia_metadata(title, year, original_title)
    if wiki_data:
        for key in ["director", "cast_info", "writer", "country", "language",
                     "duration", "release_date", "year", "summary",
                     "original_title", "genre", "tags"]:
            val = wiki_data.get(key, "")
            if val:
                metadata[key] = val

    # 2. TMDb 直接搜索 — 补充评分 (douban_rating)，Wikipedia 没有评分
    tmdb_data = _try_tmdb_direct(original_title if original_title else title, year)
    if not tmdb_data:
        tmdb_data = _try_tmdb_direct(title, year)

    if tmdb_data:
        # 取评分
        if tmdb_data.get("douban_rating") and not metadata.get("douban_rating"):
            metadata["douban_rating"] = tmdb_data["douban_rating"]

        # 如果 Wikipedia 缺了某些字段，用 TMDb 补（含 TMDb → 数据库字段映射）
        tmdb_field_map = {
            "summary": ["overview", "summary"],
            "genre": ["genres", "genre"],
            "original_title": ["original_title"],
            "duration": ["runtime", "duration"],
            "year": ["year"],
        }
        for db_key, tmdb_keys in tmdb_field_map.items():
            for tk in tmdb_keys:
                val = tmdb_data.get(tk, "")
                if val:
                    existing = metadata.get(db_key, "")
                    # 覆盖条件：缺失、或 original_title 不含英文字母（可能是中文标题）
                    if not existing or (db_key == "original_title" and not _has_ascii_alpha(existing)):
                        metadata[db_key] = val
                    break  # 找到一个就停

    return metadata


def _get_wikipedia_poster(title: str, year: str = "", lang: str = "en") -> str | None:
    """通过 Wikipedia API 获取电影海报"""
    queries = []
    if year:
        queries.append(f"{title} {year} film")
    queries.append(f"{title} film")
    queries.append(title)

    for query in queries:
        api_url = (
            f"https://{lang}.wikipedia.org/w/api.php"
            f"?action=opensearch&search={requests.utils.quote(query)}&limit=5&format=json"
        )
        resp = WIKI_SESSION.get(api_url, timeout=10)
        if resp.status_code != 200:
            continue
        data = resp.json()

        # 过滤：只保留包含 "film" 或 "movie" 的结果，或者标题长度合理的结果
        candidates = []
        for i, t in enumerate(data[1]):
            url = data[3][i] if i < len(data[3]) else ""
            if not url:
                continue
            # 排除 list、category、disambiguation 页面
            if any(x in url.lower() for x in ["/wiki/list_of", "/wiki/category:", "(disambiguation)"]):
                continue
            # 优先包含 film/movie 或年份的结果
            score = 0
            if year and year in t:
                score += 3
            if "film" in t.lower() or "movie" in t.lower():
                score += 2
            candidates.append((score, url, t))

        candidates.sort(key=lambda x: x[0], reverse=True)

        for _, page_url, _ in candidates:
            poster = _extract_wikipedia_poster(page_url, lang)
            if poster:
                return poster

    return None


def _extract_wikipedia_poster(page_url: str, lang: str = "en") -> str | None:
    """从 Wikipedia 页面提取海报图片 URL"""
    try:
        # 使用 pageimages API 获取主图
        title = page_url.split("/wiki/")[-1]
        api_url = (
            f"https://{lang}.wikipedia.org/w/api.php"
            f"?action=query&titles={requests.utils.quote(title)}"
            f"&prop=pageimages&format=json&pithumbsize=500"
        )
        resp = WIKI_SESSION.get(api_url, timeout=10)
        if resp.status_code != 200:
            return None

        data = resp.json()
        pages = data.get("query", {}).get("pages", {})
        for _pid, info in pages.items():
            thumb = info.get("thumbnail", {}).get("source", "")
            if thumb:
                # 尝试获取原图（去掉 thumbnail 路径）
                original = re.sub(r"/thumb(/[a-z0-9]/[a-z0-9]/[^/]+\.(?:jpg|png|jpeg|JPG|PNG|JPEG))/[^/]+$",
                                  r"\1", thumb)
                return original  # 返回原图 URL（如果可用），否则返回缩略图
    except Exception:
        pass
    return None


def _get_bing_poster(title: str, year: str = "") -> str | None:
    """通过 Bing 图片搜索获取海报"""
    query = f"{title} {year} movie poster".strip()
    url = f"https://www.bing.com/images/search?q={requests.utils.quote(query)}&form=HDRSC2&first=1"
    try:
        resp = SESSION.get(url, timeout=15)
        if resp.status_code != 200:
            return None

        soup = BeautifulSoup(resp.text, "lxml")
        for a in soup.select("a.iusc"):
            m_str = a.get("m", "")
            if not m_str:
                continue
            try:
                m = json.loads(m_str)
                murl = m.get("murl", "")
                if murl and (murl.endswith(".jpg") or murl.endswith(".png")):
                    return murl
            except json.JSONDecodeError:
                pass
    except Exception:
        pass
    return None


def search_cover(title: str, year: str = "", original_title: str = "") -> dict | None:
    """
    多源搜索电影封面，返回 {"cover_url": str, "metadata": dict} 或 None
    策略: 豆瓣 → TMDb → Wikipedia → Bing，全部失败则返回 None
    """
    year_str = str(year).strip() if year else ""
    orig = (original_title or "").strip()

    # ── 策略0: 豆瓣搜索（优先，被封锁时自动跳过）──
    try:
        douban_result = _try_douban_search(title, year_str, orig)
        if douban_result:
            meta = fetch_movie_metadata(title, year_str, orig)
            return {"cover_url": douban_result, "source": "douban", "metadata": meta}
    except Exception:
        pass

    # ── 策略1: TMDb 直接搜索 ──
    try:
        tmdb_result = _try_tmdb_direct_get_poster(title, year_str, orig)
        if tmdb_result:
            meta = fetch_movie_metadata(title, year_str, orig)
            return {"cover_url": tmdb_result, "source": "tmdb", "metadata": meta}
    except Exception:
        pass

    # ── 策略2: Wikipedia 封面 (英文) ──
    queries_wiki = [title]
    if orig and orig != title:
        queries_wiki.insert(0, orig)
    if year_str:
        queries_wiki.insert(0, f"{title} {year_str}")
    try:
        for q in queries_wiki:
            poster = _get_wikipedia_poster(q, year_str, "en")
            if poster:
                meta = fetch_movie_metadata(title, year_str, orig)
                return {"cover_url": poster, "source": "wikipedia", "metadata": meta}
    except Exception:
        pass

    # ── 策略3: Wikipedia 中文 ──
    try:
        for q in queries_wiki:
            poster = _get_wikipedia_poster(q, year_str, "zh")
            if poster:
                meta = fetch_movie_metadata(title, year_str, orig)
                return {"cover_url": poster, "source": "wikipedia-zh", "metadata": meta}
    except Exception:
        pass

    # ── 策略4: Bing ──
    try:
        for q in queries_wiki:
            poster = _get_bing_poster(q, year_str)
            if poster:
                meta = fetch_movie_metadata(title, year_str, orig)
                return {"cover_url": poster, "source": "bing", "metadata": meta}
    except Exception:
        pass

    # ── 策略5: 无封面，只拿元数据 ──
    try:
        meta = fetch_movie_metadata(title, year_str, orig)
        if meta:
            return {"cover_url": "", "source": "metadata-only", "metadata": meta}
    except Exception:
        pass

    return None


def _try_douban_search(title: str, year: str = "", original_title: str = "") -> str | None:
    """从豆瓣搜索电影海报 URL。被封锁时静默返回 None。"""
    queries = [title]
    if year:
        queries.insert(0, f"{title} {year}")
    if original_title and original_title != title:
        queries.append(original_title)

    for q in queries:
        try:
            # 豆瓣电影搜索
            url = f"https://movie.douban.com/subject_search?search_text={requests.utils.quote(q)}"
            resp = SESSION.get(url, headers=HEADERS, timeout=10, allow_redirects=True)
            if resp.status_code != 200:
                continue

            soup = BeautifulSoup(resp.text, "lxml")
            for img in soup.select(".item-root img, .sc-bZQynM img, img[src*='doubanio']"):
                src = img.get("src", "") or img.get("data-src", "")
                if src and "doubanio.com" in src:
                    # 转大图
                    src = re.sub(r"/s_ratio_poster/", "/l_ratio_poster/", src)
                    src = re.sub(r"/small/", "/large/", src)
                    src = re.sub(r"/m_thumb/", "/l_thumb/", src)
                    src = src.replace(".webp", ".jpg")
                    return src

            # 也尝试提取 subject id 然后直接构造海报 URL
            subject_match = re.search(r'/subject/(\d+)/', resp.text)
            if subject_match:
                sid = subject_match.group(1)
                # 尝试常见海报 URL 模式（豆瓣的 poster 通常用这个格式）
                poster_url = f"https://img9.doubanio.com/view/photo/l_ratio_poster/public/p{sid}0001.jpg"
                return poster_url

        except Exception:
            continue

    return None


def _try_tmdb_direct_get_poster(title: str, year: str = "", original_title: str = "") -> str | None:
    """从 TMDb 直接搜索并获取海报 URL（不依赖第三方搜索引擎）"""
    queries = [title]
    if year:
        queries.insert(0, f"{title} {year}")
    if original_title and original_title != title:
        queries.append(original_title)

    for q in queries:
        try:
            url = f"https://www.themoviedb.org/search?query={requests.utils.quote(q)}"
            resp = SESSION.get(url, timeout=15)
            if resp.status_code != 200:
                continue
            # 提取第一个电影的 poster_path
            match = re.search(r'data-poster-path="([^"]+)"', resp.text)
            if match:
                poster_path = match.group(1)
                return f"https://image.tmdb.org/t/p/w780{poster_path}"
        except Exception:
            continue
    return None


# ── 批量爬取 ────────────────────────────────────────────

def fetch_covers(force_all: bool = False):
    """为数据库中所有缺少封面的电影爬取封面"""
    os.makedirs(POSTER_DIR, exist_ok=True)

    if force_all:
        conn = get_db()
        movies = conn.execute(
            "SELECT id, title, original_title, year FROM movies"
        ).fetchall()
        conn.close()
        movies = [dict(r) for r in movies]
    else:
        movies = get_movies_without_covers()

    if not movies:
        print("✅ 所有电影都有封面了！")
        return

    total = len(movies)
    success = 0
    failed = []

    print(f"🎬 开始获取 {total} 部电影的封面...")
    print(f"   策略: DDG→TMDb → Wikipedia(EN/ZH) → Bing")
    print(f"   间隔: {DELAY}s/部\n")

    for i, movie in enumerate(movies):
        mid = movie["id"]
        title = movie["title"]
        year = str(movie.get("year", "") or "")
        orig = str(movie.get("original_title", "") or "")

        print(f"[{i+1}/{total}] {title} ({year}) ... ", end="", flush=True)

        result = search_cover(title, year, orig)

        if result and result["cover_url"]:
            filename = _safe_filename(title)
            filepath = os.path.join(POSTER_DIR, filename)
            if _download_image(result["cover_url"], filepath):
                update_cover(mid, result["cover_url"], filename)
                src = result.get("source", "?")
                print(f"✅ ({src})")
                success += 1
            else:
                update_cover(mid, result["cover_url"], "")
                print(f"⚠️ 下载失败")
                failed.append(title)
        else:
            print(f"❌ 未找到")
            failed.append(title)

        if i < total - 1:
            time.sleep(DELAY)

    print(f"\n{'='*50}")
    print(f"📊 结果: {success}/{total} 成功")
    if failed:
        print(f"❌ 失败 ({len(failed)}):")
        for t in failed[:15]:
            print(f"   - {t}")
        if len(failed) > 15:
            print(f"   ... 还有 {len(failed) - 15} 部")


if __name__ == "__main__":
    fetch_covers(force_all="--force" in sys.argv)
