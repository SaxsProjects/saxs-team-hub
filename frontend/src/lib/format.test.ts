import { firstName, greeting, initials, longDate, percent, rands, shortDate } from "./format";

describe("rands", () => {
  it("formats cents with a space thousands separator, as in the design", () => {
    expect(rands(8_400_000)).toBe("R84 000.00");
    expect(rands(540_000)).toBe("R5 400.00");
    expect(rands(0)).toBe("R0.00");
    expect(rands(5)).toBe("R0.05");
    expect(rands(123_456_789)).toBe("R1 234 567.89");
    expect(rands(-250)).toBe("-R2.50");
  });
});

describe("percent", () => {
  it("turns basis points into a percentage", () => {
    expect(percent(1500)).toBe("15%");
    expect(percent(1250)).toBe("12.5%");
    expect(percent(5000)).toBe("50%");
  });
});

describe("dates (South African time)", () => {
  it("formats a calendar day without shifting it", () => {
    expect(longDate("2026-11-26")).toBe("Thursday, 26 November 2026");
    expect(shortDate("2026-11-28")).toBe("28 Nov");
  });
  it("greets by the time in Johannesburg, not the browser's zone", () => {
    expect(greeting(new Date("2026-11-26T06:00:00Z"))).toBe("Good morning"); // 08:00 SAST
    expect(greeting(new Date("2026-11-26T11:30:00Z"))).toBe("Good afternoon"); // 13:30
    expect(greeting(new Date("2026-11-26T16:00:00Z"))).toBe("Good evening"); // 18:00
  });
});

describe("names", () => {
  it("takes the first name and initials", () => {
    expect(firstName("Phathutshedzo Mamagau")).toBe("Phathutshedzo");
    expect(initials("Phathutshedzo Mamagau")).toBe("PM");
    expect(initials("Thabo")).toBe("T");
    expect(initials(null)).toBe("?");
  });
});
