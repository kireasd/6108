// 쇼츠 자동 제작기 화면 동작. 실제 작업은 파이썬(app.py의 Api)이 하고,
// 진행 상황은 파이썬이 window.onJob(...)을 불러서 알려준다.

const $ = (sel) => document.querySelector(sel);
let api = null;
let state = null;
const picked = { find: null, clips: null };
let topicKeywords = [];
let running = false;

// 화면 요소를 안전하게 만든다 (유튜브 제목 같은 글자를 그대로 글자로만 넣음)
function el(tag, attrs = {}, ...children) {
  const node = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (k === "class") node.className = v;
    else if (k === "onclick") node.addEventListener("click", v);
    else node.setAttribute(k, v);
  }
  for (const c of children.flat()) {
    if (c === null || c === undefined || c === false) continue;
    node.append(c instanceof Node ? c : document.createTextNode(String(c)));
  }
  return node;
}

function baseName(path) {
  return path ? path.split(/[\\/]/).pop() : "";
}

function timeText(sec) {
  sec = Math.max(0, Math.round(sec || 0));
  const h = Math.floor(sec / 3600), m = Math.floor((sec % 3600) / 60), s = sec % 60;
  const mm = h ? String(m).padStart(2, "0") : m;
  return (h ? h + ":" : "") + mm + ":" + String(s).padStart(2, "0");
}

let toastTimer = null;
function toast(msg) {
  const t = $("#toast");
  t.textContent = msg;
  t.classList.remove("hidden");
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => t.classList.add("hidden"), 3500);
}

function setStatus(msg, frac = null, isError = false) {
  $("#statusMsg").textContent = msg;
  $(".statusbar").classList.toggle("error", isError);
  if (frac !== null) $("#progressBar").style.width = Math.round(frac * 100) + "%";
}

// ---------- 페이지 이동 ----------
function showPage(name) {
  document.querySelectorAll(".nav-item").forEach((b) => b.classList.toggle("active", b.dataset.page === name));
  document.querySelectorAll(".page").forEach((p) => p.classList.toggle("active", p.id === "page-" + name));
  if (name === "library") loadLibrary();
}

// ---------- 상태(왼쪽 아래 AI 표시, 설정 칸) ----------
function renderState(s) {
  state = s;
  $("#version").textContent = "버전 " + s.version;
  const pill = $("#aiPill");
  pill.classList.toggle("ok", s.ai.ok);
  pill.classList.toggle("no", !s.ai.ok);
  $("#aiName").textContent = s.providers[s.settings.provider] || "-";
  $("#aiMsg").textContent = s.ai.msg;

  const grid = $("#providerGrid");
  grid.replaceChildren();
  const desc = { local: "사용료 0원 · 내 컴퓨터에서 실행", claude: "글을 자연스럽게 잘 써요",
                 openai: "가장 널리 쓰여요", gemini: "구글 계정으로 시작" };
  for (const [key, label] of Object.entries(s.providers)) {
    grid.append(el("button", {
      class: "provider" + (key === s.settings.provider ? " active" : ""),
      onclick: async () => renderState(await api.set_provider(key)),
    }, label, el("small", {}, desc[key] || "")));
  }

  $("#webHint").textContent = s.settings.vision_key
    ? "💳 인터넷 전체 이미지 검색 켜짐 (장면마다 자동 검색)"
    : "🆓 장면마다 구글 렌즈 버튼으로 찾을 수 있어요 (설정에서 자동 검색 켜기 가능)";
  const voice = $("#voiceSelect");
  if (!voice.options.length) {
    for (const [label, code] of Object.entries(s.voices)) voice.append(el("option", { value: code }, label));
  }
  document.querySelectorAll("[data-key]").forEach((input) => {
    if (document.activeElement !== input) input.value = s.settings[input.dataset.key] ?? "";
  });
}

async function refreshState() {
  renderState(await api.get_state());
}

// ---------- 작업 시작 / 진행 ----------
async function startJob(kind, params, startMsg) {
  const res = await api.start_job(kind, params);
  if (!res.ok) {
    toast(res.msg);
    return false;
  }
  setStatus(startMsg, 0.01);
  setBusy(true);
  return true;
}

