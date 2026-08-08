import { delay, http, HttpResponse } from "msw";

import {
  homeConversations,
  homePapers,
  homeProjects,
  homeTurns,
} from "./fixtures";

const api = "http://127.0.0.1:7301/api/v1";
const activeConversation = {
  ...homeConversations[0]!,
  paper_context: { kind: "library" as const },
  tool_permissions: [],
};

const baseHandlers = [
  http.get(`${api}/conversations`, () =>
    HttpResponse.json({ items: homeConversations, next_cursor: null }),
  ),
  http.get(`${api}/library/papers`, () =>
    HttpResponse.json({ items: homePapers, next_cursor: null }),
  ),
  http.get(`${api}/projects`, () =>
    HttpResponse.json({ items: homeProjects, next_cursor: null }),
  ),
  http.get(`${api}/conversations/:conversationId`, () =>
    HttpResponse.json(activeConversation),
  ),
  http.get(`${api}/conversations/:conversationId/turns`, () =>
    HttpResponse.json({ items: homeTurns, next_cursor: null }),
  ),
  http.post(`${api}/conversations`, () =>
    HttpResponse.json(activeConversation, { status: 201 }),
  ),
  http.put(
    `${api}/conversations/:conversationId/context`,
    async ({ request }) => HttpResponse.json(await request.json()),
  ),
  http.post(
    `${api}/conversations/:conversationId/turns`,
    async ({ request }) => {
      const requestBody = (await request.json()) as {
        turn_id: string;
        response_id: string;
      };
      const events = [
        {
          type: "start",
          conversation_id: activeConversation.id,
          turn_id: requestBody.turn_id,
          response_id: requestBody.response_id,
        },
        {
          type: "activity",
          response_id: requestBody.response_id,
          activity: {
            kind: "activity",
            id: "search-1",
            sequence: 1,
            category: "search",
            state: "running",
            subject: "selected research",
          },
        },
        {
          type: "assistant_item_start",
          response_id: requestBody.response_id,
          item_id: `assistant:${requestBody.turn_id}:2`,
          sequence: 2,
        },
        {
          type: "assistant_item_delta",
          response_id: requestBody.response_id,
          item_id: `assistant:${requestBody.turn_id}:2`,
          delta: "The answer is grounded in your selected research.",
        },
        {
          type: "assistant_item_complete",
          response_id: requestBody.response_id,
          item: {
            id: `assistant:${requestBody.turn_id}:2`,
            sequence: 2,
            phase: "final",
            content: "The answer is grounded in your selected research.",
          },
        },
        {
          type: "complete",
          turn_id: requestBody.turn_id,
          response_id: requestBody.response_id,
          trace: {
            entries: [
              {
                kind: "activity",
                id: "search-1",
                sequence: 1,
                category: "search",
                state: "succeeded",
                subject: "selected research",
                source_count: 1,
                artifact_count: 0,
              },
            ],
            citation_summary: {
              source_count: 1,
              annotation_count: 1,
              rejected_source_count: 0,
            },
          },
          artifacts: [],
        },
      ];
      const body = events
        .map(
          (event) => `event: ${event.type}\ndata: ${JSON.stringify(event)}\n\n`,
        )
        .join("");
      return new HttpResponse(body, {
        headers: { "Content-Type": "text/event-stream" },
      });
    },
  ),
  http.post(
    `${api}/conversations/:conversationId/turns/:turnId/responses`,
    async ({ request, params }) => {
      const requestBody = (await request.json()) as { response_id: string };
      const turnId = String(params.turnId);
      const events = [
        {
          type: "start",
          conversation_id: activeConversation.id,
          turn_id: turnId,
          response_id: requestBody.response_id,
        },
        {
          type: "assistant_item_start",
          response_id: requestBody.response_id,
          item_id: `assistant:${turnId}:retry`,
          sequence: 1,
        },
        {
          type: "assistant_item_delta",
          response_id: requestBody.response_id,
          item_id: `assistant:${turnId}:retry`,
          delta: "A regenerated answer grounded in the same turn.",
        },
        {
          type: "assistant_item_complete",
          response_id: requestBody.response_id,
          item: {
            id: `assistant:${turnId}:retry`,
            sequence: 1,
            phase: "final",
            content: "A regenerated answer grounded in the same turn.",
          },
        },
        {
          type: "complete",
          turn_id: turnId,
          response_id: requestBody.response_id,
          trace: null,
          artifacts: [],
        },
      ];
      const body = events
        .map(
          (event) => `event: ${event.type}\ndata: ${JSON.stringify(event)}\n\n`,
        )
        .join("");
      return new HttpResponse(body, {
        headers: { "Content-Type": "text/event-stream" },
      });
    },
  ),
  http.put(
    `${api}/conversations/:conversationId/turns/:turnId/selected-response`,
    async ({ request }) => {
      const requestBody = (await request.json()) as { response_id: string };
      return HttpResponse.json({
        selected_response_id: requestBody.response_id,
      });
    },
  ),
  http.post(
    `${api}/conversations/:conversationId/responses/:responseId/suggestions`,
    () =>
      HttpResponse.json({
        status: "pending",
        suggestions: null,
      }),
  ),
];

export const homeHandlers = {
  populated: baseHandlers,
  empty: [
    http.get(`${api}/conversations`, () =>
      HttpResponse.json({ items: [], next_cursor: null }),
    ),
    http.get(`${api}/library/papers`, () =>
      HttpResponse.json({ items: [], next_cursor: null }),
    ),
    http.get(`${api}/projects`, () =>
      HttpResponse.json({ items: [], next_cursor: null }),
    ),
    ...baseHandlers,
  ],
  error: [
    http.get(`${api}/library/papers`, () =>
      HttpResponse.json({ code: "service_unavailable" }, { status: 503 }),
    ),
    http.get(`${api}/projects`, () =>
      HttpResponse.json({ code: "service_unavailable" }, { status: 503 }),
    ),
    ...baseHandlers,
  ],
  slow: [
    http.get(`${api}/library/papers`, async () => {
      await delay(1_800);
      return HttpResponse.json({ items: homePapers, next_cursor: null });
    }),
    http.get(`${api}/projects`, async () => {
      await delay(1_800);
      return HttpResponse.json({ items: homeProjects, next_cursor: null });
    }),
    ...baseHandlers,
  ],
  readOnly: [
    http.get(`${api}/conversations/:conversationId`, () =>
      HttpResponse.json({
        ...activeConversation,
        read_only: true,
        read_only_reason: "scope_access_lost",
        capabilities: { ...activeConversation.capabilities, send: false },
      }),
    ),
    ...baseHandlers,
  ],
  processing: [
    http.post(
      `${api}/conversations/:conversationId/turns`,
      async ({ request }) => {
        const requestBody = (await request.json()) as { response_id: string };
        const encoder = new TextEncoder();
        const body = new ReadableStream({
          start(controller) {
            controller.enqueue(
              encoder.encode(
                `event: activity\ndata: ${JSON.stringify({
                  type: "activity",
                  response_id: requestBody.response_id,
                  activity: {
                    kind: "activity",
                    id: "search-1",
                    sequence: 1,
                    category: "search",
                    state: "running",
                    subject: "selected papers",
                  },
                })}\n\n`,
              ),
            );
          },
        });
        return new HttpResponse(body, {
          headers: { "Content-Type": "text/event-stream" },
        });
      },
    ),
    ...baseHandlers,
  ],
};
