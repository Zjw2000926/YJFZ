import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import TriageTimelinePanel from "../components/triage/TriageTimelinePanel";

const timeline = {
  current_minute: 0,
  patient_state: { state_name: "T0", appearance: "清醒，可交流" },
  timeline_events: [
    {
      event_id: "EVT_T15",
      scheduled_minute: 15,
      event_type: "symptom_worsening",
      triggered: false,
      event_description: "疼痛加重",
      requires_reassessment: true,
    },
  ],
};

describe("TriageTimelinePanel", () => {
  it("初始分诊前不允许推进时间", async () => {
    const onAdvance = vi.fn();
    render(<TriageTimelinePanel timeline={timeline} onAdvance={onAdvance} canAdvance={false} />);

    const button = screen.getByRole("button", { name: /推进时间/ });
    expect(button).toBeDisabled();
    await userEvent.click(button);
    expect(onAdvance).not.toHaveBeenCalled();
  });

  it("允许推进时点击下一时间点", async () => {
    const onAdvance = vi.fn();
    render(<TriageTimelinePanel timeline={timeline} onAdvance={onAdvance} canAdvance />);

    await userEvent.click(screen.getByRole("button", { name: /推进时间/ }));
    expect(onAdvance).toHaveBeenCalledWith(15);
  });

  it("对象型阶段和事件字段不会导致渲染崩溃", () => {
    const objectTimeline = {
      current_minute: 0,
      patient_state: {
        state_name: "T0",
        appearance: { expected_level: "Ⅱ级", expected_zone: "红区" },
      },
      timeline_events: [
        {
          event_id: "EVT_OBJECT",
          scheduled_minute: 10,
          triggered: false,
          event_description: { expected_level: "Ⅱ级", expected_zone: "红区" },
        },
      ],
    };

    render(<TriageTimelinePanel timeline={objectTimeline} onAdvance={vi.fn()} canAdvance />);
    expect(screen.getByText(/病例时间轴/)).toBeInTheDocument();
  });
});