function setBusy(busy) {
  running = busy;
  document.querySelectorAll("[data-job]").forEach((b) => (b.disabled = busy || b.dataset.needs === "file" && !b.dataset.ready));
}

window.onJob = (ev) => {
  if (ev.type === "progress") {
    setStatus(ev.msg, ev.frac);
    return;
  }
  setBusy(false);
  if (ev.type === "error") {
    setStatus("문제가 생겼어요: " + ev.msg, 0, true);
    toast(ev.msg);
    return;
  }
  setStatus("완료!", 1);
  const handlers = { find: showFindResult, download: onDownloaded, script: onScript, topic: onTopicVideo, clips: onClips };
  handlers[ev.kind]?.(ev.result);
};

// ---------- 🔍 원본 찾기 ----------
let findMode = "file";

function findSource() {
  return findMode === "file" ? picked.find : $("#findLink").value.trim();
}

function updateFindStart() {
  const src = findSource();
  const ok = findMode === "file" ? !!src : /^https?:\/\/\S+$/i.test(src);
  const btn = $("#findStart");
  btn.dataset.ready = ok ? "1" : "";
  btn.disabled = !ok || running;
}

function showTab(name) {
  document.querySelectorAll(".tab").forEach((t) => t.classList.toggle("active", t.dataset.tab === name));
  document.querySelectorAll(".tab-body").forEach((b) => b.classList.toggle("hidden", b.id !== "tab-" + name));
}

function searchLinks(q) {
  const e = encodeURIComponent(q);
  return [
    ["유튜브", `https://www.youtube.com/results?search_query=${e}`],
    ["틱톡", `https://www.tiktok.com/search?q=${e}`],
    ["인스타", `https://www.instagram.com/explore/search/keyword/?q=${e}`],
    ["구글 영상", `https://www.google.com/search?tbm=vid&q=${e}`],
  ];
}

function showFindResult(r) {
  const a = r.analysis || {};
  $("#findResult").classList.remove("hidden");
  $("#anaInput").textContent = r.input?.title ? "· " + r.input.title : "";
  $("#anaSummary").textContent = a.summary || "(분석 내용 없음)";
  const kv = $("#anaKv");
  kv.replaceChildren();
  const rows = [
    ["원본 종류", a.source_type], ["원본 추정", a.guess_title],
    ["인물", (a.people || []).join(", ")], ["화면 글자", (a.on_screen_text || []).join(" / ")],
    ["영상 대사", (r.speech || "").slice(0, 200)], ["영상 길이", timeText(r.duration)],
    ["장면 수", `${r.scenes.length}개`],
  ];
  for (const [k, v] of rows) if (v) kv.append(el("dt", {}, k), el("dd", {}, v));
  $("#anaQueries").replaceChildren(...(a.queries || []).map((q) => el("span", { class: "chip" }, "🔎 " + q)));

  renderScenes(r);
  renderCands(r.candidates);
  renderSimilar(r);
  $("#cntScenes").textContent = r.scenes.length;
  $("#cntCands").textContent = r.candidates.length;
  $("#cntSimilar").textContent = r.similar.length;
  showTab(r.candidates.some((c) => c.score >= 60) ? "cands" : "scenes");
}

// 장면별 확인: 장면 사진 + 구글 렌즈 버튼 + (유료) 자동 검색 결과 + 유튜브에서 맞은 원본
function renderScenes(r) {
  const found = {};  // 장면 번호 → [원본 후보 제목, 원본 시각]
  for (const c of r.candidates) {
    for (const [si, t] of Object.entries(c.scenes || {})) if (!found[si]) found[si] = [c, t];
  }
  const grid = $("#sceneGrid");
  grid.replaceChildren();
  for (const s of r.scenes) {
    const hit = found[s.index];
    const web = s.web;
    grid.append(el("div", { class: "scene" },
      el("img", { src: s.image, alt: "" }),
      el("div", { class: "scene-body" },
        el("div", { class: "scene-time" }, `장면 ${s.index + 1} · ${timeText(s.start)} ~ ${timeText(s.end)}`),
        hit ? el("div", { class: "scene-found", title: hit[0].title }, `🎯 원본 ${timeText(hit[1])} · ${hit[0].title}`) : null,
        el("div", { class: "scene-actions" },
          el("button", { class: "btn", onclick: () => lens(s.frame, "google") }, "구글 렌즈"),
          el("button", { class: "btn", onclick: () => lens(s.frame, "bing") }, "빙"),
          el("button", { class: "btn", title: "장면 사진 파일 보기", onclick: () => api.open_folder_of(s.frame) }, "📁"),
        ),
        web ? webResults(web) : null,
      ),
    ));
  }
}

