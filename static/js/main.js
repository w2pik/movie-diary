/**
 * 电影日记 — 前端交互逻辑
 * v2 — 新增统计分析 + 添加电影功能
 */
(function () {
    "use strict";

    // ── 状态 ────────────────────────────────────────────
    const state = {
        movies: [],
        total: 0,
        activeFilters: {},
        allTags: [],
        statsCharts: {},
        currentView: "wall",
    };

    // ── DOM 快捷方式 ────────────────────────────────────
    const $ = (sel) => document.querySelector(sel);
    const $$ = (sel) => document.querySelectorAll(sel);

    // ── API 封装 ────────────────────────────────────────
    const API = {
        async getMovies(params = {}) {
            const url = new URL("/api/movies", location.origin);
            Object.entries(params).forEach(([k, v]) => { if (v) url.searchParams.set(k, v); });
            const resp = await fetch(url);
            if (!resp.ok) throw new Error("API error");
            return resp.json();
        },
        async getMovieDetail(id) {
            const resp = await fetch(`/api/movie/${id}`);
            if (!resp.ok) throw new Error("Not found");
            return resp.json();
        },
        async getStats() {
            const resp = await fetch("/api/stats");
            return resp.json();
        },
        async getTimeStats(params = {}) {
            const url = new URL("/api/stats/time", location.origin);
            Object.entries(params).forEach(([k, v]) => { if (v) url.searchParams.set(k, v); });
            const resp = await fetch(url);
            return resp.json();
        },
        async getHeatmap() {
            const resp = await fetch("/api/stats/heatmap");
            return resp.json();
        },
        async getFilters() {
            const resp = await fetch("/api/filters");
            return resp.json();
        },
        async addMovie(data) {
            const resp = await fetch("/api/movies/add", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify(data),
            });
            return resp.json();
        },
        async deleteMovie(id) {
            const resp = await fetch(`/api/movie/${id}`, { method: "DELETE" });
            return resp.json();
        },
        async updateMovie(id, data) {
            const resp = await fetch(`/api/movie/${id}`, {
                method: "PUT",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify(data),
            });
            return resp.json();
        },
        async enrichMovie(id) {
            const resp = await fetch(`/api/movie/${id}/enrich`, { method: "POST" });
            return resp.json();
        },
    };

    // ── 工具函数 ────────────────────────────────────────
    function escHtml(str) {
        if (!str) return "";
        const div = document.createElement("div");
        div.textContent = str;
        return div.innerHTML;
    }

    function formatDate(dateStr) {
        if (!dateStr) return "";
        try {
            const d = new Date(dateStr);
            if (isNaN(d.getTime())) return dateStr.slice(0, 10);
            return d.toLocaleDateString("zh-CN", { year: "numeric", month: "2-digit", day: "2-digit" });
        } catch { return dateStr.slice(0, 10); }
    }

    function debounce(fn, ms) {
        let timer;
        return function (...args) {
            clearTimeout(timer);
            timer = setTimeout(() => fn.apply(this, args), ms);
        };
    }

    // ── 双搜索框同步 ─────────────────────────────────
    function getSearchInput() {
        const d = $("#searchInputDesktop");
        const m = $("#searchInputMobile");
        const dVisible = d && d.offsetParent !== null;
        return dVisible ? d : (m || d);
    }
    function getSearchValue() {
        const el = getSearchInput();
        return el ? el.value.trim() : "";
    }
    function setSearchValue(val) {
        const d = $("#searchInputDesktop"), m = $("#searchInputMobile");
        if (d) d.value = val;
        if (m) m.value = val;
    }

    // ── 标签切换 ────────────────────────────────────────
    function switchView(view) {
        state.currentView = view;
        $("#viewWall").style.display = view === "wall" ? "" : "none";
        $("#viewStats").style.display = view === "stats" ? "" : "none";
        // 切换视图时隐藏/显示搜索
        const sd = $("#searchDesktop"), sm = $("#searchMobile");
        if (view === "wall") {
            if (sd) sd.style.display = "";
            if (sm) sm.style.display = "none";
        } else {
            if (sd) sd.style.display = "none";
            if (sm) sm.style.display = "none";
        }
        $$("#mainTabs .tab").forEach(t => {
            t.classList.toggle("active", t.dataset.tab === view);
        });
        if (view === "stats") {
            loadStatsView();
        }
    }

    $$("#mainTabs .tab").forEach(tab => {
        tab.addEventListener("click", () => switchView(tab.dataset.tab));
    });

    // ═══════════════════════════════════════════════════════
    // 电影墙视图
    // ═══════════════════════════════════════════════════════

    function renderMovieCard(movie) {
        const posterUrl = movie.cover_local ? `/posters/${movie.cover_local}` : "/posters/_none_";
        const year = movie.year || "";
        const rating = movie.douban_rating || "";
        const country = movie.country ? movie.country.split("/")[0] : "";
        const genre = movie.genre ? movie.genre.split("/")[0] : "";
        const director = movie.director || "";

        return `
            <div class="movie-card" data-id="${movie.id}" onclick="window._openDetail(${movie.id})">
                <div class="poster-wrap">
                    ${movie.cover_local
                        ? `<img src="${posterUrl}" alt="${escHtml(movie.title)}" loading="lazy"
                              onerror="this.parentElement.innerHTML='<div class=\\'poster-placeholder\\'>🎬</div>'">`
                        : `<div class="poster-placeholder">🎬</div>`
                    }
                    <div class="poster-overlay"></div>
                    ${rating ? `<div class="rating-badge">⭐ ${rating}</div>` : ""}
                </div>
                <div class="card-info">
                    <div class="card-title" title="${escHtml(movie.title)}">${escHtml(movie.title)}</div>
                    <div class="card-meta">
                        ${year ? `<span>${year}</span>` : ""}
                        ${country ? `<span class="dot"></span><span>${country}</span>` : ""}
                        ${genre ? `<span class="dot"></span><span>${genre}</span>` : ""}
                    </div>
                    <div class="card-meta-row2">
                        ${director ? `<span>${escHtml(director)}</span>` : ""}
                    </div>
                </div>
            </div>`;
    }

    function renderGrid(movies) {
        if (movies.length === 0) {
            $("#movieGrid").innerHTML = `
                <div class="empty-state">
                    <div class="icon">🎞️</div>
                    <div class="text">没有找到匹配的电影</div>
                </div>`;
            return;
        }
        $("#movieGrid").innerHTML = movies.map(renderMovieCard).join("");
    }

    function buildParams() {
        const p = {};
        const q = getSearchValue();
        if (q) p.q = q;
        p.sort_by = $("#sortSelect").value;
        p.order = $("#sortSelect").selectedOptions[0]?.dataset?.order || "DESC";
        if ($("#yearFilter").value) p.year = $("#yearFilter").value;
        if ($("#countryFilter").value) p.country = $("#countryFilter").value;
        if ($("#genreFilter").value) p.genre = $("#genreFilter").value;
        if ($("#ratingFilter").value) p.min_rating = $("#ratingFilter").value;
        const tags = state.activeFilters.tags || [];
        if (tags.length) p.tags = tags.join(" ");
        p.page = state.page;
        p.per_page = state.perPage;
        return p;
    }

    function updateActiveTags() {
        const tags = [];
        if ($("#yearFilter").value) tags.push({ label: `年份: ${$("#yearFilter").value}`, clear: () => { $("#yearFilter").value = ""; } });
        if ($("#countryFilter").value) tags.push({ label: `地区: ${$("#countryFilter").value}`, clear: () => { $("#countryFilter").value = ""; } });
        if ($("#genreFilter").value) tags.push({ label: `类型: ${$("#genreFilter").value}`, clear: () => { $("#genreFilter").value = ""; } });
        if ($("#ratingFilter").value) tags.push({ label: `≥ ${$("#ratingFilter").value}分`, clear: () => { $("#ratingFilter").value = ""; } });
        if (getSearchValue().trim()) tags.push({ label: `搜索: ${getSearchValue().trim()}`, clear: () => { setSearchValue(""); } });
        if (state.activeFilters.tags) {
            state.activeFilters.tags.forEach(t => {
                tags.push({ label: `#${t}`, clear: () => { state.activeFilters.tags = (state.activeFilters.tags || []).filter(x => x !== t); } });
            });
        }
        $("#activeTags").innerHTML = tags.map(t => `
            <span class="active-tag" onclick="(${t.clear.toString()})();window._loadMovies();">
                ${escHtml(t.label)} <span class="remove">✕</span>
            </span>`).join("");
    }

    async function loadMovies() {
        if (state.currentView !== "wall") return;
        // 显示加载中：spinner 在 grid 外面
        const grid = $("#movieGrid");
        grid.innerHTML = '<div class="loading-spinner" style="display:block;margin:40px auto;"></div>';

        try {
            const params = buildParams();
            params.per_page = 9999;
            const data = await API.getMovies(params);
            state.movies = data.movies;
            renderGrid(data.movies);
            $("#movieCount").textContent = data.total;
            updateActiveTags();
        } catch (e) {
            console.error("加载电影失败:", e);
            grid.innerHTML = '<div class="empty-state"><div class="icon">⚠️</div><div class="text">加载失败，请刷新</div></div>';
        }
    }

    window._loadMovies = () => loadMovies();

    window._clickTag = function (tag) {
        setSearchValue("");
        if (!state.activeFilters.tags) state.activeFilters.tags = [];
        if (!state.activeFilters.tags.includes(tag)) state.activeFilters.tags.push(tag);
        loadMovies();
    };

    // ── 事件 ──────────────────────────────────────────
    // 搜索：绑定两个输入框
    function bindSearchInput(id) {
        const el = $("#" + id);
        if (!el) return;
        el.addEventListener("input", debounce(() => { syncSearchFrom(el); loadMovies(); }, 300));
    }
    function syncSearchFrom(src) {
        const vals = {};
        ["searchInputDesktop","searchInputMobile"].forEach(id => {
            const e = $("#" + id); if (e) vals[id] = e.value;
        });
        // Sync all values
        const newVal = src.value;
        ["searchInputDesktop","searchInputMobile"].forEach(id => {
            const e = $("#" + id); if (e && e !== src) e.value = newVal;
        });
    }
    bindSearchInput("searchInputDesktop");
    bindSearchInput("searchInputMobile");
    function bindSearchClick(id) {
        const b = $("#" + id);
        if (b) b.addEventListener("click", () => loadMovies());
    }
    bindSearchClick("searchBtnDesktop");
    bindSearchClick("searchBtnMobile");

    // 移动端搜索切换 — 点击🔍聚焦搜索框
    const tsBtn = $("#btnToggleSearch");
    if (tsBtn) {
        tsBtn.addEventListener("click", () => {
            const inp = $("#searchInputMobile");
            if (inp) { inp.focus(); inp.scrollIntoView({ behavior: "smooth", block: "center" }); }
        });
    }

    $("#sortSelect").addEventListener("change", () => loadMovies());
    $("#yearFilter").addEventListener("change", () => loadMovies());
    $("#countryFilter").addEventListener("change", () => loadMovies());
    $("#genreFilter").addEventListener("change", () => loadMovies());
    $("#ratingFilter").addEventListener("change", () => loadMovies());
    $("#clearFilters").addEventListener("click", () => {
        setSearchValue("");
        $("#yearFilter").value = "";
        $("#countryFilter").value = "";
        $("#genreFilter").value = "";
        $("#ratingFilter").value = "";
        $("#sortSelect").value = "watch_time";
        state.activeFilters = {};
        state.movies = [];
        loadMovies();
    });

    // 快捷键
    document.addEventListener("keydown", function (e) {
        if (e.key === "/" && !$("#modalOverlay").classList.contains("active") && !$("#addModalOverlay").classList.contains("active")) {
            const inp = getSearchInput();
            if (inp && document.activeElement !== inp) {
                e.preventDefault();
                inp.focus();
            }
        }
    });

    // ═══════════════════════════════════════════════════════
    // 弹窗逻辑
    // ═══════════════════════════════════════════════════════

    window._openDetail = async function (id) {
        $("#modalContent").innerHTML = '<div style="padding:60px;text-align:center;color:var(--text-muted);"><div class="loading-spinner" style="display:block;margin:0 auto 16px;"></div>加载中...</div>';
        $("#modalOverlay").classList.add("active");
        document.body.style.overflow = "hidden";
        try {
            const movie = await API.getMovieDetail(id);
            renderModal(movie);
            $("#modal").scrollTop = 0;
        } catch (e) {
            $("#modalContent").innerHTML = '<div style="padding:60px;text-align:center;color:var(--red);">加载失败</div>';
        }
    };

    function valOrNA(val) {
        return val ? escHtml(String(val)) : '<span class="na">暂无</span>';
    }

    function renderModal(movie) {
        const posterUrl = movie.cover_local ? `/posters/${movie.cover_local}` : "/posters/_none_";
        const tags = movie.tags ? movie.tags.split("/").filter(Boolean).map(t => t.trim()) : [];
        const genres = movie.genre ? movie.genre.split("/").filter(Boolean).map(g => g.trim()) : [];
        const origTitle = movie.original_title && movie.original_title !== movie.title ? movie.original_title : "";

        $("#modalContent").innerHTML = `
            <div class="detail-header">
                <div class="detail-poster">
                    ${movie.cover_local
                        ? `<img src="${posterUrl}" alt="${escHtml(movie.title)}"
                              onerror="this.innerHTML='<div class=\\'poster-placeholder\\'>🎬</div>'">`
                        : `<div class="poster-placeholder">🎬</div>`}
                </div>
                <div class="detail-info">
                    <h2 class="detail-title">${escHtml(movie.title)}</h2>
                    ${origTitle ? `<div class="detail-original">${escHtml(origTitle)}</div>` : ""}
                    <div class="detail-rating">
                        <span class="stars">⭐ ${movie.douban_rating || "--"}</span>
                        <span class="rating-label">豆瓣评分</span>
                        ${movie.my_rating && parseFloat(movie.my_rating) > 0
                            ? `<span style="margin-left:12px;font-size:1.2rem;font-weight:700;color:var(--green);">★ ${movie.my_rating}</span><span class="rating-label">我的评分</span>`
                            : ""}
                    </div>
                    <div class="detail-meta-grid">
                        <div class="detail-meta-item"><span class="label">导演</span><span class="value">${valOrNA(movie.director)}</span></div>
                        <div class="detail-meta-item"><span class="label">年份</span><span class="value">${valOrNA(movie.year)}</span></div>
                        <div class="detail-meta-item"><span class="label">国家</span><span class="value">${valOrNA(movie.country)}</span></div>
                        <div class="detail-meta-item"><span class="label">片长</span><span class="value">${valOrNA(movie.duration)}</span></div>
                        <div class="detail-meta-item"><span class="label">语言</span><span class="value">${valOrNA(movie.language)}</span></div>
                        <div class="detail-meta-item"><span class="label">上映日期</span><span class="value">${valOrNA(movie.release_date)}</span></div>
                        <div class="detail-meta-item editable-field" data-field="watch_time" data-id="${movie.id}">
                            <span class="label">观看时间</span>
                            <span class="value editable-value" title="点击修改">${valOrNA(formatDate(movie.watch_time))}</span>
                        </div>
                        <div class="detail-meta-item"><span class="label">影片类型</span><span class="value">${valOrNA(movie.genre)}</span></div>
                    </div>
                    <div class="detail-tags">
                        ${tags.length ? tags.map(t => `<span class="tag" onclick="event.stopPropagation();window._clickTag('${escHtml(t)}')">${escHtml(t)}</span>`).join("") : '<span class="tag na-tag">暂无标签</span>'}
                    </div>
                    ${genres.length ? `<div class="detail-tags" style="margin-top:4px">${genres.map(g => `<span class="tag genre-tag">${escHtml(g)}</span>`).join("")}</div>` : ""}
                </div>
            </div>
            <div class="detail-section">
                <h3>📖 简介</h3>
                <div class="detail-summary">${valOrNA(movie.summary)}</div>
            </div>
            <div class="detail-section">
                <h3>👥 主演</h3>
                <div class="detail-cast">${valOrNA(movie.cast_info)}</div>
            </div>
            <div class="detail-section">
                <h3>✍️ 编剧</h3>
                <div class="detail-cast">${valOrNA(movie.writer)}</div>
            </div>
            <div class="detail-actions">
                ${hasMissingFields(movie)
                    ? `<button class="btn-enrich-movie" id="btnEnrichMovie">🪄 补全信息</button>`
                    : ""}
                <button class="btn-delete-movie" id="btnDeleteMovie">🗑️ 删除此电影</button>
            </div>
        `;

        // 绑定补全信息事件
        const enrichBtn = $("#btnEnrichMovie");
        if (enrichBtn) {
            enrichBtn.addEventListener("click", async function () {
                enrichBtn.textContent = "⏳ 正在从 TMDb/Wikipedia 获取...";
                enrichBtn.disabled = true;
                try {
                    const result = await API.enrichMovie(movie.id);
                    if (result.filled && result.filled.length > 0) {
                        const fieldNames = result.filled.map(f => ({
                            'year':'年份','douban_rating':'评分','genre':'类型','duration':'片长',
                            'original_title':'原名','summary':'简介','director':'导演',
                            'cast_info':'主演','writer':'编剧','country':'国家',
                            'language':'语言','release_date':'上映日期'
                        }[f] || f)).join('、');
                        alert(`✅ 已补全: ${fieldNames}`);
                        closeModal();
                        window._openDetail(movie.id);
                    } else {
                        alert("⚠️ 未能找到更多信息");
                    }
                } catch (e) {
                    alert("❌ 补全失败，请重试");
                    console.error(e);
                }
                enrichBtn.textContent = "🪄 补全信息";
                enrichBtn.disabled = false;
            });
        }

        // 绑定删除事件
        $("#btnDeleteMovie").addEventListener("click", function () {
            if (confirm(`确定要删除「${movie.title}」吗？\n\n此操作不可撤销。`)) {
                deleteMovieById(movie.id);
            }
        });

        // 绑定可编辑字段（观看时间）的点击编辑
        bindEditableFields();
    }

    function bindEditableFields() {
        $$("#modalContent .editable-value").forEach(el => {
            if (el.dataset.bound) return;
            el.dataset.bound = "1";
            el.addEventListener("click", makeEditable);
        });
    }

    async function makeEditable(e) {
        e.stopPropagation();
        const el = e.target;
        const fieldDiv = el.closest(".editable-field");
        const field = fieldDiv.dataset.field;
        const movieId = parseInt(fieldDiv.dataset.id);
        const current = el.textContent === "暂无" ? "" : el.textContent.trim();

        const input = document.createElement("input");
        input.type = "datetime-local";
        input.className = "inline-edit-input";
        if (current) {
            const d = new Date(current);
            if (!isNaN(d.getTime())) input.value = d.toISOString().slice(0, 16);
        }
        input.style.cssText = "width:100%;padding:4px 8px;background:var(--bg-secondary);color:var(--text-primary);border:1px solid var(--accent);border-radius:4px;font-size:0.85rem;font-family:inherit;";

        el.replaceWith(input);
        input.focus();

        const doSave = async () => {
            const newVal = input.value ? input.value.replace("T", " ") + ":00" : "";
            const displayVal = newVal
                ? new Date(newVal).toLocaleDateString("zh-CN", { year:"numeric", month:"2-digit", day:"2-digit" }) + " " + newVal.slice(11, 16)
                : "暂无";
            const span = document.createElement("span");
            span.className = "value editable-value";
            span.textContent = displayVal || "暂无";
            span.title = "点击修改";
            span.dataset.bound = "1";
            span.addEventListener("click", makeEditable);
            input.replaceWith(span);
            if (newVal) {
                try { await API.updateMovie(movieId, { [field]: newVal }); }
                catch (err) { console.error("Update failed:", err); }
            }
        };

        input.addEventListener("blur", doSave);
        input.addEventListener("keydown", function (ev) {
            if (ev.key === "Enter") { ev.preventDefault(); input.blur(); }
            if (ev.key === "Escape") {
                const span = document.createElement("span");
                span.className = "value editable-value";
                span.textContent = current || "暂无";
                span.title = "点击修改";
                span.dataset.bound = "1";
                span.addEventListener("click", makeEditable);
                input.replaceWith(span);
            }
        });
    }

    function hasMissingFields(movie) {
        const keyFields = ['director','year','country','douban_rating','genre',
                          'duration','language','release_date','cast_info','writer','summary'];
        return keyFields.some(f => !movie[f]);
    }

    function closeModal() {
        $("#modalOverlay").classList.remove("active");
        document.body.style.overflow = "";
    }

    async function deleteMovieById(id) {
        try {
            const result = await API.deleteMovie(id);
            if (result.message) {
                alert("✅ 已删除");
                closeModal();
                await loadMovies();
                await loadWallStats();
            }
        } catch (e) {
            alert("❌ 删除失败，请重试");
            console.error(e);
        }
    }

    $("#modalClose").addEventListener("click", closeModal);
    $("#modalOverlay").addEventListener("click", function (e) {
        if (e.target === $("#modalOverlay")) closeModal();
    });
    document.addEventListener("keydown", function (e) {
        if (e.key === "Escape" && ($("#modalOverlay").classList.contains("active") || $("#addModalOverlay").classList.contains("active"))) {
            closeModal();
            closeAddModal();
        }
    });

    // ═══════════════════════════════════════════════════════
    // 统计分析视图
    // ═══════════════════════════════════════════════════════

    const CHART_COLORS = [
        "rgba(232, 184, 75, 0.85)",
        "rgba(91, 155, 213, 0.85)",
        "rgba(76, 175, 147, 0.85)",
        "rgba(224, 85, 106, 0.85)",
        "rgba(160, 120, 220, 0.85)",
        "rgba(240, 150, 100, 0.85)",
        "rgba(100, 200, 200, 0.85)",
        "rgba(200, 130, 180, 0.85)",
    ];

    function chartDefaults() {
        return {
            responsive: true,
            maintainAspectRatio: false,
            plugins: {
                legend: {
                    labels: { color: "#9a9ab0", font: { size: 12 }, padding: 16 }
                }
            },
            scales: {
                x: {
                    ticks: { color: "#5c5c78", font: { size: 11 } },
                    grid: { color: "rgba(255,255,255,0.04)" }
                },
                y: {
                    ticks: { color: "#5c5c78", font: { size: 11 } },
                    grid: { color: "rgba(255,255,255,0.04)" },
                    beginAtZero: true,
                }
            }
        };
    }

    function destroyChart(key) {
        if (state.statsCharts[key]) {
            state.statsCharts[key].destroy();
            delete state.statsCharts[key];
        }
    }

    async function loadStatsView() {
        const stats = await API.getStats();
        const timeData = await API.getTimeStats({ granularity: "year" });

        // 摘要卡片
        $("#sTotal").textContent = stats.total;
        $("#sAvgRating").textContent = stats.avg_rating || "--";

        // 最多年份
        const yearLabels = timeData.labels || [];
        const yearCounts = timeData.counts || [];
        if (yearLabels.length > 0) {
            let maxIdx = 0;
            yearCounts.forEach((c, i) => { if (c > yearCounts[maxIdx]) maxIdx = i; });
            $("#sBestYear").textContent = yearLabels[maxIdx];
        } else {
            $("#sBestYear").textContent = "--";
        }

        // 月均观影
        if (yearLabels.length > 0) {
            const firstYear = yearLabels[0];
            const lastYear = yearLabels[yearLabels.length - 1];
            const yearSpan = parseInt(lastYear) - parseInt(firstYear) + 1;
            const monthly = yearSpan > 0 ? (stats.total / (yearSpan * 12)).toFixed(1) : (stats.total / 12).toFixed(1);
            $("#sAvgPerMonth").textContent = monthly;
        } else {
            $("#sAvgPerMonth").textContent = "--";
        }

        // 填充年份选择器
        const statsYear = $("#statsYearSelect");
        const currentVal = statsYear.value;
        statsYear.innerHTML = '<option value="">全部年份</option>';
        yearLabels.forEach(y => {
            statsYear.innerHTML += `<option value="${y}">${y}年</option>`;
        });
        statsYear.value = currentVal;

        // 年度柱状图
        renderYearlyChart(yearLabels, yearCounts, timeData.cumulative);

        // 月度柱状图
        await renderMonthlyChart(statsYear.value || null);

        // 累计趋势
        renderCumulativeChart(yearLabels, timeData.cumulative);

        // 星期分布
        await renderWeekdayChart();

        // 热力图
        await renderHeatmap();

        // 类型分布
        renderGenreChart(stats.genre_dist);

        // 国家分布
        renderCountryChart(stats.country_dist);

        // 年份切换 → 更新月度
        statsYear.onchange = async () => {
            await renderMonthlyChart(statsYear.value || null);
        };
    }

    function renderYearlyChart(labels, counts, cumulative) {
        destroyChart("yearly");
        const ctx = $("#chartYearly").getContext("2d");
        state.statsCharts.yearly = new Chart(ctx, {
            type: "bar",
            data: {
                labels: labels,
                datasets: [
                    {
                        label: "观影数量",
                        data: counts,
                        backgroundColor: CHART_COLORS[0],
                        borderRadius: 4,
                        order: 2,
                    },
                    {
                        label: "累计",
                        data: cumulative,
                        type: "line",
                        borderColor: CHART_COLORS[3],
                        backgroundColor: "rgba(224, 85, 106, 0.1)",
                        fill: true,
                        tension: 0.3,
                        pointRadius: 2,
                        pointHoverRadius: 5,
                        yAxisID: "y1",
                        order: 1,
                    }
                ]
            },
            options: {
                ...chartDefaults(),
                scales: {
                    ...chartDefaults().scales,
                    y: {
                        ...chartDefaults().scales.y,
                        title: { display: true, text: "部", color: "#5c5c78" },
                    },
                    y1: {
                        position: "right",
                        ticks: { color: "#5c5c78", font: { size: 11 } },
                        grid: { display: false },
                        beginAtZero: true,
                        title: { display: true, text: "累计", color: "#5c5c78" },
                    }
                },
                plugins: {
                    ...chartDefaults().plugins,
                    tooltip: {
                        callbacks: {
                            label: (ctx) => `${ctx.dataset.label}: ${ctx.raw} 部`
                        }
                    }
                }
            }
        });
    }

    async function renderMonthlyChart(year) {
        destroyChart("monthly");
        const params = { granularity: "month" };
        if (year) params.year = year;
        const data = await API.getTimeStats(params);
        const labels = data.labels || [];
        const counts = data.counts || [];

        const monthNames = ["1月","2月","3月","4月","5月","6月","7月","8月","9月","10月","11月","12月"];
        const displayLabels = labels.map(l => {
            const parts = l.split("-");
            return parts.length === 2 ? `${parts[0]}年${monthNames[parseInt(parts[1]) - 1]}` : l;
        });

        const ctx = $("#chartMonthly").getContext("2d");
        const colors = labels.map((_, i) => {
            const c = CHART_COLORS[i % CHART_COLORS.length];
            return c;
        });

        state.statsCharts.monthly = new Chart(ctx, {
            type: "bar",
            data: {
                labels: displayLabels,
                datasets: [{
                    label: year ? `${year}年月度观影` : "月度观影",
                    data: counts,
                    backgroundColor: colors,
                    borderRadius: 4,
                }]
            },
            options: {
                ...chartDefaults(),
                plugins: {
                    ...chartDefaults().plugins,
                    tooltip: {
                        callbacks: { label: (ctx) => `${ctx.raw} 部` }
                    }
                }
            }
        });
    }

    function renderCumulativeChart(labels, cumulative) {
        destroyChart("cumulative");
        const ctx = $("#chartCumulative").getContext("2d");
        state.statsCharts.cumulative = new Chart(ctx, {
            type: "line",
            data: {
                labels: labels,
                datasets: [{
                    label: "累计观影",
                    data: cumulative,
                    borderColor: CHART_COLORS[2],
                    backgroundColor: "rgba(76, 175, 147, 0.1)",
                    fill: true,
                    tension: 0.3,
                    pointRadius: 3,
                    pointHoverRadius: 6,
                    pointBackgroundColor: CHART_COLORS[2],
                }]
            },
            options: {
                ...chartDefaults(),
                plugins: {
                    ...chartDefaults().plugins,
                    tooltip: {
                        callbacks: { label: (ctx) => `累计: ${ctx.raw} 部` }
                    }
                }
            }
        });
    }

    async function renderWeekdayChart() {
        destroyChart("weekday");
        const data = await API.getTimeStats({ granularity: "day" });
        if (!data.labels || data.labels.length === 0) return;

        const weekCounts = [0, 0, 0, 0, 0, 0, 0];
        data.labels.forEach((label, i) => {
            const d = new Date(label);
            if (!isNaN(d.getTime())) {
                weekCounts[d.getDay()] += data.counts[i];
            }
        });

        const dayNames = ["周日", "周一", "周二", "周三", "周四", "周五", "周六"];
        const ctx = $("#chartWeekday").getContext("2d");
        const maxVal = Math.max(...weekCounts, 1);
        const bgColors = weekCounts.map((c, i) => {
            const alpha = 0.3 + (c / maxVal) * 0.55;
            return i === 0 || i === 6
                ? `rgba(224, 85, 106, ${alpha})`
                : `rgba(91, 155, 213, ${alpha})`;
        });

        state.statsCharts.weekday = new Chart(ctx, {
            type: "bar",
            data: {
                labels: dayNames,
                datasets: [{
                    label: "观影次数",
                    data: weekCounts,
                    backgroundColor: bgColors,
                    borderRadius: 6,
                }]
            },
            options: {
                ...chartDefaults(),
                plugins: {
                    ...chartDefaults().plugins,
                    tooltip: {
                        callbacks: { label: (ctx) => `${ctx.raw} 部` }
                    }
                }
            }
        });
    }

    async function renderHeatmap() {
        const raw = await API.getHeatmap();
        const monthNames = ["1月","2月","3月","4月","5月","6月","7月","8月","9月","10月","11月","12月"];
        const dayNames = ["周日","周一","周二","周三","周四","周五","周六"];

        // 构建热力图矩阵: [month][weekday] → count
        const matrix = {};
        raw.forEach(r => {
            const m = parseInt(r.month);
            const w = parseInt(r.weekday);
            if (!matrix[m]) matrix[m] = {};
            matrix[m][w] = r.count;
        });

        // 找最大值用于颜色映射
        let maxVal = 0;
        raw.forEach(r => { if (r.count > maxVal) maxVal = r.count; });
        if (maxVal === 0) maxVal = 1;

        function heatColor(val) {
            const t = val / maxVal;
            if (t === 0) return "rgba(255,255,255,0.04)";
            const r = Math.round(20 + t * 200);
            const g = Math.round(20 + t * 160);
            const b = Math.round(60 + t * 80);
            return `rgb(${r},${g},${b})`;
        }

        let html = '<table class="heatmap-table"><thead><tr><th></th>';
        dayNames.forEach(d => { html += `<th>${d}</th>`; });
        html += '</tr></thead><tbody>';

        for (let m = 1; m <= 12; m++) {
            html += `<tr><td style="text-align:left;padding-right:12px;color:var(--text-muted);font-size:0.78rem;">${monthNames[m-1]}</td>`;
            for (let w = 0; w <= 6; w++) {
                const val = (matrix[m] && matrix[m][w]) ? matrix[m][w] : 0;
                const bg = heatColor(val);
                const textColor = val / maxVal > 0.5 ? "#fff" : "var(--text-secondary)";
                html += `<td><span class="heatmap-cell${val === 0 ? ' zero' : ''}" style="background:${bg};color:${textColor};">${val || ''}</span></td>`;
            }
            html += '</tr>';
        }
        html += '</tbody></table>';
        $("#heatmapWrap").innerHTML = html;
    }

    function renderGenreChart(genreDist) {
        destroyChart("genre");
        // 拆分复合类型，统计每种类型
        const genreMap = {};
        genreDist.forEach(d => {
            (d.genre || "").split("/").forEach(g => {
                const gg = g.trim();
                if (gg) genreMap[gg] = (genreMap[gg] || 0) + d.c;
            });
        });
        const sorted = Object.entries(genreMap).sort((a, b) => b[1] - a[1]).slice(0, 15);
        const labels = sorted.map(e => e[0]);
        const counts = sorted.map(e => e[1]);

        const ctx = $("#chartGenre").getContext("2d");
        state.statsCharts.genre = new Chart(ctx, {
            type: "bar",
            data: {
                labels: labels,
                datasets: [{
                    label: "数量",
                    data: counts,
                    backgroundColor: labels.map((_, i) => CHART_COLORS[i % CHART_COLORS.length]),
                    borderRadius: 4,
                }]
            },
            options: {
                indexAxis: "y",
                ...chartDefaults(),
                plugins: {
                    ...chartDefaults().plugins,
                    legend: { display: false },
                    tooltip: {
                        callbacks: { label: (ctx) => `${ctx.raw} 部` }
                    }
                }
            }
        });
    }

    function renderCountryChart(countryDist) {
        destroyChart("country");
        const countryMap = {};
        countryDist.forEach(d => {
            (d.country || "").split("/").forEach(c => {
                const cc = c.trim();
                if (cc) countryMap[cc] = (countryMap[cc] || 0) + d.c;
            });
        });
        const sorted = Object.entries(countryMap).sort((a, b) => b[1] - a[1]).slice(0, 15);
        const labels = sorted.map(e => e[0]);
        const counts = sorted.map(e => e[1]);

        const ctx = $("#chartCountry").getContext("2d");
        state.statsCharts.country = new Chart(ctx, {
            type: "doughnut",
            data: {
                labels: labels,
                datasets: [{
                    data: counts,
                    backgroundColor: labels.map((_, i) => CHART_COLORS[i % CHART_COLORS.length]),
                    borderColor: "rgba(26,26,46,1)",
                    borderWidth: 2,
                }]
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                plugins: {
                    legend: {
                        position: "right",
                        labels: { color: "#9a9ab0", font: { size: 11 }, padding: 12 }
                    },
                    tooltip: {
                        callbacks: { label: (ctx) => `${ctx.label}: ${ctx.raw} 部 (${((ctx.raw / (ctx.dataset.data.reduce((a,b)=>a+b,0) || 1)) * 100).toFixed(1)}%)` }
                    }
                }
            }
        });
    }

    // ═══════════════════════════════════════════════════════
    // 添加电影
    // ═══════════════════════════════════════════════════════

    function openAddModal() {
        // 设置默认观影时间为当前
        const now = new Date();
        const local = now.toISOString().slice(0, 16);
        $("#addWatchTime").value = local;

        $("#addModalOverlay").classList.add("active");
        document.body.style.overflow = "hidden";
    }

    function closeAddModal() {
        $("#addModalOverlay").classList.remove("active");
        document.body.style.overflow = "";
        // 清空表单
        $("#addTitle").value = "";
        $("#addOriginalTitle").value = "";
        $("#addDoubanRating").value = "";
        $("#addMyRating").value = "";
        $("#addYear").value = "";
        $("#addDirector").value = "";
        $("#addCountry").value = "";
        $("#addReleaseDate").value = "";
        $("#addGenre").value = "";
        $("#addDuration").value = "";
        $("#addLanguage").value = "";
        $("#addCast").value = "";
        $("#addTags").value = "";
        $("#addSummary").value = "";
    }

    async function submitAddMovie() {
        const title = $("#addTitle").value.trim();
        if (!title) {
            alert("请输入电影名！");
            return;
        }

        const btn = $("#addSubmit");
        btn.textContent = "⏳ 正在添加并获取封面...";
        btn.disabled = true;

        const data = {
            title: title,
            original_title: $("#addOriginalTitle").value.trim(),
            douban_rating: $("#addDoubanRating").value.trim(),
            my_rating: $("#addMyRating").value.trim() || "0",
            year: $("#addYear").value.trim(),
            watch_time: $("#addWatchTime").value.replace("T", " ") + ":00",
            director: $("#addDirector").value.trim(),
            country: $("#addCountry").value.trim(),
            release_date: $("#addReleaseDate").value.trim(),
            genre: $("#addGenre").value.trim(),
            duration: $("#addDuration").value.trim(),
            language: $("#addLanguage").value.trim(),
            cast_info: $("#addCast").value.trim(),
            tags: $("#addTags").value.trim(),
            summary: $("#addSummary").value.trim(),
        };

        try {
            const result = await API.addMovie(data);
            if (result.id) {
                alert(`✅ "${title}" 添加成功！封面正在自动获取中...`);
                closeAddModal();
                // 刷新列表
                await loadMovies();
                await loadStatsViewIfActive();
            } else {
                alert("❌ 添加失败: " + (result.error || "未知错误"));
            }
        } catch (e) {
            alert("❌ 添加失败，请检查网络连接");
            console.error(e);
        } finally {
            btn.textContent = "✨ 添加并自动获取封面";
            btn.disabled = false;
        }
    }

    async function loadStatsViewIfActive() {
        if (state.currentView === "stats") {
            await loadStatsView();
        }
    }

    $("#btnAddMovie").addEventListener("click", openAddModal);
    $("#addCancel").addEventListener("click", closeAddModal);
    $("#addModalClose").addEventListener("click", closeAddModal);
    $("#addModalOverlay").addEventListener("click", function (e) {
        if (e.target === $("#addModalOverlay")) closeAddModal();
    });
    $("#addSubmit").addEventListener("click", submitAddMovie);

    // 添加弹窗键盘支持
    document.addEventListener("keydown", function (e) {
        if (e.key === "Escape" && $("#addModalOverlay").classList.contains("active")) {
            closeAddModal();
        }
        // Ctrl+Enter 提交
        if (e.key === "Enter" && (e.ctrlKey || e.metaKey) && $("#addModalOverlay").classList.contains("active")) {
            e.preventDefault();
            submitAddMovie();
        }
    });

    // ═══════════════════════════════════════════════════════
    // 启动
    // ═══════════════════════════════════════════════════════

    async function loadFilters() {
        try {
            const data = await API.getFilters();
            function fillSelect(sel, items, label) {
                const current = sel.value;
                sel.innerHTML = `<option value="">${label || "全部"}</option>`;
                items.forEach(item => { sel.innerHTML += `<option value="${escHtml(String(item))}">${escHtml(String(item))}</option>`; });
                sel.value = current;
            }
            fillSelect($("#yearFilter"), data.years, "全部年份");
            fillSelect($("#countryFilter"), data.countries, "全部地区");
            fillSelect($("#genreFilter"), data.genres, "全部类型");
            state.allTags = data.tags;
        } catch (e) {
            console.error("加载筛选选项失败:", e);
        }
    }

    async function loadWallStats() {
        try {
            const stats = await API.getStats();
            $("#statTotal").textContent = stats.total;
            $("#statAvg").textContent = stats.avg_rating || "--";
            const years = stats.year_dist.map(d => d.year).filter(Boolean).sort();
            if (years.length >= 2) {
                $("#statYear").textContent = `${years[years.length - 1]} - ${years[0]}`;
            } else if (years.length === 1) {
                $("#statYear").textContent = years[0];
            } else {
                $("#statYear").textContent = "--";
            }
            const countries = new Set();
            stats.country_dist.forEach(d => {
                (d.country || "").split("/").forEach(c => { const cc = c.trim(); if (cc) countries.add(cc); });
            });
            $("#statCountry").textContent = countries.size || "--";
        } catch (e) {
            console.error("加载统计失败:", e);
        }
    }

    async function init() {
        loadWallStats();
        loadFilters();
        loadMovies();
    }

    if (document.readyState === "loading") {
        document.addEventListener("DOMContentLoaded", init);
    } else {
        init();
    }
})();
