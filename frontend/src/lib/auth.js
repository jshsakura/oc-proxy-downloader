import { writable, derived } from 'svelte/store';

// 인증 상태 스토어
export const isAuthenticated = writable(false);
export const authToken = writable(null);
export const authUser = writable(null);
export const authLoading = writable(true);
export const authRequired = writable(false); // 서버에서 인증이 필요한지 여부

// 토큰 유효성 검사
function isTokenValid(token) {
    if (!token) return false;
    
    try {
        // JWT 토큰의 페이로드 디코딩 (간단한 base64 디코딩)
        const payload = JSON.parse(atob(token.split('.')[1]));
        const now = Date.now() / 1000;
        
        // 만료 시간 확인
        return payload.exp > now;
    } catch (error) {
        console.error('Token validation error:', error);
        return false;
    }
}

// 인증 매니저 클래스
class AuthManager {
    constructor() {
        this.checkAuthOnInit();
    }

    async checkAuthOnInit() {
        authLoading.set(true);
        
        try {
            // 서버에서 인증 필요 여부 확인
            const statusResponse = await fetch('/api/auth/status');
            const statusData = await statusResponse.json();
            
            authRequired.set(statusData.authentication_enabled);
            
            if (!statusData.authentication_enabled) {
                // 인증이 비활성화된 경우
                isAuthenticated.set(true);
                authUser.set({ username: 'anonymous' });
                authLoading.set(false);
                return;
            }

            // 로컬 스토리지에서 토큰 확인
            const token = localStorage.getItem('auth_token');
            const username = localStorage.getItem('auth_username');

            if (token && isTokenValid(token)) {
                // 토큰이 유효한 경우 서버에서 재검증
                try {
                    const verifyResponse = await fetch('/api/auth/verify', {
                        method: 'POST',
                        headers: {
                            'Authorization': `Bearer ${token}`,
                            'Content-Type': 'application/json'
                        }
                    });

                    if (verifyResponse.ok) {
                        // 인증 성공
                        authToken.set(token);
                        authUser.set({ username });
                        isAuthenticated.set(true);
                    } else {
                        // 토큰이 서버에서 무효
                        this.logout();
                    }
                } catch (error) {
                    console.error('Token verification failed:', error);
                    this.logout();
                }
            } else {
                // 토큰이 없거나 만료된 경우
                this.logout();
            }
        } catch (error) {
            console.error('Auth initialization failed:', error);
            // 네트워크 오류 등의 경우 기본값 유지
            authRequired.set(false);
            isAuthenticated.set(true);
        } finally {
            authLoading.set(false);
        }
    }

    async login(username, password) {
        try {
            const response = await fetch('/api/auth/login', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                },
                body: JSON.stringify({ username, password }),
            });

            if (response.ok) {
                const data = await response.json();
                
                // 로컬 스토리지에 저장
                localStorage.setItem('auth_token', data.access_token);
                localStorage.setItem('auth_username', data.username);
                
                // 스토어 업데이트
                authToken.set(data.access_token);
                authUser.set({ username: data.username });
                isAuthenticated.set(true);
                
                return { success: true, data };
            } else {
                const errorData = await response.json();
                
                // 차단된 경우 남은 시간 포함
                if (response.status === 429) {
                    const remainingTime = response.headers.get('X-RateLimit-Remaining-Time');
                    if (remainingTime) {
                        return { 
                            success: false, 
                            error: errorData.detail,
                            remainingTime: parseInt(remainingTime)
                        };
                    }
                }
                
                return { success: false, error: errorData.detail };
            }
        } catch (error) {
            console.error('Login error:', error);
            return { success: false, error: 'Network error' };
        }
    }

    logout() {
        // 로컬 스토리지 클리어
        localStorage.removeItem('auth_token');
        localStorage.removeItem('auth_username');
        
        // 스토어 클리어
        authToken.set(null);
        authUser.set(null);
        isAuthenticated.set(false);
    }

    // API 호출을 위한 인증 헤더 가져오기
    getAuthHeaders() {
        const token = localStorage.getItem('auth_token');
        return token ? { 'Authorization': `Bearer ${token}` } : {};
    }
}

// 전역 인증 매니저 인스턴스
export const authManager = new AuthManager();

// 파생 스토어 - 로그인이 필요한 상태인지
export const needsLogin = derived(
    [authRequired, isAuthenticated, authLoading],
    ([$authRequired, $isAuthenticated, $authLoading]) => {
        return $authRequired && !$isAuthenticated && !$authLoading;
    }
);

// API 요청에 인증 헤더를 추가하는 fetch 래퍼
export async function authenticatedFetch(url, options = {}) {
    const headers = {
        ...options.headers,
        ...authManager.getAuthHeaders()
    };

    return fetch(url, {
        ...options,
        headers
    });
}