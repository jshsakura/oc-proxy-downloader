<script>
  import { createEventDispatcher } from 'svelte';
  import { t } from './i18n.js';
  import { authManager } from './auth.js';
  
  const dispatch = createEventDispatcher();
  
  let username = '';
  let password = '';
  let showPassword = false;
  let isLoading = false;
  let error = '';
  let remainingLockoutTime = 0;
  let lockoutInterval = null;
  
  async function handleLogin() {
    if (!username || !password) {
      error = $t('login_fields_required');
      return;
    }
    
    isLoading = true;
    error = '';
    clearLockoutTimer();
    
    try {
      const result = await authManager.login(username, password);
      
      if (result.success) {
        // 로그인 성공 이벤트 발송
        dispatch('login', {
          token: result.data.access_token,
          username: result.data.username
        });
      } else {
        error = result.error || $t('login_failed');
        
        // 차단 시간이 있는 경우 카운트다운 시작
        if (result.remainingTime) {
          remainingLockoutTime = result.remainingTime;
          startLockoutTimer();
        }
      }
    } catch (err) {
      console.error('Login error:', err);
      error = $t('login_error');
    } finally {
      isLoading = false;
    }
  }
  
  function startLockoutTimer() {
    if (lockoutInterval) clearInterval(lockoutInterval);
    
    lockoutInterval = setInterval(() => {
      remainingLockoutTime--;
      
      if (remainingLockoutTime <= 0) {
        clearLockoutTimer();
        error = '';
      }
    }, 1000);
  }
  
  function clearLockoutTimer() {
    if (lockoutInterval) {
      clearInterval(lockoutInterval);
      lockoutInterval = null;
    }
    remainingLockoutTime = 0;
  }
  
  function formatLockoutTime(seconds) {
    const minutes = Math.floor(seconds / 60);
    const remainingSeconds = seconds % 60;
    return `${minutes}:${remainingSeconds.toString().padStart(2, '0')}`;
  }
  
  
  function handleKeyDown(event) {
    if (event.key === 'Enter') {
      handleLogin();
    }
  }
</script>

