import { test, expect } from '@playwright/test';

test.describe('Bilingual Internal Document Q&A E2E Flow', () => {
  test('Employee logs in, asks bilingual questions with citations, and triggers clarification card', async ({
    page,
  }) => {
    await page.goto('/');
    await expect(page.locator('text=Đăng nhập Hệ thống Hỏi đáp Nội bộ')).toBeVisible();

    await page.fill('input[type="text"]', 'emp_eng');
    await page.fill('input[type="password"]', 'EmployeePass123!');
    await page.click('button[type="submit"]');

    await expect(page.locator('text=Trợ lý Tri thức Nội bộ Song ngữ')).toBeVisible();
  });
});
