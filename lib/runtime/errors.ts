import { randomUUID } from "node:crypto";
import type { RuntimeErrorResponse } from "./contracts";

export class RuntimePublicError extends Error {
  constructor(
    readonly code: string,
    readonly category: RuntimeErrorResponse["error"]["category"],
    message: string,
    readonly statusCode: number,
    readonly retryable = false,
  ) {
    super(message);
    this.name = "RuntimePublicError";
  }
}

export function errorResponse(error: unknown, correlationId = randomUUID()): {
  body: RuntimeErrorResponse;
  status: number;
} {
  if (error instanceof RuntimePublicError) {
    return {
      status: error.statusCode,
      body: {
        ok: false,
        error: {
          code: error.code,
          category: error.category,
          message: error.message,
          retryable: error.retryable,
          correlationId,
        },
      },
    };
  }
  return {
    status: 500,
    body: {
      ok: false,
      error: {
        code: "runtime_validation_failed",
        category: "internal",
        message: "Runtime validation could not be completed.",
        retryable: true,
        correlationId,
      },
    },
  };
}
