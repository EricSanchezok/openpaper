import type { Meta, StoryObj } from "@storybook/nextjs-vite";
import { expect, fn, userEvent, waitFor, within } from "storybook/test";

import type { components } from "@/lib/api/generated/schema";
import { homeMessages, homePapers, homeProjects } from "../api/fixtures";
import type { LiveTurn } from "../conversation-state";
import { ConversationView } from "./conversation-view";

type Message =
  components["schemas"]["app__modules__conversations__application__contracts__conversations__MessageResponse"];

const directMessages: Message[] = [
  {
    id: "41000000-0000-4000-8000-000000000001",
    turn_id: "51000000-0000-4000-8000-000000000001",
    role: "user",
    content: "What day is it today?",
    references: null,
    artifacts: null,
    trace: null,
    scope: null,
    sequence: 1,
  },
  {
    id: "41000000-0000-4000-8000-000000000002",
    turn_id: "51000000-0000-4000-8000-000000000001",
    role: "assistant",
    content: "Today is Wednesday, August 5, 2026.",
    references: null,
    artifacts: null,
    trace: null,
    scope: null,
    sequence: 2,
  },
];

const searchActivity = {
  id: "search-1",
  sequence: 1,
  category: "search" as const,
  state: "succeeded" as const,
  tool_name: "search_papers",
  subject: "chain-of-thought compression for efficient language models",
  source_count: 3,
  artifact_count: 0,
};

const readActivity = {
  id: "read-2",
  sequence: 2,
  category: "read" as const,
  state: "succeeded" as const,
  tool_name: "get_paper_content",
  subject: "Reasoning Efficiently: Models, Methods, and Open Questions",
  source_count: 2,
  artifact_count: 0,
};

function liveTurn(overrides: Partial<LiveTurn> = {}): LiveTurn {
  return {
    turnId: "52000000-0000-4000-8000-000000000001",
    userMessage: "Compare the strongest reasoning-compression approaches.",
    content: "",
    activities: [],
    trace: null,
    references: null,
    state: "streaming",
    ...overrides,
  };
}

const meta = {
  title: "Features/Home/Conversation View",
  component: ConversationView,
  args: {
    title: "Reasoning compression",
    messages: homeMessages,
    liveTurn: null,
    context: { kind: "library" },
    papers: homePapers,
    projects: homeProjects,
    reasoningLevel: "standard",
    onContextChange: fn(),
    onReasoningLevelChange: fn(),
    onSubmit: fn(async () => undefined),
    onStop: fn(),
    onRetry: fn(),
    canSend: true,
  },
  decorators: [
    (Story) => (
      <main className="h-screen overflow-y-auto">
        <Story />
      </main>
    ),
  ],
  parameters: { layout: "fullscreen" },
} satisfies Meta<typeof ConversationView>;

export default meta;
type Story = StoryObj<typeof meta>;

export const DirectAnswer: Story = {
  args: { messages: directMessages },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(canvas.getByText(/Today is Wednesday/)).toBeVisible();
    await expect(canvas.queryByText(/Completed ·/)).not.toBeInTheDocument();
  },
};

export const ThinkingWithoutTools: Story = {
  args: { messages: [], liveTurn: liveTurn() },
  play: async ({ canvasElement }) => {
    await waitFor(() =>
      expect(within(canvasElement).getByText("Thinking…")).toBeVisible(),
    );
  },
};

export const SingleToolRunning: Story = {
  args: {
    messages: [],
    liveTurn: liveTurn({
      activities: [{ ...searchActivity, state: "running" }],
    }),
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const disclosure = canvas.getByRole("button", {
      name: "Searching your research…",
    });
    disclosure.focus();
    await userEvent.keyboard(" ");
    await expect(canvas.getByText("Searched research sources")).toBeVisible();
    await expect(canvas.queryByText("search_papers")).not.toBeInTheDocument();
    await userEvent.keyboard("{Enter}");
    await expect(disclosure).toHaveAttribute("aria-expanded", "false");
  },
};

export const MultipleToolsExpanded: Story = {
  args: {
    messages: [],
    liveTurn: liveTurn({
      activities: [searchActivity, readActivity],
      content:
        "The strongest approaches trade additional training for shorter inference traces.",
      state: "complete",
      trace: {
        activities: [searchActivity, readActivity],
        citation_summary: {
          source_count: 4,
          annotation_count: 2,
          rejected_source_count: 0,
        },
      },
    }),
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const disclosure = canvas.getByRole("button", {
      name: "Completed · 2 actions · 4 sources",
    });
    await userEvent.click(disclosure);
    await expect(canvas.getByText("Read source material")).toBeVisible();
    await expect(disclosure).toHaveAttribute("aria-expanded", "true");
  },
};

export const PartialFailure: Story = {
  args: {
    messages: [],
    liveTurn: liveTurn({
      activities: [searchActivity, { ...readActivity, state: "failed" }],
      content:
        "I found enough material to answer, although one source could not be opened.",
      state: "complete",
      trace: {
        activities: [searchActivity, { ...readActivity, state: "failed" }],
        citation_summary: {
          source_count: 2,
          annotation_count: 1,
          rejected_source_count: 0,
        },
      },
    }),
  },
};

export const Cancelled: Story = {
  args: {
    messages: [],
    liveTurn: liveTurn({ activities: [searchActivity], state: "cancelled" }),
  },
};

export const Error: Story = {
  args: { messages: [], liveTurn: liveTurn({ state: "error" }) },
};

export const NarrowLongSubject: Story = {
  globals: { viewport: { value: "smallMobile", isRotated: false } },
  args: {
    messages: [],
    liveTurn: liveTurn({
      activities: [
        {
          ...searchActivity,
          state: "running",
          subject:
            "A deliberately long research subject that must wrap safely without widening the conversation viewport or moving the composer",
        },
      ],
    }),
  },
};

export const SimplifiedChineseDark: Story = {
  globals: { appearance: "dark", locale: "zh-CN" },
  args: {
    messages: [],
    liveTurn: liveTurn({
      activities: [{ ...searchActivity, state: "running" }],
    }),
  },
};

export const OptimisticTurnDeduplicated: Story = {
  args: {
    messages: [
      {
        id: "41000000-0000-4000-8000-000000000003",
        turn_id: "52000000-0000-4000-8000-000000000001",
        role: "user",
        content: "Compare the strongest reasoning-compression approaches.",
        references: null,
        artifacts: null,
        trace: null,
        scope: null,
        sequence: 3,
      },
    ],
    liveTurn: liveTurn({
      activities: [{ ...searchActivity, state: "running" }],
    }),
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(
      canvas.getAllByText(
        "Compare the strongest reasoning-compression approaches.",
      ),
    ).toHaveLength(1);
  },
};
