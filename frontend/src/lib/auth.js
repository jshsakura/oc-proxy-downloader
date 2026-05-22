import { writable, derived } from 'svelte/store';

// Authentication state stores
export const isAuthenticated = writable(false);
export const authToken = writable(null);
export const authUser = writable(null);
export const authLoading = writable(true);
export const authRequired = writable(false); // Whether the server requires authentication

// Validate the token
function isTokenValid(token) {
    if (!token) return false;
    
    try {
        // Decode the JWT token payload (simple base64 decode)
        const payload = JSON.parse(atob(token.split('.')[1]));
        const now = Date.now() / 1000;
        
        // Check the expiration time
        return payload.exp > now;
    } catch (error) {
        console.error('Token validation error:', error);
        return false;
    }
}

// Authentication manager class
class AuthManager {
    constructor() {
        this.checkAuthOnInit();
    }

    async checkAuthOnInit() {
        authLoading.set(true);
        
        try {
            // Check with the server whether authentication is required
            const statusResponse = await fetch('/api/auth/status');
            const statusData = await statusResponse.json();
            
            authRequired.set(statusData.authentication_enabled);
            
            if (!statusData.authentication_enabled) {
                // When authentication is disabled
                isAuthenticated.set(true);
                authUser.set({ username: 'anonymous' });
                authLoading.set(false);
                return;
            }

            // Check the token in local storage
            const token = localStorage.getItem('auth_token');
            const username = localStorage.getItem('auth_username');

            if (token && isTokenValid(token)) {
                // If the token is valid, re-verify it with the server
                try {
                    const verifyResponse = await fetch('/api/auth/verify', {
                        method: 'GET',
                        headers: {
                            'Authorization': `Bearer ${token}`,
                            'Content-Type': 'application/json'
                        }
                    });

                    if (verifyResponse.ok) {
                        // Authentication succeeded
                        authToken.set(token);
                        authUser.set({ username });
                        isAuthenticated.set(true);
                    } else {
                        // The token is invalid on the server
                        this.logout();
                    }
                } catch (error) {
                    console.error('Token verification failed:', error);
                    this.logout();
                }
            } else {
                // When the token is missing or expired
                this.logout();
            }
        } catch (error) {
            console.error('Auth initialization failed:', error);
            // Keep defaults on network errors and the like
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
                
                // Save to local storage
                localStorage.setItem('auth_token', data.access_token);
                localStorage.setItem('auth_username', data.username);
                
                // Update the stores
                authToken.set(data.access_token);
                authUser.set({ username: data.username });
                isAuthenticated.set(true);
                
                return { success: true, data };
            } else {
                const errorData = await response.json();
                
                // Include the remaining time when blocked
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
        // Clear local storage
        localStorage.removeItem('auth_token');
        localStorage.removeItem('auth_username');
        
        // Clear the stores
        authToken.set(null);
        authUser.set(null);
        isAuthenticated.set(false);
    }

    // Get the authentication headers for API calls
    getAuthHeaders() {
        const token = localStorage.getItem('auth_token');
        return token ? { 'Authorization': `Bearer ${token}` } : {};
    }
}

// Global authentication manager instance
export const authManager = new AuthManager();

// Derived store - whether a login is needed
export const needsLogin = derived(
    [authRequired, isAuthenticated, authLoading],
    ([$authRequired, $isAuthenticated, $authLoading]) => {
        return $authRequired && !$isAuthenticated && !$authLoading;
    }
);

// A fetch wrapper that adds authentication headers to API requests
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