<script>
  import { t } from "../i18n.js";

  export let settings;
  export let currentSettings;
  export let fichierAccountExpanded;
  export let fichierEditMode;
  export let fichierTestLoading;
  export let startFichierEdit;
  export let clearFichierAccount;
  export let testFichierLogin;
</script>

<fieldset class="form-group telegram-notifications">
  <legend>{$t("fichier_account_title")}</legend>

  <button
    type="button"
    class="telegram-header"
    on:click={() => (fichierAccountExpanded = !fichierAccountExpanded)}
  >
    <div class="telegram-info">
      <p class="telegram-desc">{$t("fichier_account_header")}</p>
      <p class="telegram-sub">{$t("fichier_account_sub")}</p>
    </div>
    <div class="toggle-chevron" class:expanded={fichierAccountExpanded}>
      <svg
        width="20"
        height="20"
        viewBox="0 0 24 24"
        fill="none"
        stroke="currentColor"
        stroke-width="2"
        stroke-linecap="round"
        stroke-linejoin="round"
      >
        <polyline points="6,9 12,15 18,9"></polyline>
      </svg>
    </div>
  </button>

  {#if fichierAccountExpanded}
    <div class="telegram-accordion">
      <div class="accordion-content">
        {#if currentSettings?.fichier_email && currentSettings?.fichier_password && !fichierEditMode}
          <!-- 저장된 자격증명: 이메일만 깔끔하게 표시 -->
          <div class="fichier-saved">
            <div class="fichier-saved-row">
              <span class="fichier-saved-icon" aria-hidden="true">✓</span>
              <div class="fichier-saved-text">
                <div class="fichier-saved-email">{settings.fichier_email}</div>
                <div class="fichier-saved-sub">{$t("fichier_saved_sub")}</div>
              </div>
            </div>
            <div class="fichier-saved-actions">
              <button
                type="button"
                class="button button-secondary test-telegram-button"
                on:click={startFichierEdit}
              >
                {$t("fichier_change")}
              </button>
              <button
                type="button"
                class="button button-secondary test-telegram-button fichier-danger-button"
                on:click={clearFichierAccount}
              >
                {$t("fichier_delete")}
              </button>
            </div>
          </div>
        {:else}
          <!-- 입력/편집 모드 -->
          <div class="telegram-input-group">
            <div class="input-field">
              <label for="fichier-email">{$t("fichier_email_label")}</label>
              <input
                id="fichier-email"
                type="email"
                class="input"
                autocomplete="username"
                placeholder="example@mail.com"
                bind:value={settings.fichier_email}
              />
              <small class="input-hint">
                {$t("fichier_email_hint_prefix")}
                <a
                  href="https://1fichier.com/register.pl"
                  target="_blank"
                  rel="noopener"
                  class="fichier-inline-link"
                  >{$t("fichier_create_account")}</a
                >
              </small>
            </div>

            <div class="input-field">
              <label for="fichier-password"
                >{$t("fichier_password_label")}</label
              >
              <input
                id="fichier-password"
                type="password"
                class="input"
                autocomplete="current-password"
                placeholder="••••••••"
                bind:value={settings.fichier_password}
              />
              <small class="input-hint">{$t("fichier_password_hint")}</small>
            </div>

            <div class="telegram-test-section">
              <button
                type="button"
                class="button button-secondary test-telegram-button"
                disabled={!settings.fichier_email ||
                  !settings.fichier_password ||
                  fichierTestLoading}
                on:click={testFichierLogin}
              >
                {fichierTestLoading
                  ? $t("fichier_test_loading")
                  : $t("fichier_test_login")}
              </button>
              {#if currentSettings?.fichier_email}
                <button
                  type="button"
                  class="button button-secondary test-telegram-button"
                  on:click={() => {
                    settings.fichier_email = currentSettings.fichier_email || "";
                    settings.fichier_password =
                      currentSettings.fichier_password || "";
                    fichierEditMode = false;
                  }}
                >
                  {$t("fichier_cancel")}
                </button>
              {/if}
            </div>
          </div>
        {/if}
      </div>
    </div>
  {/if}
</fieldset>

<style>
  .form-group { margin-bottom: 1.5rem; }
  legend { display: block; margin-bottom: 0.5rem; font-weight: 600; font-size: 0.875rem; color: var(--text-primary); text-transform: uppercase; letter-spacing: 0.025em; }
  
  .input {
    width: 100%;
    padding: 0.875rem 1rem;
    border: 2px solid var(--card-border, #e5e7eb);
    border-radius: 12px;
    background-color: var(--input-bg, #ffffff);
    color: var(--text-primary);
    font-size: 0.875rem;
  }

  .telegram-header {
    width: 100%; background: var(--card-background); border: 1px solid var(--card-border); border-radius: 8px; padding: 1.5rem; margin-bottom: 1rem;
    display: flex; justify-content: space-between; align-items: center; cursor: pointer; text-align: left;
  }

  .telegram-desc { margin: 0; color: var(--text-primary); font-size: 0.9rem; font-weight: 500; }
  .telegram-sub { margin: 0.25rem 0 0 0; color: var(--text-secondary); font-size: 0.8rem; }
  
  .toggle-chevron { display: flex; align-items: center; justify-content: center; width: 32px; height: 32px; border-radius: 6px; background: var(--bg-secondary); color: var(--text-secondary); }
  .toggle-chevron.expanded svg { transform: rotate(180deg); }

  .telegram-accordion { border: 1px solid var(--card-border); border-radius: 8px; overflow: hidden; background: var(--card-background); margin-bottom: 0.5rem; }
  .accordion-content { padding: 1.5rem; }

  .telegram-input-group { display: flex; flex-direction: column; gap: 1rem; margin-bottom: 1.5rem; }
  .input-field { display: flex; flex-direction: column; gap: 0.5rem; }
  .input-field label { font-weight: 500; color: var(--text-primary); font-size: 0.875rem; }
  .input-hint { color: var(--text-secondary); font-size: 0.75rem; }

  .fichier-saved { display: flex; flex-direction: column; gap: 1rem; padding: 1rem 1.25rem; background: var(--card-background); border: 1px solid var(--card-border); border-radius: 10px; }
  .fichier-saved-row { display: flex; align-items: center; gap: 0.75rem; }
  .fichier-saved-icon { flex-shrink: 0; width: 1.75rem; height: 1.75rem; border-radius: 50%; background: rgba(var(--primary-color-rgb), 0.12); color: var(--primary-color); font-weight: 700; display: inline-flex; align-items: center; justify-content: center; }
  .fichier-saved-text { display: flex; flex-direction: column; gap: 0.125rem; min-width: 0; flex: 1; }
  .fichier-saved-email { font-weight: 600; color: var(--text-primary); font-size: 0.95rem; word-break: break-all; }
  .fichier-saved-sub { color: var(--text-secondary); font-size: 0.78rem; }
  .fichier-saved-actions { display: flex; gap: 0.5rem; flex-wrap: wrap; }
  
  .button { display: inline-flex; align-items: center; justify-content: center; padding: 0.75rem 1.5rem; font-size: 0.875rem; font-weight: 600; border-radius: 12px; border: 2px solid transparent; cursor: pointer; }
  .button-secondary { background: var(--card-background); color: var(--text-secondary); border-color: var(--card-border); }
  
  .fichier-danger-button { background: var(--danger-color) !important; color: #fff !important; }
  .fichier-inline-link { color: var(--primary-color); text-decoration: none; }
  
  .telegram-test-section { display: flex; justify-content: center; gap: 0.5rem; margin-top: 1rem; }
  .test-telegram-button { padding: 0.75rem 1.5rem; font-size: 0.875rem; }
</style>
