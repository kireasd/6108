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
function showFindResult(r) {
  const a = r.analysis || {};
  $("#findResult").classList.remove("hidden");
  $("#anaSummary").textContent = a.summary || "(분석 내용 없음)";
  const kv = $("#anaKv");
  kv.replaceChildren();
  const rows = [
    ["원본 종류", a.source_type], ["원본 추정", a.guess_title],
    ["인물", (a.people || []).join(", ")], ["화면 글자", (a.on_screen_text || []).join(" / ")],
    ["쇼츠 대사", (r.speech || "").slice(0, 200)], ["쇼츠 길이", timeText(r.duration)],
  ];
  for (const [k, v] of rows) if (v) kv.append(el("dt", {}, k), el("dd", {}, v));
  $("#anaQueries").replaceChildren(...(a.queries || []).map((q) => el("span", { class: "chip" }, "🔎 " + q)));

  const list = $("#candList");
  list.replaceChildren();
  $("#candCount").textContent = `${r.candidates.length}개`;
  if (!r.candidates.length) list.append(el("div", { class: "empty" }, "후보를 찾지 못했어요."));
  r.candidates.forEach((c, i) => list.append(candCard(c, i)));
}

function candCard(c, i) {
  const level = c.score >= 60 ? "high" : c.score >= 30 ? "mid" : "";
  const label = c.score >= 60 ? "원본 확실" : c.score >= 30 ? "원본 가능성" : c.deep !== undefined ? "다른 영상" : "썸네일만 비교";
  const startUrl = c.url + (c.start !== undefined ? `&t=${c.start}s` : "");
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
      c.note ? el("div", { class: "cand-note" }, c.note) : null,
      el("div", { class: "cand-actions" },
        el("button", { class: "btn small", onclick: () => api.open_url(startUrl) }, "▶ 유튜브에서 보기"),
        el("button", { class: "btn small", "data-job": "1",
          onclick: () => startJob("download", { url: c.url }, "원본 영상 받는 중...") }, "⬇ 원본 받기"),
        el("button", { class: "btn small primary", "data-job": "1",
          onclick: () => startJob("download", { url: c.url, then: "clips" }, "원본 영상 받는 중...") },
          "✂️ 받아서 쇼츠 만들기"),
      ),
    ),
    el("div", { class: "score " + level }, el("b", {}, c.score + "%"), el("span", {}, label)),
  );
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
  const btn = $(kind === "find" ? "#findStart" : "#clipsStart");
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
    startJob("find", { path: picked.find }, "원본 찾기를 시작했어요...");
  });

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
