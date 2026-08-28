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

  // 4. 문서 목록 가져오기 및 렌더링
  async function fetchDocuments(selectId = null) {
    try {
      const res = await fetch('/api/documents');
      if (!res.ok) throw new Error('문서 목록 조회 실패');
      documents = await res.json();
      renderDocumentList();

      if (selectId) {
        await loadDocument(selectId);
      } else if (currentDoc) {
        const stillExists = documents.find(d => d.id === currentDoc.id);
        if (stillExists) {
          // 메타데이터만 갱신하거나 내용 유지
          currentDoc = stillExists;
        }
      } else if (isInitialLoad && documents.length > 0) {
        // 첫 진입 시 첫 번째 문서 자동 로드
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
      const ext = (doc.original_filename || '').split('.').pop().toUpperCase() || 'DOC';
      
      let statusBadge = '';
      if (doc.status === 'completed') {
        statusBadge = '<span class="text-[10px] px-1.5 py-0.5 rounded border bg-emerald-500/20 text-emerald-300 border-emerald-500/30">완본</span>';
      } else if (doc.status === 'processing') {
        statusBadge = '<span class="text-[10px] px-1.5 py-0.5 rounded border bg-amber-500/20 text-amber-300 border-amber-500/30 flex items-center gap-1"><i class="fa-solid fa-spinner animate-spin text-[9px]"></i> AI 변환 중</span>';
      } else {
        statusBadge = '<span class="text-[10px] px-1.5 py-0.5 rounded border bg-rose-500/20 text-rose-300 border-rose-500/30">실패</span>';
      }

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
            ${statusBadge}
          </div>
          <h4 class="text-xs font-semibold text-white truncate mb-1" title="${doc.title}">
            ${doc.title || doc.original_filename}
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
      console.log('[Wiki] Loading document:', docId);
      const res = await fetch(`/api/documents/${encodeURIComponent(docId)}`);
      if (!res.ok) throw new Error(`문서 상세 조회 실패 (${res.status})`);
      currentDoc = await res.json();

      if (emptyView) emptyView.classList.add('hidden');
      if (documentViewer) documentViewer.classList.remove('hidden');

      // 메타데이터 렌더링
      const ext = (currentDoc.original_filename || '').split('.').pop().toUpperCase() || 'DOC';
      if (docFormatBadge) docFormatBadge.textContent = ext;
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

      // 마크다운 렌더링 실행
      await renderMarkdownContent(currentDoc.content || '');
      renderDocumentList();
    } catch (err) {
      console.error('문서 로드 오류:', err);
      showToast('문서 본문을 불러오지 못했습니다.', 'error');
    }
  }

  // 6. 안전하고 강력한 마크다운 렌더링 함수
  async function renderMarkdownContent(content) {
    if (rawContent) rawContent.textContent = content;

    try {
      let html = '';

      // 1. Marked.js 파싱 시도
      if (window.marked) {
        if (typeof window.marked.parse === 'function') {
          html = await Promise.resolve(window.marked.parse(content));
        } else if (typeof window.marked === 'function') {
          html = await Promise.resolve(window.marked(content));
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
        renderedContent.innerHTML = html;

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

          // 3. figure & figcaption 감싸기
          let containerElem = (img.parentElement && img.parentElement.tagName === 'P') ? img.parentElement : img;
          let prevElem = containerElem.previousElementSibling;
          let hasDuplicateTitleBefore = false;

          if (prevElem && altText) {
            const prevText = prevElem.textContent.trim().replace(/^[\s\*\#\-\_•·■]+/, '').replace(/[\s\*\#\-\_]+$/, '');
            const cleanAlt = altText.trim().replace(/^[\s\*\#\-\_•·■]+/, '').replace(/[\s\*\#\-\_]+$/, '');
            if (prevText && cleanAlt && (prevText === cleanAlt || prevText.includes(cleanAlt) || cleanAlt.includes(prevText))) {
              hasDuplicateTitleBefore = true;
            }
          }

          if (img.parentElement && img.parentElement.tagName !== 'FIGURE') {
            const figure = document.createElement('figure');
            figure.className = 'my-6 p-3 bg-slate-800/50 rounded-2xl border border-slate-700/70 max-w-full flex flex-col items-center shadow-inner';
            
            img.parentElement.insertBefore(figure, img);
            figure.appendChild(img);

            // 본문 직전에 이미 제목이 명시되어 있는 경우 중복 figcaption 표기 생략
            if (altText && altText !== 'image' && !hasDuplicateTitleBefore) {
              const caption = document.createElement('figcaption');
              caption.className = 'text-xs text-slate-400 mt-2.5 font-sans italic text-center';
              caption.innerHTML = `<i class="fa-regular fa-image text-brand-400 mr-1"></i> ${altText}`;
              figure.appendChild(caption);
            }
          }

          // 4. 클릭 시 라이트박스 모달 줌
          img.addEventListener('click', () => {
            if (modalImage && imageModal) {
              modalImage.src = img.src;
              if (modalCaption) modalCaption.textContent = altText || '문서 추출 이미지';
              imageModal.classList.remove('hidden');
            }
          });
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

  // 10. 라이트박스 모달 닫기
  if (closeModalBtn) closeModalBtn.addEventListener('click', () => imageModal && imageModal.classList.add('hidden'));
  if (imageModal) {
    imageModal.addEventListener('click', (e) => {
      if (e.target === imageModal) imageModal.classList.add('hidden');
    });
  }

  // 11. Source 폴더 수동 스캔 실행
  if (scanBtn) {
    scanBtn.addEventListener('click', async () => {
      if (scanIcon) scanIcon.classList.add('animate-spin');
      try {
        const res = await fetch('/api/scan', { method: 'POST' });
        const data = await res.json();
        showToast(`스캔 완료: 신규 ${data.processed_count}건 변환, ${data.skipped_count}건 중복 건너뜀`, 'success');
        await fetchDocuments();
      } catch (err) {
        showToast('스캔 중 오류가 발생했습니다.', 'error');
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

  // 14. 주기적 자동 폴링 (5초마다 문서 목록 갱신)
  setInterval(() => {
    fetchDocuments();
  }, 5000);

  // 초기 실행
  fetchDocuments();
});