function webResults(web) {
  if (web.error) return el("div", { class: "web-results" }, el("div", { class: "web-empty" }, "⚠️ " + web.error));
  if (!web.pages.length) return el("div", { class: "web-results" }, el("div", { class: "web-empty" }, "인터넷에서 같은 장면을 못 찾았어요"));
  return el("div", { class: "web-results" },
    ...web.pages.slice(0, 5).map((p) =>
      el("button", { class: "web-link", title: p.url, onclick: () => api.open_url(p.url) },
        el("b", {}, p.platform), p.title || p.url)));
}

async function lens(path, engine) {
  const copied = await api.image_search(path, engine);
  toast(copied ? "장면 사진을 복사했어요. 열린 검색창에서 Ctrl+V를 누르세요."
               : "검색창을 열었어요. 📁 버튼으로 장면 사진을 찾아 검색창에 끌어다 놓으세요.");
}

function renderCands(cands) {
  const list = $("#candList");
  list.replaceChildren();
  if (!cands.length) list.append(el("div", { class: "empty" }, "유튜브에서 원본 후보를 찾지 못했어요. 장면별 확인에서 구글 렌즈로 찾아보세요."));
  cands.forEach((c, i) => list.append(candCard(c, i)));
}

function candCard(c, i) {
  const level = c.score >= 60 ? "high" : c.score >= 30 ? "mid" : "";
  const label = c.score >= 60 ? "원본 확실" : c.score >= 30 ? "원본 가능성" : c.deep !== undefined ? "다른 영상" : "썸네일만 비교";
  const startUrl = c.url + (c.start !== undefined ? `&t=${c.start}s` : "");
  const sceneNums = Object.keys(c.scenes || {}).map((n) => Number(n) + 1);
  return el("div", { class: "cand" + (i === 0 && c.score >= 60 ? " top" : "") },
    el("img", { class: "thumb", src: c.thumb, alt: "" }),
    el("div", { class: "cand-body" },
      el("div", { class: "cand-title", title: c.title }, c.title || "(제목 없음)"),
      el("div", { class: "cand-meta" },
        [c.channel, c.duration ? timeText(c.duration) : null, c.views ? `조회수 ${c.views.toLocaleString()}회` : null]
          .filter(Boolean).join(" · ")),
      c.start !== undefined
        ? el("div", { class: "cand-pos" }, `📍 원본의 ${timeText(c.start)} ~ ${timeText(c.end)} 부분`)
        : null,
      sceneNums.length ? el("div", { class: "cand-scenes" }, `맞은 장면: ${sceneNums.join(", ")}번`) : null,
      c.proofs?.length
        ? el("div", { class: "proofs" }, ...c.proofs.map((p) => el("div", { class: "proof" },
            el("figure", {}, el("img", { src: p.mine, alt: "" }), el("figcaption", {}, `내 장면 ${p.scene + 1}`)),
            el("figure", {}, el("img", { src: p.orig, alt: "" }), el("figcaption", {}, `원본 ${timeText(p.time)}`)))))
        : null,
      c.note ? el("div", { class: "cand-note" }, c.note) : null,
      el("div", { class: "cand-actions" },
        el("button", { class: "btn small", onclick: () => api.open_url(startUrl) }, "▶ 유튜브에서 보기"),
        downloadButtons(c.url),
      ),
    ),
    el("div", { class: "score " + level }, el("b", {}, c.score + "%"), el("span", {}, label)),
  );
}

