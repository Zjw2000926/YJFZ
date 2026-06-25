/**
 * P2-2: 动态预检分诊平台 MVP E2E 验收测试
 *
 * 前置条件: 后端运行在 http://127.0.0.1:8010
 * 运行: npx playwright test
 */
import { test, expect } from "@playwright/test";

const STUDENT = { username: "student1", password: "123456" };

test.describe("动态预检分诊 MVP E2E", () => {

  test("登录页正常加载", async ({ page }) => {
    await page.goto("/login");
    await expect(page.locator("h1")).toContainText("预检分诊训练系统");
    // 捕获控制台错误
    const errors = [];
    page.on("console", (msg) => { if (msg.type() === "error") errors.push(msg.text()); });
    await page.fill('input[placeholder="用户名"]', STUDENT.username);
    await page.fill('input[placeholder="密码"]', STUDENT.password);
    await page.click('button[type="submit"]');
    // 应跳转到病例列表页
    await page.waitForURL(/\/triage/, { timeout: 10000 });
    expect(errors.length).toBe(0);
  });

  test("病例列表包含动态病例", async ({ page }) => {
    // 登录
    await page.goto("/login");
    await page.fill('input[placeholder="用户名"]', STUDENT.username);
    await page.fill('input[placeholder="密码"]', STUDENT.password);
    await page.click('button[type="submit"]');
    await page.waitForURL(/\/triage/, { timeout: 10000 });
    // 检查页面上有预检分诊标题
    await expect(page.locator("text=预检分诊训练")).toBeVisible({ timeout: 5000 });
  });

  test("动态病例完整流程: 初诊 -> T15 -> T30 -> 复评 -> 升级 -> 提交", async ({ page }) => {
    // 登录
    await page.goto("/login");
    await page.fill('input[placeholder="用户名"]', STUDENT.username);
    await page.fill('input[placeholder="密码"]', STUDENT.password);
    await page.click('button[type="submit"]');
    await page.waitForURL(/\/triage/, { timeout: 10000 });

    // 直接进入指定动态病例，避免病例列表排序变化影响验收。
    await page.goto("/triage/dynamic/start?case=TRIAGE-DYN-RLQ-001");
    await expect(page.getByTestId("measure-all-vitals")).toBeVisible({ timeout: 10000 });

    // 确认进入动态训练页（应包含时间轴、测量按钮等）
    const pageContent = await page.content();
    expect(pageContent).toContain("测量");

    // 输入问诊
    const inputBox = page.locator('input[placeholder*="输入"]').first();
    if (await inputBox.isVisible({ timeout: 3000 }).catch(() => false)) {
      await inputBox.fill("哪里不舒服？");
      await page.click('button[class*="send"]');
      await page.waitForTimeout(1000);
    }

    // 测量生命体征
    await page.getByTestId("measure-all-vitals").click();
    await expect(page.locator("text=94次/分")).toBeVisible({ timeout: 5000 });

    // 初始分诊: Ⅲ级 + 黄区 + 30分钟复评
    await page.getByTestId("triage-level-3").click();
    await page.getByTestId("zone-option-yellow").click();

    await page.getByTestId("record-initial-triage").click();
    await expect(page.getByTestId("record-initial-triage")).toContainText("已记录", { timeout: 5000 });

    // 推进时间到 T30
    await page.getByTestId("advance-timeline").click();
    await expect(page.locator("text=模拟第15分钟").first()).toBeVisible({ timeout: 5000 });
    await page.getByTestId("advance-timeline").click();
    await expect(page.locator("text=模拟第30分钟").first()).toBeVisible({ timeout: 5000 });

    // T30恶化后复评并升级: Ⅱ级 + 红区
    await page.getByTestId("triage-level-2").click();
    await page.getByTestId("zone-option-red").click();
    await page.getByTestId("perform-reassessment").click();
    await page.getByTestId("confirm-ok").click();
    await expect(page.locator("text=122次/分")).toBeVisible({ timeout: 5000 });

    // 勾选通知医生 (force click 绕过遮挡的 label div)
    const notifyCheck = page.locator('input[type="checkbox"]').first();
    if (await notifyCheck.isVisible({ timeout: 2000 }).catch(() => false)) {
      const isChecked = await notifyCheck.isChecked();
      if (!isChecked) await notifyCheck.click({ force: true });
    }

    // 通知医生按钮
    await page.getByTestId("notify-doctor").click();
    await expect(page.locator("text=已通知").first()).toBeVisible({ timeout: 5000 });

    // 记录说明
    const noteBtn = page.locator("text=记录说明").first();
    if (await noteBtn.isVisible({ timeout: 2000 }).catch(() => false)) {
      await noteBtn.click();
      await page.waitForTimeout(300);
      const textarea = page.locator("textarea").first();
      if (await textarea.isVisible({ timeout: 2000 }).catch(() => false)) {
        await textarea.fill("已升级Ⅱ级红区，通知医生");
        await page.locator("text=保存").first().click();
        await page.waitForTimeout(500);
      }
    }

    // 提交分诊
    const submitBtn = page.getByTestId("submit-triage");
    await expect(submitBtn).toBeEnabled({ timeout: 5000 });
    await submitBtn.click();
    await page.getByTestId("confirm-ok").click();
    await page.waitForURL(/\/triage\/record\//, { timeout: 10000 });

    // 应进入报告页
    const reportContent = await page.content();
    expect(reportContent).toContain("分");
    console.log("E2E flow completed successfully");
  });

});
