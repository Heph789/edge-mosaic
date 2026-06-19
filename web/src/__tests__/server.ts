import { setupServer } from "msw/node";

// Per-test handlers are registered with server.use(...); the server starts empty.
export const server = setupServer();
