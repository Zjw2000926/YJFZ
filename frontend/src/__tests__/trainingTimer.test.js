import { describe, expect, it } from "vitest";
import { calculateTimeLeftSeconds, formatCountdownTime, isTrainingRecordExpired } from "../utils/trainingTimer";

describe("trainingTimer", () => {
  it("calculates remaining seconds from started_at and time limit", () => {
    const now = Date.parse("2026-06-21T08:00:30.000Z");
    expect(calculateTimeLeftSeconds("2026-06-21T08:00:00.000Z", 8, now)).toBe(450);
  });

  it("marks only expired in-progress records as expired", () => {
    const now = Date.parse("2026-06-21T08:09:00.000Z");
    expect(isTrainingRecordExpired({
      status: "in_progress",
      started_at: "2026-06-21T08:00:00.000Z",
      time_limit_minutes: 8,
    }, 8, now)).toBe(true);
    expect(isTrainingRecordExpired({
      status: "scored",
      started_at: "2026-06-21T08:00:00.000Z",
      time_limit_minutes: 8,
    }, 8, now)).toBe(false);
  });

  it("formats countdown text consistently", () => {
    expect(formatCountdownTime(476)).toBe("07:56");
    expect(formatCountdownTime(-1)).toBe("00:00");
  });
});