function downloadButtons(url, makeLabel = "✂️ 받아서 쇼츠 만들기") {
  return [
    el("button", { class: "btn small", "data-job": "1",
      onclick: () => startJob("download", { url }, "영상 받는 중...") }, "⬇ 받기"),
    el("button", { class: "btn small primary", "data-job": "1",
      onclick: () => startJob("download", { url, then: "clips" }, "영상 받는 중...") }, makeLabel),
  ];
}

function renderSimilar(r) {
  const a = r.analysis || {};
  $("#trendText").textContent = a.trend || "AI가 컨셉을 정리하지 못했어요.";
  const qs = a.similar_queries || [];
  const links = $("#trendLinks");
  links.replaceChildren();
  if (qs.length) {
    const q = qs[0];
    links.append(el("span", { class: "chip" }, `"${q}" 바로 검색:`));
    for (const [name, url] of searchLinks(q)) {
      links.append(el("span", { class: "chip link", onclick: () => api.open_url(url) }, name + " ↗"));
    }
    for (const other of qs.slice(1)) {
      links.append(el("span", { class: "chip link", title: "유튜브에서 검색",
        onclick: () => api.open_url(searchLinks(other)[0][1]) }, "🔎 " + other));
    }
  }
  const grid = $("#similarGrid");
  grid.replaceChildren();
  if (!r.similar.length) grid.append(el("div", { class: "empty" }, "비슷한 영상을 찾지 못했어요. 위 검색 버튼으로 찾아보세요."));
  for (const v of r.similar) {
    grid.append(el("div", { class: "sim" },
      el("img", { src: v.thumb, alt: "" }),
      el("div", { class: "sim-body" },
        el("div", { class: "sim-title", title: v.title }, v.title),
        el("div", { class: "cand-meta" },
          [v.channel, v.duration ? timeText(v.duration) : null, v.views ? `조회수 ${v.views.toLocaleString()}회` : null]
            .filter(Boolean).join(" · ")),
        el("div", { class: "scene-actions" },
          el("button", { class: "btn small", onclick: () => api.open_url(v.url) }, "▶ 보기"),
          ...downloadButtons(v.url, "✂️ 쇼츠로"),
        ),
      ),
    ));
  }
}

function onDownloaded(r) {
  toast("원본을 받았어요: " + baseName(r.path));
  if (r.then === "clips") {
    setPicked("clips", r.path);
    showPage("clips");
  } else {
    setStatus("원본을 받았어요: " + r.path, 1);
  }
}

// ---------- ✍️ 주제로 만들기 ----------
function onScript(r) {
  $("#topicTitle").value = r.title;
  $("#topicScript").value = r.lines.join("\n");
  topicKeywords = r.keywords || [];
}

function resultRow(path, extra) {
  return el("div", { class: "result" },
    el("span", { class: "tag" }, "완성"),
    el("div", { class: "result-name" }, baseName(path), extra ? el("div", { class: "result-meta" }, extra) : null),
    el("button", { class: "btn small", onclick: () => api.open_path(path) }, "▶ 재생"),
    el("button", { class: "btn small", onclick: () => api.open_folder_of(path) }, "📁 폴더에서 보기"),
  );
}

function onTopicVideo(r) {
  $("#topicResult").replaceChildren(resultRow(r.path));
}

// ---------- ✂️ 긴 영상 자르기 ----------
function setPicked(kind, path) {
  picked[kind] = path;
  const name = $("#" + kind + "File");
  name.textContent = path ? baseName(path) : "선택한 영상이 없어요";
  name.title = path || "";
  name.classList.toggle("has", !!path);
  if (kind === "find") return updateFindStart();
  const btn = $("#clipsStart");
  btn.dataset.ready = path ? "1" : "";
  btn.disabled = !path || running;
}

function onClips(r) {
  const notes = (r.notes || "").split("\n");
  $("#clipsResult").replaceChildren(...r.paths.map((p, i) => resultRow(p, notes[i])));
}

