// M4 end to end (#108): a reviewer reviews an upload in the browser. Excludes a row, edits a cell,
// checks the history, reloads to show it persisted, and confirms the imported table is unchanged.
//
// Needs the API and the frontend running, and a tenant admin or reviewer account:
//   E2E_TENANT=dev E2E_USER=admin E2E_PASSWORD=... node scripts/e2e/m4-review.js
// Optional: E2E_API (default http://127.0.0.1:8000), E2E_FRONTEND (default http://127.0.0.1:8080).
// Uses Playwright's Chromium. Prints one PASS or FAIL line per check; exits 1 on any FAIL.
const { chromium } = require('playwright');
const API = process.env.E2E_API || 'http://127.0.0.1:8000', FE = process.env.E2E_FRONTEND || 'http://127.0.0.1:8080';
const tenant = process.env.E2E_TENANT, user = process.env.E2E_USER, pw = process.env.E2E_PASSWORD;
if (!tenant || !user || !pw) { console.error('Set E2E_TENANT, E2E_USER and E2E_PASSWORD'); process.exit(2); }
const name = `m4_${Date.now()}.csv`;
const check = (label, ok) => { console.log(`${ok ? 'PASS' : 'FAIL'} ${label}`); if (!ok) process.exitCode = 1; };

(async () => {
  const login = await (await fetch(API + '/api/auth/login', { method: 'POST', headers: { 'content-type': 'application/json' },
    body: JSON.stringify({ tenant, username: user, password: pw }) })).json();
  const auth = { authorization: 'Bearer ' + login.token, 'content-type': 'application/json' };
  const up = await (await fetch(API + '/api/csv/upload', { method: 'POST', headers: auth,
    body: JSON.stringify({ fileName: name, content: `n,t\n1,${name}\nx,b\n3,c\n`, types: ['int8', 'text'] }) })).json();
  console.log('upload', up.status, 'inserted', up.insertedRows, 'failed', up.failedRows, 'uploadId', up.uploadId);

  const browser = await chromium.launch();
  const page = await (await browser.newContext()).newPage();
  const errs = [];
  page.on('pageerror', (e) => errs.push(e.message));
  await page.goto(FE + '/auth');
  await page.fill('#tenant', tenant); await page.fill('#username', user); await page.fill('#password', pw);
  await page.click('button[type=submit]');
  await page.waitForURL(FE + '/');
  await page.locator('tr', { hasText: name }).getByRole('link', { name: 'Review' }).click();
  await page.waitForURL(`${FE}/review/${up.uploadId}`);
  await page.getByRole('heading', { name }).waitFor();
  check('3 rows listed', await page.getByText(/3 rows · 0 excluded · 0 edited/).count() === 1);
  check('row 2 flagged invalid', await page.getByText('Invalid').count() === 1);

  const row3 = page.locator('tr', { has: page.getByRole('button', { name: 'Edit row 3 n' }) });
  await row3.getByRole('button', { name: 'Exclude' }).click();
  await page.fill('#review-reason', 'duplicate of row 1');
  await page.getByRole('button', { name: 'Save' }).click();
  await page.getByText(/1 excluded/).waitFor();
  check('row 3 excluded', await row3.getByText('Excluded').count() === 1);

  await page.getByRole('button', { name: 'Edit row 2 n' }).click();
  await page.fill('#review-value', '2');
  await page.fill('#review-reason', 'typo in the source file');
  await page.getByRole('button', { name: 'Save' }).click();
  await page.getByText(/1 edited/).waitFor();
  check('row 2 now valid', await page.getByText('Invalid').count() === 0);

  await page.reload();
  await page.getByText(/3 rows · 1 excluded · 1 edited/).waitFor();
  const cell = page.getByRole('button', { name: 'Edit row 2 n' }).locator('xpath=..');
  check('after reload: edit kept, original shown', (await cell.getAttribute('title')) === 'Original: x');

  const row2 = page.locator('tr', { has: page.getByRole('button', { name: 'Edit row 2 n' }) });
  await row2.getByRole('button', { name: 'History of row 2' }).click();
  await page.getByText('n: "x" → "2"').waitFor();
  check('history shows the edit with actor and reason',
    await page.getByText(new RegExp(`${user} · .* · typo in the source file`)).count() === 1);
  await page.keyboard.press('Escape');

  const files = await (await fetch(API + '/api/csv/files', { headers: auth })).json();
  check('imported table unchanged (decision 1)', files.find((f) => f.upload_id === up.uploadId).row_count === 2);
  check('no page errors', errs.length === 0);
  await browser.close();
})().catch((e) => { console.error(e); process.exit(1); });
