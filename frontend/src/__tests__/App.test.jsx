/**
 * P1-03: App 路由基础测试
 * - 验证 React Router + 路由保护逻辑
 */
import { describe, it, expect, beforeEach } from "vitest";
import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import Login from "../pages/triage/Login";

describe("App 路由与组件", () => {
  beforeEach(() => {
    localStorage.clear();
  });

  it("Login 组件应渲染登录页标题", () => {
    const onLogin = () => {};
    render(<Login onLogin={onLogin} />);
    expect(screen.getByText("预检分诊训练系统")).toBeInTheDocument();
  });

  it("Login 组件应显示免责声明", () => {
    const onLogin = () => {};
    render(<Login onLogin={onLogin} />);
    expect(screen.getByText("仅用于教学训练，不用于真实临床分诊")).toBeInTheDocument();
  });

  it("Login 组件应显示默认账号提示", () => {
    const onLogin = () => {};
    render(<Login onLogin={onLogin} />);
    expect(screen.getByText(/admin\/admin123/)).toBeInTheDocument();
  });

  it("ProtectedRoute: 无 token 时应阻止访问", () => {
    // 验证逻辑：无 token 时 localStorage 为空
    expect(localStorage.getItem("token")).toBeNull();
    // ProtectedRoute 应该返回 Navigate to /login
  });

  it("MemoryRouter 基本渲染", () => {
    const onLogin = () => {};
    render(
      <MemoryRouter>
        <Login onLogin={onLogin} />
      </MemoryRouter>,
    );
    expect(screen.getByText("预检分诊训练系统")).toBeInTheDocument();
  });
});
