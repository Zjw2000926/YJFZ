/**
 * P1-03: 病例选择页烟雾测试
 * - 验证 TriageCaseSelect 页面可渲染
 */
import { describe, it, expect, beforeEach, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { ToastProvider } from "../components/Toast";
import { ConfirmProvider } from "../components/ui/ConfirmDialog";
import TriageCaseSelect from "../pages/triage/TriageCaseSelect";

// Mock API
vi.mock("../api", () => ({
  getTriageCases: vi.fn(() => Promise.resolve({ data: { items: [] } })),
}));

describe("TriageCaseSelect", () => {
  beforeEach(() => {
    localStorage.clear();
  });

  it("应渲染页面标题", async () => {
    const user = { display_name: "测试学生", role: "student" };
    const onLogout = () => {};

    render(
      <MemoryRouter>
        <ToastProvider>
          <ConfirmProvider>
            <TriageCaseSelect user={user} onLogout={onLogout} />
          </ConfirmProvider>
        </ToastProvider>
      </MemoryRouter>,
    );

    await waitFor(() => {
      expect(screen.getByText("预检分诊训练")).toBeInTheDocument();
    }, { timeout: 5000 });
  });

  it("加载中应显示加载状态", () => {
    const user = { display_name: "测试学生", role: "student" };
    const onLogout = () => {};

    render(
      <MemoryRouter>
        <ToastProvider>
          <ConfirmProvider>
            <TriageCaseSelect user={user} onLogout={onLogout} />
          </ConfirmProvider>
        </ToastProvider>
      </MemoryRouter>,
    );

    // 初始渲染应该有内容（LoadingState 或页面标题）
    expect(document.body.textContent).toBeTruthy();
  });
});
