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
