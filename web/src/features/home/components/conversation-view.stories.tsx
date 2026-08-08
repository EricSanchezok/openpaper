import type { Meta, StoryObj } from "@storybook/nextjs-vite";
import { expect, fn, userEvent, waitFor, within } from "storybook/test";

import type { components } from "@/lib/api/generated/schema";
import { homePapers, homeProjects, homeTurns } from "../api/fixtures";
import type { LiveTurn } from "../conversation-state";
import {
  ConversationView,
  type ConversationResponseVariant,
  type ConversationTurn,
} from "./conversation-view";

type ReferenceBundle = components["schemas"]["ReferenceBundle"];

const turnId = "51000000-0000-4000-8000-000000000001";
const responseId = "41000000-0000-4000-8000-000000000001";

function response(
  overrides: Partial<ConversationResponseVariant> = {},
): ConversationResponseVariant {
  return {
    id: responseId,
    variant_index: 1,
    status: "completed",
    content: "Today is Wednesday, August 5, 2026.",
    references: null,
    artifacts: null,
    trace: null,
    suggestions_status: "completed",
    suggestions: [
      "What is tomorrow’s date?",
      "Which time zone are you using?",
      "Show this week as a calendar.",
    ],
    ...overrides,
  };
}

function turn(
  overrides: Partial<ConversationTurn> & {
    responses?: ConversationResponseVariant[];
  } = {},
): ConversationTurn {
  const responses = overrides.responses ?? [response()];
  return {
    id: turnId,
    user_query: "What day is it today?",
    locale: "en",
    time_zone: "Asia/Shanghai",
    reasoning_level: "standard",
    scope: null,
    sequence: 1,
    user_references: null,
    selected_response_id: responses.at(-1)?.id ?? null,
    ...overrides,
    responses,
  };
}

const researchContent = `# 思维链压缩技术调研

思维链压缩关注如何在保留复杂推理能力的同时，减少中间推理步骤、延迟和推理成本。

## 主要研究方向

1. **短推理轨迹训练**：使用质量筛选或蒸馏，让模型学习更短但仍然可靠的推理路径。
2. **隐式推理表示**：把部分自然语言推理转移到隐藏状态，减少生成 token 的数量。
3. **动态推理预算**：根据问题难度决定推理深度，避免简单问题使用固定的长链路。

## 评估时需要注意

- 不能只比较输出长度，还要检查答案正确率和校准程度。
- 对数学、代码和开放式研究问题应分别评估。`;

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

const researchTrace = {
  entries: [searchActivity, readActivity],
  citation_summary: {
    source_count: 3,
    annotation_count: 2,
    rejected_source_count: 0,
  },
};

const researchReferences: ReferenceBundle = {
  annotations: [
    {
      start_offset: researchContent.indexOf("思维链压缩关注"),
      end_offset:
        researchContent.indexOf("思维链压缩关注") + "思维链压缩".length,
      source_keys: [1],
    },
  ],
  sources: homePapers.slice(0, 3).map((paper, index) => ({
    key: index + 1,
    kind: "document" as const,
    document_id: paper.document.document_id,
    title: paper.document.title,
    authors: paper.document.authors ?? [],
    reference: `第 ${index + 1} 个研究依据`,
    locator: { section: "Introduction" },
  })),
};

function researchTurn(overrides: Partial<ConversationTurn> = {}) {
  return turn({
    id: "51000000-0000-4000-8000-000000000011",
    user_query: "帮我调研一下思维链压缩技术",
    locale: "zh-CN",
    selected_response_id: "41000000-0000-4000-8000-000000000011",
    responses: [
      response({
        id: "41000000-0000-4000-8000-000000000011",
        content: researchContent,
        references: researchReferences,
        trace: researchTrace,
        suggestions: [
          "比较三种主流压缩路线",
          "如何设计统一评测？",
          "列出值得阅读的论文",
        ],
      }),
    ],
    ...overrides,
  });
}

function liveTurn(overrides: Partial<LiveTurn> = {}): LiveTurn {
  return {
    turnId: "52000000-0000-4000-8000-000000000001",
    responseId: "42000000-0000-4000-8000-000000000001",
    generationKind: "initial",
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
    turns: homeTurns,
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
    onRetryResponse: fn(),
    onSelectResponse: fn(),
    onUseSuggestion: fn(),
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
  args: { turns: [turn()] },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(canvas.getByText(/Today is Wednesday/)).toBeVisible();
    await expect(
      canvas.queryByText(/Research complete/),
    ).not.toBeInTheDocument();
  },
};

