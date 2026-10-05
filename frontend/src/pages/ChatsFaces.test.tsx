import { screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { PeoplePicker } from "../components/chat/PeoplePicker";
import { entry, renderChats as render, row, visible } from "../test/chat";
import { renderWithProviders } from "../test/helpers";

beforeEach(() => visible("visible"));
afterEach(() => {
  vi.unstubAllGlobals();
  visible("visible");
});

const LEAD = "/files/avatars/2026/10/aaaaaaaaaaaaaaaa.jpg";
const MONA = "/files/avatars/2026/10/bbbbbbbbbbbbbbbb.jpg";

describe("colleagues' pictures in the chats", () => {
  it("draws a colleague's picture in the list, and the initials for one who has none", async () => {
    const { container } = render("/chats?type=staff", {
      lists: {
        staff: [
          row("u5", { staff: true, label: "Mona", initials: "MS", avatar: MONA }),
          row("u6", { staff: true, label: "Nour", initials: "NO", avatar: null }),
          row("u7", { staff: true, label: "Sam", initials: "SA" }),
        ],
      },
    });
    await screen.findByText("Mona");
    const mona = container.querySelector('[data-code="u5"]') as HTMLElement;
    expect(mona.querySelector("img")).toHaveAttribute("src", MONA);
    expect(within(mona).queryByText("MS")).toBeNull();
    for (const [code, initials] of [["u6", "NO"], ["u7", "SA"]] as const) {
      const line = container.querySelector(`[data-code="${code}"]`) as HTMLElement;
      expect(line.querySelector("img"), code).toBeNull();
      expect(within(line).getByText(initials)).toHaveClass("avatar--staff");
    }
  });

  it("never draws a face on a client's row or a group's, whatever the row carries", async () => {
    const { container } = render("/chats", {
      lists: {
        clients: [row("CL-0001", { avatar: MONA })],
      },
    });
    await screen.findByText("CL-0001");
    expect((container.querySelector('[data-code="CL-0001"]') as HTMLElement).querySelector("img")).toBeNull();
    const groups = render("/chats?type=groups", { lists: { groups: [row("g3", { group: true, team: true, label: "Work", avatar: MONA })] } });
    await screen.findByText("Work");
    expect((groups.container.querySelector('[data-code="g3"]') as HTMLElement).querySelector("img")).toBeNull();
  });

  it("draws the colleague's picture at the head of the open chat", async () => {
    const { container } = render("/chats/u5", {
      thread: { client: row("u5", { staff: true, initials: "MS", label: "Mona", avatar: MONA }), messages: [entry(1)] },
    });
    await screen.findByText("message 1");
    const head = container.querySelector(".cchat__head") as HTMLElement;
    await waitFor(() => expect(head.querySelector("img")).toHaveAttribute("src", MONA));
  });

  it("puts the initials at the head of the chat when the colleague has no picture", async () => {
    const { container } = render("/chats/u5", {
      thread: { client: row("u5", { staff: true, initials: "MS", label: "Mona", avatar: null }), messages: [entry(1)] },
    });
    await screen.findByText("message 1");
    const head = container.querySelector(".cchat__head") as HTMLElement;
    expect(head.querySelector("img")).toBeNull();
    expect(within(head).getByText("MS")).toBeInTheDocument();
  });

  it("shows the sender's picture beside their name under a message, and nothing extra when they have none", async () => {
    const { container } = render("/chats/g3?type=groups", {
      types: ["groups", "staff"],
      thread: {
        client: row("g3", { group: true, team: true, label: "Work" }),
        messages: [
          entry(1, { kind: "out", sender: "Lead Mona", sender_id: 4, sender_avatar: LEAD, body: "from the leader" }),
          entry(2, { kind: "out", sender: "Sam Adel", sender_id: 5, sender_avatar: null, body: "from sam" }),
        ],
      },
    });
    await screen.findByText("from the leader");
    const bubbles = [...container.querySelectorAll(".bub__foot")] as HTMLElement[];
    const lead = bubbles.find((foot) => foot.textContent?.includes("Lead Mona"))!;
    const sam = bubbles.find((foot) => foot.textContent?.includes("Sam Adel"))!;
    expect(lead.querySelector("img")).toHaveAttribute("src", LEAD);
    expect(lead.querySelector(".avatar--xs")).not.toBeNull();
    expect(sam.querySelector("img")).toBeNull();
    expect(sam.querySelector(".avatar")).toBeNull();
  });

  it("draws no face under a client's own message", async () => {
    const { container } = render("/chats/CL-0001", {
      thread: { client: row("CL-0001"), messages: [entry(1, { kind: "in", sender: "", sender_avatar: MONA, body: "hello from the client" })] },
    });
    await screen.findByText("hello from the client");
    expect(container.querySelector(".bub__foot img")).toBeNull();
  });
});

describe("the people picker", () => {
  it("draws each person's picture, or their initials", () => {
    const { container } = renderWithProviders(
      <PeoplePicker
        people={[
          { id: 4, name: "Lead Mona", initials: "LM", avatar: LEAD, role: "team_lead" },
          { id: 5, name: "Sam Adel", initials: "SA", avatar: null, role: "translator" },
          { id: 6, name: "Old Timer", initials: "OT", role: "hr" },
        ]}
        picked={[]}
        onChange={() => undefined}
        label="People"
      />,
    );
    const rows = [...container.querySelectorAll(".fwd-row")] as HTMLElement[];
    expect(rows[0]!.querySelector("img")).toHaveAttribute("src", LEAD);
    expect(rows[1]!.querySelector("img")).toBeNull();
    expect(within(rows[1]!).getByText("SA")).toBeInTheDocument();
    expect(within(rows[2]!).getByText("OT")).toBeInTheDocument();
  });
});
