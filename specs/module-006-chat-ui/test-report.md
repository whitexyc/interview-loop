# Test Report — Module-006: 前端知识库问答界面

## Overview

| Item | Status |
|------|--------|
| Test Files | 3 passed |
| Tests | 20 passed |
| TypeScript | `tsc --noEmit` zero errors |
| Date | 2026-07-30 |

## Test Files

### 1. `ChatPage.test.tsx` (5 tests, all passed)

| # | Test | Status |
|---|------|--------|
| 1 | should render chat page with title, input and send button | PASS |
| 2 | should disable send button when input is empty | PASS |
| 3 | should show loading state after sending a message | PASS |
| 4 | should render search panel | PASS |
| 5 | should show error alert when chat API fails | PASS |

**Coverage areas:**
- Component rendering (title, input, send button, search panel)
- Empty input state (send button disabled)
- Loading state during API call
- Error state with retry button

### 2. `DocumentPage.test.tsx` (7 tests, all passed)

| # | Test | Status |
|---|------|--------|
| 1 | should render upload form with title, content fields and submit button | PASS |
| 2 | should disable submit button when both fields are empty | PASS |
| 3 | should disable submit button when only title is filled | PASS |
| 4 | should disable submit button when only content is filled | PASS |
| 5 | should enable submit button when both fields are filled | PASS |
| 6 | should show success message after successful upload | PASS |
| 7 | should show error message when upload fails | PASS |

**Coverage areas:**
- Component rendering (card title, inputs, submit button)
- Form validation (empty fields disable button)
- Partial form state (only title / only content)
- Success feedback after upload
- Error handling with error message display

### 3. `ResumePage.test.tsx` (8 tests, all passed)

Pre-existing tests — all pass without regression.

## Verification Commands

| Command | Result |
|---------|--------|
| `npx tsc --noEmit` | Zero errors |
| `npx vitest run` | 20/20 passed |

## Notes

- Added `Element.prototype.scrollIntoView` mock to `setup.ts` since jsdom does not implement it.
- Used `screen.getByRole('button', { name: /提\s*交/ })` and similar flexible name matchers to accommodate Ant Design's DOM rendering (which inserts spaces between characters in button text).
- All service calls are mocked via `vi.mock` to avoid real network requests.
