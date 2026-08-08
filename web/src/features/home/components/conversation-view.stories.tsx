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

const mobileResearchMessages: Message[] = [
  {
    id: "41000000-0000-4000-8000-000000000011",
    turn_id: "51000000-0000-4000-8000-000000000011",
    role: "user",
    content: "帮我调研一下思维链压缩技术",
    references: null,
    artifacts: null,
    trace: null,
    scope: null,
    sequence: 1,
  },
  {
    id: "41000000-0000-4000-8000-000000000012",
    turn_id: "51000000-0000-4000-8000-000000000011",
    role: "assistant",
    content: `# 思维链压缩技术调研

思维链压缩关注如何在保留复杂推理能力的同时，减少中间推理步骤、延迟和推理成本。它并不是简单删除文字，而是尝试保留对最终答案真正有贡献的信息。

## 主要研究方向

1. **短推理轨迹训练**：使用质量筛选或蒸馏，让模型学习更短但仍然可靠的推理路径。
2. **隐式推理表示**：把部分自然语言推理转移到隐藏状态，减少生成 token 的数量。
3. **动态推理预算**：根据问题难度决定推理深度，避免简单问题使用固定的长链路。

## 评估时需要注意

- 不能只比较输出长度，还要检查答案正确率和校准程度。
- 对数学、代码和开放式研究问题应分别评估。
- 压缩后的推理过程仍需保留必要的可验证证据。

下一步可以从推理长度、准确率、延迟和成本四个维度建立统一的实验表。`,
    references: null,
    artifacts: null,
    trace: null,
    scope: null,
    sequence: 2,
  },
];

const mobileSourceMessages: Message[] = mobileResearchMessages.map((message) =>
  message.role !== "assistant"
    ? message
    : {
        ...message,
        references: {
          annotations: [],
          sources: homePapers.slice(0, 3).map((paper, index) => ({
            key: index + 1,
            kind: "document" as const,
            document_id: paper.document.document_id,
            title: paper.document.title,
            authors: paper.document.authors ?? [],
            reference: `第 ${index + 1} 个研究依据`,
            locator: { section: "Introduction" },
          })),
        },
      },
);

const mobileLongThreadMessages: Message[] = Array.from({ length: 3 }).flatMap(
  (_, index) =>
    mobileResearchMessages.map((message, messageIndex) => ({
      ...message,
      id: `41000000-0000-4000-8000-${String(index * 2 + messageIndex + 1).padStart(12, "0")}`,
      turn_id: `51000000-0000-4000-8000-${String(index + 1).padStart(12, "0")}`,
      sequence: message.sequence + index * 2,
    })),
);

const searchActivity = {
  kind: "activity" as const,
  id: "search-1",
  sequence: 1,
  category: "search" as const,
  state: "succeeded" as const,
  subject: "chain-of-thought compression for efficient language models",
  source_count: 3,
  artifact_count: 0,
};

const readActivity = {
  kind: "activity" as const,
  id: "read-2",
  sequence: 2,
  category: "read" as const,
  state: "succeeded" as const,
  subject: "Reasoning Efficiently: Models, Methods, and Open Questions",
  source_count: 2,
  artifact_count: 0,
};

