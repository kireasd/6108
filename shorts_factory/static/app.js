const $ = (s) => document.querySelector(s);
let settings = null;

const STATUS = { queued: '대기', running: '작업 중', done: '완료', error: '실패', canceled: '취소' };

function esc(t) { const d = document.createElement('div'); d.textContent = t ?? ''; return d.innerHTML; }

document.querySelectorAll('.tab').forEach((b) => b.addEventListener('click', () => {
  document.querySelectorAll('.tab').forEach((x) => x.classList.toggle('active', x === b));
  document.querySelectorAll('.panel').forEach((p) => p.classList.toggle('active', p.id === 'tab-' + b.dataset.tab));
}));

async function loadSettings() {
  settings = await (await fetch('/api/settings')).json();
  $('#channelSelect').innerHTML = settings.channels.map((c) => `<option value="${esc(c.id)}">${esc(c.name)}</option>`).join('');
  $('#model').value = settings.model;
  $('#fontFile').value = settings.font_file;
  $('#keyState').textContent = settings.has_api_key
    ? '✅ API 키가 연결되어 있습니다. 제목·자막을 AI가 자동으로 만듭니다.'
    : '⚠️ API 키가 없습니다. AI 각색 없이 원본 자막과 직접 입력한 제목으로 만듭니다.';
  $('#fontState').textContent = settings.detected_font ? '사용 중인 폰트: ' + settings.detected_font : '⚠️ 한글 폰트를 찾지 못했습니다.';
  $('#hint').textContent = settings.has_api_key ? '' : 'AI 자동 각색을 쓰려면 설정 탭에서 API 키를 넣어주세요.';
  renderChannels();
}

function renderChannels() {
  const list = $('#channelList');
  list.innerHTML = '';
  settings.channels.forEach((c) => addChannelCard(c));
}

function addChannelCard(c) {
  const node = $('#channelTpl').content.firstElementChild.cloneNode(true);
  node.dataset.id = c.id || '';
  node.querySelectorAll('[data-k]').forEach((el) => {
    const v = c[el.dataset.k];
    if (el.type === 'checkbox') el.checked = !!v; else el.value = v ?? '';
  });
  node.querySelector('.del').onclick = () => node.remove();
  $('#channelList').appendChild(node);
}

$('#addChannel').onclick = () => addChannelCard({ ...settings.channels[0], id: '', name: '새 채널', watermark: '' });

$('#saveChannels').onclick = async () => {
  const channels = [...document.querySelectorAll('#channelList .channel')].map((node) => {
    const c = { id: node.dataset.id };
    node.querySelectorAll('[data-k]').forEach((el) => { c[el.dataset.k] = el.type === 'checkbox' ? el.checked : el.value; });
    return c;
  });
  await fetch('/api/settings', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ channels }) });
  await loadSettings();
  alert('채널 프리셋을 저장했습니다.');
};

$('#saveSettings').onclick = async () => {
  await fetch('/api/settings', { method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ anthropic_api_key: $('#apiKey').value, model: $('#model').value, font_file: $('#fontFile').value }) });
  $('#apiKey').value = '';
  await loadSettings();
  alert('설정을 저장했습니다.');
};

$('#clearKey').onclick = async () => {
  await fetch('/api/settings', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ clear_api_key: true }) });
  await loadSettings();
};

$('#goBtn').onclick = async () => {
  const fd = new FormData();
  fd.append('urls', $('#urls').value);
  fd.append('channel_id', $('#channelSelect').value);
  fd.append('title', $('#title').value);
  fd.append('highlight', $('#highlight').value);
  fd.append('start', $('#start').value);
  for (const f of $('#files').files) fd.append('files', f);
  $('#goBtn').disabled = true;
  try {
    const res = await fetch('/api/jobs', { method: 'POST', body: fd });
    const data = await res.json();
    if (!res.ok) { alert(data.error); return; }
    $('#urls').value = ''; $('#files').value = '';
    refreshJobs();
  } finally { $('#goBtn').disabled = false; }
};

$('#openOut').onclick = async () => {
  const r = await (await fetch('/api/open-output', { method: 'POST' })).json();
  $('#hint').textContent = '출력 폴더: ' + r.path;
};

let lastSig = '';
async function refreshJobs() {
  const jobs = await (await fetch('/api/jobs')).json();
  // 변경이 있을 때만 다시 그려서 재생 중인 영상이 끊기지 않게 한다
  const sig = JSON.stringify(jobs.map((j) => [j.id, j.status, j.logs.length]));
  if (sig === lastSig) return;
  lastSig = sig;
  const box = $('#jobs');
  if (!jobs.length) { box.innerHTML = '<p class="empty">아직 작업이 없습니다.</p>'; return; }
  box.innerHTML = jobs.map((j) => `
    <div class="job">
      <div>
        <div class="src">${esc(j.result ? j.result.title.join(' ') : j.source)}</div>
        <div class="meta">${esc(j.channel)} · ${esc(j.source)}${j.result ? ' · ' + j.result.duration + '초' : ''}</div>
      </div>
      <span class="badge ${j.status}">${STATUS[j.status] || j.status}</span>
      <pre>${esc(j.logs.slice(-6).join('\n'))}</pre>
      ${j.status === 'done' ? `<video src="/api/jobs/${j.id}/video" controls preload="metadata"></video>` : ''}
      <div class="actions">
        ${j.status === 'done' ? `<a class="ghost" href="/api/jobs/${j.id}/video" download>다운로드</a>` : ''}
        ${j.status !== 'running' ? `<button class="ghost" onclick="removeJob('${j.id}')">${j.status === 'queued' ? '취소' : '목록에서 지우기'}</button>` : ''}
      </div>
    </div>`).join('');
}

async function removeJob(id) { await fetch('/api/jobs/' + id, { method: 'DELETE' }); refreshJobs(); }

loadSettings();
refreshJobs();
setInterval(refreshJobs, 2000);
