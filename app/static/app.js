/**
 * LLM Wiki 지식 인제스트 대시보드 클라이언트 스크립트
 */

document.addEventListener('DOMContentLoaded', () => {
  // DOM 요소 참조
  const mobileMenuBtn = document.getElementById('mobileMenuBtn');
  const sidebar = document.getElementById('sidebar');
  const mobileOverlay = document.getElementById('mobileOverlay');
  const docListContainer = document.getElementById('docListContainer');
  const docCountText = document.getElementById('docCountText');
  const searchInput = document.getElementById('searchInput');
  const scanBtn = document.getElementById('scanBtn');
  const scanIcon = document.getElementById('scanIcon');
  const refreshListBtn = document.getElementById('refreshListBtn');
  const fileUploadInput = document.getElementById('fileUploadInput');

  const emptyView = document.getElementById('emptyView');
  const documentViewer = document.getElementById('documentViewer');
  const docTitleHeading = document.getElementById('docTitleHeading');
  const docFormatBadge = document.getElementById('docFormatBadge');
  const docStatusBadge = document.getElementById('docStatusBadge');
  const docDateText = document.getElementById('docDateText');
  const metaOrigName = document.getElementById('metaOrigName');
  const metaFileSize = document.getElementById('metaFileSize');
  const metaHash = document.getElementById('metaHash');

  const renderedContent = document.getElementById('renderedContent');
  const rawContent = document.getElementById('rawContent');
  const toggleRawBtn = document.getElementById('toggleRawBtn');
  const copyMdBtn = document.getElementById('copyMdBtn');
  const tocContainer = document.getElementById('tocContainer');

  const imageModal = document.getElementById('imageModal');
  const modalImage = document.getElementById('modalImage');
  const modalCaption = document.getElementById('modalCaption');
  const closeModalBtn = document.getElementById('closeModalBtn');
  const toastContainer = document.getElementById('toastContainer');

  // 상태 변수
  let documents = [];
  let currentDoc = null;
  let isRawView = false;

  // 1. 토스트 알림 함수
  function showToast(message, type = 'info') {
    const toast = document.createElement('div');
    const bgColors = {
      success: 'bg-emerald-600 border-emerald-500 text-white',
      error: 'bg-rose-600 border-rose-500 text-white',
      info: 'bg-slate-800 border-slate-600 text-slate-200'
    };

    toast.className = `px-4 py-2.5 rounded-xl border text-xs shadow-xl flex items-center gap-2 transform transition-all duration-300 translate-y-2 opacity-0 pointer-events-auto ${bgColors[type] || bgColors.info}`;
    
    let icon = 'fa-circle-info';
    if (type === 'success') icon = 'fa-circle-check';
    if (type === 'error') icon = 'fa-circle-exclamation';

    toast.innerHTML = `<i class="fa-solid ${icon}"></i> <span>${message}</span>`;
    toastContainer.appendChild(toast);

    requestAnimationFrame(() => {
      toast.classList.remove('translate-y-2', 'opacity-0');
    });

    setTimeout(() => {
      toast.classList.add('opacity-0', 'translate-y-2');
      setTimeout(() => toast.remove(), 300);
    }, 3000);
  }

  // 2. 바이트 크기 포맷터
  function formatBytes(bytes, decimals = 1) {
    if (!bytes || bytes === 0) return '0 B';
    const k = 1024;
    const dm = decimals < 0 ? 0 : decimals;
    const sizes = ['B', 'KB', 'MB', 'GB'];
    const i = Math.floor(Math.log(bytes) / Math.log(k));
    return parseFloat((bytes / Math.pow(k, i)).toFixed(dm)) + ' ' + sizes[i];
  }

  // 3. 모바일 사이드바 토글
  function toggleMobileMenu(open) {
    if (open) {
      sidebar.classList.remove('-translate-x-full');
      mobileOverlay.classList.remove('hidden');
    } else {
      sidebar.classList.add('-translate-x-full');
      mobileOverlay.classList.add('hidden');
    }
  }

  mobileMenuBtn.addEventListener('click', () => toggleMobileMenu(true));
  mobileOverlay.addEventListener('click', () => toggleMobileMenu(false));

  // 4. 문서 목록 가져오기 및 렌더링
  async function fetchDocuments(selectId = null) {
    try {
      const res = await fetch('/api/documents');
      if (!res.ok) throw new Error('문서 목록 조회 실패');
      documents = await res.json();
      renderDocumentList();

      if (selectId) {
        loadDocument(selectId);
      } else if (currentDoc) {
        const stillExists = documents.find(d => d.id === currentDoc.id);
        if (stillExists) loadDocument(currentDoc.id);
      }
    } catch (err) {
      console.error(err);
      showToast('문서 목록을 불러오지 못했습니다.', 'error');
    }
  }

  function renderDocumentList() {
    const query = searchInput.value.trim().toLowerCase();
    const filtered = documents.filter(doc => 
      doc.title.toLowerCase().includes(query) || 
      doc.original_filename.toLowerCase().includes(query)
    );

    docCountText.textContent = `총 ${filtered.length}개 문서`;

    if (filtered.length === 0) {
      docListContainer.innerHTML = `
        <div class="text-center py-10 text-slate-500 text-xs">
          <i class="fa-solid fa-folder-open text-2xl mb-2 opacity-40"></i>
          <p>${query ? '검색 결과가 없습니다.' : '등록된 문서가 없습니다.'}</p>
        </div>
      `;
      return;
    }

    docListContainer.innerHTML = filtered.map(doc => {
      const isSelected = currentDoc && currentDoc.id === doc.id;
      const ext = doc.original_filename.split('.').pop().toUpperCase();
      const statusColor = doc.status === 'completed' 
        ? 'bg-emerald-500/20 text-emerald-300 border-emerald-500/30' 
        : 'bg-rose-500/20 text-rose-300 border-rose-500/30';

      return `
        <div class="doc-card p-2.5 rounded-xl border transition cursor-pointer ${
          isSelected 
            ? 'bg-slate-700/90 border-brand-500 shadow-md shadow-brand-500/10' 
            : 'bg-slate-800/60 border-slate-700/60 hover:bg-slate-700/50 hover:border-slate-600'
        }" data-id="${doc.id}">
          <div class="flex items-start justify-between gap-2 mb-1">
            <span class="text-[10px] font-mono font-bold px-1.5 py-0.5 rounded bg-slate-900 text-slate-300 border border-slate-700">
              ${ext}
            </span>
            <span class="text-[10px] px-1.5 py-0.5 rounded border ${statusColor}">
              ${doc.status === 'completed' ? '완본' : '실패'}
            </span>
          </div>
          <h4 class="text-xs font-semibold text-white truncate mb-1" title="${doc.title}">
            ${doc.title}
          </h4>
          <div class="flex items-center justify-between text-[10px] text-slate-400">
            <span class="truncate max-w-[120px] font-mono">${doc.original_filename}</span>
            <span>${formatBytes(doc.file_size)}</span>
          </div>
        </div>
      `;
    }).join('');

    // 카드 클릭 이벤트 바인딩
    docListContainer.querySelectorAll('.doc-card').forEach(card => {
      card.addEventListener('click', () => {
        const id = card.getAttribute('data-id');
        loadDocument(id);
        toggleMobileMenu(false);
      });
    });
  }

  // 5. 문서 상세 및 마크다운 본문 로드
  async function loadDocument(docId) {
    try {
      const res = await fetch(`/api/documents/${docId}`);
      if (!res.ok) throw new Error('문서 상세 조회 실패');
      currentDoc = await res.json();

      emptyView.classList.add('hidden');
      documentViewer.classList.remove('hidden');

      // 메타데이터 렌더링
      const ext = currentDoc.original_filename.split('.').pop().toUpperCase();
      docFormatBadge.textContent = ext;
      docTitleHeading.textContent = currentDoc.title;
      docDateText.textContent = new Date(currentDoc.ingested_at).toLocaleString('ko-KR');
      metaOrigName.textContent = currentDoc.original_filename;
      metaFileSize.textContent = formatBytes(currentDoc.file_size);
      metaHash.textContent = currentDoc.file_hash ? currentDoc.file_hash.substring(0, 16) + '...' : '-';
      metaHash.title = currentDoc.file_hash || '';

      // 마크다운 렌더링
      renderMarkdownContent(currentDoc.content);
      renderDocumentList();
    } catch (err) {
      console.error(err);
      showToast('문서 본문을 불러오지 못했습니다.', 'error');
    }
  }

  function renderMarkdownContent(content) {
    rawContent.textContent = content;

    // Marked 옵션 및 커스텀 이미지 렌더러 설정
    const renderer = new marked.Renderer();

    renderer.image = function(token) {
      // Marked v4/v11+ 호환 처리 (객체 또는 인자)
      let href = typeof token === 'object' ? token.href : token;
      let title = typeof token === 'object' ? token.title : arguments[1];
      let text = typeof token === 'object' ? token.text : arguments[2];

      let src = href || '';
      if (!src.startsWith('http://') && !src.startsWith('https://') && !src.startsWith('data:') && !src.startsWith('/api/assets/')) {
        const cleanName = src.replace(/^(\.\/|\.\.\/|images\/|\\images\\)/, '').split('/').pop().split('\\').pop();
        if (currentDoc) {
          src = `/api/assets/${currentDoc.id}/${cleanName}`;
        }
      }

      const caption = text || title || '';
      const titleAttr = title ? ` title="${title}"` : '';
      const captionHtml = caption ? `<figcaption class="text-xs text-slate-400 mt-2 font-sans italic text-center">📊 ${caption}</figcaption>` : '';

      return `
        <figure class="my-6 p-2 bg-slate-800/40 rounded-xl border border-slate-700/60 max-w-full flex flex-col items-center">
          <img src="${src}" alt="${text || ''}"${titleAttr} class="max-h-[600px] object-contain rounded-lg shadow-md cursor-zoom-in hover:scale-[1.01] transition" loading="lazy" onerror="console.warn('이미지 로드 실패:', this.src);">
          ${captionHtml}
        </figure>
      `;
    };

    marked.setOptions({
      renderer: renderer,
      gfm: true,
      breaks: true,
      highlight: function(code, lang) {
        if (lang && hljs.getLanguage(lang)) {
          try {
            return hljs.highlight(code, { language: lang }).value;
          } catch (e) {}
        }
        return hljs.highlightAuto(code).value;
      }
    });

    const parsedHtml = marked.parse(content);
    renderedContent.innerHTML = parsedHtml;

    // 수식 렌더링 (KaTeX)
    if (window.renderMathInElement) {
      renderMathInElement(renderedContent, {
        delimiters: [
          {left: '$$', right: '$$', display: true},
          {left: '$', right: '$', display: false},
          {left: '\\(', right: '\\)', display: false},
          {left: '\\[', right: '\\]', display: true}
        ],
        throwOnError: false
      });
    }

    // 인라인 이미지 라이트박스 클릭 이벤트 연결
    renderedContent.querySelectorAll('img').forEach(img => {
      img.addEventListener('click', () => {
        modalImage.src = img.src;
        modalCaption.textContent = img.alt || img.title || '문서 추출 도표 이미지';
        imageModal.classList.remove('hidden');
      });
    });

    // 목차 (TOC) 생성
    buildTableOfContents();
  }

  // 6. 목차 (TOC) 자동 추출
  function buildTableOfContents() {
    tocContainer.innerHTML = '';
    const headings = renderedContent.querySelectorAll('h1, h2, h3');

    if (headings.length === 0) {
      tocContainer.innerHTML = '<p class="text-[11px] text-slate-500 italic">헤딩이 없습니다.</p>';
      return;
    }

    headings.forEach((heading, index) => {
      const anchorId = `heading-${index}`;
      heading.id = anchorId;

      const link = document.createElement('a');
      link.href = `#${anchorId}`;
      link.textContent = heading.textContent;
      
      const level = parseInt(heading.tagName.replace('H', ''), 10);
      const indent = level === 1 ? 'pl-0 font-semibold text-slate-200' : level === 2 ? 'pl-3' : 'pl-6 text-[11px]';

      link.className = `block py-1 truncate hover:text-brand-400 transition ${indent}`;
      link.addEventListener('click', (e) => {
        e.preventDefault();
        heading.scrollIntoView({ behavior: 'smooth' });
      });

      tocContainer.appendChild(link);
    });
  }

  // 7. 원문 보기 / 렌더링 보기 토글
  toggleRawBtn.addEventListener('click', () => {
    isRawView = !isRawView;
    if (isRawView) {
      renderedContent.classList.add('hidden');
      rawContent.classList.remove('hidden');
      toggleRawBtn.innerHTML = '<i class="fa-solid fa-eye"></i> <span class="hidden md:inline">렌더링 보기</span>';
    } else {
      renderedContent.classList.remove('hidden');
      rawContent.classList.add('hidden');
      toggleRawBtn.innerHTML = '<i class="fa-solid fa-code"></i> <span class="hidden md:inline">원문 보기</span>';
    }
  });

  // 8. 마크다운 원문 복사
  copyMdBtn.addEventListener('click', async () => {
    if (!currentDoc || !currentDoc.content) return;
    try {
      await navigator.clipboard.writeText(currentDoc.content);
      showToast('마크다운 원문이 클립보드에 복사되었습니다.', 'success');
    } catch (err) {
      showToast('복사에 실패했습니다.', 'error');
    }
  });

  // 9. 라이트박스 모달 닫기
  closeModalBtn.addEventListener('click', () => imageModal.classList.add('hidden'));
  imageModal.addEventListener('click', (e) => {
    if (e.target === imageModal) imageModal.classList.add('hidden');
  });

  // 10. Source 폴더 수동 스캔 실행
  scanBtn.addEventListener('click', async () => {
    scanIcon.classList.add('animate-spin');
    try {
      const res = await fetch('/api/scan', { method: 'POST' });
      const data = await res.json();
      showToast(`스캔 완료: 신규 ${data.processed_count}건 변환, ${data.skipped_count}건 중복 건너뜀`, 'success');
      await fetchDocuments();
    } catch (err) {
      showToast('스캔 중 오류가 발생했습니다.', 'error');
    } finally {
      scanIcon.classList.remove('animate-spin');
    }
  });

  // 11. 파일 직접 업로드
  fileUploadInput.addEventListener('change', async (e) => {
    const files = e.target.files;
    if (!files || files.length === 0) return;

    showToast(`${files.length}개 파일 업로드 및 변환 시작...`, 'info');

    for (const file of files) {
      const formData = new FormData();
      formData.append('file', file);

      try {
        const res = await fetch('/api/upload', {
          method: 'POST',
          body: formData
        });
        if (res.ok) {
          showToast(`${file.name} 업로드 및 인제스트 완료!`, 'success');
        } else {
          showToast(`${file.name} 업로드 실패`, 'error');
        }
      } catch (err) {
        showToast(`${file.name} 처리 중 에러`, 'error');
      }
    }

    fileUploadInput.value = '';
    await fetchDocuments();
  });

  // 12. 검색 필터링 및 새로고침 이벤트
  searchInput.addEventListener('input', renderDocumentList);
  refreshListBtn.addEventListener('click', () => fetchDocuments());

  // 13. 주기적 자동 폴링 (5초마다 문서 목록 갱신)
  setInterval(() => {
    fetchDocuments();
  }, 5000);

  // 초기 실행
  fetchDocuments();
});