export const LatestAnswerActions: Story = {
  args: { turns: [turn()], onRetryResponse: fn() },
  play: async ({ args, canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(
      canvas.getByRole("button", { name: "Copy answer" }),
    ).toBeVisible();
    await userEvent.click(
      canvas.getByRole("button", { name: "Try another response" }),
    );
    await expect(args.onRetryResponse).toHaveBeenCalledTimes(1);
  },
};

export const RetriedResponseVersions: Story = {
  args: {
    turns: [
      turn({
        selected_response_id: "41000000-0000-4000-8000-000000000002",
        responses: [
          response(),
          response({
            id: "41000000-0000-4000-8000-000000000002",
            variant_index: 2,
            content: "The regenerated answer is Wednesday.",
          }),
        ],
      }),
    ],
    onSelectResponse: fn(),
  },
  play: async ({ args, canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(canvas.getByLabelText("Response 2 of 2")).toBeVisible();
    await userEvent.click(
      canvas.getByRole("button", { name: "Previous response" }),
    );
    await expect(args.onSelectResponse).toHaveBeenCalledWith(
      turnId,
      responseId,
    );
  },
};

export const HistoricalAnswerHasNoRetry: Story = {
  args: {
    turns: [
      turn(),
      turn({
        id: "51000000-0000-4000-8000-000000000002",
        sequence: 2,
        user_query: "And tomorrow?",
        selected_response_id: "41000000-0000-4000-8000-000000000003",
        responses: [
          response({
            id: "41000000-0000-4000-8000-000000000003",
            content: "Tomorrow is Thursday.",
            suggestions: null,
            suggestions_status: "idle",
          }),
        ],
      }),
    ],
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(
      canvas.getAllByRole("button", { name: "Try another response" }),
    ).toHaveLength(1);
    await expect(
      canvas.queryByLabelText("Response 1 of 1"),
    ).not.toBeInTheDocument();
  },
};

export const SuggestedFollowUps: Story = {
  args: { turns: [turn()], onUseSuggestion: fn() },
  play: async ({ args, canvasElement }) => {
    const canvas = within(canvasElement);
    const suggestion = canvas.getByRole("button", {
      name: "What is tomorrow’s date?",
    });
    await userEvent.click(suggestion);
    await expect(args.onUseSuggestion).toHaveBeenCalledWith(
      "What is tomorrow’s date?",
    );
    await expect(args.onSubmit).not.toHaveBeenCalled();
  },
};

export const SuggestionsPending: Story = {
  args: {
    turns: [
      turn({
        responses: [
          response({ suggestions: null, suggestions_status: "pending" }),
        ],
      }),
    ],
  },
  play: async ({ canvasElement }) => {
    await expect(
      within(canvasElement).getByRole("status", {
        name: "Preparing follow-up suggestions…",
      }),
    ).toBeVisible();
  },
};

export const SuggestionsUnavailable: Story = {
  args: {
    turns: [
      turn({
        responses: [
          response({ suggestions: null, suggestions_status: "failed" }),
        ],
      }),
    ],
  },
  play: async ({ canvasElement }) => {
    await expect(
      within(canvasElement).getByText(
        "Follow-up suggestions are unavailable for this answer.",
      ),
    ).toBeVisible();
  },
};

export const RetryInProgress: Story = {
  args: {
    turns: [turn()],
    liveTurn: liveTurn({
      turnId,
      generationKind: "retry",
      provisionalItems: [
        {
          id: "assistant:retry:1",
          sequence: 1,
          phase: "provisional",
          content: "I’m checking the evidence again before answering.",
        },
      ],
    }),
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(
      canvas.getByText("I’m checking the evidence again before answering."),
    ).toBeVisible();
    await expect(canvas.getAllByText("What day is it today?")).toHaveLength(1);
    await expect(
      canvas.queryByRole("button", { name: "Try another response" }),
    ).not.toBeInTheDocument();
  },
};

export const RetryFailed: Story = {
  args: {
    turns: [turn()],
    liveTurn: liveTurn({
      turnId,
      generationKind: "retry",
      state: "error",
      failure: {
        code: "research_service_unavailable",
        kind: "unavailable",
        retryable: true,
        diagnosticId: "diagnostic-retry-123",
      },
    }),
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await waitFor(() =>
      expect(
        canvas.getByText(/Research service is temporarily unavailable/),
      ).toBeVisible(),
    );
    await expect(canvas.getAllByText("What day is it today?")).toHaveLength(1);
  },
};

export const MobileResearchAnswer: Story = {
  globals: { locale: "zh-CN", viewport: { value: "mobile", isRotated: false } },
  args: { turns: [researchTurn()], title: "思维链压缩技术调研" },
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

export const AnswerSources: Story = {
  globals: { locale: "zh-CN" },
  args: { turns: [researchTurn()], title: "思维链压缩技术调研" },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.click(canvas.getByRole("button", { name: "打开来源 1" }));
    const page = within(canvasElement.ownerDocument.body);
    await expect(
      page.getByRole("dialog", { name: "引用来源 3" }),
    ).toBeVisible();
    await expect(
      page.getByText(homePapers[0]!.document.title ?? "Source 1"),
    ).toBeVisible();
  },
};

export const MobileWorklogExpanded: Story = {
  globals: { locale: "zh-CN", viewport: { value: "mobile", isRotated: false } },
  args: {
    turns: [],
    liveTurn: liveTurn({
      entries: [
        {
          kind: "progress",
          id: "assistant:mobile:1",
          sequence: 1,
          content: "我会先检查资料库，再比较相邻的推理效率研究。",
        },
        { ...searchActivity, sequence: 2, subject: "思维链压缩与短推理轨迹" },
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
        { ...readActivity, sequence: 5, subject: "Reasoning Efficiently" },
      ],
      content: "现有研究主要围绕短轨迹训练、隐式推理和动态预算展开。",
      state: "complete",
      trace: researchTrace,
    }),
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const disclosure = canvas.getByRole("button", { name: /已完成研究/ });
    await userEvent.click(disclosure);
    await expect(canvas.getByText("检索了 2 次")).toBeVisible();
  },
};

export const ThinkingWithoutTools: Story = {
  args: { turns: [], liveTurn: liveTurn() },
  play: async ({ canvasElement }) => {
    await waitFor(() =>
      expect(within(canvasElement).getByText("Thinking…")).toBeVisible(),
    );
  },
};

export const ProvisionalResponse: Story = {
  args: {
    turns: [],
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
    turns: [],
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
    turns: [],
    liveTurn: liveTurn({
      entries: [
        searchActivity,
        readActivity,
        { ...searchActivity, id: "search-3", sequence: 3 },
      ],
    }),
  },
};

export const StrategyChange: Story = {
  args: {
    turns: [],
    liveTurn: liveTurn({
      entries: [
        searchActivity,
        {
          kind: "progress",
          id: "assistant:turn:2",
          sequence: 2,
          content:
            "The first search was too narrow, so I’ll compare adjacent work.",
        },
        { ...readActivity, sequence: 3, state: "running" },
      ],
    }),
  },
};

export const SingleToolRunning: Story = {
  args: {
    turns: [],
    liveTurn: liveTurn({ entries: [{ ...searchActivity, state: "running" }] }),
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const disclosure = canvas.getByRole("button", {
      name: "Searching your research…",
    });
    await expect(disclosure).toHaveAttribute("aria-expanded", "true");
    disclosure.focus();
    await userEvent.keyboard(" ");
    await expect(disclosure).toHaveAttribute("aria-expanded", "false");
  },
};

export const CompletedCollapsed: Story = {
  args: {
    turns: [],
    liveTurn: liveTurn({
      entries: [searchActivity, readActivity],
      content: "The evidence supports a shorter distilled reasoning trace.",
      state: "complete",
      trace: researchTrace,
    }),
  },
  play: async ({ canvasElement }) => {
    const disclosure = within(canvasElement).getByRole("button", {
      name: "Research complete · 2 actions · 3 sources",
    });
    await expect(disclosure).toHaveAttribute("aria-expanded", "false");
  },
};

export const PartialFailure: Story = {
  args: {
    turns: [],
    liveTurn: liveTurn({
      entries: [searchActivity, { ...readActivity, state: "failed" }],
      content: "I found enough material to answer.",
      state: "complete",
      trace: {
        ...researchTrace,
        entries: [searchActivity, { ...readActivity, state: "failed" }],
      },
    }),
  },
};

export const Cancelled: Story = {
  args: {
    turns: [],
    liveTurn: liveTurn({ entries: [searchActivity], state: "cancelled" }),
  },
};

export const Error: Story = {
  args: {
    turns: [],
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
    turns: [],
    liveTurn: liveTurn({
      entries: [
        {
          ...searchActivity,
          state: "running",
          subject:
            "A deliberately long research subject that must wrap safely without widening the conversation viewport",
        },
      ],
    }),
  },
};

export const SimplifiedChineseDark: Story = {
  globals: { appearance: "dark", locale: "zh-CN" },
  args: {
    turns: [],
    liveTurn: liveTurn({ entries: [{ ...searchActivity, state: "running" }] }),
  },
};

export const OptimisticTurnDeduplicated: Story = {
  args: {
    turns: [
      turn({
        id: "52000000-0000-4000-8000-000000000001",
        user_query: "Compare the strongest reasoning-compression approaches.",
        selected_response_id: null,
        responses: [],
      }),
    ],
    liveTurn: liveTurn({ entries: [{ ...searchActivity, state: "running" }] }),
  },
  play: async ({ canvasElement }) => {
    await expect(
      within(canvasElement).getAllByText(
        "Compare the strongest reasoning-compression approaches.",
      ),
    ).toHaveLength(1);
  },
};
