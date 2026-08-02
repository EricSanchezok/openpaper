import { setupWorker } from "msw/browser";
import { successHandlers } from "../../.storybook/msw/handlers";

export const worker = setupWorker(...successHandlers);