// ---------- 🎞️ 만든 영상 ----------
async function loadLibrary() {
  const items = await api.list_library();
  const list = $("#libList");
  list.replaceChildren();
  if (!items.length) {
    list.append(el("div", { class: "empty" }, "아직 만든 영상이 없어요."));
    return;
  }
  for (const it of items) {
    list.append(el("div", { class: "result" },
      el("span", { class: "tag" + (it.kind === "원본" ? " src" : "") }, it.kind),
      el("div", { class: "result-name", title: it.path }, it.name,
        el("div", { class: "result-meta" }, `${it.date} · ${it.size}MB`)),
      el("button", { class: "btn small", onclick: () => api.open_path(it.path) }, "▶ 재생"),
      el("button", { class: "btn small", onclick: () => api.open_folder_of(it.path) }, "📁 폴더에서 보기"),
      it.kind === "원본"
        ? el("button", { class: "btn small primary", onclick: () => { setPicked("clips", it.path); showPage("clips"); } },
            "✂️ 쇼츠 만들기")
        : null,
    ));
  }
}

// ---------- 버튼 연결 ----------
function bind() {
  document.querySelectorAll(".nav-item").forEach((b) => b.addEventListener("click", () => showPage(b.dataset.page)));
  $("#btnOpenOutput").addEventListener("click", () => api.open_output());
  $("#libRefresh").addEventListener("click", loadLibrary);

  for (const kind of ["find", "clips"]) {
    $("#" + kind + "Pick").addEventListener("click", async () => {
      const path = await api.pick_video();
      if (path) setPicked(kind, path);
    });
  }
  const findStart = $("#findStart");
  findStart.dataset.job = "1";
  findStart.dataset.needs = "file";
  findStart.addEventListener("click", () => {
    $("#findResult").classList.add("hidden");
    startJob("find", { source: findSource() }, "원본 찾기를 시작했어요...");
  });
  document.querySelectorAll(".input-tab").forEach((t) => t.addEventListener("click", () => {
    findMode = t.dataset.input;
    document.querySelectorAll(".input-tab").forEach((x) => x.classList.toggle("active", x === t));
    $("#inputFile").classList.toggle("hidden", findMode !== "file");
    $("#inputLink").classList.toggle("hidden", findMode !== "link");
    updateFindStart();
  }));
  $("#findLink").addEventListener("input", updateFindStart);
  document.querySelectorAll(".tab").forEach((t) => t.addEventListener("click", () => showTab(t.dataset.tab)));

  const clipsStart = $("#clipsStart");
  clipsStart.dataset.job = "1";
  clipsStart.dataset.needs = "file";
  clipsStart.addEventListener("click", () =>
    startJob("clips", { path: picked.clips, count: $("#clipsCount").value }, "긴 영상 분석을 시작했어요..."));

  const scriptBtn = $("#topicScriptBtn");
  scriptBtn.dataset.job = "1";
  scriptBtn.addEventListener("click", () => {
    const topic = $("#topicInput").value.trim();
    if (!topic) return toast("주제를 먼저 적어 주세요.");
    startJob("script", { topic, seconds: $("#topicSeconds").value }, "AI가 대본 쓰는 중...");
  });

  const makeBtn = $("#topicMakeBtn");
  makeBtn.dataset.job = "1";
  makeBtn.addEventListener("click", () => {
    const lines = $("#topicScript").value.split("\n").map((l) => l.trim()).filter(Boolean);
    if (!lines.length) return toast("대본이 비어 있어요. 먼저 '대본 만들기'를 눌러 주세요.");
    startJob("topic", { title: $("#topicTitle").value, lines, keywords: topicKeywords }, "영상 만드는 중...");
  });

  $("#pickOutput").addEventListener("click", async () => {
    const folder = await api.pick_folder();
    if (folder) document.querySelector('[data-key="output_dir"]').value = folder;
  });
  $("#saveSettings").addEventListener("click", async () => {
    const data = {};
    document.querySelectorAll("[data-key]").forEach((i) => (data[i.dataset.key] = i.value));
    renderState(await api.save_settings(data));
    toast("설정을 저장했어요.");
  });
}

window.addEventListener("pywebviewready", async () => {
  api = window.pywebview.api;
  bind();
  await refreshState();
});
