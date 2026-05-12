# Project Maintenance & Quality Improvement Plan

## 1. Frontend Refactoring

### Problem: Monolithic Components
- `SettingsModal.svelte` (~3,300 lines)
- `App.svelte` (~2,300 lines)
- `DetailModal.svelte` (~1,100 lines)

### Actions Taken:
- Extracted core utility functions (date/byte formatting, URL validation) into `src/lib/utils.js`.
- Updated `App.svelte` to use these shared utilities, reducing redundancy and improving testability.

### Future Recommendations:
- **Component Decomposition:** Split `SettingsModal.svelte` into smaller pieces:
  - `GeneralSettings.svelte`
  - `ProxySettings.svelte`
  - `TelegramSettings.svelte`
  - `AuthSettings.svelte`
- **Store-based State Management:** Move `downloads` and `proxyStats` into Svelte stores (`src/lib/stores/downloads.js`) to eliminate prop-drilling.
- **API Service Layer:** Create `src/lib/api.js` to centralize all `fetch` calls.

## 2. Testing Strategy

### Backend:
- **Status:** Good coverage (~190 tests), mostly unit and service-level.
- **Improvement:** Added `backend/tests/test_api_integration.py` to verify end-to-end API response cycles.
- **Cleanup:** Fixed `xfail` and `skipif` in `test_history_period_stats.py` that were blocking valid tests.

### Frontend:
- **Status:** Previously zero tests.
- **Improvement:** 
  - Added `vitest` to `package.json`.
  - Created `frontend/tests/utils.test.js` to verify core utility logic.
- **Future:** Implement component testing with `@testing-library/svelte` and E2E testing with Playwright.

## 3. Deployment & CI
- **Version Management:** Unified versioning in `backend/core/version.py` and `standalone/version_info.txt`.
- **Recommendation:** Integrate `npm test` and `pytest` into the GitHub Actions workflows to prevent regression.
