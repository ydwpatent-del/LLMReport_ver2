// LLM Wiki 서비스 워커 (PWA 지원 및 오프라인 캐싱)
const CACHE_NAME = 'llm-wiki-pwa-v1';
const STATIC_ASSETS = [
  '/',
  '/manifest.webmanifest',
  '/static/manifest.webmanifest',
  '/static/style.css',
  '/static/app.js',
  '/static/icons/icon-192.png',
  '/static/icons/icon-512.png',
  '/static/vendor/marked.min.js',
  '/static/vendor/highlight.min.js',
  '/static/vendor/atom-one-dark.min.css'
];

// 1. 설치(Install): 핵심 정적 자산 사전 캐싱 및 즉시 활성화 준비
self.addEventListener('install', (event) => {
  event.waitUntil(
    caches.open(CACHE_NAME).then((cache) => {
      return cache.addAll(STATIC_ASSETS);
    })
  );
  self.skipWaiting();
});

// 2. 활성화(Activate): 구버전 캐시 정리 및 활성 클라이언트 즉시 제어권 획득
self.addEventListener('activate', (event) => {
  event.waitUntil(
    caches.keys().then((keys) => {
      return Promise.all(
        keys.map((key) => {
          if (key !== CACHE_NAME) {
            return caches.delete(key);
          }
        })
      );
    })
  );
  self.clients.claim();
});

// 3. 요청 가로채기(Fetch):
// - API 및 백엔드 데이터 요청은 캐시 없이 항상 네트워크로 직접 통신
// - 정적 자원은 네트워크 우선(Network-First)으로 가져오고, 오프라인 시 캐시 폴백
self.addEventListener('fetch', (event) => {
  const url = new URL(event.request.url);

  // API 요청, 인증, 파일 업로드 등은 항상 네트워크로 직접 통신
  if (url.pathname.startsWith('/api') || url.pathname.startsWith('/login') || event.request.method !== 'GET') {
    return;
  }

  event.respondWith(
    fetch(event.request)
      .then((response) => {
        // 유효한 정상 응답(200 OK)인 경우 캐시 갱신
        if (response && response.status === 200 && response.type === 'basic') {
          const responseToCache = response.clone();
          caches.open(CACHE_NAME).then((cache) => {
            cache.put(event.request, responseToCache);
          });
        }
        return response;
      })
      .catch(() => {
        // 네트워크 단절 또는 오류 발생 시 캐시된 자원 반환
        return caches.match(event.request);
      })
  );
});