function liveTurn(overrides: Partial<LiveTurn> = {}): LiveTurn {
  return {
    turnId: "52000000-0000-4000-8000-000000000001",
    userMessage: "Compare the strongest reasoning-compression approaches.",
    content: "",
    entries: [],
    provisionalItems: [],
    completedItemIds: [],
    trace: null,
    references: null,
    failure: null,
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
      <main className="h-dvh overflow-y-auto">
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

export const MobileResearchAnswer: Story = {
  globals: {
    locale: "zh-CN",
    viewport: { value: "mobile", isRotated: false },
  },
  args: {
    messages: mobileResearchMessages,
    title: "思维链压缩技术调研",
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(
      canvas.getByRole("heading", { name: "思维链压缩技术调研" }),
    ).toBeVisible();
    await expect(canvas.getByText("主要研究方向")).toBeVisible();
  },
};

export const MobileResearchAnswerDark: Story = {
  ...MobileResearchAnswer,
  globals: {
    appearance: "dark",
    locale: "zh-CN",
    viewport: { value: "largeMobile", isRotated: false },
  },
};

export const MobileLongAnswer: Story = {
  ...MobileResearchAnswer,
};

export const MobileWorklogExpanded: Story = {
  globals: {
    locale: "zh-CN",
    viewport: { value: "mobile", isRotated: false },
  },
  args: {
    messages: [],
    liveTurn: liveTurn({
      entries: [
        {
          kind: "progress",
          id: "assistant:mobile:1",
          sequence: 1,
          content: "我会先检查资料库，再比较相邻的推理效率研究。",
        },
        {
          ...searchActivity,
          sequence: 2,
          subject: "思维链压缩与短推理轨迹",
        },
        {
          ...searchActivity,
          id: "search-mobile-2",
          sequence: 3,
          subject: "动态推理预算",
        },
        {
          kind: "progress",
          id: "assistant:mobile:2",
          sequence: 4,
          content: "初步结果较少，我将范围扩展到隐式推理与蒸馏方法。",
        },
        {
          ...readActivity,
          sequence: 5,
          subject: "Reasoning Efficiently",
        },
      ],
      content: "现有研究主要围绕短轨迹训练、隐式推理和动态预算展开。",
      state: "complete",
      trace: {
        entries: [],
        citation_summary: {
          source_count: 3,
          annotation_count: 2,
          rejected_source_count: 0,
        },
      },
    }),
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const disclosure = canvas.getByRole("button", {
      name: /已完成研究/,
    });
    await userEvent.click(disclosure);
    await expect(
      canvas.getByText("我会先检查资料库，再比较相邻的推理效率研究。"),
    ).toBeVisible();
    await expect(canvas.getByText("检索了 2 次")).toBeVisible();
  },
};

export const MobileSourcesAggregated: Story = {
  globals: {
    locale: "zh-CN",
    viewport: { value: "mobile", isRotated: false },
  },
  args: {
    messages: mobileSourceMessages,
    title: "思维链压缩技术调研",
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const disclosure = canvas.getByLabelText("展开 3 个来源");
    await expect(disclosure).toBeVisible();
    await userEvent.click(disclosure);
    const firstPaperTitle = homePapers[0]!.document.title;
    if (!firstPaperTitle) {
      throw new globalThis.Error(
        "Mobile source fixture must include a paper title",
      );
    }
    const details = disclosure.closest("details");
    if (!details) {
      throw new globalThis.Error("Mobile source disclosure must use details");
    }
    await expect(within(details).getByText(firstPaperTitle)).toBeVisible();
  },
};

export const MobileJumpToLatest: Story = {
  globals: {
    locale: "zh-CN",
    viewport: { value: "mobile", isRotated: false },
  },
  args: {
    messages: mobileLongThreadMessages,
    title: "思维链压缩技术调研",
  },
  play: async ({ canvasElement }) => {
    const scroller = canvasElement.querySelector("main");
    if (!(scroller instanceof HTMLElement)) {
      throw new globalThis.Error(
        "Conversation story scroll container was not found",
      );
    }
    await waitFor(() =>
      expect(scroller.scrollHeight).toBeGreaterThan(scroller.clientHeight),
    );
    scroller.scrollTo({ top: 0 });
    scroller.dispatchEvent(new window.Event("scroll"));
    await expect(
      within(canvasElement).getByRole("button", { name: "返回最新消息" }),
    ).toBeVisible();
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

export const ProvisionalResponse: Story = {
  args: {
    messages: [],
    liveTurn: liveTurn({
      provisionalItems: [
        {
          id: "assistant:turn:1",
          sequence: 1,
          phase: "provisional",
          content: "I’ll first inspect the research available in your library.",
        },
      ],
    }),
  },
};

export const ProgressBeforeTools: Story = {
  args: {
    messages: [],
    liveTurn: liveTurn({
      entries: [
        {
          kind: "progress",
          id: "assistant:turn:1",
          sequence: 1,
          content: "I’ll first inspect the research available in your library.",
        },
        { ...searchActivity, sequence: 2, state: "running" },
      ],
    }),
  },
};

export const ConsecutiveToolBatch: Story = {
  args: {
    messages: [],
    liveTurn: liveTurn({
      entries: [
        searchActivity,
        readActivity,
        {
          ...searchActivity,
          id: "search-3",
          sequence: 3,
          subject: "latent reasoning compression",
        },
      ],
    }),
  },
};

export const StrategyChange: Story = {
  args: {
    messages: [],
    liveTurn: liveTurn({
      entries: [
        searchActivity,
        {
          kind: "progress",
          id: "assistant:turn:2",
          sequence: 2,
          content:
            "The first search was too narrow, so I’ll compare adjacent reasoning-efficiency work.",
        },
        { ...readActivity, sequence: 3, state: "running" },
      ],
    }),
  },
};

export const SingleToolRunning: Story = {
  args: {
    messages: [],
    liveTurn: liveTurn({
      entries: [{ ...searchActivity, state: "running" }],
    }),
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const disclosure = canvas.getByRole("button", {
      name: "Searching your research…",
    });
    await expect(disclosure).toHaveAttribute("aria-expanded", "true");
    await expect(canvas.getByText("Searched 1 time")).toBeVisible();
    disclosure.focus();
    await userEvent.keyboard(" ");
    await expect(disclosure).toHaveAttribute("aria-expanded", "false");
    await expect(canvas.queryByText("search_papers")).not.toBeInTheDocument();
    await userEvent.keyboard("{Enter}");
    await expect(disclosure).toHaveAttribute("aria-expanded", "true");
  },
};

export const MultipleToolsExpanded: Story = {
  args: {
    messages: [],
    liveTurn: liveTurn({
      entries: [searchActivity, readActivity],
      content:
        "The strongest approaches trade additional training for shorter inference traces.",
      state: "complete",
      trace: {
        entries: [searchActivity, readActivity],
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
      name: "Research complete · 2 actions · 4 sources",
    });
    await userEvent.click(disclosure);
    await expect(
      canvas.getByText("Searched 1 time · Read 1 source"),
    ).toBeVisible();
    await expect(disclosure).toHaveAttribute("aria-expanded", "true");
  },
};

export const CompletedCollapsed: Story = {
  args: {
    messages: [],
    liveTurn: liveTurn({
      entries: [searchActivity, readActivity],
      content: "The evidence supports a shorter distilled reasoning trace.",
      state: "complete",
      trace: {
        entries: [searchActivity, readActivity],
        citation_summary: {
          source_count: 4,
          annotation_count: 2,
          rejected_source_count: 0,
        },
      },
    }),
  },
  play: async ({ canvasElement }) => {
    const disclosure = within(canvasElement).getByRole("button", {
      name: "Research complete · 2 actions · 4 sources",
    });
    await expect(disclosure).toHaveAttribute("aria-expanded", "false");
  },
};

export const PartialFailure: Story = {
  args: {
    messages: [],
    liveTurn: liveTurn({
      entries: [searchActivity, { ...readActivity, state: "failed" }],
      content:
        "I found enough material to answer, although one source could not be opened.",
      state: "complete",
      trace: {
        entries: [searchActivity, { ...readActivity, state: "failed" }],
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
    liveTurn: liveTurn({ entries: [searchActivity], state: "cancelled" }),
  },
};

export const Error: Story = {
  args: {
    messages: [],
    liveTurn: liveTurn({
      state: "error",
      failure: {
        code: "rate_limit_unavailable",
        kind: "unavailable",
        retryable: true,
        diagnosticId: "diagnostic-123",
      },
    }),
  },
};

export const NarrowLongSubject: Story = {
  globals: { viewport: { value: "smallMobile", isRotated: false } },
  args: {
    messages: [],
    liveTurn: liveTurn({
      entries: [
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
      entries: [{ ...searchActivity, state: "running" }],
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
      entries: [{ ...searchActivity, state: "running" }],
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
