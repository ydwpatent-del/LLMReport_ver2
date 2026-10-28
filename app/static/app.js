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
  const deleteDocHeaderBtn = document.getElementById('deleteDocHeaderBtn');
  const auditDocBtn = document.getElementById('auditDocBtn');
  const auditIcon = document.getElementById('auditIcon');
  const docHtmlBtn = document.getElementById('docHtmlBtn');
  const docPdfBtn = document.getElementById('docPdfBtn');
  const tocContainer = document.getElementById('tocContainer');

  const imageModal = document.getElementById('imageModal');
  const modalImage = document.getElementById('modalImage');
  const modalCaption = document.getElementById('modalCaption');
  const closeModalBtn = document.getElementById('closeModalBtn');
  const toastContainer = document.getElementById('toastContainer');

  // 품질 검수 및 자율 치유 모달 DOM 요소
  const auditModal = document.getElementById('auditModal');
  const closeAuditModalBtn = document.getElementById('closeAuditModalBtn');
  const closeAuditModalBottomBtn = document.getElementById('closeAuditModalBottomBtn');
  const executeHealBtn = document.getElementById('executeHealBtn');
  const healBtnText = document.getElementById('healBtnText');
  const auditModalTitle = document.getElementById('auditModalTitle');
  const auditModalDocName = document.getElementById('auditModalDocName');
  const auditModalBody = document.getElementById('auditModalBody');
  const auditModalIconBg = document.getElementById('auditModalIconBg');

  // Marked.js 마크다운 줄바꿈(breaks), GFM 및 취소선 토크나이저 커스텀 설정
  // 단일 틸드(~) 수치 범위 표시(예: 92~95%, ~370mAh/g, 5~15%)가 취소선으로 파싱되는 오작동을 차단
  // 취소선은 오직 표준 이중 틸드(~~취소선~~)일 때만 작동하도록 제한
  const markedConfig = {
    breaks: true,
    gfm: true,
    tokenizer: {
      del(src) {
        const match = /^(~~)(?=[^\s~])([\s\S]*?[^\s~])\1(?=[^~]|$)/.exec(src);
        if (match) {
          return {
            type: 'del',
            raw: match[0],
            text: match[2],
            tokens: this.lexer.inlineTokens(match[2])
          };
        }
        return undefined;
      }
    }
  };
  if (window.marked && typeof window.marked.use === 'function') {
    window.marked.use(markedConfig);
  }

  // 탭 및 보고서 생성기 관련 DOM 요소
  const tabBtnViewer = document.getElementById('tabBtnViewer');
  const tabBtnGenerator = document.getElementById('tabBtnGenerator');
  const viewerTabContent = document.getElementById('viewerTabContent');
  const generatorTabContent = document.getElementById('generatorTabContent');

  const topicInput = document.getElementById('topicInput');
  const btnGenerateTopic = document.getElementById('btnGenerateTopic');
  const genIcon = document.getElementById('genIcon');
  const genBtnText = document.getElementById('genBtnText');
  const topicSuggestionsBar = document.getElementById('topicSuggestionsBar');
  const topicEmptyState = document.getElementById('topicEmptyState');
  const topicLoadingState = document.getElementById('topicLoadingState');
  const loadingStageTitle = document.getElementById('loadingStageTitle');
  const loadingStageDesc = document.getElementById('loadingStageDesc');
  const loadingProgressBar = document.getElementById('loadingProgressBar');
  const topicReportViewer = document.getElementById('topicReportViewer');
  const reportTitleHeading = document.getElementById('reportTitleHeading');
  const reportDateBadge = document.getElementById('reportDateBadge');
  const topicRenderedContent = document.getElementById('topicRenderedContent');
  const copyGenMdBtn = document.getElementById('copyGenMdBtn');
  const downloadGenMdBtn = document.getElementById('downloadGenMdBtn');
  const btnOpenHtmlReport = document.getElementById('btnOpenHtmlReport');
  const btnDownloadPdfReport = document.getElementById('btnDownloadPdfReport');
  const topicHistoryList = document.getElementById('topicHistoryList');
  const reportCountBadge = document.getElementById('reportCountBadge');

  // 보고서 품질 검수 및 피드백 반영 모달 DOM 요소
  const btnReviewReport = document.getElementById('btnReviewReport');
  const reviewIcon = document.getElementById('reviewIcon');
  const btnReviewReportText = document.getElementById('btnReviewReportText');
  const reportReviewModal = document.getElementById('reportReviewModal');
  const reviewModalReportTitle = document.getElementById('reviewModalReportTitle');
  const btnCloseReviewModal = document.getElementById('btnCloseReviewModal');
  const btnCloseReviewModal2 = document.getElementById('btnCloseReviewModal2');
  const reviewChecklistContainer = document.getElementById('reviewChecklistContainer');
  const reviewDefectsList = document.getElementById('reviewDefectsList');
  const reviewSuggestionsList = document.getElementById('reviewSuggestionsList');
  const reviewDefectsSection = document.getElementById('reviewDefectsSection');
  const reviewSuggestionsSection = document.getElementById('reviewSuggestionsSection');
  const btnApplyRefine = document.getElementById('btnApplyRefine');
  const refineIcon = document.getElementById('refineIcon');
  const refineBtnText = document.getElementById('refineBtnText');

  // 상태 변수
  let documents = [];
  let currentDoc = null;
  let currentTopicReport = null;
  let currentActiveTopicReportId = null;
  let lastReviewResult = null;
  let isRawView = false;
  let isInitialLoad = true;

  // 1. 토스트 알림 함수
  function showToast(message, type = 'info') {
    if (!toastContainer) return;
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

  // 2-1. XSS 방어용 경량 HTML 정화기 (Sanitizer)
  function sanitizeHtml(dirtyHtml) {
    if (!dirtyHtml || typeof dirtyHtml !== 'string') return '';
    try {
      const parser = new DOMParser();
      const doc = parser.parseFromString(dirtyHtml, 'text/html');
      const dangerousTags = ['script', 'iframe', 'object', 'embed', 'style', 'base', 'link', 'meta'];
      dangerousTags.forEach(tag => {
        doc.querySelectorAll(tag).forEach(el => el.remove());
      });
      doc.querySelectorAll('*').forEach(el => {
        Array.from(el.attributes).forEach(attr => {
          const name = attr.name.toLowerCase();
          const val = attr.value.toLowerCase().replace(/\s+/g, '');
          if (name.startsWith('on')) {
            el.removeAttribute(attr.name);
          } else if ((name === 'href' || name === 'src') && (val.startsWith('javascript:') || val.startsWith('vbscript:'))) {
            el.removeAttribute(attr.name);
          }
        });
      });
      return doc.body.innerHTML;
    } catch (e) {
      console.warn('HTML 정화 중 오류:', e);
      return dirtyHtml;
    }
  }


  // 3. 모바일 사이드바 토글
  function toggleMobileMenu(open) {
    if (!sidebar || !mobileOverlay) return;
    if (open) {
      sidebar.classList.remove('-translate-x-full');
      mobileOverlay.classList.remove('hidden');
    } else {
      sidebar.classList.add('-translate-x-full');
      mobileOverlay.classList.add('hidden');
    }
  }

  if (mobileMenuBtn) mobileMenuBtn.addEventListener('click', () => toggleMobileMenu(true));
  if (mobileOverlay) mobileOverlay.addEventListener('click', () => toggleMobileMenu(false));

  // 4. 문서 목록 가져오기 및 렌더링 (원본 문서 + AI 생성 보고서 안전 병합)
  async function fetchDocuments(selectId = null) {
    try {
      const [resDocs, resReports] = await Promise.all([
        fetch('/api/documents').catch(() => null),
        fetch('/api/topic/reports').catch(() => null)
      ]);

      const originDocs = (resDocs && resDocs.ok) ? await resDocs.json() : [];
      const reportDocs = (resReports && resReports.ok) ? await resReports.json() : [];

      // AI 생성 보고서는 최신순으로 상단에 배치하고 원본과 결합
      documents = [...reportDocs, ...originDocs];
      renderDocumentList();

      if (selectId) {
        await loadDocument(selectId);
      } else if (currentDoc) {
        const stillExists = documents.find(d => d.id === currentDoc.id);
        if (stillExists) {
          const statusChanged = currentDoc.status !== stillExists.status;
          currentDoc = stillExists;
          if (statusChanged) {
            await loadDocument(currentDoc.id);
          }
        }
      } else if (isInitialLoad && documents.length > 0) {
        isInitialLoad = false;
        await loadDocument(documents[0].id);
      }
    } catch (err) {
      console.error('문서 목록 로드 오류:', err);
    }
  }

  function renderDocumentList() {
    if (!docListContainer) return;
    const query = searchInput ? searchInput.value.trim().toLowerCase() : '';
    const filtered = documents.filter(doc => 
      (doc.title && doc.title.toLowerCase().includes(query)) || 
      (doc.original_filename && doc.original_filename.toLowerCase().includes(query))
    );

    if (docCountText) docCountText.textContent = `총 ${filtered.length}개 문서`;

    // Fast-path: 선택 상태, 문서 ID, 변환 상태가 동일한 경우 DOM 덮어쓰기 생략 (스크롤 튐 방지)
    const selectedId = currentDoc ? currentDoc.id : '';
    const currentSignature = docListContainer.getAttribute('data-list-sig') || '';
    const newSignature = `${selectedId}::` + filtered.map(d => `${d.id}:${d.status}:${d.title || ''}`).join(',');
    if (currentSignature === newSignature && docListContainer.querySelectorAll('.doc-card').length > 0) {
      return;
    }
    docListContainer.setAttribute('data-list-sig', newSignature);

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
      const isSynthesized = doc.is_synthesized || doc.id.startsWith('REPORT_');
      const ext = (doc.original_filename || '').split('.').pop().toUpperCase() || 'DOC';
      
      let badgeType = '';
      if (isSynthesized) {
        badgeType = '<span class="text-[10px] font-mono font-bold px-1.5 py-0.5 rounded bg-purple-950 text-purple-300 border border-purple-500/40 flex items-center gap-1"><i class="fa-solid fa-robot text-[9px]"></i> AI 보고서</span>';
      } else {
        badgeType = `<span class="text-[10px] font-mono font-bold px-1.5 py-0.5 rounded bg-slate-900 text-slate-300 border border-slate-700">${ext}</span>`;
      }

      let statusBadge = '';
      if (isSynthesized) {
        statusBadge = '<span class="text-[10px] px-1.5 py-0.5 rounded border bg-purple-500/20 text-purple-300 border-purple-500/30">합성완료</span>';
      } else if (doc.status === 'completed') {
        statusBadge = '<span class="text-[10px] px-1.5 py-0.5 rounded border bg-emerald-500/20 text-emerald-300 border-emerald-500/30">완본</span>';
      } else if (doc.status === 'processing') {
        statusBadge = '<span class="text-[10px] px-1.5 py-0.5 rounded border bg-amber-500/20 text-amber-300 border-amber-500/30 flex items-center gap-1"><i class="fa-solid fa-spinner animate-spin text-[9px]"></i> AI 변환 중</span>';
      } else {
        statusBadge = '<span class="text-[10px] px-1.5 py-0.5 rounded border bg-rose-500/20 text-rose-300 border-rose-500/30">실패</span>';
      }

      return `
        <div class="doc-card group relative p-2.5 rounded-xl border transition cursor-pointer ${
          isSelected 
            ? 'bg-slate-700/90 border-brand-500 shadow-md shadow-brand-500/10' 
            : 'bg-slate-800/60 border-slate-700/60 hover:bg-slate-700/50 hover:border-slate-600'
        }" data-id="${doc.id}">
          <div class="flex items-start justify-between gap-2 mb-1">
            ${badgeType}
            <div class="flex items-center gap-1.5">
              ${statusBadge}
              <button class="delete-doc-btn opacity-0 group-hover:opacity-100 p-1 text-slate-400 hover:text-rose-400 hover:bg-rose-500/20 rounded transition" title="문서 및 에셋 전체 삭제" data-id="${doc.id}" data-title="${doc.title || doc.original_filename}">
                <i class="fa-regular fa-trash-can text-[11px]"></i>
              </button>
            </div>
          </div>
          <h4 class="text-xs font-semibold text-white truncate mb-1 pr-4" title="${doc.title}">
            ${doc.title || doc.original_filename}
          </h4>
          <div class="flex items-center justify-between text-[10px] text-slate-400">
            <span class="truncate max-w-[120px] font-mono">${doc.original_filename}</span>
            <span>${formatBytes(doc.file_size)}</span>
          </div>
        </div>
      `;
    }).join('');
  }

  // 문서 목록 이벤트 위임 (카드 클릭 및 삭제 버튼)
  if (docListContainer) {
    docListContainer.addEventListener('click', async (e) => {
      const deleteBtn = e.target.closest('.delete-doc-btn');
      if (deleteBtn) {
        e.stopPropagation();
        const docId = deleteBtn.getAttribute('data-id');
        const title = deleteBtn.getAttribute('data-title') || '해당 문서';
        if (!confirm(`정말로 '${title}' 문서를 삭제하시겠습니까?\n\n마크다운 파일 및 관련 에셋이 삭제됩니다.`)) {
          return;
        }
        await deleteDocument(docId);
        return;
      }

      const card = e.target.closest('.doc-card');
      if (card) {
        const id = card.getAttribute('data-id');
        loadDocument(id);
        toggleMobileMenu(false);
      }
    });
  }

  // 4.5 문서 삭제 처리 함수
  async function deleteDocument(docId) {
    try {
      showToast('문서 및 에셋을 삭제하는 중...', 'info');
      let res = null;
      if (docId.startsWith('REPORT_')) {
        res = await fetch(`/api/topic/reports/${encodeURIComponent(docId)}`, {
          method: 'DELETE'
        });
      }
      if (!res || !res.ok) {
        res = await fetch(`/api/documents/${encodeURIComponent(docId)}`, {
          method: 'DELETE'
        });
      }

      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        throw new Error(err.detail || `삭제 실패 (${res.status})`);
      }

      showToast('문서가 삭제되었습니다.', 'success');

      if (currentDoc && (currentDoc.id === docId || currentDoc.id === decodeURIComponent(docId))) {
        currentDoc = null;
        if (documentViewer) documentViewer.classList.add('hidden');
        if (emptyView) emptyView.classList.remove('hidden');
      }

      if (currentTopicReport && (currentTopicReport.id === docId || currentTopicReport.id === decodeURIComponent(docId))) {
        currentTopicReport = null;
        if (topicReportViewer) topicReportViewer.classList.add('hidden');
        if (topicEmptyState) topicEmptyState.classList.remove('hidden');
      }

      await fetchDocuments();
      if (typeof loadTopicHistory === 'function') {
        loadTopicHistory();
      }
    } catch (err) {
      console.error('문서 삭제 오류:', err);
      showToast(`삭제 실패: ${err.message}`, 'error');
    }
  }

  // 5. 문서 상세 및 마크다운 본문 로드
  async function loadDocument(docId) {
    try {
      console.log('[Wiki] Loading document:', docId);
      let res = null;
      if (docId.startsWith('REPORT_')) {
        res = await fetch(`/api/topic/reports/${encodeURIComponent(docId)}`);
      }
      if (!res || !res.ok) {
        res = await fetch(`/api/documents/${encodeURIComponent(docId)}`);
      }
      if (!res.ok) throw new Error(`문서 상세 조회 실패 (${res.status})`);
      currentDoc = await res.json();

      if (emptyView) emptyView.classList.add('hidden');
      if (documentViewer) documentViewer.classList.remove('hidden');

      // 메타데이터 렌더링
      const isSynthesized = currentDoc.is_synthesized || currentDoc.id.startsWith('REPORT_');
      if (isSynthesized) {
        currentActiveTopicReportId = currentDoc.id || docId;
      }
      const ext = (currentDoc.original_filename || '').split('.').pop().toUpperCase() || 'DOC';
      if (docFormatBadge) {
        docFormatBadge.textContent = isSynthesized ? '🤖 AI 보고서' : ext;
        if (isSynthesized) {
          docFormatBadge.className = 'text-[10px] font-bold px-2 py-0.5 rounded bg-purple-900/60 text-purple-300 border border-purple-500/30';
        } else {
          docFormatBadge.className = 'text-[10px] uppercase font-bold px-2 py-0.5 rounded bg-brand-500/20 text-brand-300 border border-brand-500/30';
        }
      }

      // 보고서인 경우 HTML 열기 및 PDF 다운로드 버튼 노출
      if (docHtmlBtn) {
        if (isSynthesized) {
          docHtmlBtn.classList.remove('hidden');
          docHtmlBtn.classList.add('flex');
        } else {
          docHtmlBtn.classList.add('hidden');
          docHtmlBtn.classList.remove('flex');
        }
      }
      if (docPdfBtn) {
        if (isSynthesized) {
          docPdfBtn.classList.remove('hidden');
          docPdfBtn.classList.add('flex');
        } else {
          docPdfBtn.classList.add('hidden');
          docPdfBtn.classList.remove('flex');
        }
      }
      // 마크다운 본문의 레벨 1 대제목(# 제목) 추출 및 동기화
      if (currentDoc.content) {
        const h1Match = currentDoc.content.match(/^#\s+(.+)$/m);
        if (h1Match && h1Match[1]) {
          const extractedH1 = h1Match[1].replace(/\[([^\]]+)\]\([^\)]+\)/g, '$1').replace(/[*_`]/g, '').trim();
          if (extractedH1) {
            currentDoc.title = extractedH1;
            const targetListItem = documents.find(d => d.id === currentDoc.id);
            if (targetListItem) targetListItem.title = extractedH1;
          }
        }
      }
      if (docTitleHeading) docTitleHeading.textContent = currentDoc.title || currentDoc.original_filename;
      if (docDateText) {
        docDateText.textContent = currentDoc.ingested_at ? new Date(currentDoc.ingested_at).toLocaleString('ko-KR') : '';
      }
      if (metaOrigName) metaOrigName.textContent = currentDoc.original_filename || '-';
      if (metaFileSize) metaFileSize.textContent = formatBytes(currentDoc.file_size);
      if (metaHash) {
        metaHash.textContent = currentDoc.file_hash ? currentDoc.file_hash.substring(0, 16) + '...' : '-';
        metaHash.title = currentDoc.file_hash || '';
      }

      // 상태별 뱃지
      if (docStatusBadge) {
        if (currentDoc.status === 'completed') {
          docStatusBadge.className = 'text-[10px] font-bold px-2 py-0.5 rounded bg-emerald-500/20 text-emerald-300 border border-emerald-500/30';
          docStatusBadge.textContent = '완료됨';
        } else if (currentDoc.status === 'processing') {
          docStatusBadge.className = 'text-[10px] font-bold px-2 py-0.5 rounded bg-amber-500/20 text-amber-300 border border-amber-500/30 animate-pulse';
          docStatusBadge.textContent = 'AI 변환 중...';
        } else {
          docStatusBadge.className = 'text-[10px] font-bold px-2 py-0.5 rounded bg-rose-500/20 text-rose-300 border border-rose-500/30';
          docStatusBadge.textContent = '변환 실패';
        }
      }

      // 처리 중인 경우 로딩 안내
      if (currentDoc.status === 'processing') {
        if (renderedContent) {
          renderedContent.innerHTML = `
            <div class="flex flex-col items-center justify-center p-12 text-center my-12 bg-slate-800/40 rounded-2xl border border-slate-700/60">
              <div class="w-14 h-14 rounded-full bg-brand-500/20 border border-brand-500/40 flex items-center justify-center mb-4 text-brand-400">
                <i class="fa-solid fa-wand-magic-sparkles text-2xl animate-bounce"></i>
              </div>
              <h3 class="text-base font-bold text-white mb-1">Gemini AI 위키 인제스트 진행 중</h3>
              <p class="text-xs text-slate-400 max-w-md leading-relaxed">
                /kordoc-wiki-ingest 에이전트가 텍스트 전수 복원, 차트 수치화, 도표 캡션 인라인 결합을 수행하고 있습니다. 잠시 후 자동으로 완료됩니다.
              </p>
            </div>
          `;
        }
        return;
      }

      // 본문 내용이 비어 있는 경우 자가 치유 안내
      if (!currentDoc.content || currentDoc.content.trim() === '') {
        if (renderedContent) {
          renderedContent.innerHTML = `
            <div class="flex flex-col items-center justify-center p-12 text-center my-12 bg-slate-800/40 rounded-2xl border border-slate-700/60">
              <div class="w-12 h-12 rounded-full bg-amber-500/20 border border-amber-500/40 flex items-center justify-center mb-3 text-amber-400">
                <i class="fa-solid fa-triangle-exclamation text-xl"></i>
              </div>
              <h3 class="text-sm font-bold text-white mb-1">마크다운 본문을 표시할 수 없습니다</h3>
              <p class="text-xs text-slate-400 max-w-md leading-relaxed mb-4">
                디스크 파일 경로 불일치 또는 동기화 지연일 수 있습니다. 아래 버튼을 눌러 WikiDB를 즉시 동기화하십시오.
              </p>
              <button id="reconcileFixBtn" class="px-3.5 py-1.5 rounded-lg bg-brand-500 hover:bg-brand-600 text-white text-xs font-semibold shadow transition flex items-center gap-1.5">
                <i class="fa-solid fa-arrows-rotate"></i> WikiDB 자가 치유 동기화
              </button>
            </div>
          `;
          const fixBtn = document.getElementById('reconcileFixBtn');
          if (fixBtn) {
            fixBtn.addEventListener('click', async () => {
              showToast('WikiDB 자가 치유 동기화 중...', 'info');
              await fetch('/api/reconcile', { method: 'POST' });
              await fetchDocuments(currentDoc.id);
            });
          }
        }
        if (tocContainer) tocContainer.innerHTML = '<p class="text-[11px] text-slate-500 italic">헤딩이 없습니다.</p>';
        renderDocumentList();
        return;
      }

      // 마크다운 렌더링 실행
      await renderMarkdownContent(currentDoc.content || '');
      renderDocumentList();
    } catch (err) {
      console.error('문서 로드 오류:', err);
      showToast('문서 본문을 불러오지 못했습니다.', 'error');
    }
  }

  // 5-1. 마크다운 표, 이미지 분리, 출처 표기 보정 공통 전처리기
  function preprocessMarkdown(content) {
    if (!content || typeof content !== 'string') return '';
    let text = content;

    // [마크다운 표 종결 경계 정규화 및 인라인 이미지 독립 분리 (GFM 셀 오염 방어)]
    text = text.replace(/([>)]|\*(?:[^*]+)\*)\s*(!\[[^\n\]]*\]\([^\n\)]+\))/g, '$1\n\n$2');

    // 1) 불릿 하위나 들여쓰기된 표 행들을 라인 시작부(^|)로 평탄화 (인덴트 코드블록 오인식 방지)
    text = text.replace(/^[ \t]+(\|[^\n]+\|[ \t]*)$/gm, '$1');

    // 2) 표 내부 파이프 행 사이에 끼어든 고립된 빈 줄 자동 봉합 (연속 분할 표 완벽 봉합)
    for (let i = 0; i < 5; i++) {
      if (!/(\|[^\n]+\|[ \t]*)\n{2,}[ \t]*(\|[^\n]+\|[ \t]*)/.test(text)) break;
      text = text.replace(/(\|[^\n]+\|[ \t]*)\n{2,}[ \t]*(\|[^\n]+\|[ \t]*)/g, '$1\n$2');
    }

    // 3) 표 종결 경계 분리: 다음 줄이 공백을 포함해 파이프로 시작하지 않고 빈 줄도 아닐 때만 안전하게 빈 줄 삽입
    text = text.replace(/([ \t]*\|[^\n]*\|)[ \t]*\n(?![ \t]*\|)(?![ \t]*\n)/g, '$1\n\n');

    // 4) 표 시작 전 일반 문단과의 분리 보장
    text = text.replace(/((?:^|\n)(?!\s*\|)[^\n|]+?)[ \t]*\n(?=[ \t]*\|[^\n]+\|\n[ \t]*\|(?:\s*:?-+:?\s*\|)+)/g, '$1\n\n');

    // [출처 표기 백틱 제거, 파손된 각주 URL 복원 및 대괄호 중첩 링크 보정]
    text = text.replace(/(\/api\/documents\/[^\s)>\]]+?)\[\^(\d+)\](?=[,>\s\)]|$)/g, '$1$2)');
    text = text.replace(/`\s*(<출처\s*:[^>]+>)\s*`/g, '$1');
    text = text.replace(/`\s*(\[[^\]\n]+\]\((?:\/api\/documents\/)?[^)\n]+\))\s*`/g, '$1');
    text = text.replace(/\[\s*\[([^\[\]\n]+)\]\s*([^\[\]\n]*)\]\(([^)\n]+)\)/g, '[($1) $2]($3)');

    // [소제목 및 헤딩 경계 분리 (인라인 결합 및 뭉침 방어)]
    text = text.replace(/([^\n#])[ \t]*(#{1,6}\s+[^\n]+)/g, '$1\n\n$2');

    return text;
  }

  // 6. 안전하고 강력한 마크다운 렌더링 함수
  async function renderMarkdownContent(content) {
    if (rawContent) rawContent.textContent = content;

    try {
      let html = '';
      let preprocessed = preprocessMarkdown(content || '');
      preprocessed = preprocessed.replace(/(?:<출처\s*:\s*\[(.*?)\]\(((?:\/api\/documents\/)?[^)]+)\)>[ \t]*,?[ \t]*)+/g, (full) => {
        const regex = /<출처\s*:\s*\[(.*?)\]\(((?:\/api\/documents\/)?[^)]+)\)>/g;
        let match;
        const seen = new Set();
        const unique = [];
        while ((match = regex.exec(full)) !== null) {
          const title = match[1];
          const link = match[2];
          const key = title.replace(/[\s_()\[\]\-\.]+/g, '').toLowerCase();
          if (!seen.has(key)) {
            seen.add(key);
            unique.push(`<출처: [${title}](${link})>`);
          }
        }
        return unique.join(', ');
      });
      const normalizedContent = preprocessed.replace(/<출처\s*:\s*([^>]+)>/g, (match, inner) => {
        if (inner.includes('](')) {
          return inner.trim();
        }
        return `<span class="source-badge"><i class="fa-solid fa-bookmark text-amber-400 mr-1"></i><span>&lt;출처 : <span class="font-semibold text-indigo-100">${inner.trim()}</span>&gt;</span></span>`;
      });

      // 1. Marked.js 파싱 시도
      if (window.marked) {
        if (typeof window.marked.use === 'function') {
          window.marked.use(markedConfig);
        }
        if (typeof window.marked.parse === 'function') {
          html = await Promise.resolve(window.marked.parse(normalizedContent));
        } else if (typeof window.marked === 'function') {
          html = await Promise.resolve(window.marked(normalizedContent));
        }
      }

      // 2. 파싱 결과가 비어있거나 객체인 경우 안전 폴백
      if (!html || typeof html !== 'string' || html.trim() === '') {
        // 간단한 기본 마크다운 파서 폴백
        html = content
          .replace(/^### (.*$)/gim, '<h3 class="text-base font-bold text-slate-200 mt-6 mb-2">$1</h3>')
          .replace(/^## (.*$)/gim, '<h2 class="text-lg font-bold text-white mt-8 mb-3 pb-2 border-b border-slate-700">$1</h2>')
          .replace(/^# (.*$)/gim, '<h1 class="text-xl font-extrabold text-white mt-4 mb-4">$1</h1>')
          .replace(/^\> (.*$)/gim, '<blockquote class="border-l-4 border-brand-500 pl-4 py-1.5 my-3 bg-slate-800/40 rounded-r-lg text-slate-300">$1</blockquote>')
          .replace(/\*\*(.*?)\*\*/gim, '<strong>$1</strong>')
          .replace(/\*(.*?)\*/gim, '<em>$1</em>')
          .replace(/!\[(.*?)\]\((.*?)\)/gim, '<img src="$2" alt="$1">')
          .replace(/\n\n/gim, '<br><br>');
      }

      if (renderedContent) {
        renderedContent.innerHTML = sanitizeHtml(html);


        // [인라인 이미지 후처리 & 시각화 강화]
        const images = renderedContent.querySelectorAll('img');
        images.forEach(img => {
          let src = img.getAttribute('src') || '';
          const altText = img.getAttribute('alt') || img.getAttribute('title') || '';

          // 1. 상대경로 이미지 링크 보정 (/api/assets/<doc_id>/<filename>)
          if (src && !src.startsWith('http://') && !src.startsWith('https://') && !src.startsWith('data:') && !src.startsWith('/api/assets/')) {
            const filename = src.replace(/^(\.\/|\.\.\/|images\/|\\images\\)/, '').split('/').pop().split('\\').pop();
            if (currentDoc && currentDoc.id) {
              src = `/api/assets/${encodeURIComponent(currentDoc.id)}/${encodeURIComponent(filename)}`;
              img.setAttribute('src', src);
            }
          }

          // 2. 이미지 스타일 적용
          img.className = 'max-h-[650px] max-w-full object-contain rounded-lg shadow-lg cursor-zoom-in hover:scale-[1.01] transition border border-slate-700';
          img.loading = 'lazy';

          // 3. figure & figcaption 감싸기 (안전한 replaceWith 사용)
          if (img.parentElement && img.parentElement.tagName !== 'FIGURE') {
            let containerElem = (img.parentElement && img.parentElement.tagName === 'P') ? img.parentElement : img;
            let prevElem = containerElem.previousElementSibling;
            let nextElem = containerElem.nextElementSibling;
            let hasDuplicateTitleBefore = false;
            let hasCaptionAfter = Boolean(currentDoc && currentDoc.is_synthesized);

            if (prevElem && altText) {
              const prevText = prevElem.textContent.trim().replace(/^[\s\*\#\-\_•·■]+/, '').replace(/[\s\*\#\-\_]+$/, '');
              const cleanAlt = altText.trim().replace(/^[\s\*\#\-\_•·■]+/, '').replace(/[\s\*\#\-\_]+$/, '');
              if (prevText && cleanAlt && (prevText === cleanAlt || prevText.includes(cleanAlt) || cleanAlt.includes(prevText))) {
                hasDuplicateTitleBefore = true;
              }
            }

            // 이미지 하단(동일 단락 내 후속 노드 또는 직후 단락)에 도표제목-출처 표시가 있는지 확인
            if (!hasCaptionAfter) {
              let afterText = '';
              let sibling = img.nextSibling;
              while (sibling) {
                afterText += (sibling.textContent || '');
                sibling = sibling.nextSibling;
              }
              if (!afterText.trim() && nextElem) {
                afterText = nextElem.textContent || '';
              }
              if (/^\s*\**(?:[\(<\[])?\s*(?:도표|그림|표|차트|자료|출처)\s*[:：]/i.test(afterText.trim())) {
                hasCaptionAfter = true;
              }
            }

            const figure = document.createElement('figure');
            figure.className = 'my-6 p-3 bg-slate-800/50 rounded-2xl border border-slate-700/70 max-w-full flex flex-col items-center shadow-inner';
            
            // img 복제 및 figure 구성
            const imgClone = img.cloneNode(true);
            figure.appendChild(imgClone);

            // 본문 직전에 제목이 명시되어 있거나 하단에 도표제목-출처 표시가 있는 경우 중복 figcaption 표기 생략
            if (altText && altText !== 'image' && !hasDuplicateTitleBefore && !hasCaptionAfter) {
              const caption = document.createElement('figcaption');
              caption.className = 'text-xs text-slate-400 mt-2.5 font-sans italic text-center';
              caption.innerHTML = `<i class="fa-regular fa-image text-brand-400 mr-1"></i> ${altText}`;
              figure.appendChild(caption);
            }

            // 클릭 시 라이트박스 모달 줌 연결
            imgClone.addEventListener('click', () => {
              if (modalImage && imageModal) {
                modalImage.src = imgClone.src;
                if (modalCaption) modalCaption.textContent = altText || '문서 추출 이미지';
                imageModal.classList.remove('hidden');
              }
            });

            // 안전하게 DOM 노드 치환
            if (img.parentElement && img.parentElement.tagName === 'P' && img.parentElement.childNodes.length === 1) {
              img.parentElement.replaceWith(figure);
            } else {
              img.replaceWith(figure);
            }
          }
        });

        // [코드 문법 하이라이팅]
        if (window.hljs) {
          renderedContent.querySelectorAll('pre code').forEach(block => {
            try {
              window.hljs.highlightElement(block);
            } catch (e) {}
          });
        }

        // [수식 렌더링 (KaTeX)]
        if (window.renderMathInElement) {
          try {
            window.renderMathInElement(renderedContent, {
              delimiters: [
                {left: '$$', right: '$$', display: true},
                {left: '$', right: '$', display: false},
                {left: '\\(', right: '\\)', display: false},
                {left: '\\[', right: '\\]', display: true}
              ],
              throwOnError: false
            });
          } catch (e) {}
        }

        // [출처 링크 시각적 알약 배지화 및 문서 뷰어 내 클릭 이동 바인딩]
        renderedContent.querySelectorAll('a').forEach(link => {
          const href = link.getAttribute('href') || '';
          const text = link.textContent.trim();
          const isSourceLink = href.startsWith('/api/documents/') || href.includes('/documents/') || text.includes('출처');
          if (isSourceLink) {
            link.className = 'source-badge';
            link.title = '클릭 시 지식 DB 원본 문서로 이동하여 완본 열람';
            let cleanText = text.replace(/^[<\[\s]*출처\s*:\s*/, '').replace(/[>\]\s]*$/, '');
            link.innerHTML = `<i class="fa-solid fa-bookmark text-amber-400 mr-1"></i><span>&lt;출처 : <span class="font-semibold text-indigo-100 underline decoration-indigo-400/50">${cleanText || '원본 문서'}</span>&gt;</span>`;

            if (href.includes('/documents/')) {
              link.addEventListener('click', async (e) => {
                e.preventDefault();
                const parts = href.split('/api/documents/');
                const rawDocId = parts.length > 1 ? parts[1] : href.split('/').pop();
                const cleanDocId = decodeURIComponent(rawDocId)
                  .replace(/\[\^(\d+)\][,\]\)]*$/, '$1')
                  .replace(/[\],>.)]+$/, '')
                  .trim();

                showToast(`지식 DB 원본 문서로 이동: ${cleanDocId}`, 'info');
                switchTab('viewer');
                await loadDocument(cleanDocId);
                if (renderedContent && renderedContent.parentElement) {
                  renderedContent.parentElement.scrollTo({ top: 0, behavior: 'smooth' });
                }
              });
            }
          }
        });
      }
    } catch (err) {
      console.error('마크다운 렌더링 에러:', err);
      if (renderedContent) {
        renderedContent.innerHTML = `<pre class="whitespace-pre-wrap text-xs text-slate-300 font-mono">${content}</pre>`;
      }
    }

    // 목차 (TOC) 생성
    buildTableOfContents();
  }

  // 7. 목차 (TOC) 자동 추출
  function buildTableOfContents() {
    if (!tocContainer || !renderedContent) return;
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

  // 8. 원문 보기 / 렌더링 보기 토글
  if (toggleRawBtn) {
    toggleRawBtn.addEventListener('click', () => {
      isRawView = !isRawView;
      if (isRawView) {
        if (renderedContent) renderedContent.classList.add('hidden');
        if (rawContent) rawContent.classList.remove('hidden');
        toggleRawBtn.innerHTML = '<i class="fa-solid fa-eye"></i> <span class="hidden md:inline">렌더링 보기</span>';
      } else {
        if (renderedContent) renderedContent.classList.remove('hidden');
        if (rawContent) rawContent.classList.add('hidden');
        toggleRawBtn.innerHTML = '<i class="fa-solid fa-code"></i> <span class="hidden md:inline">원문 보기</span>';
      }
    });
  }

  // 9. 마크다운 원문 복사
  if (copyMdBtn) {
    copyMdBtn.addEventListener('click', async () => {
      if (!currentDoc || !currentDoc.content) return;
      try {
        await navigator.clipboard.writeText(currentDoc.content);
        showToast('마크다운 원문이 클립보드에 복사되었습니다.', 'success');
      } catch (err) {
        showToast('복사에 실패했습니다.', 'error');
      }
    });
  }

  // 9.5 헤더 문서 삭제 버튼
  if (deleteDocHeaderBtn) {
    deleteDocHeaderBtn.addEventListener('click', async () => {
      if (!currentDoc) return;
      const title = currentDoc.title || currentDoc.original_filename || '현재 문서';
      if (!confirm(`정말로 '${title}' 문서를 삭제하시겠습니까?\n\nWikiDB의 마크다운 파일 및 추출된 모든 이미지 에셋이 영구 삭제됩니다.`)) {
        return;
      }
      await deleteDocument(currentDoc.id);
    });
  }

  // 9.8 개별 문서 무결성 및 품질 검수 버튼
  // AI 생성 보고서(REPORT_ 접두사 또는 is_synthesized)의 경우 5대 기준 품질검수(review) API를,
  // 일반 원본 문서의 경우 무결성 검수(audit) API를 각각 호출한다.
  if (auditDocBtn) {
    auditDocBtn.addEventListener('click', async () => {
      if (!currentDoc) {
        showToast('선택된 문서가 없습니다.', 'warning');
        return;
      }

      if (auditIcon) auditIcon.className = 'fa-solid fa-spinner fa-spin';
      auditDocBtn.disabled = true;

      const isSynthesizedDoc = currentDoc.is_synthesized || currentDoc.id.startsWith('REPORT_');

      try {
        showToast('품질 검수 중...', 'info');

        if (isSynthesizedDoc) {
          // AI 생성 보고서: 5대 기준 품질검수 (review) API 호출
          const res = await fetch(`/api/topic/reports/${encodeURIComponent(currentDoc.id)}/review`, {
            method: 'POST'
          });
          if (!res.ok) {
            const err = await res.json().catch(() => ({}));
            throw new Error(err.detail || `검수 실패 (${res.status})`);
          }
          const data = await res.json();
          // currentTopicReport를 현재 문서 정보로 동기화하여 openReviewModal 내부의 제목 표시에 활용
          currentTopicReport = currentTopicReport || {};
          currentTopicReport.title = currentDoc.title || currentDoc.original_filename;
          currentActiveTopicReportId = currentDoc.id;
          openReviewModal(data.review || data);
          showToast('품질 검수가 완료되었습니다.', 'success');
        } else {
          // 원본 문서: 무결성 검수 (audit) API 호출
          const res = await fetch(`/api/documents/${encodeURIComponent(currentDoc.id)}/audit`, {
            method: 'POST'
          });
          if (!res.ok) {
            const err = await res.json().catch(() => ({}));
            throw new Error(err.detail || `검수 실패 (${res.status})`);
          }
          const report = await res.json();
          showAuditModal(report);
        }
      } catch (err) {
        console.error('품질 검수 오류:', err);
        showToast(`품질 검수 오류: ${err.message}`, 'error');
      } finally {
        if (auditIcon) auditIcon.className = 'fa-solid fa-shield-halved';
        auditDocBtn.disabled = false;
      }
    });
  }

  // 품질 검수 결과 모달 렌더링 함수
  function showAuditModal(report) {
    if (!auditModal) return;

    if (auditModalDocName) {
      auditModalDocName.textContent = currentDoc.title || currentDoc.original_filename;
    }

    const isHealthy = report.is_healthy;

    if (auditModalIconBg) {
      if (isHealthy) {
        auditModalIconBg.className = 'w-8 h-8 rounded-lg bg-emerald-500/20 text-emerald-400 flex items-center justify-center';
        auditModalIconBg.innerHTML = '<i class="fa-solid fa-circle-check text-base"></i>';
      } else {
        auditModalIconBg.className = 'w-8 h-8 rounded-lg bg-amber-500/20 text-amber-400 flex items-center justify-center';
        auditModalIconBg.innerHTML = '<i class="fa-solid fa-triangle-exclamation text-base"></i>';
      }
    }

    if (auditModalTitle) {
      auditModalTitle.textContent = isHealthy ? '품질 검수 통과 (무결성 100%)' : '품질 결함 감지 (보정 필요)';
    }

    let html = '';
    if (isHealthy) {
      html = `
        <div class="p-4 rounded-xl bg-emerald-500/10 border border-emerald-500/30 text-emerald-300 text-xs leading-relaxed space-y-2">
          <div class="font-bold flex items-center gap-1.5 text-emerald-400 text-sm">
            <i class="fa-solid fa-check"></i> 모든 품질 기준 합격
          </div>
          <p>kordoc-wiki-ingest 5대 원칙(무삭제, 불릿 계층, 수식, 표, 인라인 이미지)에 완벽히 부합하며 누락된 단락이나 서식 결함이 없습니다.</p>
          <div class="text-[11px] text-emerald-400/80 pt-1 border-t border-emerald-500/20">
            검사 페이지: ${report.inspected_pages || 'N/A'}p | 발견된 결함: 0건
          </div>
        </div>
      `;
      if (executeHealBtn) executeHealBtn.classList.add('hidden');
    } else {
      const redFlags = report.red_flags || [];
      const missingSecs = report.missing_sections || [];
      const missingTables = report.missing_tables || [];
      const totalIssues = (report.issues || []).length + redFlags.length;

      html = `
        <div class="p-3.5 rounded-xl bg-amber-500/10 border border-amber-500/30 text-amber-300 text-xs space-y-2">
          <div class="font-bold flex items-center gap-1.5 text-amber-400 text-sm">
            <i class="fa-solid fa-circle-exclamation"></i> 총 ${totalIssues}건의 보정 대상 결함 발견
          </div>
          <p class="text-slate-300">원문 대조 검사 결과 누락 단락 또는 서식 규격 미달이 감지되었습니다. 아래 [자율 치유 실행] 버튼을 누르면 원클릭으로 자동 보정됩니다.</p>
        </div>

        <div class="space-y-2">
          <h4 class="text-xs font-semibold text-slate-300 flex items-center gap-1">
            <i class="fa-solid fa-list-check text-slate-400"></i> 세부 결함 내역
          </h4>
          <div class="max-h-48 overflow-y-auto space-y-1.5 pr-1 text-xs">
      `;

      if (redFlags.length > 0) {
        redFlags.forEach(rf => {
          html += `
            <div class="p-2 rounded-lg bg-slate-900/80 border border-slate-700/80 text-rose-300 flex items-start gap-2">
              <i class="fa-solid fa-flag text-rose-400 mt-0.5 shrink-0 text-[10px]"></i>
              <span class="break-words">${rf}</span>
            </div>
          `;
        });
      }

      if (missingSecs.length > 0) {
        missingSecs.slice(0, 5).forEach(sec => {
          html += `
            <div class="p-2 rounded-lg bg-slate-900/80 border border-slate-700/80 text-amber-200/90 flex items-start gap-2">
              <i class="fa-solid fa-file-circle-xmark text-amber-400 mt-0.5 shrink-0 text-[10px]"></i>
              <span class="break-words">원문 단락 누락: ${sec}</span>
            </div>
          `;
        });
        if (missingSecs.length > 5) {
          html += `<div class="text-[11px] text-slate-400 pl-2">...외 ${missingSecs.length - 5}건 단락 누락</div>`;
        }
      }

      if (missingTables.length > 0) {
        missingTables.slice(0, 5).forEach(tbl => {
          html += `
            <div class="p-2 rounded-lg bg-slate-900/80 border border-slate-700/80 text-cyan-200/90 flex items-start gap-2">
              <i class="fa-solid fa-table text-cyan-400 mt-0.5 shrink-0 text-[10px]"></i>
              <span class="break-words">원문 표 누락: ${tbl}</span>
            </div>
          `;
        });
      }

      html += `
          </div>
        </div>
      `;

      if (executeHealBtn) {
        executeHealBtn.classList.remove('hidden');
        if (healBtnText) healBtnText.textContent = '자율 치유 실행';
        executeHealBtn.disabled = false;
      }
    }

    if (auditModalBody) auditModalBody.innerHTML = html;
    auditModal.classList.remove('hidden');
  }

  // 자율 치유 실행 버튼
  if (executeHealBtn) {
    executeHealBtn.addEventListener('click', async () => {
      if (!currentDoc) return;

      if (healBtnText) healBtnText.textContent = '치유 작업 중...';
      executeHealBtn.disabled = true;

      try {
        showToast('자율 치유를 진행하고 있습니다. 잠시만 기다려주십시오...', 'info');
        const res = await fetch(`/api/documents/${encodeURIComponent(currentDoc.id)}/heal`, {
          method: 'POST'
        });

        if (!res.ok) {
          const err = await res.json().catch(() => ({}));
          throw new Error(err.detail || `치유 실패 (${res.status})`);
        }

        const data = await res.json();
        showToast(data.message || '자율 치유가 완료되었습니다.', 'success');

        if (auditModal) auditModal.classList.add('hidden');

        // 최신 치유된 문서 본문 즉시 재로드
        await loadDocument(currentDoc.id);
        await fetchDocuments();
      } catch (err) {
        console.error('자율 치유 오류:', err);
        showToast(`치유 실패: ${err.message}`, 'error');
      } finally {
        if (healBtnText) healBtnText.textContent = '자율 치유 실행';
        executeHealBtn.disabled = false;
      }
    });
  }

  // 품질 검수 모달 닫기 이벤트
  if (closeAuditModalBtn) closeAuditModalBtn.addEventListener('click', () => auditModal && auditModal.classList.add('hidden'));
  if (closeAuditModalBottomBtn) closeAuditModalBottomBtn.addEventListener('click', () => auditModal && auditModal.classList.add('hidden'));
  if (auditModal) {
    auditModal.addEventListener('click', (e) => {
      if (e.target === auditModal) auditModal.classList.add('hidden');
    });
  }

  // 10. 라이트박스 모달 닫기
  if (closeModalBtn) closeModalBtn.addEventListener('click', () => imageModal && imageModal.classList.add('hidden'));
  if (imageModal) {
    imageModal.addEventListener('click', (e) => {
      if (e.target === imageModal) imageModal.classList.add('hidden');
    });
  }

  // 11. Source 폴더 및 Google Drive 원격 동기화 실행 (로컬/클라우드 하이브리드 지원)
  if (scanBtn) {
    scanBtn.addEventListener('click', async () => {
      if (scanIcon) scanIcon.classList.add('animate-spin');
      try {
        const res = await fetch('/api/scan', { method: 'POST' });
        const data = await res.json();
        if (!res.ok) {
          showToast(data.detail || '동기화 중 오류가 발생했습니다.', 'error');
          return;
        }
        const successMsg = data.message || `동기화 완료: ${data.processed_count || 0}건 갱신`;
        showToast(successMsg, 'success');
        await fetchDocuments();
      } catch (err) {
        showToast('동기화 통신 중 오류가 발생했습니다.', 'error');
      } finally {
        if (scanIcon) scanIcon.classList.remove('animate-spin');
      }
    });
  }

  // 12. 파일 직접 업로드
  if (fileUploadInput) {
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
  }

  // 13. 검색 필터링 및 새로고침 이벤트
  if (searchInput) searchInput.addEventListener('input', renderDocumentList);
  if (refreshListBtn) refreshListBtn.addEventListener('click', () => fetchDocuments());

  // 14. 탭 전환 제어
  function switchTab(tabName) {
    if (!tabBtnViewer || !tabBtnGenerator || !viewerTabContent || !generatorTabContent) return;

    if (tabName === 'viewer') {
      tabBtnViewer.className = 'px-3 py-1.5 text-xs font-semibold rounded-lg bg-brand-600 text-white shadow-md transition flex items-center gap-1.5 cursor-pointer';
      tabBtnGenerator.className = 'px-3 py-1.5 text-xs font-semibold rounded-lg text-slate-400 hover:text-white hover:bg-slate-700/50 transition flex items-center gap-1.5 cursor-pointer';
      viewerTabContent.classList.remove('hidden');
      generatorTabContent.classList.add('hidden');
    } else {
      tabBtnGenerator.className = 'px-3 py-1.5 text-xs font-semibold rounded-lg bg-brand-600 text-white shadow-md transition flex items-center gap-1.5 cursor-pointer';
      tabBtnViewer.className = 'px-3 py-1.5 text-xs font-semibold rounded-lg text-slate-400 hover:text-white hover:bg-slate-700/50 transition flex items-center gap-1.5 cursor-pointer';
      generatorTabContent.classList.remove('hidden');
      viewerTabContent.classList.add('hidden');
      if (topicInput) topicInput.focus();
    }
  }

  if (tabBtnViewer) tabBtnViewer.addEventListener('click', () => switchTab('viewer'));
  if (tabBtnGenerator) tabBtnGenerator.addEventListener('click', () => switchTab('generator'));

  // 15. 추천 키워드 로드
  async function loadTopicSuggestions() {
    if (!topicSuggestionsBar) return;
    try {
      const res = await fetch('/api/topic/suggestions');
      if (!res.ok) return;
      const data = await res.json();
      const list = data.suggestions || [];
      if (list.length === 0) return;

      topicSuggestionsBar.innerHTML = list.map(kw => `
        <button class="suggestion-tag px-2 py-0.5 rounded-md bg-slate-700/70 hover:bg-brand-600/80 hover:text-white text-slate-300 text-[11px] border border-slate-600/60 transition cursor-pointer" data-keyword="${kw}">
          #${kw}
        </button>
      `).join('');

      topicSuggestionsBar.querySelectorAll('.suggestion-tag').forEach(tag => {
        tag.addEventListener('click', () => {
          const kw = tag.getAttribute('data-keyword');
          if (topicInput) {
            topicInput.value = kw;
            topicInput.focus();
          }
        });
      });
    } catch (err) {
      console.warn('추천 키워드 로드 실패:', err);
    }
  }

  // 16. 생성 이력 패널 로드
  async function loadTopicHistory() {
    if (!topicHistoryList) return;
    try {
      const res = await fetch('/api/topic/reports');
      if (!res.ok) return;
      const reports = await res.json();
      
      if (reportCountBadge) reportCountBadge.textContent = `${reports.length}건`;

      if (reports.length === 0) {
        topicHistoryList.innerHTML = `
          <div class="text-center py-8 text-slate-500 text-xs">
            <i class="fa-solid fa-clock-rotate-left text-xl mb-1 opacity-40"></i>
            <p>생성된 보고서가 없습니다.</p>
          </div>
        `;
        return;
      }

      topicHistoryList.innerHTML = reports.map(rep => {
        const isSelected = currentTopicReport && currentTopicReport.id === rep.id;
        return `
          <div class="history-item p-2.5 rounded-xl border transition cursor-pointer ${
            isSelected 
              ? 'bg-purple-900/40 border-purple-500 text-white' 
              : 'bg-slate-800/60 border-slate-700/60 hover:bg-slate-700/50 hover:border-slate-600 text-slate-300'
          }" data-id="${rep.id}">
            <div class="flex items-center justify-between text-[10px] text-purple-300 font-semibold mb-1">
              <span class="truncate"><i class="fa-solid fa-robot mr-1"></i>${rep.topic || '주제'}</span>
              <span class="text-slate-400 font-normal">${rep.ingested_at ? rep.ingested_at.split(' ')[0] : ''}</span>
            </div>
            <h5 class="text-xs font-medium truncate text-slate-100" title="${rep.title}">${rep.title}</h5>
            <div class="flex items-center justify-between text-[10px] text-slate-500 mt-1">
              <span>${formatBytes(rep.file_size)}</span>
              <span class="hover:text-purple-300"><i class="fa-solid fa-chevron-right text-[9px]"></i></span>
            </div>
          </div>
        `;
      }).join('');

      topicHistoryList.querySelectorAll('.history-item').forEach(item => {
        item.addEventListener('click', async () => {
          const id = item.getAttribute('data-id');
          await loadTopicReportDetail(id);
        });
      });
    } catch (err) {
      console.warn('생성 이력 로드 실패:', err);
    }
  }

  // 17. 특정 생성 보고서 불러오기
  async function loadTopicReportDetail(reportId) {
    try {
      showToast('보고서를 불러오는 중...', 'info');
      const res = await fetch(`/api/topic/reports/${encodeURIComponent(reportId)}`);
      if (!res.ok) throw new Error('보고서 로드 실패');
      const data = await res.json();
      currentTopicReport = data;
      currentActiveTopicReportId = data.id || reportId;

      if (reportTitleHeading) reportTitleHeading.textContent = data.title;
      if (reportDateBadge) reportDateBadge.textContent = data.ingested_at || '';

      renderTopicMarkdown(data.content || data.markdown || '');

      if (topicEmptyState) topicEmptyState.classList.add('hidden');
      if (topicLoadingState) topicLoadingState.classList.add('hidden');
      if (topicReportViewer) topicReportViewer.classList.remove('hidden');

      loadTopicHistory();
    } catch (err) {
      console.error('보고서 로드 오류:', err);
      showToast(`보고서 로드 실패: ${err.message}`, 'error');
    }
  }

  // 18. 보고서 마크다운 렌더링 및 크로스 탭 출처 링크 바인딩
  function renderTopicMarkdown(mdText) {
    if (!topicRenderedContent) return;

    // [공통 전처리기 적용: 표 정규화, 인라인 이미지 분리, 출처 표기 보정]
    let preprocessedMd = preprocessMarkdown(mdText || '');
    preprocessedMd = preprocessedMd.replace(/(?:<출처\s*:\s*\[(.*?)\]\(((?:\/api\/documents\/)?[^)]+)\)>[ \t]*,?[ \t]*)+/g, (full) => {
      const regex = /<출처\s*:\s*\[(.*?)\]\(((?:\/api\/documents\/)?[^)]+)\)>/g;
      let match;
      const seen = new Set();
      const unique = [];
      while ((match = regex.exec(full)) !== null) {
        const title = match[1];
        const link = match[2];
        const key = title.replace(/[\s_()\[\]\-\.]+/g, '').toLowerCase();
        if (!seen.has(key)) {
          seen.add(key);
          unique.push(`<출처: [${title}](${link})>`);
        }
      }
      return unique.join(', ');
    });

    // 출처 표기 정규화:
    // 1) 링크가 포함된 <출처: [문서](링크)> 또는 복수 출처 태그는 껍데기를 벗겨 마크다운 링크로 노출
    // 2) 링크가 없는 순수 평문 <출처: 기관명>은 마크다운 파싱 전 안전하게 알약 배지 HTML로 선치환
    const normalizedMd = preprocessedMd.replace(/<출처\s*:\s*([^>]+)>/g, (match, inner) => {
      if (inner.includes('](')) {
        return inner.trim();
      }
      return `<span class="source-badge"><i class="fa-solid fa-bookmark text-amber-400 mr-1"></i><span>&lt;출처 : <span class="font-semibold text-indigo-100">${inner.trim()}</span>&gt;</span></span>`;
    });

    // 출처 배지 치환 후에도 뒤에 개행 없이 붙은 헤딩이 있는 경우 최종 분리 보장
    const finalMd = normalizedMd.replace(/([^\n#])[ \t]*(#{1,6}\s+[^\n]+)/g, '$1\n\n$2');

    // marked 렌더링
    if (typeof marked !== 'undefined') {
      if (typeof marked.use === 'function') {
        marked.use(markedConfig);
      }
      topicRenderedContent.innerHTML = sanitizeHtml(marked.parse(finalMd));
    } else {
      topicRenderedContent.textContent = finalMd;
    }


    // KaTeX 수식 렌더링
    if (typeof renderMathInElement !== 'undefined') {
      renderMathInElement(topicRenderedContent, {
        delimiters: [
          { left: '$$', right: '$$', display: true },
          { left: '$', right: '$', display: false }
        ],
        throwOnError: false
      });
    }

    // 코드 하이라이트
    if (typeof hljs !== 'undefined') {
      topicRenderedContent.querySelectorAll('pre code').forEach(block => {
        hljs.highlightElement(block);
      });
    }

    // 본문 내 이미지 클릭 시 라이트박스 팝업 연동
    topicRenderedContent.querySelectorAll('img').forEach(img => {
      img.classList.add('cursor-zoom-in', 'hover:opacity-90', 'transition', 'rounded-lg', 'shadow-md');
      img.addEventListener('click', () => {
        if (typeof openImageModal === 'function') {
          openImageModal(img.src, img.alt);
        } else if (imageModal && modalImage) {
          modalImage.src = img.src;
          if (modalCaption) modalCaption.textContent = img.alt || '';
          imageModal.classList.remove('hidden');
        }
      });
    });

    // 출처 하이퍼링크 크로스 탭 내비게이션 및 시각적 알약 배지(Badge) 바인딩
    topicRenderedContent.querySelectorAll('a').forEach(link => {
      const href = link.getAttribute('href') || '';
      const text = link.textContent.trim();
      const isSourceLink = href.startsWith('/api/documents/') || href.includes('/documents/') || text.includes('출처');

      if (isSourceLink) {
        link.className = 'source-badge';
        link.title = '클릭 시 지식 DB 원본 문서로 이동하여 완본 열람';

        let cleanText = text.replace(/^[<\[\s]*출처\s*:\s*/, '').replace(/[>\]\s]*$/, '');
        if (!cleanText) cleanText = '원본 문서';
        link.innerHTML = `<i class="fa-solid fa-bookmark text-amber-400 mr-1"></i><span>&lt;출처 : <span class="font-semibold text-indigo-100 underline decoration-indigo-400/50">${cleanText}</span>&gt;</span>`;

        link.addEventListener('click', async (e) => {
          e.preventDefault();
          const parts = href.split('/api/documents/');
          const rawDocId = parts.length > 1 ? parts[1] : href.split('/').pop();
          const cleanDocId = decodeURIComponent(rawDocId)
            .replace(/\[\^(\d+)\][,\]\)]*$/, '$1')
            .replace(/[\],>.)]+$/, '')
            .trim();

          showToast(`지식 DB 원본 문서로 이동: ${cleanDocId}`, 'info');
          switchTab('viewer');
          await loadDocument(cleanDocId);
        });
      }
    });

    // 5. 데이터 출처 섹션 목록 내 동일 문헌 중복 li 요소 정리
    const allHeaders = Array.from(topicRenderedContent.querySelectorAll('h1, h2, h3'));
    const sec5Header = allHeaders.find(h => h.textContent.includes('데이터 출처') || h.textContent.includes('5. 데이터'));
    if (sec5Header) {
      let nextElem = sec5Header.nextElementSibling;
      while (nextElem && !['H1', 'H2', 'H3'].includes(nextElem.tagName)) {
        if (nextElem.tagName === 'UL' || nextElem.tagName === 'OL') {
          const seenKeys = new Set();
          Array.from(nextElem.querySelectorAll('li')).forEach(li => {
            const rawText = li.textContent.replace(/[\s_()\[\]\-\.]+/g, '').replace(/출처/g, '').toLowerCase();
            if (seenKeys.has(rawText)) {
              li.remove();
            } else {
              seenKeys.add(rawText);
            }
          });
        }
        nextElem = nextElem.nextElementSibling;
      }
    }
  }

  // 19. 보고서 생성 실행
  async function generateTopicReport() {
    const topic = topicInput ? topicInput.value.trim() : '';
    if (!topic) {
      showToast('생성할 주제어를 입력해 주십시오.', 'error');
      if (topicInput) topicInput.focus();
      return;
    }

    // 로딩 상태 시작
    if (btnGenerateTopic) btnGenerateTopic.disabled = true;
    if (genIcon) genIcon.className = 'fa-solid fa-spinner animate-spin';
    if (genBtnText) genBtnText.textContent = '생성 중...';

    if (topicEmptyState) topicEmptyState.classList.add('hidden');
    if (topicReportViewer) topicReportViewer.classList.add('hidden');
    if (topicLoadingState) topicLoadingState.classList.remove('hidden');

    // 단계별 상태 메시지 애니메이션
    const stages = [
      { title: 'WikiDB 지식 데이터베이스 탐색 중...', desc: '축적된 완본 문서들에서 주제 키워드와 연관 섹션을 매핑하고 있습니다.', progress: '30%' },
      { title: '핵심 텍스트 및 도표 이미지 추출 중...', desc: '인용에 활용할 기술 아키텍처 다이어그램 및 시장 규모 그래프를 선별하고 있습니다.', progress: '65%' },
      { title: 'Gemini LLM 5대 목차 보고서 종합 작성 중...', desc: '기술개요, 기술동향, 시장동향, 주요업체, 데이터 출처 체계로 완본 마크다운을 작성 중입니다.', progress: '90%' }
    ];

    let currentStage = 0;
    const stageTimer = setInterval(() => {
      currentStage = (currentStage + 1) % stages.length;
      if (loadingStageTitle) loadingStageTitle.textContent = stages[currentStage].title;
      if (loadingStageDesc) loadingStageDesc.textContent = stages[currentStage].desc;
      if (loadingProgressBar) loadingProgressBar.style.width = stages[currentStage].progress;
    }, 4000);

    try {
      // 1. 비동기 작업 등록 요청 (Cloud Run 및 모바일 타임아웃 방어)
      const res = await fetch('/api/topic/generate/async', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ topic: topic })
      });

      if (!res.ok) {
        clearInterval(stageTimer);
        const errData = await res.json().catch(() => ({}));
        throw new Error(errData.detail || `보고서 작업 등록 실패 (${res.status})`);
      }

      const { task_id } = await res.json();

      // 2. 1초 주기로 백그라운드 작업 상태 폴링 (최대 180초 대기)
      let pollCount = 0;
      let reportData = null;
      while (pollCount < 180) {
        await new Promise(resolve => setTimeout(resolve, 1000));
        pollCount++;

        try {
          const statusRes = await fetch(`/api/topic/tasks/${encodeURIComponent(task_id)}`);
          if (!statusRes.ok) continue;

          const task = await statusRes.json();
          // 실시간 진행 상황 UI 업데이트
          if (task.message && loadingStageTitle) {
            loadingStageTitle.textContent = task.message;
          }
          if (typeof task.progress === 'number' && loadingProgressBar) {
            loadingProgressBar.style.width = `${Math.max(task.progress, 15)}%`;
          }

          if (task.status === 'COMPLETED') {
            reportData = task.result;
            break;
          } else if (task.status === 'FAILED') {
            throw new Error(task.error || '보고서 생성 작업에 실패하였습니다.');
          }
        } catch (pollErr) {
          if (pollErr.message && pollErr.message.includes('실패')) throw pollErr;
          console.warn('작업 상태 폴링 일시 오류 (재시도 중):', pollErr);
        }
      }

      clearInterval(stageTimer);

      if (!reportData) {
        throw new Error('보고서 생성 대기 시간이 초과되었습니다. 잠시 후 보고서 목록을 확인해 주십시오.');
      }
      currentTopicReport = reportData;
      currentActiveTopicReportId = reportData.id;

      // 렌더링
      if (reportTitleHeading) reportTitleHeading.textContent = reportData.title;
      if (reportDateBadge) reportDateBadge.textContent = reportData.created_at || '';
      renderTopicMarkdown(reportData.markdown);

      if (topicLoadingState) topicLoadingState.classList.add('hidden');
      if (topicReportViewer) topicReportViewer.classList.remove('hidden');

      showToast(`'${topic}' 보고서가 성공적으로 생성 및 저장되었습니다!`, 'success');

      // 이력 및 사이드바 새로고침
      await loadTopicHistory();
      await fetchDocuments();
    } catch (err) {
      clearInterval(stageTimer);
      console.error('보고서 생성 실패:', err);
      showToast(err.message, 'error');
      if (topicLoadingState) topicLoadingState.classList.add('hidden');
      if (topicEmptyState) topicEmptyState.classList.remove('hidden');
    } finally {
      if (btnGenerateTopic) btnGenerateTopic.disabled = false;
      if (genIcon) genIcon.className = 'fa-solid fa-wand-magic-sparkles';
      if (genBtnText) genBtnText.textContent = '보고서 생성';
      if (loadingProgressBar) loadingProgressBar.style.width = '30%';
    }
  }

  if (btnGenerateTopic) {
    btnGenerateTopic.addEventListener('click', generateTopicReport);
  }
  if (topicInput) {
    topicInput.addEventListener('keydown', (e) => {
      if (e.key === 'Enter') {
        e.preventDefault();
        generateTopicReport();
      }
    });
  }

  // 20. 생성된 마크다운 복사 및 다운로드
  if (copyGenMdBtn) {
    copyGenMdBtn.addEventListener('click', async () => {
      if (!currentTopicReport || !currentTopicReport.markdown) {
        showToast('복사할 보고서 내용이 없습니다.', 'error');
        return;
      }
      try {
        await navigator.clipboard.writeText(currentTopicReport.markdown);
        showToast('보고서 마크다운이 클립보드에 복사되었습니다!', 'success');
      } catch (err) {
        showToast('클립보드 복사 실패', 'error');
      }
    });
  }

  if (downloadGenMdBtn) {
    downloadGenMdBtn.addEventListener('click', () => {
      if (!currentTopicReport || !currentTopicReport.markdown) {
        showToast('다운로드할 보고서가 없습니다.', 'error');
        return;
      }
      const blob = new Blob([currentTopicReport.markdown], { type: 'text/markdown;charset=utf-8' });
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = currentTopicReport.file_name || `${currentTopicReport.topic || 'report'}.md`;
      document.body.appendChild(a);
      a.click();
      document.body.removeChild(a);
      URL.revokeObjectURL(url);
      showToast('보고서 파일 다운로드가 시작되었습니다.', 'success');
    });
  }

  // 20-1. HTML 보고서 열기 (html-doc 편집기 내장 독립형 문서)
  function handleOpenHtmlReport() {
    const reportId = (currentDoc && currentDoc.id && currentDoc.id.startsWith('REPORT_') ? currentDoc.id : null)
      || currentActiveTopicReportId
      || (currentTopicReport && currentTopicReport.id);
    if (!reportId) {
      showToast('열람할 보고서가 선택되지 않았습니다.', 'error');
      return;
    }
    const url = `/api/topic/reports/${encodeURIComponent(reportId)}/export/html`;
    const win = window.open(url, '_blank');
    if (!win) {
      window.location.href = url;
    }
    showToast('독립 실행형 편집 가능 HTML 보고서를 새 탭에서 엽니다.', 'info');
  }

  // 20-2. HTML 양식 100% 보존 고품질 PDF 저장/인쇄 (브라우저 벡터 엔진 활용)
  async function handleDownloadPdfReport() {
    const reportId = (currentDoc && currentDoc.id && currentDoc.id.startsWith('REPORT_') ? currentDoc.id : null)
      || currentActiveTopicReportId
      || (currentTopicReport && currentTopicReport.id);
    if (!reportId) {
      showToast('저장할 보고서가 선택되지 않았습니다.', 'error');
      return;
    }
    showToast('HTML 보고서 양식 그대로 PDF 저장/인쇄 창을 준비 중입니다...', 'info');
    try {
      const printUrl = `/api/topic/reports/${encodeURIComponent(reportId)}/export/html?print_mode=true`;

      // 기존 인쇄 프레임이 남아있다면 제거
      const oldFrame = document.getElementById('reportPrintFrame');
      if (oldFrame) oldFrame.remove();

      // 보이지 않는 백그라운드 iframe 생성하여 완본 HTML 로드 후 인쇄 트리거
      const iframe = document.createElement('iframe');
      iframe.id = 'reportPrintFrame';
      iframe.style.position = 'fixed';
      iframe.style.right = '0';
      iframe.style.bottom = '0';
      iframe.style.width = '0';
      iframe.style.height = '0';
      iframe.style.border = '0';
      iframe.src = printUrl;

      let triggered = false;
      const triggerPrint = () => {
        if (triggered) return;
        triggered = true;
        try {
          iframe.contentWindow.focus();
          iframe.contentWindow.print();
          showToast('인쇄 창에서 "PDF로 저장"을 선택하시면 HTML 양식 그대로 저장됩니다.', 'success');
        } catch (e) {
          console.warn('iframe 인쇄 실패, 새 탭 인쇄로 폴백합니다:', e);
          const win = window.open(printUrl, '_blank');
          if (!win) window.location.href = printUrl;
        }
      };

      iframe.onload = () => {
        setTimeout(triggerPrint, 350);
      };

      // 타임아웃 안전장치 (지연 시 2.5초 후 폴백 창 열기)
      setTimeout(() => {
        if (!triggered) {
          triggerPrint();
        }
      }, 2500);

      document.body.appendChild(iframe);
    } catch (err) {
      console.error('PDF 인쇄 창 호출 실패:', err);
      // 최종 비상 폴백: 백엔드 바이너리 직접 다운로드
      const fallbackUrl = `/api/topic/reports/${encodeURIComponent(reportId)}/export/pdf`;
      window.open(fallbackUrl, '_blank');
    }
  }

  if (btnOpenHtmlReport) btnOpenHtmlReport.addEventListener('click', handleOpenHtmlReport);
  if (btnDownloadPdfReport) btnDownloadPdfReport.addEventListener('click', handleDownloadPdfReport);
  if (docHtmlBtn) docHtmlBtn.addEventListener('click', handleOpenHtmlReport);
  if (docPdfBtn) docPdfBtn.addEventListener('click', handleDownloadPdfReport);

  // 21. 보고서 품질 검수 모달 열기 및 렌더링
  function openReviewModal(reviewData) {
    if (!reportReviewModal) return;
    lastReviewResult = reviewData;

    // 모달 상단 보고서 제목 표시
    if (reviewModalReportTitle) {
      reviewModalReportTitle.textContent = (currentTopicReport && currentTopicReport.title)
        ? currentTopicReport.title
        : (currentActiveTopicReportId || '보고서 검수');
    }

    // 5대 핵심 체크리스트 렌더링 (점수 메타데이터는 UI에 노출하지 않음)
    if (reviewChecklistContainer) {
      const checklistItems = [
        { key: 'structure_valid', label: '5대 표준 목차 준수 (기술개요~데이터출처)' },
        { key: 'tables_valid', label: '3대 필수 비교 표 구비 (기술/시장/기업)' },
        { key: 'quantitative_data_valid', label: '정량 데이터 및 단위 규격 충실도' },
        { key: 'images_valid', label: '시각 자산(도표 및 구조도) 결합' },
        { key: 'tone_valid', label: '전문 보고서 어조 및 AI 상투어 배제' }
      ];

      const checklist = (reviewData && reviewData.checklist) || {};

      // WikiDB 신규 지식 동기화 검사 항목이 포함된 경우 체크리스트에 동적 추가
      if (checklist.fresh_knowledge_synced !== undefined) {
        checklistItems.push({
          key: 'fresh_knowledge_synced',
          label: 'WikiDB 최신 등재 지식 동기화 상태'
        });
      }

      reviewChecklistContainer.innerHTML = checklistItems.map(item => {
        const isValid = Boolean(checklist[item.key]);
        const statusBadge = isValid
          ? '<span class="text-[10px] font-bold px-2 py-0.5 rounded bg-emerald-900/60 text-emerald-300 border border-emerald-500/30 flex items-center gap-1"><i class="fa-solid fa-check text-[9px]"></i> 통과</span>'
          : '<span class="text-[10px] font-bold px-2 py-0.5 rounded bg-rose-900/60 text-rose-300 border border-rose-500/30 flex items-center gap-1"><i class="fa-solid fa-xmark text-[9px]"></i> 미흡</span>';

        return `
          <div class="flex items-center justify-between p-2 rounded-lg bg-slate-900/60 border ${isValid ? 'border-slate-700/60' : 'border-rose-500/40'}">
            <span class="text-xs ${isValid ? 'text-slate-200' : 'text-rose-200 font-medium'} flex items-center gap-2">
              <i class="fa-solid ${isValid ? 'fa-circle-check text-emerald-400' : 'fa-circle-exclamation text-rose-400'} text-xs"></i>
              ${item.label}
            </span>
            ${statusBadge}
          </div>
        `;
      }).join('');
    }

    // 지적된 결함 목록 렌더링
    if (reviewDefectsList) {
      const defects = (reviewData && reviewData.defects) || [];
      if (defects.length > 0) {
        if (reviewDefectsSection) reviewDefectsSection.classList.remove('hidden');
        reviewDefectsList.innerHTML = defects.map(defect => `
          <div class="p-2.5 rounded-lg bg-rose-950/40 border border-rose-500/30 text-rose-200 text-xs flex items-start gap-2">
            <i class="fa-solid fa-triangle-exclamation text-rose-400 mt-0.5 shrink-0"></i>
            <div class="flex-1">${defect}</div>
          </div>
        `).join('');
      } else {
        reviewDefectsList.innerHTML = `
          <div class="p-2.5 rounded-lg bg-emerald-950/40 border border-emerald-500/30 text-emerald-200 text-xs flex items-center gap-2">
            <i class="fa-solid fa-circle-check text-emerald-400 shrink-0"></i>
            <span>지적된 결함이 없습니다. 모든 품질 기준을 충족합니다.</span>
          </div>
        `;
      }
    }

    // 권장 개선 제안 렌더링
    if (reviewSuggestionsList) {
      const suggestions = (reviewData && reviewData.actionable_suggestions) || [];
      if (suggestions.length > 0) {
        if (reviewSuggestionsSection) reviewSuggestionsSection.classList.remove('hidden');
        reviewSuggestionsList.innerHTML = suggestions.map(sugg => `
          <div class="p-2.5 rounded-lg bg-amber-950/30 border border-amber-500/30 text-amber-200 text-xs flex items-start gap-2">
            <i class="fa-solid fa-lightbulb text-amber-400 mt-0.5 shrink-0"></i>
            <div class="flex-1">${sugg}</div>
          </div>
        `).join('');
      } else {
        reviewSuggestionsList.innerHTML = `
          <div class="p-2.5 rounded-lg bg-slate-900/60 border border-slate-700/60 text-slate-400 text-xs">
            권장 개선 제안이 없습니다.
          </div>
        `;
      }
    }

    // 보정 버튼 상태 제어 (결함 또는 신규 지식이 있는 경우 적극 활성화)
    if (btnApplyRefine) {
      const defects = (reviewData && reviewData.defects) || [];
      const freshDocs = (reviewData && reviewData.fresh_docs) || [];
      const freshDocsCount = freshDocs.length || (reviewData && reviewData.fresh_docs_count) || 0;
      const hasDefectsOrFresh = defects.length > 0 || freshDocsCount > 0 || !(reviewData && reviewData.passed_all);

      if (!hasDefectsOrFresh) {
        btnApplyRefine.classList.add('opacity-60', 'pointer-events-none');
        btnApplyRefine.title = '모든 품질 기준을 통과하였고 최신 지식과 동기화되어 있어 추가 보정이 불필요합니다.';
        if (refineBtnText) refineBtnText.textContent = '피드백 반영 보정';
      } else {
        btnApplyRefine.classList.remove('opacity-60', 'pointer-events-none');
        if (freshDocsCount > 0) {
          btnApplyRefine.title = `WikiDB 최신 등재 문서(${freshDocsCount}건) 및 검수 피드백을 반영하여 보고서를 최신화합니다.`;
          if (refineBtnText) refineBtnText.textContent = `최신 지식(${freshDocsCount}건) 반영 보정`;
        } else {
          btnApplyRefine.title = '검수 피드백을 반영하여 보고서를 자동 보정합니다.';
          if (refineBtnText) refineBtnText.textContent = '피드백 반영 보정';
        }
      }
    }

    reportReviewModal.classList.remove('hidden');
  }

  // 22. 보고서 품질 검수 모달 닫기
  function closeReviewModal() {
    if (reportReviewModal) {
      reportReviewModal.classList.add('hidden');
    }
  }

  // 23. 모달 닫기 이벤트 리스너 바인딩
  if (btnCloseReviewModal) {
    btnCloseReviewModal.addEventListener('click', closeReviewModal);
  }
  if (btnCloseReviewModal2) {
    btnCloseReviewModal2.addEventListener('click', closeReviewModal);
  }
  if (reportReviewModal) {
    reportReviewModal.addEventListener('click', (e) => {
      if (e.target === reportReviewModal) {
        closeReviewModal();
      }
    });
  }

  // 24. 보고서 품질 검수 실행 이벤트 핸들러
  if (btnReviewReport) {
    btnReviewReport.addEventListener('click', async () => {
      const targetReportId = currentActiveTopicReportId || (currentTopicReport && currentTopicReport.id);
      if (!targetReportId) {
        showToast('검수할 대상 보고서가 없습니다. 보고서를 먼저 선택하거나 생성하십시오.', 'error');
        return;
      }

      // 로딩 상태 전환
      btnReviewReport.disabled = true;
      if (reviewIcon) reviewIcon.className = 'fa-solid fa-spinner animate-spin';
      if (btnReviewReportText) btnReviewReportText.textContent = '검수 중...';

      try {
        showToast('보고서 품질 검수를 진행하고 있습니다...', 'info');
        const res = await fetch(`/api/topic/reports/${encodeURIComponent(targetReportId)}/review`, {
          method: 'POST'
        });

        if (!res.ok) {
          const errData = await res.json().catch(() => ({}));
          throw new Error(errData.detail || `보고서 검수 실패 (${res.status})`);
        }

        const data = await res.json();
        const reviewData = data.review || data;
        openReviewModal(reviewData);
        showToast('품질 검수가 완료되었습니다.', 'success');
      } catch (err) {
        console.error('보고서 품질 검수 실패:', err);
        showToast(`품질 검수 실패: ${err.message}`, 'error');
      } finally {
        btnReviewReport.disabled = false;
        if (reviewIcon) reviewIcon.className = 'fa-solid fa-clipboard-check';
        if (btnReviewReportText) btnReviewReportText.textContent = '품질 검수';
      }
    });
  }

  // 25. 피드백 반영 보정 실행 이벤트 핸들러
  if (btnApplyRefine) {
    btnApplyRefine.addEventListener('click', async () => {
      const targetReportId = currentActiveTopicReportId || (currentTopicReport && currentTopicReport.id);
      if (!targetReportId) {
        showToast('보정할 대상 보고서 ID가 없습니다.', 'error');
        return;
      }
      if (!lastReviewResult) {
        showToast('반영할 검수 피드백 정보가 없습니다. 먼저 품질 검수를 실행하십시오.', 'error');
        return;
      }

      // 로딩 상태 전환
      btnApplyRefine.disabled = true;
      if (refineIcon) refineIcon.className = 'fa-solid fa-spinner animate-spin';
      if (refineBtnText) refineBtnText.textContent = '보정 반영 중...';

      try {
        showToast('피드백을 반영하여 보고서를 보정 중입니다. 잠시만 기다려 주십시오...', 'info');

        const res = await fetch(`/api/topic/reports/${encodeURIComponent(targetReportId)}/refine`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ feedback: lastReviewResult })
        });

        if (!res.ok) {
          const errData = await res.json().catch(() => ({}));
          throw new Error(errData.detail || `보고서 보정 실패 (${res.status})`);
        }

        const updatedReport = await res.json();
        currentTopicReport = updatedReport;
        currentActiveTopicReportId = updatedReport.id || targetReportId;

        // 뷰어 본문 및 헤더 즉시 리프레시
        if (reportTitleHeading) reportTitleHeading.textContent = updatedReport.title;
        if (reportDateBadge) reportDateBadge.textContent = updatedReport.ingested_at || updatedReport.created_at || '';
        renderTopicMarkdown(updatedReport.content || updatedReport.markdown || '');

        // 검수 모달 닫기
        closeReviewModal();

        showToast('피드백이 반영되어 보고서가 성공적으로 보정되었습니다!', 'success');

        // 사이드바 및 이력 목록 갱신
        if (typeof loadTopicHistory === 'function') await loadTopicHistory();
        if (typeof fetchDocuments === 'function') await fetchDocuments();
      } catch (err) {
        console.error('보고서 보정 실패:', err);
        showToast(`보고서 보정 실패: ${err.message}`, 'error');
      } finally {
        btnApplyRefine.disabled = false;
        if (refineIcon) refineIcon.className = 'fa-solid fa-wand-magic-sparkles';
        if (refineBtnText) refineBtnText.textContent = '피드백 반영 보정';
      }
    });
  }

  // 26. 스마트 자동 폴링 (Page Visibility API 적용: 모바일 배터리/데이터 절감)
  let documentPollingTimer = null;

  function startSmartPolling() {
    if (documentPollingTimer) clearInterval(documentPollingTimer);
    documentPollingTimer = setInterval(() => {
      if (document.visibilityState === 'visible') {
        fetchDocuments();
      }
    }, 5000);
  }

  function stopSmartPolling() {
    if (documentPollingTimer) {
      clearInterval(documentPollingTimer);
      documentPollingTimer = null;
    }
  }

  document.addEventListener('visibilitychange', () => {
    if (document.visibilityState === 'visible') {
      fetchDocuments();
      startSmartPolling();
    } else {
      stopSmartPolling();
    }
  });

  startSmartPolling();

  // 초기 실행
  fetchDocuments();
  loadTopicSuggestions();
  loadTopicHistory();
});

// PWA 지원을 위한 서비스 워커 등록
if ('serviceWorker' in navigator) {
  window.addEventListener('load', () => {
    navigator.serviceWorker
      .register('/service-worker.js')
      .then((reg) => {
        console.log('LLM Wiki PWA 서비스 워커 등록 완료:', reg.scope);
      })
      .catch((err) => {
        console.warn('PWA 서비스 워커 등록 실패:', err);
      });
  });
}
