import { delay, http, HttpResponse } from "msw";

const apiUrl = "http://localhost:8000/api/v1/foundation-check";

export function foundationHandler({
  network,
  data,
}: {
  network: "instant" | "slow" | "offline";
  data: "populated" | "empty" | "error";
}) {
  return http.get(apiUrl, async () => {
    if (network === "offline") return HttpResponse.error();
    if (network === "slow") await delay(1800);
    if (data === "error")
      return HttpResponse.json({ message: "Server error" }, { status: 500 });
    return HttpResponse.json({
      items: data === "empty" ? [] : [{ id: "1", title: "Foundation item" }],
    });
  });
}

export const successHandlers = [
  http.get(apiUrl, () =>
    HttpResponse.json({ items: [{ id: "1", title: "Foundation item" }] }),
  ),
];
export const slowHandlers = [
  http.get(apiUrl, async () => {
    await delay(1800);
    return HttpResponse.json({ items: [{ id: "1", title: "Delayed item" }] });
  }),
];
export const emptyHandlers = [
  http.get(apiUrl, () => HttpResponse.json({ items: [] })),
];
export const businessErrorHandlers = [
  http.get(apiUrl, () =>
    HttpResponse.json(
      { code: "LIMIT_REACHED", message: "The operation is not available." },
      { status: 409 },
    ),
  ),
];
export const serverErrorHandlers = [
  http.get(apiUrl, () =>
    HttpResponse.json({ message: "Server error" }, { status: 500 }),
  ),
];
export const unauthorizedHandlers = [
  http.get(apiUrl, () =>
    HttpResponse.json({ message: "Unauthorized" }, { status: 401 }),
  ),
];
export const offlineHandlers = [http.get(apiUrl, () => HttpResponse.error())];
