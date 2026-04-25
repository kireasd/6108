let appData = { folders: [], channels: [] };
let currentPlatform = 'all';
let currentFolderId = 'all';
let selectedAvatar = '';

document.addEventListener('DOMContentLoaded', async () => {
    await refreshData();
    
    // 버튼 이벤트
    document.getElementById('addChannelBtn').onclick = () => document.getElementById('modalOverlay').style.display = 'flex';
    document.getElementById('submitBtn').onclick = saveChannel;
    document.getElementById('addFolderBtn').onclick = addFolder;
    document.getElementById('resetAllBtn').onclick = resetAllData;
    
    // 플랫폼 탭
    document.querySelectorAll('.tab-btn, .tab-icon-btn').forEach(btn => {
        btn.onclick = () => {
            document.querySelectorAll('.tab-btn, .tab-icon-btn').forEach(b => b.classList.remove('active'));
            btn.classList.add('active');
            currentPlatform = btn.dataset.platform;
            renderChannels();
        };
    });

    document.getElementById('searchInput').oninput = (e) => renderChannels(e.target.value);
});

async function refreshData() {
    const data = await eel.load_data()();
    if (data) appData = data;
    renderFolders();
    renderChannels();
}

function renderFolders() {
    const list = document.getElementById('folderList');
    list.innerHTML = '';
    
    // 상위탭: 전체보기
    const totalCount = appData.channels.length;
    const allTab = document.createElement('li');
    allTab.className = `folder-item parent ${currentFolderId === 'all' ? 'active' : ''}`;
    allTab.onclick = () => filterFolder('all');
    allTab.innerHTML = `<span class="folder-name"># 전체보기 (${totalCount})</span>`;
    list.appendChild(allTab);

    // 하위탭: 사용자 폴더들
    appData.folders.forEach(f => {
        const count = appData.channels.filter(c => c.folderId === f.id).length;
        const item = document.createElement('li');
        item.className = `folder-item child ${currentFolderId === f.id ? 'active' : ''}`;
        item.onclick = () => filterFolder(f.id);
        item.innerHTML = `
            <span class="folder-name"># ${f.name} (${count})</span>
            <div class="folder-actions">
                <i class="fas fa-pencil-alt" title="수정" onclick="event.stopPropagation(); editFolder('${f.id}')"></i>
                <i class="fas fa-trash-alt" title="삭제" onclick="event.stopPropagation(); deleteFolder('${f.id}')"></i>
            </div>
        `;
        list.appendChild(item);
    });
}

function renderChannels(keyword = '') {
    const grid = document.getElementById('channelGrid');
    grid.innerHTML = '';
    const filtered = appData.channels.filter(c => {
        const matchPlatform = (currentPlatform === 'all' || c.platform === currentPlatform);
        const matchFolder = (currentFolderId === 'all' || c.folderId === currentFolderId);
        return matchPlatform && matchFolder && c.name.toLowerCase().includes(keyword.toLowerCase());
    });

    filtered.forEach(c => {
        const card = document.createElement('div');
        card.className = 'channel-card';
        card.innerHTML = `
            <img src="${c.thumbnail || 'https://via.placeholder.com/60'}" class="avatar">
            <div class="info-container">
                <div class="name-row">
                    <i class="fab fa-${c.platform.toLowerCase()}" style="color:red;"></i>
                    <span>${c.name}</span>
                </div>
                <div class="stats-row">
                    <span class="sub-count">${c.subscribers}</span>
                    <span class="time-tag">최근 갱신</span>
                </div>
            </div>
            <div class="memo-area"><span>${c.memo || ''}</span></div>
            <div class="card-actions">
                <i class="far fa-edit"></i>
                <i class="far fa-trash-alt" onclick="deleteChannel(${c.id})"></i>
            </div>
        `;
        grid.appendChild(card);
    });
}

async function addFolder() {
    const name = prompt("새 폴 por 이름을 입력하세요:");
    if (name) {
        appData.folders.push({ id: 'f_' + Date.now(), name: name });
        await eel.save_data(appData)();
        renderFolders();
    }
}

async function editFolder(id) {
    const folder = appData.folders.find(f => f.id === id);
    const newName = prompt("수정할 폴더 이름을 입력하세요:", folder.name);
    if (newName && newName !== folder.name) {
        folder.name = newName;
        await eel.save_data(appData)();
        renderFolders();
    }
}

async function deleteFolder(id) {
    if (confirm("폴더를 삭제하시겠습니까? (채널은 유지됩니다)")) {
        appData.folders = appData.folders.filter(f => f.id !== id);
        appData.channels.forEach(c => { if(c.folderId === id) c.folderId = 'all'; });
        await eel.save_data(appData)();
        renderFolders();
        renderChannels();
    }
}

async function resetAllData() {
    const input = prompt("'전체 초기화'를 직접 입력하시면 모든 데이터가 삭제됩니다.");
    if (input === "전체 초기화") {
        appData = { folders: [], channels: [] };
        await eel.save_data(appData)();
        alert("모든 데이터가 초기화되었습니다.");
        refreshData();
    } else if (input !== null) {
        alert("문구가 일치하지 않습니다.");
    }
}

function filterFolder(id) {
    currentFolderId = id;
    renderFolders();
    renderChannels();
}

async function saveChannel() {
    const name = document.getElementById('inputName').value;
    if (!name) return;
    const newChannel = {
        id: Date.now(),
        name: name,
        subscribers: document.getElementById('inputSubs').value || '0',
        url: document.getElementById('inputUrl').value,
        memo: document.getElementById('inputMemo').value,
        platform: document.querySelector('.plat-btn.active').dataset.val,
        thumbnail: selectedAvatar || '',
        folderId: document.getElementById('inputFolder').value
    };
    appData.channels.push(newChannel);
    await eel.save_data(appData)();
    document.getElementById('modalOverlay').style.display = 'none';
    refreshData();
}

async function deleteChannel(id) {
    if (confirm("삭제하시겠습니까?")) {
        appData.channels = appData.channels.filter(c => c.id !== id);
        await eel.save_data(appData)();
        refreshData();
    }
}
