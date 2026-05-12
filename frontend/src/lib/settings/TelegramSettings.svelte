<script>
  import { t } from "../i18n.js";

  export let settings;
  export let telegramGuideExpanded;
  export let detailedGuideExpanded;
  export let telegramSettingsExpanded;
  export let testTelegramNotification;
</script>

<fieldset class="form-group telegram-notifications">
  <legend>{$t("telegram_notifications")}</legend>

  <!-- 텔레그램 설정 가이드 아코디언 -->
  <button
    type="button"
    class="telegram-header"
    on:click={() => (telegramGuideExpanded = !telegramGuideExpanded)}
  >
    <div class="telegram-info">
      <p class="telegram-desc">📚 {$t("telegram_setup_guide")}</p>
    </div>
    <div class="toggle-chevron" class:expanded={telegramGuideExpanded}>
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

  {#if telegramGuideExpanded}
    <div class="telegram-accordion">
      <div class="accordion-content">
        <!-- 텔레그램 설정 가이드 -->
        <div class="telegram-setup-guide">
          <div class="setup-guide-header">
            <h4 class="guide-title">📱 {$t("telegram_setup_guide")}</h4>
            <p class="guide-description">{$t("telegram_description")}</p>
          </div>

          <div class="setup-steps">
            <div class="setup-step">
              <div class="step-header">
                <span class="step-icon">🤖</span>
                <h5 class="step-title">{$t("telegram_step1_title")}</h5>
              </div>
              <p class="step-description">{$t("telegram_step1_desc")}</p>
              <a
                href="https://t.me/botfather"
                target="_blank"
                rel="noopener noreferrer"
                class="telegram-link botfather-link"
              >
                🔗 {$t("telegram_botfather_link")}
              </a>
            </div>

            <div class="setup-step">
              <div class="step-header">
                <span class="step-icon">🆔</span>
                <h5 class="step-title">{$t("telegram_step2_title")}</h5>
              </div>
              <p class="step-description">{$t("telegram_step2_desc")}</p>
              <a
                href="https://t.me/userinfobot"
                target="_blank"
                rel="noopener noreferrer"
                class="telegram-link getid-link"
              >
                🔗 {$t("telegram_getid_bot")}
              </a>
            </div>
          </div>

          <div class="detailed-guide">
            <button
              type="button"
              class="guide-header-button"
              on:click={() => (detailedGuideExpanded = !detailedGuideExpanded)}
            >
              <div class="guide-info">
                <p class="guide-desc">📋 {$t("telegram_guide_detailed")}</p>
              </div>
              <div class="toggle-chevron" class:expanded={detailedGuideExpanded}>
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

            {#if detailedGuideExpanded}
              <div class="guide-accordion">
                <div class="guide-accordion-content">
                  <ol class="guide-steps">
                    <li>{$t("telegram_guide_step1_detail")}</li>
                    <li>{$t("telegram_guide_step2_detail")}</li>
                    <li>{$t("telegram_guide_step3_detail")}</li>
                    <li>{$t("telegram_guide_step4_detail")}</li>
                    <li>{$t("telegram_guide_step5_detail")}</li>
                    <li>{$t("telegram_guide_step6_detail")}</li>
                  </ol>
                  <div class="guide-note">💡 {$t("telegram_guide_group_note")}</div>
                </div>
              </div>
            {/if}
          </div>
        </div>
      </div>
    </div>
  {/if}

  <!-- 텔레그램 설정 아코디언 -->
  <button
    type="button"
    class="telegram-header"
    on:click={() => (telegramSettingsExpanded = !telegramSettingsExpanded)}
  >
    <div class="telegram-info">
      <p class="telegram-desc">⚙️ {$t("telegram_settings")}</p>
    </div>
    <div class="toggle-chevron" class:expanded={telegramSettingsExpanded}>
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

  {#if telegramSettingsExpanded}
    <div class="telegram-accordion">
      <div class="accordion-content">
        <div class="telegram-input-group">
          <div class="input-field">
            <label for="telegram-bot-token">{$t("telegram_bot_token")}</label>
            <input
              id="telegram-bot-token"
              type="text"
              class="input telegram-token-input"
              bind:value={settings.telegram_bot_token}
              placeholder="1234567890:ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijk"
            />
            <small class="input-hint">{$t("telegram_bot_token_hint")}</small>
          </div>

          <div class="input-field">
            <label for="telegram-chat-id">{$t("telegram_chat_id")}</label>
            <input
              id="telegram-chat-id"
              type="text"
              class="input telegram-chat-input"
              bind:value={settings.telegram_chat_id}
              placeholder="123456789"
            />
            <small class="input-hint">{$t("telegram_chat_id_hint")}</small>
          </div>
        </div>

        <div class="telegram-options">
          <div class="telegram-checkbox-group">
            <label class="telegram-checkbox-label">
              <input
                type="checkbox"
                bind:checked={settings.telegram_notify_success}
              />
              <span class="telegram-checkbox-text">✅ {$t("telegram_notify_success")}</span>
            </label>

            <label class="telegram-checkbox-label">
              <input
                type="checkbox"
                bind:checked={settings.telegram_notify_failure}
              />
              <span class="telegram-checkbox-text">❌ {$t("telegram_notify_failure")}</span>
            </label>

            <label class="telegram-checkbox-label">
              <input
                type="checkbox"
                bind:checked={settings.telegram_notify_wait}
              />
              <span class="telegram-checkbox-text">⏳ {$t("telegram_notify_wait")}</span>
            </label>
            <div class="telegram-option-description">
              {$t("telegram_notify_wait_description")}
            </div>

            <label class="telegram-checkbox-label">
              <input
                type="checkbox"
                bind:checked={settings.telegram_notify_start}
              />
              <span class="telegram-checkbox-text">⬇️ {$t("telegram_notify_start")}</span>
            </label>
            <div class="telegram-option-description">
              {$t("telegram_notify_start_description")}
            </div>
          </div>
        </div>

        <div class="telegram-test-section">
          <button
            class="button button-secondary test-telegram-button"
            on:click={testTelegramNotification}
            disabled={!settings.telegram_bot_token || !settings.telegram_chat_id}
          >
            📨 {$t("telegram_test_notification")}
          </button>
        </div>
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

  .telegram-desc { margin: 0; color: var(--text-primary); font-size: 0.9rem; font-weight: 500; display: flex; align-items: center; gap: 0.5rem; }
  
  .toggle-chevron { display: flex; align-items: center; justify-content: center; width: 32px; height: 32px; border-radius: 6px; background: var(--bg-secondary); color: var(--text-secondary); transition: all 0.2s ease; }
  .toggle-chevron.expanded svg { transform: rotate(180deg); }

  .telegram-accordion { border: 1px solid var(--card-border); border-radius: 8px; overflow: hidden; background: var(--card-background); margin-bottom: 0.5rem; }
  .accordion-content { padding: 1.5rem; }

  .telegram-input-group { display: flex; flex-direction: column; gap: 1rem; margin-bottom: 1.5rem; }
  .input-field { display: flex; flex-direction: column; gap: 0.5rem; }
  .input-field label { font-weight: 500; color: var(--text-primary); font-size: 0.875rem; }

  .input-hint { color: var(--text-secondary); font-size: 0.75rem; }

  .telegram-options { margin-bottom: 1.5rem; padding: 1rem; background: var(--bg-secondary); border-radius: 6px; border: 1px solid var(--card-border); }
  .telegram-checkbox-group { display: flex; flex-direction: column; gap: 0.75rem; }
  .telegram-checkbox-label { display: flex; align-items: center; gap: 0.75rem; cursor: pointer; font-size: 0.875rem; padding: 0.5rem; border-radius: 4px; }
  .telegram-checkbox-label:hover { background: var(--card-background); }
  .telegram-checkbox-text { color: var(--text-primary); font-weight: 500; }
  .telegram-option-description { margin-top: -0.25rem; margin-left: 2rem; color: var(--text-secondary); font-size: 0.75rem; line-height: 1.3; }

  .telegram-test-section { display: flex; justify-content: center; gap: 0.5rem; margin-top: 1rem; }
  
  .button { display: inline-flex; align-items: center; justify-content: center; padding: 0.75rem 1.5rem; font-size: 0.875rem; font-weight: 600; border-radius: 12px; border: 2px solid transparent; cursor: pointer; }
  .button-secondary { background: var(--card-background); color: var(--text-secondary); border-color: var(--card-border); }

  .telegram-setup-guide { background: rgba(59, 130, 246, 0.05); border: 1px solid rgba(59, 130, 246, 0.15); border-radius: 12px; padding: 1.5rem; margin-bottom: 2rem; }
  .guide-title { margin: 0 0 0.5rem 0; font-size: 1.1rem; font-weight: 600; color: var(--primary-color); }
  .setup-steps { display: grid; grid-template-columns: repeat(auto-fit, minmax(280px, 1fr)); gap: 1.5rem; margin-bottom: 1.5rem; }
  .setup-step { background: var(--card-background); border: 1px solid var(--card-border); border-radius: 8px; padding: 1.25rem; }
  .step-header { display: flex; align-items: center; gap: 0.75rem; margin-bottom: 0.75rem; }
  .step-title { margin: 0; font-size: 1rem; font-weight: 600; color: var(--text-primary); }
  
  .telegram-link { display: inline-flex; align-items: center; gap: 0.5rem; padding: 0.5rem 1rem; color: white; text-decoration: none; border-radius: 6px; font-size: 0.875rem; font-weight: 500; }
  .botfather-link { background: #0088cc; }
  .getid-link { background: #28a745; }

  .guide-header-button { width: 100%; background: var(--card-background); border: 1px solid var(--card-border); border-radius: 8px; padding: 1.5rem; display: flex; justify-content: space-between; align-items: center; cursor: pointer; text-align: left; }
  .guide-steps { margin: 0 0 1rem 0; padding-left: 1.5rem; color: var(--text-primary); }
  .guide-steps li { margin-bottom: 0.5rem; line-height: 1.5; font-size: 0.875rem; }
  .guide-note { background: rgba(59, 130, 246, 0.1); border: 1px solid rgba(59, 130, 246, 0.2); border-radius: 6px; padding: 0.75rem; font-size: 0.875rem; color: var(--text-primary); }

  @media (max-width: 640px) {
    .setup-steps { grid-template-columns: 1fr; }
    .telegram-link { width: 100%; justify-content: center; }
  }
</style>
