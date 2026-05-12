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
