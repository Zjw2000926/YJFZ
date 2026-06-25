/** MVP 动态训练页: 模块结构验证 */
import { describe, it, expect } from "vitest";

// 验证 API 函数存在
import {
  startTriageTraining, advanceTriageTimeline, reassessTriagePatient,
  getTriageTimeline, recordInitialDecision, notifyDoctor, saveTrainingNotes
} from "../api";

describe("动态训练 API 函数", () => {
  it("startTriageTraining 存在", () => { expect(typeof startTriageTraining).toBe("function"); });
  it("advanceTriageTimeline 存在", () => { expect(typeof advanceTriageTimeline).toBe("function"); });
  it("reassessTriagePatient 存在", () => { expect(typeof reassessTriagePatient).toBe("function"); });
  it("getTriageTimeline 存在", () => { expect(typeof getTriageTimeline).toBe("function"); });
  it("recordInitialDecision 存在", () => { expect(typeof recordInitialDecision).toBe("function"); });
  it("notifyDoctor 存在", () => { expect(typeof notifyDoctor).toBe("function"); });
  it("saveTrainingNotes 存在", () => { expect(typeof saveTrainingNotes).toBe("function"); });
});

describe("动态训练组件结构", () => {
  it("TriageDynamicTraining 模块可导入", async () => {
    const mod = await import("../pages/triage/TriageDynamicTraining");
    expect(mod.default).toBeDefined();
  });

  it("TriageTimelinePanel 模块可导入", async () => {
    const mod = await import("../components/triage/TriageTimelinePanel");
    expect(mod.default).toBeDefined();
  });
});
