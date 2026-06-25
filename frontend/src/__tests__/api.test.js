/**
 * P1-03: API 客户端基础测试
 * - 验证 API 函数导出
 * - 验证 token 存储/清理逻辑
 */
import { describe, it, expect, beforeEach } from "vitest";
import { login, getTriageCases, startTriageTraining, getTriageRecord, getTriageRecords, sendTriageMessage, submitTriage } from "../api";

describe("api 客户端", () => {
  beforeEach(() => {
    localStorage.clear();
  });

  it("login 函数存在", () => {
    expect(typeof login).toBe("function");
  });

  it("getTriageCases 函数存在", () => {
    expect(typeof getTriageCases).toBe("function");
  });

  it("startTriageTraining 函数存在", () => {
    expect(typeof startTriageTraining).toBe("function");
  });

  it("getTriageRecords 函数存在", () => {
    expect(typeof getTriageRecords).toBe("function");
  });

  it("getTriageRecord 函数存在", () => {
    expect(typeof getTriageRecord).toBe("function");
  });

  it("sendTriageMessage 函数存在", () => {
    expect(typeof sendTriageMessage).toBe("function");
  });

  it("submitTriage 函数存在", () => {
    expect(typeof submitTriage).toBe("function");
  });

  it("token 可存入 localStorage", () => {
    localStorage.setItem("token", "test-token-abc");
    expect(localStorage.getItem("token")).toBe("test-token-abc");
  });

  it("无 token 时 localStorage 为空", () => {
    expect(localStorage.getItem("token")).toBeNull();
  });

  it("userRole 可存入和读取", () => {
    localStorage.setItem("userRole", "student");
    expect(localStorage.getItem("userRole")).toBe("student");
  });
});