<div class="login-container">
  <div class="login-card">
    <div class="login-header">
      <div class="logo-container">
        <h1 class="logo-text">LOGIN</h1>
      </div>
    </div>
    
    <form class="login-form" on:submit|preventDefault={handleLogin}>
      {#if error}
        <div class="error-message" class:locked={remainingLockoutTime > 0}>
          {#if remainingLockoutTime > 0}
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
              <rect x="3" y="11" width="18" height="11" rx="2" ry="2"/>
              <circle cx="12" cy="16" r="1"/>
              <path d="M7 11V7a5 5 0 0110 0v4"/>
            </svg>
            {error}
            <div class="lockout-timer">({formatLockoutTime(remainingLockoutTime)})</div>
          {:else}
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
              <circle cx="12" cy="12" r="10"/>
              <line x1="15" y1="9" x2="9" y2="15"/>
              <line x1="9" y1="9" x2="15" y2="15"/>
            </svg>
            {error}
          {/if}
        </div>
      {/if}
      
      <div class="input-group">
        <label for="username">{$t('login_username')}</label>
        <input
          id="username"
          type="text"
          bind:value={username}
          placeholder={$t('login_username_placeholder')}
          disabled={isLoading}
          on:keydown={handleKeyDown}
          autocomplete="username"
          required
        />
      </div>
      
      <div class="input-group">
        <label for="password">{$t('login_password')}</label>
        <div class="password-input-container">
          <input
            id="password"
            type={showPassword ? 'text' : 'password'}
            bind:value={password}
            placeholder={$t('login_password_placeholder')}
            disabled={isLoading}
            on:keydown={handleKeyDown}
            autocomplete="current-password"
            required
          />
          <button
            type="button"
            class="password-toggle"
            on:click={() => showPassword = !showPassword}
            tabindex="-1"
          >
            {#if showPassword}
              <!-- Eye slash icon (hide) -->
              <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                <path d="M9.88 9.88a3 3 0 1 0 4.24 4.24"/>
                <path d="M10.73 5.08A10.43 10.43 0 0 1 12 5c7 0 10 7 10 7a13.16 13.16 0 0 1-1.67 2.68"/>
                <path d="M6.61 6.61A13.526 13.526 0 0 0 2 12s3 7 10 7a9.74 9.74 0 0 0 5.39-1.61"/>
                <line x1="2" y1="2" x2="22" y2="22"/>
              </svg>
            {:else}
              <!-- Eye icon (show) -->
              <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                <path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z"/>
                <circle cx="12" cy="12" r="3"/>
              </svg>
            {/if}
          </button>
        </div>
      </div>
      
      <button
        type="submit"
        class="login-button"
        disabled={isLoading || remainingLockoutTime > 0}
      >
        {#if isLoading}
          <div class="spinner"></div>
          {$t('login_logging_in')}
        {:else}
          {$t('login_button')}
        {/if}
      </button>
      
      <p class="login-subtitle">{$t('login_welcome')}</p>
    </form>
  </div>
</div>

<style>
  .login-container {
    position: fixed;
    top: 0;
    left: 0;
    right: 0;
    bottom: 0;
    display: flex;
    align-items: center;
    justify-content: center;
    background: linear-gradient(135deg, var(--primary-color) 0%, var(--primary-color-dark) 100%);
    padding: 1rem;
    overflow: hidden;
  }

  .login-card {
    background: var(--card-background);
    border-radius: 16px;
    padding: 2rem;
    width: 100%;
    max-width: 400px;
    box-shadow: 0 20px 50px rgba(0, 0, 0, 0.2);
    border: 1px solid var(--card-border);
  }

  .login-header {
    text-align: center;
    margin-bottom: 2rem;
    margin-top: 1rem;
  }

  .logo-container {
    display: flex;
    align-items: center;
    justify-content: center;
  }


  .logo-text {
    font-size: 2.7rem;
    color: var(--text-primary);
    margin: 0;
    letter-spacing: 0px;
  }

  .login-subtitle {
    color: var(--text-secondary);
    margin: 0.5rem 0 0 0;
    font-size: 0.9rem;
    text-align: center;
  }

  .login-form {
    display: flex;
    flex-direction: column;
    gap: 1.5rem;
  }

  .error-message {
    display: flex;
    align-items: center;
    gap: 0.5rem;
    color: var(--danger-color);
    background: rgba(var(--danger-color-rgb), 0.1);
    padding: 0.75rem;
    border-radius: 8px;
    border: 1px solid rgba(var(--danger-color-rgb), 0.2);
    font-size: 0.875rem;
  }

  .error-message.locked {
    color: var(--warning-color);
    background: rgba(255, 193, 7, 0.1);
    border-color: rgba(255, 193, 7, 0.2);
  }

  .lockout-timer {
    font-weight: 600;
    color: var(--warning-color);
    margin-left: auto;
  }

  .input-group {
    display: flex;
    flex-direction: column;
    gap: 0.5rem;
  }

  .input-group label {
    font-weight: 500;
    color: var(--text-primary);
    font-size: 0.875rem;
  }

  .input-group input {
    padding: 0.75rem;
    border: 1px solid var(--input-border);
    border-radius: 8px;
    background: var(--input-background);
    color: var(--text-primary);
    font-size: 1rem;
    transition: border-color 0.2s ease, box-shadow 0.2s ease;
  }

  .input-group input:focus {
    outline: none;
    border-color: var(--primary-color);
    box-shadow: 0 0 0 3px rgba(var(--primary-color-rgb), 0.1);
  }

  .input-group input:disabled {
    opacity: 0.6;
    cursor: not-allowed;
  }

  .password-input-container {
    position: relative;
    display: flex;
    align-items: center;
  }

  .password-input-container input {
    padding-right: 2.5rem;
    width: 100%;
  }

  .password-toggle {
    position: absolute;
    right: 0.75rem;
    background: none;
    border: none;
    color: var(--text-secondary);
    cursor: pointer;
    padding: 0;
    display: flex;
    align-items: center;
    justify-content: center;
    transition: color 0.2s ease;
  }

  .password-toggle:hover {
    color: var(--text-primary);
  }

  .password-toggle:focus {
    outline: none;
    color: var(--primary-color);
  }

  .login-button {
    background-color: var(--primary-color);
    color: #fff;
    border: 1px solid transparent;
    padding: 0.75rem 1.5rem;
    border-radius: 10px;
    font-size: 1rem;
    font-weight: 600;
    cursor: pointer;
    display: flex;
    align-items: center;
    justify-content: center;
    gap: 0.5rem;
    transition: background-color 0.3s ease, border-color 0.3s ease, color 0.3s ease, box-shadow 0.3s ease;
    text-decoration: none;
    box-shadow: var(--shadow-light);
  }

  .login-button:hover:not(:disabled) {
    background-color: var(--primary-hover);
    box-shadow: var(--shadow-medium);
  }

  .login-button:disabled {
    opacity: 0.7;
    cursor: not-allowed;
    transform: none;
  }

  .spinner {
    width: 16px;
    height: 16px;
    border: 2px solid transparent;
    border-top: 2px solid currentColor;
    border-radius: 50%;
    animation: spin 1s linear infinite;
  }

  @keyframes spin {
    0% { transform: rotate(0deg); }
    100% { transform: rotate(360deg); }
  }

  /* Mobile responsive */
  @media (max-width: 480px) {
    .login-card {
      padding: 1.5rem;
      border-radius: 12px;
    }

    .logo-text {
      font-size: 1.8rem;
    }
  }
</style>