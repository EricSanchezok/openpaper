import { delay, http, HttpResponse } from "msw";

import {
  homeConversations,
  homeMessages,
  homePapers,
  homeProjects,
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
  http.get(`${api}/conversations/:conversationId/messages`, () =>
    HttpResponse.json({ items: homeMessages, next_cursor: null }),
  ),
  http.post(`${api}/conversations`, () =>
    HttpResponse.json(activeConversation, { status: 201 }),
  ),
  http.put(
    `${api}/conversations/:conversationId/context`,
    async ({ request }) => HttpResponse.json(await request.json()),
  ),
  http.post(`${api}/conversations/:conversationId/messages`, () => {
    const events = [
      {
        type: "start",
        conversation_id: activeConversation.id,
        turn_id: crypto.randomUUID(),
      },
      { type: "status", message: "Searching the library" },
      {
        type: "content_delta",
        delta: "The answer is grounded in your selected research.",
      },
      {
        type: "complete",
        turn_id: crypto.randomUUID(),
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
  }),
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
    http.post(`${api}/conversations/:conversationId/messages`, () => {
      const encoder = new TextEncoder();
      const body = new ReadableStream({
        start(controller) {
          controller.enqueue(
            encoder.encode(
              `event: status\ndata: ${JSON.stringify({
                type: "status",
                message: "Searching the library",
              })}\n\n`,
            ),
          );
        },
      });
      return new HttpResponse(body, {
        headers: { "Content-Type": "text/event-stream" },
      });
    }),
    ...baseHandlers,
  ],
};
